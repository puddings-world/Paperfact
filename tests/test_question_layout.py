"""Candidate explanations cannot displace the question composer."""

import os
import threading
import time
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

from paper_daily import llm
from paper_daily import research_questions as rq
from paper_daily.desktop.research_questions import ResearchQuestions

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QUOTE = "The mechanism assumes independent observations across study populations."


def long_candidate():
    return rq.validate(
        [{"question": "Which assumption matters? " * 10,
          "why": "\n".join(["Research limitation"] * 40), "evidence": QUOTE}],
        [{"page": 3, "text": QUOTE}],
    )[0]


def process(app, predicate=lambda: False, timeout=0.15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)


@pytest.fixture
def shell(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(rq, "cached", lambda *_: {"items": []})
    monkeypatch.setattr(llm, "capture_connections", lambda: {})
    monkeypatch.setattr(llm, "connection_scope", lambda *_: nullcontext())
    window = QWidget()
    layout = QVBoxLayout(window)
    questions = ResearchQuestions(window)
    composer = QLineEdit()
    layout.addWidget(questions)
    layout.addStretch(1)
    layout.addWidget(composer)
    yield app, window, questions, composer
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_long_valid_candidate_keeps_composer_visible_and_content_reachable(shell):
    app, window, questions, composer = shell
    item = long_candidate()
    questions._fill([item])
    questions.status.setText("A long diagnostic\n" * 80)
    window.resize(740, 400)
    window.show()
    process(app)
    assert window.height() <= 400
    assert window.rect().contains(composer.mapTo(window, composer.rect().bottomRight()))
    assert item["why"] in questions.detail.text()
    questions.open_browser()
    process(app)
    scroll = questions.details_scroll
    assert scroll.verticalScrollBar().maximum() > 0
    scroll.ensureWidgetVisible(questions.source)
    process(app)
    assert scroll.viewport().rect().intersects(
        questions.source.rect().translated(questions.source.mapTo(scroll.viewport(), QPoint()))
    )
    chosen, sources = [], []
    questions.chosen.connect(chosen.append)
    questions.source_requested.connect(sources.append)
    questions.insert.click()
    questions.source.click()
    assert chosen == [item["question"]]
    assert sources == [{"kind": "original", "page": 3, "text": QUOTE}]


def test_background_question_completion_preserves_typed_draft_and_focus(shell, monkeypatch):
    app, window, questions, composer = shell
    release = threading.Event()

    def ensure(*_args, **_kwargs):
        assert release.wait(5)
        return {"items": [long_candidate()]}, "ok"

    monkeypatch.setattr(rq, "ensure", ensure)
    questions.load("fixture-paper")
    window.resize(740, 400)
    window.show()
    window.activateWindow()
    process(app, lambda: questions.runner.busy)
    try:
        assert questions.runner.busy
        composer.setFocus()
        QTest.keyClicks(composer, "My unfinished question")
        assert composer.hasFocus()
    finally:
        release.set()
        process(app, lambda: not questions.runner.busy, timeout=5)
    assert not questions.runner.busy
    assert questions.picker.count() == 1
    assert composer.text() == "My unfinished question"
    assert composer.hasFocus()
    assert window.height() <= 400


@pytest.fixture
def application_appearance():
    app = QApplication.instance() or QApplication([])
    previous_font = app.font()
    previous_style = app.style().objectName()
    yield app
    app.setStyle(previous_style)
    app.setFont(previous_font)


@pytest.mark.parametrize("larger_font", [False, True], ids=["production", "ten-point"])
def test_full_reader_short_window_keeps_bottom_composer_visible(
    tmp_path, monkeypatch, application_appearance, larger_font
):
    from paper_daily import store
    from paper_daily.desktop import fonts, main
    from paper_daily.desktop.account_status import AccountStatus
    from paper_daily.desktop.update_banner import UpdateBanner

    app = application_appearance
    main.style(app)
    fonts.load()
    if larger_font:
        app.setFont(QFont("Microsoft JhengHei", 10))
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(AccountStatus, "check", lambda *_: None)
    monkeypatch.setattr(UpdateBanner, "check_in_background", lambda *_: None)
    monkeypatch.setattr(main.MainWindow, "_refresh_ai_summary", lambda *_, **__: None)
    monkeypatch.setattr(main.MainWindow, "announce_ready", lambda *_: None)
    monkeypatch.setattr(llm, "complete", lambda *_, **__: pytest.fail("Unexpected model call"))
    monkeypatch.setattr(rq, "cached", lambda *_: {"items": []})
    store.init_db()
    window = main.MainWindow()
    reader = window.reader_page
    reader.paper = SimpleNamespace(id="fixture-paper")
    reader.title.setText("Synthetic paper")
    reader.byline.setText("Synthetic authors")
    reader.facts.setText("Isolated layout regression")
    reader.questions._fill([long_candidate()])
    reader.tabs.setCurrentWidget(reader.ask_tab)
    window.stack.setCurrentWidget(reader)
    try:
        window.show()
        process(app)
        window.resize(1200, 560)
        process(app)
        assert window.height() <= 560
        composer = reader.ask_box
        assert composer.isVisible() and composer.isEnabled()
        assert window.rect().contains(composer.mapTo(window, composer.rect().bottomRight()))
        reader.questions.open_browser()
        process(app)
        assert reader.questions.details_scroll.verticalScrollBar().maximum() > 0
        reader.questions.browser.reject()
        window.activateWindow()
        composer.setFocus()
        QTest.keyClicks(composer, "Keep this question")
        assert composer.text() == "Keep this question"
    finally:
        window._ready_poll.stop()
        window.workspace_changes.timer.stop()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()

