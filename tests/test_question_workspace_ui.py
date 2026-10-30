"""Question browsing stays local and pending work cannot repaint another view."""

import json
import sqlite3
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget
from test_question_layout import long_candidate, process

from paper_daily import annotation_reader, llm
from paper_daily.desktop.research_questions import ResearchQuestions


@pytest.fixture
def view(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    database = [tmp_path / "first.db"]
    saved = {"items": [long_candidate()], "known": True, "document_hash": "a" * 64}
    monkeypatch.setattr(annotation_reader, "questions", lambda *a, **k: dict(saved))
    window = QWidget()
    layout = QVBoxLayout(window)
    widget = ResearchQuestions(database=lambda: database[0])
    composer = QLineEdit("Unfinished personal question")
    layout.addWidget(widget)
    layout.addWidget(composer)
    pending = []
    runner = SimpleNamespace(busy=False)

    def start(prompt, done, failed, **kwargs):
        runner.busy = True
        pending.append((done, failed, kwargs))

    runner.start = start
    widget.runner = runner
    widget.load("paper")
    window.show()
    process(app)
    yield app, widget, composer, database, saved, pending
    window.close()
    window.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("kind", ["canonical", "legacy", "deleted"])
def test_browsing_saved_questions_requires_no_account_or_model(view, monkeypatch, kind):
    app, widget, composer, _, saved, pending = view
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("Read touched accounts"))
    if kind == "legacy":
        saved.update(known=False, legacy_unverified=True, document_hash=None)
    elif kind == "deleted":
        saved.update(items=[], document_hash=None)
    widget.load("paper")
    widget.open_browser()
    process(app)
    assert not pending
    assert composer.text() == "Unfinished personal question"
    assert widget.picker.count() == (0 if kind == "deleted" else 1)
    if kind == "legacy":
        assert "尚未核對" in widget.status.text()
        assert widget.source.isHidden()
        assert "來源版本未確認" in widget.detail.text()


def test_source_navigation_carries_exact_original_hash(view):
    app, widget, _, _, saved, _ = view
    navigated = []
    widget.source_requested.connect(navigated.append)
    widget.open_browser()
    process(app)
    widget.source.click()
    assert navigated == [
        {
            "kind": "original",
            "page": 3,
            "text": saved["items"][0]["evidence"],
            "document_hash": "a" * 64,
        }
    ]


def test_same_paper_in_another_workspace_closes_old_preview(view):
    app, widget, composer, database, saved, _ = view
    widget.open_browser()
    process(app)
    database[0] = database[0].with_name("second.db")
    saved.update(items=[])
    drafted = []
    widget.chosen.connect(drafted.append)
    widget.load("paper")
    process(app)
    assert not widget.browser.isVisible()
    assert widget.picker.count() == 0
    widget.insert.click()
    assert not drafted
    assert composer.text() == "Unfinished personal question"


def test_query_failure_keeps_existing_view_and_draft_without_starting_ai(view, monkeypatch):
    app, widget, composer, _, _, pending = view
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("Read touched accounts"))

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("busy")

    monkeypatch.setattr(annotation_reader, "questions", fail)
    widget.load("paper")
    widget.generate(force=True)
    process(app)
    assert not pending
    assert widget.picker.count() == 1
    assert "暫時無法讀取" in widget.status.text()
    assert composer.text() == "Unfinished personal question"
    widget.load("different-paper")
    assert widget.picker.count() == 0


@pytest.mark.parametrize("legacy", [False, True])
def test_repeated_update_and_failure_preserve_saved_questions(view, monkeypatch, legacy):
    app, widget, composer, _, saved, pending = view
    monkeypatch.setattr(llm, "capture_connections", lambda: {"account": "original"})
    if legacy:
        saved.update(legacy_unverified=True, document_hash=None)
        widget.load("paper")
    for _ in range(20):
        widget.generate(force=True)
    assert len(pending) == 1 and not widget.refresh_button.isEnabled()
    widget.runner.busy = False
    pending[0][1]("Fixture model unavailable")
    process(app)
    assert widget.refresh_button.isEnabled()
    assert "Fixture model unavailable" in widget.status.text()
    assert widget._item() == saved["items"][0]
    assert composer.text() == "Unfinished personal question"


@pytest.mark.parametrize("change", ["workspace", "away-and-back", "same-view-reload"])
def test_late_answer_cannot_replace_a_reloaded_question_view(view, monkeypatch, change):
    app, widget, composer, database, saved, pending = view
    monkeypatch.setattr(llm, "capture_connections", lambda: {"account": "original"})
    widget.generate(force=True)
    if change == "workspace":
        database[0] = database[0].with_name("second.db")
    elif change == "away-and-back":
        widget.load("other")
    saved["items"] = [{**long_candidate(), "question": "Newly saved question"}]
    widget.load("paper")
    widget.runner.busy = False
    pending[0][0](json.dumps({"items": [long_candidate()], "known": True}))
    process(app)
    assert widget._item()["question"] == "Newly saved question"
    assert len(pending) == 1
    assert composer.text() == "Unfinished personal question"
