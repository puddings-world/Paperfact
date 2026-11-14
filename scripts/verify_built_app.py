"""Exercise a frozen app using generated research and isolated account/data homes."""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
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
    "lineage-audit",
    "lineage-audit-result",
    "credential-isolation",
    "local-integration",
    "appimage-integration",
    "mac-foreground",
    "windows-installer-preflight",
    "windows-install",
    "windows-installed-version",
    "windows-installed-reader",
    "windows-installed-integration",
    "windows-reinstall",
    "windows-uninstall",
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
               QT_QPA_PLATFORM=("cocoa" if sys.platform == "darwin" else
                                os.environ.get('QT_QPA_PLATFORM', 'offscreen')),
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
               HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9')
    system = Path(os.environ.get('SYSTEMROOT', '/usr'))
    env['PATH'] = os.pathsep.join(map(str, [Path(sys.executable).parent, system / 'System32',
                                          system] if os.name == 'nt' else ['/usr/bin', '/bin']))
    return env


def _safe_stamp(path):
    """Reject links/reparse points before executing anything that can remove files."""
    path = Path(path).absolute()
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Installer acceptance refuses linked paths")
    info = path.stat()
    if not info.st_ino:
        raise ValueError("Installer acceptance requires stable filesystem identities")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _file_hash(path, limit):
    before = _safe_stamp(path)
    if not path.is_file() or before[2] > limit:
        raise ValueError("Installer acceptance file exceeds its budget")
    digest = hashlib.sha256()
    used = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            used += len(chunk)
            if used > limit:
                raise ValueError("Installer acceptance file grew beyond its budget")
            digest.update(chunk)
    if before != _safe_stamp(path):
        raise ValueError("Installer acceptance file changed while checking")
    return digest.hexdigest()


def _data_hash(root):
    """Exact bounded fixture content; no traversal of a linked directory."""
    identity = _safe_stamp(root)[:2]
    pending, entries, used = [root], [], 0
    while pending:
        for path in pending.pop().iterdir():
            if len(entries) >= 4096:
                raise ValueError("Installer fixture exceeds its file budget")
            token = _safe_stamp(path)
            if path.is_dir():
                pending.append(path)
                entries.append((path.relative_to(root).as_posix(), None))
            elif path.is_file():
                used += token[2]
                if used > 64 * 1024**2:
                    raise ValueError("Installer fixture exceeds its byte budget")
                entries.append((path.relative_to(root).as_posix(), _file_hash(path, 64 * 1024**2)))
            else:
                raise ValueError("Installer fixture contains a special file")
    if identity != _safe_stamp(root)[:2]:
        raise ValueError("Installer fixture directory changed")
    return hashlib.sha256(json.dumps(sorted(entries)).encode("utf-8")).hexdigest()


def _installer_input(built, out, installer):
    """Only this repository's fresh CI build, never a maintainer's daily install."""
    from paper_daily import __version__

    root = ROOT.resolve()
    info = packaged_identity(built)
    if (sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REPOSITORY", "").casefold() != "puddings-world/paperfact"
            or Path(os.environ.get("GITHUB_WORKSPACE", "")).resolve() != root
            or info["dirty"] is not False or not info["commit"]
            or info["commit"] != os.environ.get("GITHUB_SHA")):
        raise ValueError("Installer acceptance requires a matching clean Windows CI build")
    installer = Path(installer).absolute()
    if (built != root / "dist/Paperfact" or out.parent != root / "build"
            or installer != root / "dist" / f"Paperfact-{__version__}-windows-x64-setup.exe"):
        raise ValueError("Installer acceptance requires the expected CI artifact paths")
    identity = _safe_stamp(out)[:2]
    token = _safe_stamp(installer)
    if not token[2]:
        raise ValueError("Installer acceptance requires a nonempty executable")
    digest = _file_hash(installer, 512 * 1024**2)
    installed = out / "installed-app"
    installed.mkdir(exist_ok=False)
    return dict(installer=installer, token=token, sha256=digest, installed=installed,
                install_identity=_safe_stamp(installed)[:2], output_identity=identity,
                source_identity=info, version=__version__)


def _windows_install(plan, out, recipient, empty, run, acceptance, integration_check):
    installed, installer = plan["installed"], plan["installer"]
    data = Path(recipient["HOME"]).parent
    if acceptance.report["build"]["version"] != plan["version"]:
        raise ValueError("Frozen version differs from the CI source version")
    if data != out / "recipient":
        raise ValueError("Installer data must be the exact generated recipient")

    def owned(*, may_be_removed=False):
        if _safe_stamp(out)[:2] != plan["output_identity"]:
            raise ValueError("Installer output directory changed")
        if (not may_be_removed or installed.exists()) and (
            _safe_stamp(installed)[:2] != plan["install_identity"]
        ):
            raise ValueError("Installer destination directory changed")
        if _safe_stamp(installer) != plan["token"]:
            raise ValueError("Installer bytes changed since preflight")

    def mutate(label, command, *, uninstall=False):
        snapshot = []

        def ready():
            owned()
            if uninstall:
                _safe_stamp(command[0])
            snapshot.append(_data_hash(data))

        def retained(stdout):
            owned(may_be_removed=uninstall)
            if snapshot[0] != _data_hash(data):
                raise ValueError("Installer changed the research fixture")
            if uninstall and any(
                (installed / name).exists() for name in ("Paperfact.exe", "paperfact-cli.exe")
            ):
                raise ValueError("Uninstall left executable payloads behind")
            if not uninstall and packaged_identity(installed) != plan["source_identity"]:
                raise ValueError("Installed source identity differs from the frozen bundle")

        run(label, [*command, "/LOG=" + str(out / (label + "-inno.log"))],
            recipient, before=ready, after=retained)

    flags = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
    setup = [installer, *flags, "/SP-", "/LANG=en", "/NOCLOSEAPPLICATIONS",
             "/NORESTARTAPPLICATIONS", "/ACCEPTANCETEST=1", "/DIR=" + str(installed)]
    mutate("windows-install", setup)
    def version_matches(stdout):
        if stdout.strip() != ("paperfact " + plan["version"]).encode("ascii"):
            raise ValueError("Installed executable reports a different version")

    run("windows-installed-version", [installed / "paperfact-cli.exe", "--version"],
        recipient, after=version_matches)
    run("windows-installed-reader", [installed / "Paperfact.exe", "--paper", "demo:paperfact"],
        recipient)
    integration = acceptance.call(
        "windows-installed-integration",
        lambda: integration_check([installed / "paperfact-cli.exe"],
                                  out / "installed-integration", empty),
    )
    mutate("windows-reinstall", setup)
    uninstaller = installed / "unins000.exe"
    mutate("windows-uninstall", [uninstaller, *flags], uninstall=True)
    return dict(installed=True, reinstalled=True, uninstalled=True, research_preserved=True,
                installer_sha256=plan["sha256"], integration=integration,
                acceptance_mode=True, older_release_upgrade_checked=False,
                registry_shortcuts_checked=False)


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


def _verify(built, out, acceptance, *, installer=None):
    installation = acceptance.call(
        "windows-installer-preflight", lambda: _installer_input(built, out, installer),
    ) if installer is not None else None
    folder = built / "Contents/MacOS" if sys.platform == "darwin" else built
    ext = ".exe" if os.name == "nt" else ""
    cli, gui = folder / ("paperfact-cli" + ext), folder / ("Paperfact" + ext)

    def run(label, command, env, *, before=None, after=None):
        def execute():
            if before is not None:
                before()
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
            if after is not None:
                after(result.stdout)
            return result.stdout

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
        "from pathlib import Path; demo_workspace.acceptance_package(Path(sys.argv[1]))"
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
    # Two native Mac candidates crashed here while a later one passed. Require
    # three consecutive launches of the same bundle/workspace; never retry a failure.
    reader_launches = 3 if sys.platform == "darwin" else 1
    for _ in range(reader_launches):
        run("reader", [gui, "--paper", "demo:paperfact"], recipient)
    run("export", [cli, "list-export", "demo", "-o", returned], recipient)
    files = acceptance.call("file-fidelity", lambda: compare_files(original, returned))
    workspace = Path(recipient["PAPERFACT_DATA"])

    def content():
        from contextlib import closing

        with closing(sqlite3.connect(workspace / "papers.db")) as db:
            require(db.execute("SELECT count(*) FROM list_papers").fetchone()[0] == 1)
            require(bool(db.execute("SELECT body FROM dives").fetchone()[0]))
            rows = db.execute("SELECT paper_id,corpus_key FROM paper_lineage_sets").fetchall()
            require(len(rows) == 1 and rows[0][0] == "demo:paperfact")
            return dict(paper_id=rows[0][0], corpus_key=rows[0][1])

    audit_args = acceptance.call("research-content", content)
    arguments = out / "lineage-input.json"
    arguments.write_text(json.dumps(audit_args), encoding="utf-8")
    audit_output = run(
        "lineage-audit",
        [cli, "integration", "analysis.audit", "--workspace", workspace, "--file", arguments],
        recipient,
    )

    def checked_lineage():
        require(len(audit_output) <= 2 * 1024**2)
        response = json.loads(audit_output.decode("utf-8"))
        require(response.get("ok") is True)
        report = response["result"]
        require(report["format"] == "paperfact.lineage-audit.v1")
        require(report["originals_checked"] == report["originals_total"] == 3)
        require(len(report["sources"]) == 3 and report["semantics"] == "not_checked")
        require(all(source["state"] == "available" for source in report["sources"]))
        checks = [check for source in report["sources"] for check in source["report"]["checks"]
                  if check["rule"] == "quote_location"]
        require(len(checks) == 5 and all(check["state"] == "located" for check in checks))

    acceptance.call("lineage-audit-result", checked_lineage)
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
        # Launch Services foreground activation, separate from direct reader startup.
        run(
            "mac-foreground",
            ["/usr/bin/swift", ROOT / "scripts/verify_mac_app.swift", built],
            {**recipient, "QT_QPA_PLATFORM": "cocoa", "PAPERFACT_SMOKE_SECONDS": "45"},
        )
    result = {
        "passed": True,
        "research_files_preserved": files,
        "reader_launches_verified": reader_launches,
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
            "lineage-corpus",
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
    if installation is not None:
        result["windows_installer"] = _windows_install(
            installation, out, recipient, empty, run, acceptance, integration_check,
        )
        result["checks"].append("windows-install-reinstall-uninstall")
        result["limitations"] += (
            " Isolated CI install and same-version reinstall only; no older-release upgrade "
            "or registry/shortcut audit."
        )
    return result


def verify(built, out, *, installer=None):
    # A reused output directory must never overwrite an earlier acceptance run.
    try:
        out.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise OutputExists("Choose a new acceptance output directory") from None
    acceptance = Acceptance(built, out)
    try:
        result = _verify(built, out, acceptance, installer=installer)
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
    parser.add_argument("--installer", type=Path,
                        help="Windows CI only: verify isolated install/reinstall/uninstall")
    args = parser.parse_args(argv)
    try:
        verify(args.built.resolve(), args.out.resolve(),
               installer=args.installer.absolute() if args.installer else None)
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
