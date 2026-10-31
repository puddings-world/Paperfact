"""The actual reader toolbar wraps all controls without changing research or focus."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_window_fits import reader as reader_fixture

from paper_daily import llm
from paper_daily.desktop.ai_dialog import AIStatusButton

base_reader = reader_fixture


@pytest.fixture
def reader(base_reader):
    window, app = base_reader
    # This suite exercises a user-controlled resize, after startup fitting yields.
    # Genuine harmless input uses the same public ownership boundary as a user.
    window.activateWindow()
    QTest.keyClick(window, Qt.Key.Key_Shift)
    app.processEvents()
    return window, app


@pytest.fixture(autouse=True)
def fake_account_status(monkeypatch):
    def refresh(button):
        button.setText("AI: Fixture / Model A")
        button.setToolTip("Fixture account / Model A; no live account lookup")

    monkeypatch.setattr(AIStatusButton, "refresh", refresh)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("Resize called AI"))
    monkeypatch.setattr(llm, "probe", lambda *a, **k: pytest.fail("Resize probed an account"))


def settle(app):
    for _ in range(4):
        app.processEvents()


def controls(window):
    layout = window.top_toolbar.layout()
    return [
        layout.itemAt(i).widget()
        for i in range(layout.count())
        if layout.itemAt(i).widget() is not None and not layout.itemAt(i).isEmpty()
    ]


def english(window):
    for widget, text in (
        (window.back_btn, "Back"),
        (window.research_data_button, "Research data"),
        (window.schedule_btn, "Analysis queue"),
        (window.read_btn, "Mark read"),
        (window.next_btn, "Next paper"),
        (window.top_toggle, "Collapse"),
    ):
        widget.setText(text)
    window.list_picker.setItemText(window.list_picker.currentIndex(), "Reading collection")


def assert_inside(window):
    bar = window.top_toolbar
    shown = controls(window)
    assert window.list_picker in shown and window.ai_picker in shown
    assert window.research_data_button in shown and window.next_btn in shown
    for widget in shown:
        rect = widget.geometry()
        assert rect.left() >= 0 and rect.top() >= 0, widget
        assert rect.right() < bar.width(), (type(widget).__name__, rect, bar.size())
        assert rect.bottom() < bar.height(), (type(widget).__name__, rect, bar.size())
        assert rect.width() >= min(widget.sizeHint().width(), widget.maximumWidth()), widget


@pytest.mark.parametrize("language", ["en", "zh-TW"])
@pytest.mark.parametrize("width", [900, 1264, 1800])
def test_actual_toolbar_fits_without_clipping_hiding_or_changing_labels(reader, language, width):
    window, app = reader
    if language == "en":
        english(window)
    else:
        window.ai_picker.setText("目前 AI：測試帳號 · 模型甲")
        window.ai_picker.setToolTip("測試帳號 / 模型甲；不存取真實帳號")
    labels = {id(widget): widget.text() for widget in controls(window) if hasattr(widget, "text")}
    expected = set(map(id, controls(window)))
    window.resize(1800, 820)
    settle(app)
    assert window.width() == 1800
    assert window.top_toolbar.width() == 1800
    wide_height = window.top_toolbar.height()
    window.resize(width, 820)
    settle(app)
    assert window.width() <= width
    assert window.minimumSizeHint().width() <= 1264
    assert set(map(id, controls(window))) == expected
    assert_inside(window)
    for widget in controls(window):
        if id(widget) in labels:
            assert widget.text() == labels[id(widget)]
    if width == 900:
        assert window.top_toolbar.height() > wide_height
    if width == 1800:
        centers = [widget.geometry().center().y() for widget in controls(window)]
        assert max(centers) - min(centers) <= 1


def test_resize_preserves_active_paper_drafts_text_selection_and_focus(reader):
    window, app = reader
    page = window.reader_page
    page.tabs.setCurrentWidget(page.notes_tab)
    page.note_edit.setPlainText("Keep this exact unfinished thought")
    page.ask_box.setText("Keep my question")
    window.activateWindow()
    page.note_edit.setFocus()
    cursor = page.note_edit.textCursor()
    cursor.setPosition(2)
    cursor.setPosition(9, cursor.MoveMode.KeepAnchor)
    page.note_edit.setTextCursor(cursor)
    selected = cursor.selectedText()
    paper = page.paper
    for width in [1264, 900, 1800, 900, 1264]:
        window.resize(width, 820)
        settle(app)
        assert_inside(window)
        assert page.paper is paper
        assert page.note_edit.toPlainText() == "Keep this exact unfinished thought"
        assert page.ask_box.text() == "Keep my question"
        assert page.note_edit.textCursor().selectedText() == selected
        assert QApplication.focusWidget() is page.note_edit


def test_collapse_expand_and_keyboard_menu_keep_all_actions_reachable(reader):
    window, app = reader
    window.resize(900, 820)
    settle(app)
    actions = list(window.research_data_button.menu().actions())
    window.top_toggle.setChecked(True)
    settle(app)
    assert not window.top_toolbar.isVisible() and window.compact_header.isVisible()
    window.top_expand.click()
    settle(app)
    assert window.top_toolbar.isVisible() and not window.compact_header.isVisible()
    assert_inside(window)
    assert window.research_data_button.menu().actions() == actions
    window.research_data_button.setFocus()
    QTest.keyClick(window.research_data_button, Qt.Key.Key_Space)
    settle(app)
    menu = window.research_data_button.menu()
    assert menu.isVisible()
    QTest.keyClick(menu, Qt.Key.Key_Escape)
    settle(app)
    assert not menu.isVisible()


def test_readable_larger_fonts_reflow_without_dropping_global_ai_status(reader):
    window, app = reader
    english(window)
    for widget in controls(window):
        font = QFont(widget.font())
        if font.pixelSize() > 0:
            font.setPixelSize(font.pixelSize() + 2)
            widget.setFont(font)
    window.resize(1264, 820)
    settle(app)
    assert_inside(window)
    assert window.ai_picker.text() == "AI: Fixture / Model A"
    assert "Fixture account / Model A" in window.ai_picker.toolTip()


def test_changed_status_labels_reflow_without_replacing_drafts_or_focus(reader):
    window, app = reader
    window.resize(900, 820)
    page = window.reader_page
    page.tabs.setCurrentWidget(page.notes_tab)
    page.note_edit.setPlainText("Keep the active draft")
    window.activateWindow()
    page.note_edit.setFocus()
    window.ai_picker.setText("目前 AI：測試模型乙")
    window.ai_picker.setToolTip("Fixture account B / Model B")
    window.progress.setText("Recorded progress · 1 / 20")
    settle(app)
    assert_inside(window)
    assert window.ai_picker.text() == "目前 AI：測試模型乙"
    assert window.ai_picker.toolTip() == "Fixture account B / Model B"
    assert page.note_edit.toPlainText() == "Keep the active draft"
    assert QApplication.focusWidget() is page.note_edit


def test_wide_toolbar_returns_unused_vertical_space_to_reader(reader):
    window, app = reader
    for width in [900, 1800, 900, 1800]:
        window.resize(width, 820)
        settle(app)
        bar = window.top_toolbar
        assert bar.height() == bar.layout().heightForWidth(bar.width())
        assert_inside(window)
