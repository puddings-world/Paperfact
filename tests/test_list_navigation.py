import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from paper_daily import llm, store
from paper_daily.desktop.main import MainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    store.init_db()
    # Navigation operates on an explicitly created list; fresh installs no longer
    # manufacture an ML queue merely to provide a selectable item.
    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('first','First list','now')")
        conn.commit()
    widget = MainWindow()
    monkeypatch.setattr(widget, "top_up_dives", lambda: None)
    widget.show()
    widget.activateWindow()
    app.processEvents()
    yield widget, app
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_alt_left_opens_list_overview_with_current_list_focused(window):
    widget, app = window
    widget.show_queue()
    QTest.keyClick(widget.queue_page.view, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    app.processEvents()
    assert widget.stack.currentWidget() is widget.lists_page
    assert widget.lists_page.view.currentRow() == widget.list_picker.currentIndex()
    assert QApplication.focusWidget() is widget.lists_page.view
    QTest.keyClick(widget.lists_page.view, Qt.Key.Key_Return)
    assert widget.stack.currentWidget() is widget.queue_page
    assert QApplication.focusWidget() is widget.queue_page.view


def test_overview_arrows_enter_lists_and_empty_lists_are_safe(window):
    widget, app = window
    # The picker is the overview's source, so this also covers arbitrary future list modules.
    widget.list_picker.blockSignals(True)
    widget.list_picker.addItem("Independent research", "research")
    widget.list_picker.blockSignals(False)
    widget.lists_page.refresh()
    widget.stack.setCurrentWidget(widget.lists_page)
    app.processEvents()
    QTest.keyClick(widget.lists_page.view, Qt.Key.Key_Down)
    QTest.keyClick(widget.lists_page.view, Qt.Key.Key_Right)
    assert widget.active_list == "research"
    assert widget.stack.currentWidget() is widget.queue_page
    QTest.keyClick(widget.queue_page.view, Qt.Key.Key_Right)
    assert widget.stack.currentWidget() is widget.queue_page
    widget.go_back()
    assert widget.stack.currentWidget() is widget.lists_page
    widget.go_forward()
    assert widget.stack.currentWidget() is widget.queue_page


def test_enter_opens_a_list_even_where_the_view_does_not_activate_on_enter(window):
    # macOS list views take Return as "edit" and emit no itemActivated signal.
    widget, app = window
    widget.show_lists()
    app.processEvents()
    widget.lists_page.view.blockSignals(True)
    QTest.keyClick(widget.lists_page.view, Qt.Key.Key_Return)
    assert widget.stack.currentWidget() is widget.queue_page
