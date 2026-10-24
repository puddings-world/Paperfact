"""Portable launch settings; no account credentials or host-config mutations."""

import os
from pathlib import Path

from paper_daily import runtime
from paper_daily.config import DATA_DIR


def host_config():
    args = ["mcp", "--workspace", str(DATA_DIR.resolve())]
    if runtime.FROZEN and os.environ.get("APPIMAGE"):
        command = [os.environ["APPIMAGE"], "--cli", *args]
    else:
        command = runtime.cli_command(*args)
    # pythonw has no console streams. A GUI-launched source checkout needs its
    # console twin for the stdio protocol, even though the desktop stays windowless.
    if Path(command[0]).name.lower() == "pythonw.exe":
        command[0] = str(Path(command[0]).with_name("python.exe"))
    return {
        "mcpServers": {
            "paperfact": {"command": str(command[0]), "args": [str(arg) for arg in command[1:]]}
        }
    }
