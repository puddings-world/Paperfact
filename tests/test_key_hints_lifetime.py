import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QTabBar  # noqa: E402
from shiboken6 import isValid  # noqa: E402

from paper_daily.desktop.key_hints import KeyHints  # noqa: E402


def test_closing_tabs_disconnects_global_focus_and_state_callbacks(monkeypatch):
    app = QApplication.instance() or QApplication([])
    failures = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: failures.append(error))
    for _ in range(5):
        bar = QTabBar()
        bar.addTab("Reading")
        hints = KeyHints(bar, Qt.KeyboardModifier.ControlModifier, lambda: ["1"], lambda: True)
        bar.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not isValid(hints)
        app.focusWindowChanged.emit(None)
        app.applicationStateChanged.emit(Qt.ApplicationState.ApplicationInactive)
        app.processEvents()
    assert failures == [], "\n".join("".join(traceback.format_exception(*e)) for e in failures)
