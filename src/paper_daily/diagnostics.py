"""Bounded, content-minimized support reports; no upload, login, DB reads or AI."""

import argparse
import builtins
import faulthandler
import importlib.metadata
import json
import os
import platform
import re
import sys
import tempfile
import threading
import traceback
import zipfile
from pathlib import Path

from paper_daily import __version__, build_identity, executables, runtime

LIMIT = 256 * 1024
MAX_EVENTS = 40
_LOCK = threading.Lock()
_fault_stream = None
ERRORS = {name for name in dir(builtins) if name.endswith(("Error", "Exception"))} | {
    "OperationalError",
    "DatabaseError",
    "IntegrityError",
    "CancelledError",
    "OtherError",
}
PHASES = {"startup", "desktop", "worker", "native", "background"}
# Only shipped module names, never arbitrary names from user-controlled logs.
MODULES = frozenset(
    {
        "paper_daily",
        "paper_daily.cli",
        "paper_daily.runtime",
        "paper_daily.integration_entry",
        "paper_daily.diagnostics",
        "paper_daily.store",
        "paper_daily.llm",
        "paper_daily.ai_accounts",
        "paper_daily.ai_profiles",
        "paper_daily.ai_providers",
        "paper_daily.fetch",
        "paper_daily.analyze",
        "paper_daily.presentations",
        "paper_daily.research_chat",
        "paper_daily.desktop.main",
        "paper_daily.desktop.ask",
        "paper_daily.desktop.ai_access",
        "paper_daily.desktop.presentation_pane",
        "paper_daily.desktop.pdfpane",
        "paper_daily.desktop.activity",
        "paper_daily.desktop.workspace_changes",
        "paper_daily.document_reader",
        "paper_daily.updates",
        "paper_daily.desktop.update_banner",
    }
)
KNOWN_LOG_FILES = ("app.log", "app.log.1", "app-fault.log", "startup.log")


def location():
    configured = sys.modules.get("paper_daily.config")
    if configured is not None:
        return Path(configured.DATA_DIR)
    # Match normal launch configuration, but never export the environment/file.
    env = dict(os.environ)
    if not runtime.FROZEN:
        local = runtime.read_env_file(runtime.bundle_root() / ".env")
        for key in ("PAPERFACT_DATA", "PAPER_DAILY_DATA"):
            if key in local:
                env.setdefault(key, local[key])
    return runtime.data_dir(env=env)


def _regular(path):
    return not any(
        p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in (path, *path.parents)
    )


def _version(value):
    match = re.match(r"\d+(?:\.\d+){0,3}", str(value))
    return match[0] if match else "unknown"


PACKAGES = ("PySide6", "PySide6-Essentials", "PyMuPDF", "httpx")
_packages: dict = {}


def package_version(name):
    """Installed packages do not change while the app runs, and reading their
    metadata scans site-packages: the diagnostics dialog took half a second to open.
    Keyed by the lookup too, so a test's stand-in is asked afresh."""
    key = (importlib.metadata.version, name)
    if key not in _packages:
        try:
            _packages[key] = _version(importlib.metadata.version(name))
        except importlib.metadata.PackageNotFoundError:
            # Bundled modules can exist without distribution metadata.
            _packages[key] = "version-unavailable"
    return _packages[key]


def _event(value):
    """Reconstruct a closed report row; stored logs are not trusted input."""
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("phase"), str)
        or value["phase"] not in PHASES
    ):
        return None
    frames = []
    candidates = value.get("frames")
    for frame in candidates[:20] if isinstance(candidates, list) else []:
        if (
            isinstance(frame, dict)
            and isinstance(frame.get("module"), str)
            and frame["module"] in MODULES
            and type(frame.get("line")) is int
            and 1 <= frame["line"] <= 100000
        ):
            frames.append({"module": frame["module"], "line": frame["line"]})
    # No exception message, locals, function source, paths, IDs or arbitrary fields.
    kind = value.get("error_type")
    return {
        "phase": value["phase"],
        "error_type": kind if isinstance(kind, str) and kind in ERRORS else "OtherError",
        "frames": frames,
    }


def record_exception(kind, tb, *, phase="desktop", directory=None):
    try:
        directory = Path(directory) if directory is not None else location()
        if not _regular(directory):
            return False
        frames = (
            [
                {"module": frame.f_globals.get("__name__", ""), "line": line}
                for frame, line in traceback.walk_tb(tb)
            ]
            if tb
            else []
        )
        event = _event(
            {
                "phase": phase,
                "error_type": getattr(kind, "__name__", "OtherError"),
                "frames": frames[-20:],
            }
        )
        if event is None:
            return False
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "diagnostics.jsonl"
        if not _regular(path):
            return False
        with _LOCK:
            if path.exists() and path.stat().st_size > LIMIT:
                path.write_bytes(b"")
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, separators=(",", ":")) + "\n")
        return True
    except (OSError, ValueError, TypeError):
        return False  # Diagnostic storage must never break the user's operation.


def _tail(path):
    if not _regular(path) or not path.is_file():
        return None
    with path.open("rb") as stream:
        size = stream.seek(0, 2)
        stream.seek(max(0, size - LIMIT))
        data = stream.read(LIMIT)
    if size > LIMIT:
        data = data.partition(b"\n")[2]
    return data.decode("utf-8", errors="replace")


def _legacy(text):
    """Old release logs: retain only recognized app frames and error classes."""
    events, frames = [], []
    # Fixed module names keep arbitrary user filenames out of legacy exports.
    known = {
        "main",
        "ask",
        "ai_access",
        "presentation_pane",
        "pdfpane",
        "activity",
        "cli",
        "runtime",
        "integration_entry",
        "llm",
        "ai_accounts",
        "ai_profiles",
        "ai_providers",
        "store",
        "fetch",
        "analyze",
        "presentations",
    }
    for line in text.splitlines():
        match = re.search(r'[/\\]paper_daily[/\\](desktop[/\\])?([a-z_]+)\.py", line (\d+)', line)
        if match and match[2] in known:
            frames.append(
                {
                    "module": "paper_daily." + ("desktop." if match[1] else "") + match[2],
                    "line": int(match[3]),
                }
            )
        kind = re.match(r"^([A-Za-z]+(?:Error|Exception))(?::|$)", line)
        if kind and kind[1] in ERRORS:
            events.append({"phase": "desktop", "error_type": kind[1], "frames": frames[-20:]})
            frames = []
        elif line.startswith("Fatal Python error:"):
            events.append({"phase": "native", "error_type": "OtherError", "frames": []})
    return events[-MAX_EVENTS:]


def collect(directory=None):
    directory = Path(directory) if directory is not None else location()
    events, sources = [], {}
    for name in (*KNOWN_LOG_FILES, "diagnostics.jsonl"):
        try:
            text = _tail(directory / name)
            sources[name] = "available" if text is not None else "unavailable"
            if text is None:
                continue
            if name == "diagnostics.jsonl":
                for line in text.splitlines()[-MAX_EVENTS:]:
                    try:
                        event = _event(json.loads(line))
                    except (ValueError, TypeError, KeyError):
                        continue
                    if event:
                        events.append(event)
            else:
                events.extend(_legacy(text))
        except OSError:
            sources[name] = "unreadable"
    stalls = []
    for name in ("ui-stalls.log.1", "ui-stalls.log"):
        try:
            text = _tail(directory / name)
            sources[name] = "available" if text is not None else "unavailable"
            current = None
            for line in (text or "").splitlines():
                header = re.search(r"\bstall (\d{1,9}) ms \(stack in \d+/\d+ samples\)$", line)
                if header:
                    current = {"duration_ms": min(int(header[1]), 3600000), "frames": []}
                    stalls.append(current)
                elif current is not None:
                    frame = re.fullmatch(r"  ([\w.]+):[^:\n]*:(\d{1,6})", line)
                    if frame and frame[1] in MODULES and 0 < int(frame[2]) <= 100000:
                        current["frames"].append({"module": frame[1], "line": int(frame[2])})
                        current["frames"] = current["frames"][-8:]
        except OSError:
            sources[name] = "unreadable"
    packages = {name: package_version(name) for name in PACKAGES}
    machine = platform.machine().lower()
    return {
        "schema_version": 1,
        "app": "Paperfact",
        "version": __version__,
        "install": "release" if runtime.FROZEN else "source",
        "build": build_identity.identity(),
        "system": {
            "os": {"win32": "Windows", "darwin": "macOS", "linux": "Linux"}.get(
                sys.platform, "other"
            ),
            "release": _version(
                platform.mac_ver()[0] if sys.platform == "darwin" else platform.release()
            ),
            "architecture": machine
            if machine in {"arm64", "aarch64", "x86_64", "amd64", "x86", "i386", "i686"}
            else "other",
            "python": _version(platform.python_version()),
        },
        "packages": packages,
        "agent_commands_found": {
            name: executables.which(name) is not None for name in ("claude", "codex", "gemini")
        },
        "logs": sources,
        "errors": events[-MAX_EVENTS:],
        "ui_stalls": stalls[-20:],
        "limits": [
            "No raw messages, environment, paths, account identifiers or research content.",
            "No upload. This report is not guaranteed anonymous when shared.",
            "Only bounded log tails; events can come from earlier versions.",
            "Absent errors do not prove health; handled AI failures may not be logged.",
            "Command presence reflects this process PATH, not account login or quota.",
            "OS loader/Gatekeeper failures before Python starts need separate evidence.",
        ],
    }


def render(report):
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def export(report, destination):
    """Write exactly the reviewed payload, atomically; no automatic overwrite."""
    destination = Path(destination)
    if destination.exists() or not _regular(destination):
        raise FileExistsError("Choose a new diagnostic filename")
    payload = render(report).encode("utf-8")
    if len(payload) > LIMIT:
        raise ValueError("Diagnostic report exceeds its bound")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, suffix=".zip", delete=False
        ) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("diagnostics.json", payload)
            archive.writestr(
                "READ-ME.txt",
                "Review diagnostics.json before sharing. Do not attach your data folder, "
                "credentials or raw logs. GitHub issues are public. Describe steps, "
                "expected/actual results, and whether this came from a release "
                "or source checkout.\n",
            )
        # Exclusive publication: a destination that appears during generation is preserved.
        from paper_daily.sync_recovery_fs import publish_directory

        # The platform-exclusive rename primitive also publishes regular files.
        publish_directory(temporary, destination)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return destination


def install_error_hooks(*, phase="desktop", directory=None):
    """Local crash evidence before Qt/imports; retain the native handler's file."""
    global _fault_stream
    try:
        directory = Path(directory) if directory is not None else location()
        if not _regular(directory):
            return False
        directory.mkdir(parents=True, exist_ok=True)
        log = directory / "app.log"
        if not _regular(log):
            return False
        # Rotating once at launch bounds retained private tracebacks.
        if log.exists() and log.stat().st_size > LIMIT:
            previous = directory / "app.log.1"
            if _regular(previous):
                os.replace(log, previous)

        def hook(kind, value, tb, *, error_phase=phase):
            record_exception(kind, tb, phase=error_phase, directory=directory)
            try:
                if _regular(log):
                    with _LOCK:
                        if log.exists() and log.stat().st_size > LIMIT:
                            log.write_bytes(b"")
                        with log.open("a", encoding="utf-8") as stream:
                            traceback.print_exception(kind, value, tb, file=stream)
            except (OSError, ValueError):
                pass
            sys.__excepthook__(kind, value, tb)

        sys.excepthook = hook
        threading.excepthook = lambda args: hook(
            args.exc_type, args.exc_value, args.exc_traceback, error_phase="worker"
        )
        fault_path = directory / "app-fault.log"
        if not _regular(fault_path):
            return True
        if _fault_stream is not None:
            faulthandler.disable()
            _fault_stream.close()
            _fault_stream = None
        if fault_path.exists() and fault_path.stat().st_size > LIMIT:
            fault_path.write_bytes(b"")
        _fault_stream = fault_path.open("a", encoding="utf-8")
        faulthandler.enable(file=_fault_stream, all_threads=True)
        return True
    except (OSError, ValueError, RuntimeError):
        return False  # Startup remains usable when diagnostic storage is unavailable.


def main(argv=None):
    parser = argparse.ArgumentParser(prog="paperfact diagnostics")
    parser.add_argument(
        "--workspace", type=Path, help="Local data folder; never included in export"
    )
    parser.add_argument(
        "--output", type=Path, help="New ZIP filename; otherwise print safe preview"
    )
    args = parser.parse_args(argv)
    try:
        report = collect(args.workspace)
        if args.output:
            export(report, args.output)
            print(
                "Diagnostic package saved locally. Review it before sharing; nothing was uploaded."
            )
        else:
            print(render(report), end="")
    except (OSError, ValueError):
        print(
            "Could not create diagnostics. Choose a writable, new output filename.", file=sys.stderr
        )
        return 2
    return 0
