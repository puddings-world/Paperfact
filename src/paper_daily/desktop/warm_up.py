"""Pay first-use costs while the window is idle, not when they are asked for.

The first paper opened imported PyMuPDF and built the Markdown parser (a quarter
to half a second), the first 本地整合 imported pydantic (half a second), the first
診斷與回報 walked PATH for three agent CLIs and read package metadata, and the first
AI 設定 looked for its CLI again. Each froze the window just as it was asked for.
Done once on a thread soon after startup, they find it all ready. Only lookups
and imports happen here: no widget is made and nothing is written.
"""

from __future__ import annotations

import importlib
import platform
import threading

from paper_daily import diagnostics, executables

DELAY_MS = 1500
PROGRAMS = ("claude", "codex", "gemini", "node")
MODULES = (
    "paper_daily.local_operations",
    "paper_daily.desktop.integration_dialog",
    "paper_daily.desktop.ai_picker",
    "paper_daily.desktop.bundle_dialog",
    "paper_daily.desktop.bundle_link_dialog",
)


def warm() -> None:
    # What opening the first paper waits for, before what the dialogs do.
    importlib.import_module("pymupdf")
    from paper_daily.desktop import rich_html

    rich_html.markdown("**warm**")
    for name in PROGRAMS:
        executables.which(name)
    for name in diagnostics.PACKAGES:
        diagnostics.package_version(name)
    # Asked of the system once and remembered; on Windows the first ask is slow.
    platform.uname()
    for module in MODULES:
        importlib.import_module(module)


def start() -> threading.Thread:
    thread = threading.Thread(target=warm, name="warm-up", daemon=True)
    thread.start()
    return thread
