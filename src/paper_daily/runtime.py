"""Where the app is running from: a source checkout, or an installed build.

An installed build (PyInstaller) unpacks its code and resources into one folder that
may be replaced wholesale by the next update, so user data cannot live beside it as
it does in a checkout. It also cannot run `python -m paper_daily`: there is no
interpreter to hand `-m` to, only the two executables the build ships.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_NAME = "Paperfact"
FROZEN = bool(getattr(sys, "frozen", False))
# The console twin of the windowed app, shipped beside it: background jobs need
# stdout, which a windowed executable on Windows does not have.
CLI_NAME = "paperfact-cli"


def bundle_root() -> Path:
    """The folder holding fonts/, vendor/ and assets/: the checkout, or the build's."""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def user_data_dir(platform: str = sys.platform, env=os.environ, home: Path | None = None) -> Path:
    """Each platform's place for an application's own files, which updates never touch."""
    home = home or Path.home()
    if platform == "win32":
        base = env.get("APPDATA")
        return (Path(base) if base else home / "AppData" / "Roaming") / APP_NAME
    if platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    base = env.get("XDG_DATA_HOME")
    return (Path(base) if base else home / ".local" / "share") / APP_NAME


def data_dir(env=os.environ, frozen: bool = FROZEN) -> Path:
    """Where papers.db, PDFs and notes go, unless PAPERFACT_DATA says otherwise.

    A checkout keeps them beside the code; an installed build's folder is replaced
    by every update, so its data lives where the platform keeps app data.
    """
    chosen = env.get("PAPERFACT_DATA") or env.get("PAPER_DAILY_DATA")
    if chosen:
        return Path(chosen)
    return user_data_dir(env=env) if frozen else bundle_root() / "data"


def read_env_file(path: Path) -> dict[str, str]:
    """`KEY=value` lines from a .env file; blank lines and # comments are skipped and
    one pair of matching quotes around a value is dropped."""
    if not path.is_file():
        return {}
    found = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key.startswith("export "):
            key = key[len("export "):].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            found[key] = value
    return found


def load_env_file(env=os.environ, frozen: bool = FROZEN, path: Path | None = None) -> None:
    """Apply a checkout's .env, so one ignored file keeps a maintainer's data folder
    and keys out of the repo. A variable already set in the environment wins, and an
    installed build has no checkout, so it never reads one."""
    if frozen:
        return
    for key, value in read_env_file(path or bundle_root() / ".env").items():
        env.setdefault(key, value)


def cli_command(*args: str, frozen: bool = FROZEN, executable: str = sys.executable) -> list[str]:
    """The command line that runs a `paperfact` subcommand in a separate process."""
    if not frozen:
        return [executable, "-m", "paper_daily", *args]
    name = CLI_NAME + (".exe" if sys.platform == "win32" else "")
    return [str(Path(executable).with_name(name)), *args]


def login_path(shell: str | None = None, timeout: float = 4.0) -> str | None:
    """The PATH a terminal would have.

    Apps opened from Finder or a desktop launcher get a bare system PATH, which hides
    the claude / codex / gemini CLIs that npm and Homebrew put in the user's own
    directories, and the AI features would report them as not installed.
    """
    shell = shell or os.environ.get("SHELL") or "/bin/sh"
    try:
        done = subprocess.run(
            [shell, "-ilc", 'printf "%s" "$PATH"'],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip().splitlines()[-1] if done.stdout.strip() else None


def merged_path(current: str, login: str | None) -> str:
    """The login shell's PATH first, then anything only this process had."""
    if not login:
        return current
    seen: list[str] = []
    for part in [*login.split(os.pathsep), *current.split(os.pathsep)]:
        if part and part not in seen:
            seen.append(part)
    return os.pathsep.join(seen)


def adopt_login_path() -> None:
    if FROZEN and sys.platform != "win32":
        os.environ["PATH"] = merged_path(os.environ.get("PATH", ""), login_path())
