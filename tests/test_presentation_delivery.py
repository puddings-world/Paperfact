"""Actual managed producer -> native editor delivery, without real model calls."""

import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import get_ident
from uuid import uuid4

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid
from test_sync_files import LOCAL, png, save_current
from test_sync_files import codec as _codec
from test_sync_files import pair as _pair

from paper_daily import llm, presentation_export, presentations, store
from paper_daily.ai_types import Settings
from paper_daily.desktop.presentation_pane import PresentationPane

codec = _codec
pair = _pair


@pytest.fixture
def generated(pair, codec, monkeypatch):
    app = QApplication.instance() or QApplication([])
    save_current(pair, codec[0])
    widget = PresentationPane()
    widget.load(LOCAL, "Paper")
    captured = []
    calls = []
    gui = get_ident()
    monkeypatch.setattr(llm, "settings", lambda **_kwargs: Settings("gateway", model="fixture"))
    monkeypatch.setattr(llm, "available", lambda **_kwargs: True)

    def produce(paper_id, **options):
        assert get_ident() != gui
        calls.append((paper_id, options))
        fresh = presentations.load_deck(paper_id, options["mode"])
        assert fresh is not None
        fresh.deck_id = uuid4().hex
        fresh.title = "New published guide"
        presentations.save_deck(fresh, observation=fresh._file_observation)
        return fresh, "ok"

    def start(prompt, done, failed, *, call, task):
        captured.append(dict(prompt=prompt, done=done, failed=failed, call=call, task=task))

    monkeypatch.setattr(presentations, "generate", produce)
    monkeypatch.setattr(widget.runner, "start", start)
    yield widget, captured, calls, app, pair
    if isValid(widget):
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def execute(request):
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(request["call"], request["prompt"]).result(timeout=60)


def test_published_managed_generation_remains_editable_and_exports_original_figures(generated):
    widget, pending, calls, _app, _pair = generated
    for _ in range(25):
        widget._start_generation_ready()
    assert len(pending) == 1 and widget._generating
    answer, reason = execute(pending[0])
    assert answer is not None and reason == "ok" and len(calls) == 1
    pending[0]["done"](answer)
    assert not widget._generating and widget.deck.title == "New published guide"
    widget.slide_title.setText("Edited after generation")
    assert widget.save_changes()
    reopened = presentations.load_deck(LOCAL, "guide")
    assert reopened.title == "New published guide"
    assert reopened.slides[0].title == "Edited after generation"
    assert reopened.slides[0].speaker_notes == "Speaker explanation"
    assert reopened.slides[0].elements[2]["text"] == "Editable"
    assert presentations.figure_bytes(reopened, "figure:1") == png("red")
    assert presentations.figure_bytes(reopened, "figure:2") == png("blue")
    assert "data:image/png;base64," in presentation_export.render_html(reopened)
    assert len(calls) == 1


def test_duplicate_delivery_cannot_erase_the_next_unsaved_edit(generated):
    widget, pending, _calls, _app, _pair = generated
    widget._start_generation_ready()
    answer, _reason = execute(pending[0])
    pending[0]["done"](answer)
    widget.slide_title.setText("Keep this next unsaved edit")
    assert widget._dirty and widget._autosave.isActive()
    pending[0]["done"](answer)
    assert widget.slide_title.text() == "Keep this next unsaved edit"
    assert widget._dirty and widget._autosave.isActive()
    assert widget.save_changes()
    assert presentations.load_deck(LOCAL, "guide").slides[0].title == "Keep this next unsaved edit"


@pytest.mark.parametrize("change", ["database", "folder", "native"])
def test_published_result_does_not_replace_view_after_workspace_change(
    generated, monkeypatch, tmp_path, change
):
    widget, pending, _calls, _app, _pair = generated
    before = widget.deck.to_dict()
    widget._start_generation_ready()
    answer, _reason = execute(pending[0])
    database = store.DB_PATH
    held = tmp_path / "original-held.sqlite"
    assert database.resolve().is_relative_to(tmp_path.resolve())
    if change == "database":
        replacement = tmp_path / "other.sqlite"
        monkeypatch.setattr(store, "DB_PATH", replacement)
    elif change == "folder":
        replacement = tmp_path / "other-decks"
        monkeypatch.setattr(presentations, "DECK_DIR", replacement)
    else:
        replacement = tmp_path / "replacement.sqlite"
        with closing(sqlite3.connect(replacement)) as conn:
            conn.executescript(store.SCHEMA)
        os.replace(database, held)
        os.replace(replacement, database)
    try:
        pending[0]["done"](answer)
        assert widget.deck.to_dict() == before
        assert not widget._generating
        if change != "native":
            assert not replacement.exists()
    finally:
        if held.exists():
            os.replace(held, database)


@pytest.mark.parametrize("change", ["database", "folder"])
def test_workspace_change_before_worker_starts_refuses_without_calling_producer(
    generated, monkeypatch, tmp_path, change
):
    widget, pending, calls, _app, _pair = generated
    before = widget.deck.to_dict()
    widget._start_generation_ready()
    destination = tmp_path / ("other.sqlite" if change == "database" else "other-decks")
    monkeypatch.setattr(
        store if change == "database" else presentations,
        "DB_PATH" if change == "database" else "DECK_DIR",
        destination,
    )
    answer, reason = execute(pending[0])
    assert answer is None and reason
    assert calls == [] and not destination.exists()
    pending[0]["failed"](reason)
    assert not widget._generating and widget.deck.to_dict() == before


def test_destroyed_native_pane_ignores_late_result_without_touching_qt(generated):
    widget, pending, _calls, app, _pair = generated
    widget._start_generation_ready()
    answer, _reason = execute(pending[0])
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    pending[0]["done"](answer)
    assert presentations.load_deck(LOCAL, "guide").title == "New published guide"


def test_failure_keeps_saved_deck_and_retry_admits_only_one_new_job(generated, monkeypatch):
    widget, pending, calls, _app, _pair = generated
    before = presentations.load_deck(LOCAL, "guide").to_dict()
    original = presentations.generate
    with monkeypatch.context() as patch:
        patch.setattr(
            presentations, "generate", lambda *_args, **_kwargs: (None, "fixture failure")
        )
        widget._start_generation_ready()
        answer, reason = execute(pending[0])
        assert answer is None and reason == "fixture failure"
        pending[0]["failed"](reason)
    assert presentations.generate is original
    assert not widget._generating
    assert presentations.load_deck(LOCAL, "guide").to_dict() == before
    for _ in range(20):
        widget._start_generation_ready()
    assert len(pending) == 2
    answer, reason = execute(pending[1])
    assert answer is not None and reason == "ok" and len(calls) == 1
    pending[1]["done"](answer)
    widget.slide_title.setText("Retry remains editable")
    assert widget.save_changes()
    assert presentations.load_deck(LOCAL, "guide").slides[0].title == "Retry remains editable"


def test_altered_transport_json_is_not_another_published_deck(generated):
    widget, pending, _calls, _app, _pair = generated
    before = widget.deck.to_dict()
    widget._start_generation_ready()
    answer, _reason = execute(pending[0])
    changed = json.loads(answer)
    changed["title"] = "Not the producer result"
    pending[0]["done"](json.dumps(changed))
    assert widget.deck.to_dict() == before
    assert not widget._generating
    assert presentations.load_deck(LOCAL, "guide").title == "New published guide"


def test_closed_outer_workspace_drops_result_even_at_same_native_path(generated):
    from paper_daily.desktop.window_workspace import WindowWorkspace

    widget, pending, _calls, _app, _pair = generated
    before = widget.deck.to_dict()
    widget._workspace_owner = WindowWorkspace.capture()
    widget._start_generation_ready()
    answer, _reason = execute(pending[0])
    widget._workspace_owner.close()
    pending[0]["done"](answer)
    assert widget.deck.to_dict() == before
    assert not widget._generating
    assert presentations.load_deck(LOCAL, "guide").title == "New published guide"


def test_transport_without_worker_result_cannot_replace_pending_edits(generated):
    widget, pending, calls, _app, _pair = generated
    before = presentations.load_deck(LOCAL, "guide").to_dict()
    widget._start_generation_ready()
    widget.slide_title.setText("Keep pending edit")
    raw = widget.deck.to_dict()
    raw["title"] = "Never produced"
    pending[0]["done"](json.dumps(raw))
    assert calls == [] and widget.slide_title.text() == "Keep pending edit"
    assert widget._dirty and not widget._generating
    assert presentations.load_deck(LOCAL, "guide").to_dict() == before
