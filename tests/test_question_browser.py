"""Suggestions are readable drafts, not conversation history or implicit AI calls."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from test_question_layout import long_candidate, process
from test_workspace_transfer_ui import workspace as _workspace

from paper_daily import research_questions as rq
from paper_daily.desktop.research_questions import ResearchQuestions

workspace = _workspace


def test_browser_shows_full_question_why_and_source_without_sending(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(rq, "ensure", lambda *a, **k: pytest.fail("Browsing called AI"))
    widget = ResearchQuestions()
    item = long_candidate()
    widget._fill([item, {**item, "question": "A second question?"}])
    drafted = []
    widget.chosen.connect(drafted.append)
    try:
        widget.show()
        widget.open_browser()
        process(app)
        assert widget.browser.isVisible()
        assert item["question"] in widget.detail.text()
        assert item["why"] in widget.detail.text()
        assert item["evidence"] in widget.detail.text()
        assert len(widget.picker.item(0).text()) <= 68
        assert not drafted
        widget.picker.setCurrentRow(1)
        assert "A second question?" in widget.detail.text()
        widget.cancel.click()
        assert not widget.browser.isVisible() and not drafted
        widget.open_browser()
        process(app)
        widget.insert.click()
        assert drafted == ["A second question?"]
        assert not widget.browser.isVisible()
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()


def test_empty_browser_and_switching_paper_cannot_insert_stale_question(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(rq, "cached", lambda *a: {"items": []})
    widget = ResearchQuestions()
    drafted = []
    widget.chosen.connect(drafted.append)
    try:
        widget.open_browser()
        process(app)
        assert not widget.insert.isEnabled()
        assert "直接" in widget.detail.text()
        widget.browser.reject()
        widget.paper_id = "old"
        widget._fill([long_candidate()])
        widget.open_browser()
        widget.open_browser()
        process(app)
        widget.load("new")
        assert not widget.browser.isVisible()
        assert widget.picker.count() == 0
        widget.insert.click()
        assert not drafted
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()


def test_narrow_browser_wraps_layout_and_keyboard_selection_drafts_only():
    app = QApplication.instance() or QApplication([])
    widget = ResearchQuestions()
    widget._fill([long_candidate(), {**long_candidate(), "question": "Second"}])
    drafted = []
    widget.chosen.connect(drafted.append)
    try:
        widget.open_browser()
        widget.browser.resize(600, 500)
        process(app)
        assert widget.browser.split.orientation() == Qt.Orientation.Vertical
        widget.picker.setFocus()
        QTest.keyClick(widget.picker, Qt.Key.Key_Down)
        assert widget.picker.currentRow() == 1 and not drafted
        QTest.keyClick(widget.picker, Qt.Key.Key_Return)
        assert drafted == ["Second"]
    finally:
        widget.browser.reject()
        widget.close()
        widget.deleteLater()
        app.processEvents()


def test_quick_templates_fill_draft_without_dispatch_or_changing_history(workspace, monkeypatch):
    from paper_daily.desktop import main

    monkeypatch.setattr(main.MainWindow, "_refresh_ai_summary", lambda *a, **k: None)
    monkeypatch.setattr(main.MainWindow, "announce_ready", lambda *a, **k: None)
    widget = main.MainWindow()
    reader = widget.reader_page
    monkeypatch.setattr(reader, "_ask_from_box", lambda *a: pytest.fail("Template sent AI"))
    reader.chat_view.setHtml("Existing conversation")
    try:
        for title, question in main.SEED_QUESTIONS:
            button = next(b for b in reader.ask_tab.findChildren(QPushButton) if b.text() == title)
            button.click()
            assert reader.ask_box.text() == question
            assert reader.chat_view._body == "Existing conversation"
        widget.stack.setCurrentWidget(reader)
        reader.tabs.setCurrentWidget(reader.ask_tab)
        widget.show()
        widget.activateWindow()
        process(workspace[0])
        draft = reader.ask_box.text()
        reader.questions.browse.click()
        process(workspace[0])
        reader.questions.cancel.click()
        process(workspace[0])
        # Offscreen Qt has no window manager to reactivate the modal's owner.
        # Check the remembered focus before simulating that OS activation.
        assert widget.focusWidget() is reader.ask_box
        widget.activateWindow()
        process(workspace[0])
        assert reader.ask_box.text() == draft and reader.ask_box.hasFocus()
        sent = []
        monkeypatch.setattr(reader, "_ask_from_box", sent.append)
        reader.ask_btn.click()
        assert sent == [main.SEED_QUESTIONS[-1][1]]
    finally:
        widget.close()
        widget.deleteLater()
