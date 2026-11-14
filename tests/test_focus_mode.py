"""Focus mode leaves only the page on screen and puts the layout back afterwards."""

from PySide6.QtCore import Qt
from test_workspace_transfer_ui import workspace as _workspace

from paper_daily.desktop.main import MainWindow

workspace = _workspace


def _chrome(win):
    reader = win.reader_page
    return {
        "toolbar": win.top_toolbar,
        "header": reader.paper_header,
        "pdf bar": reader.pdf_bar,
        "panels": reader.tabs,
    }


def _shown(win):
    return {name for name, widget in _chrome(win).items() if widget.isVisibleTo(win)}


def test_focus_hides_everything_but_the_page_and_restores_it(workspace, monkeypatch):
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest

    original = QKeySequence.keyBindings
    monkeypatch.setattr(QKeySequence, "keyBindings", lambda value: [] if value ==
                        QKeySequence.StandardKey.FullScreen else original(value))
    app, _ = workspace
    win = MainWindow()
    try:
        win.show()
        # Only the reader has a page to focus on.
        assert not win.focus_mode.enter()
        win.stack.setCurrentWidget(win.reader_page)
        before = _shown(win)
        assert {"toolbar", "pdf bar", "panels"} <= before

        win.reader_page.focus_button.click()
        assert win.focus_mode.active and _shown(win) == set()
        assert win.windowState() & Qt.WindowState.WindowFullScreen
        assert win.focus_mode.hint.isVisible() and "Esc" in win.focus_mode.hint.text()

        win.focus_mode.escape.activated.emit()
        assert not win.focus_mode.active and _shown(win) == before
        assert not win.windowState() & Qt.WindowState.WindowFullScreen
        win.activateWindow()
        win.setFocus()
        app.processEvents()
        assert "F11" in win.reader_page.focus_button.toolTip()
        QTest.keyClick(win, Qt.Key.Key_F11)
        app.processEvents()
        assert win.focus_mode.active
        QTest.keyClick(win, Qt.Key.Key_F11)
        app.processEvents()
        assert not win.focus_mode.active and _shown(win) == before
    finally:
        win.close()
        win.deleteLater()


def test_a_collapsed_toolbar_stays_collapsed_and_leaving_the_reader_ends_focus(workspace):
    win = MainWindow()
    try:
        win.show()
        win.stack.setCurrentWidget(win.reader_page)
        win.top_toggle.setChecked(True)
        before = _shown(win)
        assert "toolbar" not in before

        win.focus_mode.toggle()
        assert win.focus_mode.active
        win.stack.setCurrentWidget(win.queue_page)
        assert not win.focus_mode.active
        win.stack.setCurrentWidget(win.reader_page)
        assert _shown(win) == before
        # Esc does nothing outside focus mode, so it keeps its other meanings.
        assert not win.focus_mode.escape.isEnabled()
    finally:
        win.close()
        win.deleteLater()


def test_the_reading_ruler_is_remembered_and_only_lives_in_focus_mode(workspace):
    from paper_daily.desktop import ui_state

    win = MainWindow()
    try:
        win.show()
        win.stack.setCurrentWidget(win.reader_page)
        assert not win.focus_mode.ruler_key.isEnabled()
        win.focus_mode.enter()
        assert win.focus_mode.ruler_key.isEnabled() and not win.focus_mode.ruler
        assert "R 閱讀尺" in win.focus_mode.hint.text()
        win.focus_mode.ruler_key.activated.emit()
        assert win.focus_mode.ruler
        ui_state.flush()
        win.focus_mode.leave()
        assert not win.focus_mode.ruler_key.isEnabled()
        win.focus_mode.enter()
        assert win.focus_mode.ruler
    finally:
        win.close()
        win.deleteLater()
