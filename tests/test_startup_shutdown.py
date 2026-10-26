"""A pending startup fit must survive native WebEngine window destruction."""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROBE = r'''
import sys
if sys.platform == "win32":
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x8003)
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from shiboken6 import delete, isValid
from paper_daily.desktop.reading_layout import _StartupFit, schedule_startup_fit

QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
app = QApplication([])
window = QWidget()
layout = QVBoxLayout(window)
view = QWebEngineView(window)
profile = QWebEngineProfile(window)  # Off the record; outlives the earlier-created view.
view.setPage(QWebEnginePage(profile, view))
layout.addWidget(view)
view.setHtml("<p>Isolated shutdown regression</p>")
window.show()
window.activateWindow()
view.setFocus()
for _ in range(5):
    app.processEvents()
# Fast CI rendering can finish while normal startup fitting is still pending.
# Keep that lifecycle state deterministic without sleeping or calling any model.
_StartupFit._DELAYS = (60000,)
handler = schedule_startup_fit(window)
assert handler.active
if sys.argv[1] == "native-delete":
    delete(window)
    assert not isValid(window) and not isValid(handler)
    app.processEvents()
print("SCREENSHOTS_COMPLETE", flush=True)
# Intentionally exercise interpreter teardown without an explicit close. This
# mirrors the screenshot script after writing its final report.
'''


@pytest.mark.parametrize("mode", ["fast-exit", "native-delete"])
def test_active_startup_fit_native_shutdown_exits_cleanly(tmp_path, mode):
    if importlib.util.find_spec("PySide6.QtWebEngineWidgets") is None:
        pytest.skip("The optional Qt WebEngine runtime is not installed")
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "PAPERFACT_DATA": str(tmp_path / "workspace"),
        "QT_QPA_PLATFORM": "offscreen",
        "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu",
    }
    command = [sys.executable, "-X", "faulthandler", "-c", PROBE, mode]
    if sys.platform.startswith("linux"):
        xvfb = shutil.which("xvfb-run")
        if xvfb is None:
            pytest.skip("Real WebEngine needs an isolated Xvfb display on Linux")
        env["QT_QPA_PLATFORM"] = "xcb"
        command = [xvfb, "-a", "-s", "-screen 0 800x600x24", *command]
    result = subprocess.run(
        command,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SCREENSHOTS_COMPLETE" in result.stdout
