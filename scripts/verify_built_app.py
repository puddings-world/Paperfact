"""Exercise a frozen app using generated research and isolated account/data homes."""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import sysconfig
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


FORMAT = "paperfact.packaged-acceptance.v1"
STAGES = {
    "isolation",
    "version",
    "doctor",
    "first-use",
    "first-use-privacy",
    "seed",
    "share-link",
    "share-link-checksum",
    "import",
    "import-again",
    "fixture-ack",
    "reader",
    "export",
    "file-fidelity",
    "research-content",
    "credential-isolation",
    "local-integration",
    "appimage-integration",
    "mac-foreground",
}


class OutputExists(FileExistsError):
    """Only the run destination already exists; preserve its earlier report."""


class CheckFailure(RuntimeError):
    def __init__(self, label, code, returncode=None):
        super().__init__(f"{label} failed ({returncode}); inspect the captured local log")
        self.code, self.returncode = code, returncode


def failure_category(error):
    if isinstance(error, CheckFailure):
        return dict(code=error.code, returncode=error.returncode)
    for kind, code in (
        (KeyboardInterrupt, "interrupted"),
        (subprocess.TimeoutExpired, "timeout"),
        (FileNotFoundError, "missing_file"),
        (PermissionError, "permission_denied"),
        (AssertionError, "assertion_failed"),
        (ValueError, "validation_failed"),
        (OSError, "os_error"),
        (RuntimeError, "check_failed"),
    ):
        if isinstance(error, kind):
            return dict(code=code, returncode=None)
    return dict(code="unexpected_error", returncode=None)


def packaged_identity(built):
    # Read only fixed packaged metadata, never the mutable checkout's commit/version.
    result = dict(commit=None, dirty=None, version=None)
    for relative in (
        "_internal/build-info.json",
        "build-info.json",
        "Contents/Resources/build-info.json",
        "Contents/Frameworks/build-info.json",
    ):
        try:
            with (built / relative).open("rb") as stream:
                raw = stream.read(128 * 1024 + 1)
            if len(raw) > 128 * 1024:
                continue
            info = json.loads(raw)
            if not isinstance(info, dict):
                continue
            commit = info.get("commit")
            result["commit"] = (
                commit.lower()
                if isinstance(commit, str) and re.fullmatch(r"[a-fA-F0-9]{40,64}", commit)
                else None
            )
            result["dirty"] = info.get("dirty") if type(info.get("dirty")) is bool else None
            return result
        except (OSError, ValueError, UnicodeError):
            continue
    return result


def host_architecture():
    # Match the app footer: platform.machine can launch cmd on cold Windows.
    if sys.platform == "win32":
        machine = sysconfig.get_platform().removeprefix("win-").lower()
        return "x86" if machine == "win32" else machine
    return os.uname().machine.lower() if hasattr(os, "uname") else "other"


class Acceptance:
    """Durable categorical progress; raw subprocess output stays in local logs."""

    def __init__(self, built, out):
        self.out = out
        machine = host_architecture()
        self.report = dict(
            format=FORMAT,
            passed=False,
            status="running",
            active_check=None,
            completed_checks=[],
            failure=None,
            build=packaged_identity(built),
            host=dict(
                os={"win32": "Windows", "darwin": "macOS", "linux": "Linux"}.get(
                    sys.platform, "other"
                ),
                architecture=machine
                if machine in {"amd64", "x86_64", "arm64", "aarch64", "x86", "i686"}
                else "other",
            ),
        )
        self.write()

    def write(self):
        temporary = self.out / "report.pending.json"
        temporary.write_text(json.dumps(self.report, indent=2), encoding="utf-8")
        temporary.replace(self.out / "report.json")

    def call(self, label, function):
        if label not in STAGES:
            raise ValueError("Unknown acceptance stage")
        self.report["active_check"] = label
        self.write()
        value = function()
        self.report["completed_checks"].append(label)
        self.report["active_check"] = None
        self.write()
        return value

    def failed(self, error):
        self.report.update(
            passed=False,
            status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
            failure=failure_category(error),
        )
        self.write()

    def finish(self, result):
        self.report.update(
            result, format=FORMAT, status="passed", passed=True, active_check=None, failure=None
        )
        self.write()
        return self.report


def isolated_env(folder):
    home = folder / 'home'
    home.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if k.upper() in {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC',
                            'DISPLAY', 'XAUTHORITY', 'QTWEBENGINE_CHROMIUM_FLAGS'}}
    env.update(HOME=str(home), USERPROFILE=str(home),
               APPDATA=str(home / 'roaming'), LOCALAPPDATA=str(home / 'local'),
               XDG_CONFIG_HOME=str(home / '.config'),
               PAPERFACT_DATA=str(folder / 'workspace'), PAPERFACT_SMOKE_SECONDS='5',
               QT_QPA_PLATFORM=os.environ.get('QT_QPA_PLATFORM', 'offscreen'),
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
               HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9')
    system = Path(os.environ.get('SYSTEMROOT', '/usr'))
    env['PATH'] = os.pathsep.join(map(str, [Path(sys.executable).parent, system / 'System32',
                                          system] if os.name == 'nt' else ['/usr/bin', '/bin']))
    return env


def compare_files(first, second):
    with zipfile.ZipFile(first) as a, zipfile.ZipFile(second) as b:
        files = {name: a.read(name) for name in a.namelist() if name.startswith('files/')}
        other = {name: b.read(name) for name in b.namelist() if name.startswith('files/')}
        if not files or files != other:
            raise ValueError('Research files changed during frozen-app round trip')
        return len(files)


def check_process(result, label):
    if result.returncode or b"Traceback (most recent call last):" in result.stdout + result.stderr:
        raise CheckFailure(
            label,
            "process_failed" if result.returncode else "background_traceback",
            result.returncode,
        )


def _verify(built, out, acceptance):
    folder = built / "Contents/MacOS" if sys.platform == "darwin" else built
    ext = ".exe" if os.name == "nt" else ""
    cli, gui = folder / ("paperfact-cli" + ext), folder / ("Paperfact" + ext)

    def run(label, command, env):
        def execute():
            try:
                result = subprocess.run(
                    list(map(str, command)), cwd=ROOT, env=env, capture_output=True, timeout=90
                )
            except subprocess.TimeoutExpired as error:
                (out / (label + ".log")).write_bytes((error.stdout or b"") + (error.stderr or b""))
                raise
            (out / (label + ".log")).write_bytes(result.stdout + result.stderr)
            check_process(result, label)
            if label == "version" and len(result.stdout) <= 96:
                text = result.stdout.decode("ascii", errors="replace").strip()
                match = re.fullmatch(
                    r"paperfact (\d+\.\d+\.\d+(?:(?:\.dev|[ab]|rc)\d*|-(?:alpha|beta|rc)\d*)?)",
                    text,
                )
                if match:
                    acceptance.report["build"]["version"] = match[1]
            log = Path(env["PAPERFACT_DATA"]) / "app.log"
            if log.exists() and "Traceback" in log.read_text(encoding="utf-8", errors="replace"):
                raise CheckFailure(label, "app_traceback")

        return acceptance.call(label, execute)

    def require(condition):
        if not condition:
            raise AssertionError("Packaged acceptance condition failed")

    empty, recipient, sender = acceptance.call(
        "isolation",
        lambda: tuple(isolated_env(out / name) for name in ("empty", "recipient", "sender")),
    )
    run("version", [cli, "--version"], empty)
    run("doctor", [cli, "doctor"], empty)
    run("first-use", [gui], empty)
    acceptance.call(
        "first-use-privacy",
        lambda: require(not (Path(empty["PAPERFACT_DATA"]) / "llm.json").exists()),
    )
    original, returned = out / "original.zip", out / "returned.zip"
    seed = (
        "import sys; sys.path.insert(0, 'scripts'); import demo_workspace; "
        "demo_workspace.seed(); from paper_daily import bundle; "
        "from pathlib import Path; bundle.export('demo', Path(sys.argv[1]))"
    )
    run("seed", [sys.executable, "-c", seed, original], sender)
    run(
        "share-link",
        [cli, "list-share-link", original, "https://files.example.org/research.zip"],
        sender,
    )

    def checksum():
        expected = "https://files.example.org/research.zip#paperfact-sha256=" + (
            hashlib.sha256(original.read_bytes()).hexdigest()
        )
        require(expected in (out / "share-link.log").read_text(encoding="utf-8"))

    acceptance.call("share-link-checksum", checksum)
    run("import", [cli, "list-import", original], recipient)
    run("import-again", [cli, "list-import", original], recipient)
    # This acknowledges only the generated test recipient's local fixture.
    run(
        "fixture-ack",
        [
            sys.executable,
            "-c",
            "from paper_daily import onboarding; onboarding.accept(analytics=False)",
        ],
        recipient,
    )
    run("reader", [gui, "--paper", "demo:paperfact"], recipient)
    run("export", [cli, "list-export", "demo", "-o", returned], recipient)
    files = acceptance.call("file-fidelity", lambda: compare_files(original, returned))
    workspace = Path(recipient["PAPERFACT_DATA"])

    def content():
        from contextlib import closing

        with closing(sqlite3.connect(workspace / "papers.db")) as db:
            require(db.execute("SELECT count(*) FROM list_papers").fetchone()[0] == 1)
            require(bool(db.execute("SELECT body FROM dives").fetchone()[0]))

    acceptance.call("research-content", content)
    acceptance.call("credential-isolation", lambda: require(not (workspace / "llm.json").exists()))

    def integration_check(command, folder, env):
        from verify_local_integration import verify as verify_integration

        return verify_integration(command, folder, env)

    integration = acceptance.call(
        "local-integration", lambda: integration_check([cli], out / "integration-workspace", empty)
    )
    if sys.platform.startswith("linux"):
        from paper_daily import __version__

        appimage = ROOT / "dist" / f"Paperfact-{__version__}-linux-x86_64.AppImage"
        if appimage.exists():
            integration["appimage"] = acceptance.call(
                "appimage-integration",
                lambda: integration_check(
                    [appimage, "--cli"],
                    out / "appimage-workspace",
                    {**empty, "APPIMAGE_EXTRACT_AND_RUN": "1"},
                ),
            )
    if sys.platform == "darwin":
        # Launch Services + Cocoa, separate from offscreen startup/data checks.
        run(
            "mac-foreground",
            ["/usr/bin/swift", ROOT / "scripts/verify_mac_app.swift", built],
            {**recipient, "QT_QPA_PLATFORM": "cocoa", "PAPERFACT_SMOKE_SECONDS": "45"},
        )
    result = {
        "passed": True,
        "research_files_preserved": files,
        "integration": integration,
        "checks": [
            "version",
            "doctor",
            "first-use",
            "import",
            "duplicate-import",
            "reader",
            "export",
            "file-fidelity",
            "share-link-checksum",
            "json-cli",
            "mcp-stdio",
            "mcp-retry",
        ],
        "limitations": (
            "Packaged local workflows only; no real provider login, model call, Google Slides "
            "export, hosted multi-device sync, Safari or physical-phone acceptance."
        ),
    }
    if sys.platform == "darwin":
        result["checks"].append("mac-launch-services-foreground")
    return result


def verify(built, out):
    # A reused output directory must never overwrite an earlier acceptance run.
    try:
        out.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise OutputExists("Choose a new acceptance output directory") from None
    acceptance = Acceptance(built, out)
    try:
        result = _verify(built, out, acceptance)
    except BaseException as error:
        acceptance.failed(error)
        raise
    result = acceptance.finish(result)
    print(json.dumps(result))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("built", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    try:
        verify(args.built.resolve(), args.out.resolve())
    except KeyboardInterrupt:
        print(
            "Acceptance interrupted; inspect the chosen output folder/report.json.", file=sys.stderr
        )
        return 130
    except OutputExists:
        print(
            "Choose a new output directory; an existing report belongs to an earlier run.",
            file=sys.stderr,
        )
        return 1
    except (Exception, SystemExit):
        print(
            "Acceptance failed; inspect the chosen output folder/report.json if available. "
            "Raw logs stay local and need review before sharing.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
