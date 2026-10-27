"""Explicit new-process workspace opening; never rebind the running reader."""

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from paper_daily.workspace_service import _safe_path

STARTUP = "PAPERFACT_OPEN_WORKSPACE"


@dataclass(frozen=True)
class WorkspaceDestination:
    workspace_root: Path
    database_path: Path
    paper_id: str | None = None
    deck_id: str | None = None

    def checked(self):
        if any(
            not isinstance(value, (str, Path)) or not Path(value).is_absolute()
            for value in (self.workspace_root, self.database_path)
        ):
            raise ValueError("Workspace paths must be explicit absolute paths")
        root, database = _safe_path(self.workspace_root), _safe_path(self.database_path)
        if database != root / "papers.db" or not root.is_dir() or not database.is_file():
            raise ValueError("Choose an existing Paperfact workspace")
        for identifier in (self.paper_id, self.deck_id):
            if identifier is not None and (
                not isinstance(identifier, str)
                or not identifier
                or len(identifier) > 512
                or any(ord(char) < 32 for char in identifier)
            ):
                raise ValueError("Invalid workspace focus")
        if self.deck_id and not self.paper_id:
            raise ValueError("A deck needs its explicit paper")
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)) as conn:
            conn.execute("SELECT id FROM papers LIMIT 1").fetchall()
            if (
                self.paper_id
                and not conn.execute("SELECT 1 FROM papers WHERE id=?", (self.paper_id,)).fetchone()
            ):
                raise ValueError("The selected paper is not in this workspace")
        if self.deck_id:
            try:
                from paper_daily.recovery_deck_copy import locate
            except ImportError as exc:
                raise ValueError(
                    "This build does not include editable recovered-deck support"
                ) from exc

            if locate(database, paper_id=self.paper_id, deck_id=self.deck_id) is None:
                raise ValueError("The selected editable deck is not in this workspace")
        return WorkspaceDestination(root, database, self.paper_id, self.deck_id)

    def payload(self):
        return {
            "workspace_root": str(self.workspace_root),
            "database_path": str(self.database_path),
            "paper_id": self.paper_id,
            "deck_id": self.deck_id,
        }


def destination(value):
    if isinstance(value, WorkspaceDestination):
        return value.checked()
    if not isinstance(value, dict) or set(value) != {
        "workspace_root",
        "database_path",
        "paper_id",
        "deck_id",
    }:
        raise ValueError("Invalid workspace destination")
    return WorkspaceDestination(**value).checked()


def _environment(environ):
    # Pass OS/display prerequisites, not provider credentials, job flags or tokens.
    allowed = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "LANG",
        "LANGUAGE",
        "LC_ALL",
        "LC_CTYPE",
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "XDG_RUNTIME_DIR",
        "XDG_DATA_HOME",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "DBUS_SESSION_BUS_ADDRESS",
        "QT_QPA_PLATFORM",
        "QTWEBENGINE_DISABLE_SANDBOX",
        "FONTCONFIG_PATH",
        "FONTCONFIG_FILE",
    }
    return {key: value for key, value in environ.items() if key.upper() in allowed}


def open_workspace(value, *, launch=None, environ=None, executable=None, frozen=None):
    """Launch or raise the destination's existing reader; leave this one untouched."""
    chosen = destination(value)
    info = chosen.database_path.stat()
    environment = _environment(os.environ if environ is None else environ)
    environment["PAPERFACT_DATA"] = str(chosen.workspace_root)
    environment[STARTUP] = json.dumps(
        {"destination": chosen.payload(), "identity": [info.st_dev, info.st_ino]},
        separators=(",", ":"),
    )
    packaged = getattr(sys, "frozen", False) if frozen is None else frozen
    command = [str(executable or sys.executable)]
    if not packaged:
        command += ["-m", "paper_daily.integration_entry", "app"]
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
    kwargs = {
        "env": environment,
        "cwd": str(chosen.workspace_root),
        "shell": False,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    (launch or subprocess.Popen)(command, **kwargs)
    return chosen


def consume_startup(database_path, *, environ=None):
    """Validate before startup migrations; remove inherited routing after use."""
    environment = os.environ if environ is None else environ
    raw = environment.pop(STARTUP, None)
    if raw is None:
        return None
    if len(raw) > 8192:
        raise ValueError("Invalid workspace launch")
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {"destination", "identity"}:
        raise ValueError("Invalid workspace launch")
    identity = value["identity"]
    if (
        not isinstance(identity, list)
        or len(identity) != 2
        or any(type(part) is not int or part < 0 for part in identity)
    ):
        raise ValueError("Invalid workspace file identity")
    chosen = destination(value["destination"])
    info = chosen.database_path.stat()
    if chosen.database_path != _safe_path(database_path) or value["identity"] != [
        info.st_dev,
        info.st_ino,
    ]:
        raise ValueError("The selected workspace changed before opening")
    return chosen


def focus_workspace(window, value):
    """Use the normal paper-navigation guard; do not replace current editor state."""
    chosen = destination(value)
    from paper_daily import store

    if chosen.database_path != Path(store.DB_PATH).resolve():
        raise ValueError("The destination does not match this reader")
    if not chosen.paper_id:
        return
    reader = window.reader_page
    if reader.paper is None or reader.paper.id != chosen.paper_id:
        pane = reader.presentation_pane
        if (
            pane._dirty
            or pane.busy
            or reader.ask_box.text().strip()
            or reader.note_edit.toPlainText().strip()
        ):
            return  # Raising an existing window must not navigate away from drafts.
        window.open_anywhere(chosen.paper_id)
    if reader.paper is None or reader.paper.id != chosen.paper_id or not chosen.deck_id:
        return
    from paper_daily.recovery_deck_copy import locate

    record = locate(chosen.database_path, paper_id=chosen.paper_id, deck_id=chosen.deck_id)
    pane = reader.presentation_pane
    if record and not pane._dirty and not pane.busy:
        index = pane.mode.findData(record["slot"])
        if index >= 0:
            pane.mode.setCurrentIndex(index)
            reader.tabs.setCurrentWidget(pane)


def focus_command(raw):
    """Bounded newline-framed local IPC; None means an incomplete focus request."""
    prefix = b"workspace-open:"
    if not isinstance(raw, bytes) or len(raw) > 8192:
        raise ValueError("Invalid workspace focus")
    if prefix.startswith(raw):
        return None
    if not raw.startswith(prefix):
        raise ValueError("Invalid workspace focus")
    if not raw.endswith(b"\n"):
        return None
    return destination(json.loads(raw[len(prefix) : -1].decode("utf-8")))
