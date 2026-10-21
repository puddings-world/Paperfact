"""Input handlers watch the app's windows and focused widget, never the whole
application: on Linux an application-wide Python filter crashed the app as soon as
a window showing a web view was resized."""

import os

import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QTabBar, QVBoxLayout, QWidget

from paper_daily import llm, store
from paper_daily.desktop import key_hints, window_events
from paper_daily.desktop.main import MainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_the_main_window_installs_no_application_wide_filter(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    store.init_db()
    on_app = []
    install = QObject.installEventFilter

    def recording(self, handler):
        if self is app:
            on_app.append(type(handler).__name__)
        return install(self, handler)

    monkeypatch.setattr(QObject, "installEventFilter", recording)
    widget = MainWindow()
    monkeypatch.setattr(widget, "top_up_dives", lambda: None)
    widget.show()
    widget.activateWindow()
    app.processEvents()
    assert on_app == []
    widget.close()
    widget.deleteLater()
    app.processEvents()


@pytest.fixture
def hinted():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    bar = QTabBar()
    bar.addTab("one")
    bar.addTab("two")
    edit = QLineEdit()
    layout = QVBoxLayout(host)
    layout.addWidget(bar)
    layout.addWidget(edit)
    hints = key_hints.KeyHints(
        bar, Qt.KeyboardModifier.ControlModifier, lambda: ["1", "2"], lambda: True
    )
    host.show()
    host.activateWindow()
    edit.setFocus()
    app.processEvents()
    yield app, host, edit, hints
    host.deleteLater()
    app.processEvents()


def test_holding_the_modifier_in_a_focused_field_shows_the_badges(hinted, monkeypatch):
    app, _host, edit, hints = hinted
    monkeypatch.setattr(key_hints, "DELAY_MS", 0)
    hints._timer.setInterval(0)
    QTest.keyPress(edit, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(20)
    assert [b.text() for b in hints.badges] == ["1", "2"]
    QTest.keyRelease(edit, Qt.Key.Key_Control)
    assert hints.badges == []


def test_a_handler_that_is_gone_is_skipped_when_focus_moves(hinted):
    app, host, edit, _hints = hinted
    gone = QObject()
    window_events.watch(gone)
    gone.deleteLater()
    app.processEvents()
    other = QLineEdit(host)
    host.layout().addWidget(other)
    other.setFocus()
    app.processEvents()
    assert other.hasFocus()
