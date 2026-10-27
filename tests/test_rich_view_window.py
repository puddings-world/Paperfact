"""Showing typeset text for the first time must not recreate the window.

Run in a child process: the web engine needs a QApplication made with shared OpenGL
contexts and a real window system, and the suite's own views are plain text.
"""

import importlib.util
import os
import subprocess
import sys

import pytest

from paper_daily.web_assets import WEB_DIR

SCRIPT = r"""
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QStackedWidget
from paper_daily.desktop import rich_view
from paper_daily.desktop.main import palette

sys.excepthook = lambda *exc: (sys.__excepthook__(*exc), sys.exit(1))

rich_view.prepare()
app = QApplication(sys.argv)
win = QMainWindow()
stack = QStackedWidget()
stack.addWidget(QLabel("list"))
view = rich_view.RichView(palette())
assert view.rich
stack.addWidget(view)
win.setCentralWidget(stack)
win.show()
first = int(win.winId())
handles = []

def open_reader():
    stack.setCurrentWidget(view)
    view.setHtml("<p>A paper</p>")
    QTimer.singleShot(1500, finish)

def finish():
    handles.append(int(win.winId()))
    app.quit()

QTimer.singleShot(500, open_reader)
app.exec()
print("same" if handles == [first] else f"recreated {first} -> {handles}")
"""


@pytest.mark.skipif(sys.platform != "win32", reason="checked against the Windows window system")
@pytest.mark.skipif(
    importlib.util.find_spec("PySide6.QtWebEngineWidgets") is None
    or not (WEB_DIR / "katex" / "katex.min.js").exists(),
    reason="needs Qt WebEngine and the vendored web assets",
)
def test_opening_the_reader_keeps_the_same_window():
    env = {
        k: v for k, v in os.environ.items() if k not in ("PAPERFACT_PLAIN_VIEWS", "QT_QPA_PLATFORM")
    }
    done = subprocess.run(
        [sys.executable, "-c", SCRIPT], capture_output=True, text=True, timeout=60, env=env
    )
    assert done.stdout.strip().splitlines()[-1:] == ["same"], done.stdout + done.stderr
