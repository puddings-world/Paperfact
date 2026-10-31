"""0.5-only window lifetime union: keep position and dialog barriers intact."""

import os
import sqlite3
from contextlib import closing
from threading import Event
from types import SimpleNamespace

import pytest
from test_main_window_workspace_scope import (
    _clear_drafts,
    _kv,
    capture_connections,
)
from test_main_window_workspace_scope import owner as owner_fixture
from test_position_update_guard import native_reader as native_position_reader_fixture
from test_reading_position_controller import idle, until
from test_reading_positions import records
from test_window_fits import reader as window_reader_fixture

from paper_daily import reading_position_ops as operations
from paper_daily import reading_positions as positions
from paper_daily import store

owner = owner_fixture
native_position_reader = native_position_reader_fixture
window_reader = window_reader_fixture


@pytest.mark.parametrize("legacy", ["actual", "missing", "none"])
def test_stale_no_draft_close_disposes_actual_position_controller_after_barriers(
    owner, monkeypatch, legacy
):
    window = owner.window
    _clear_drafts(window)
    controller = window.reader_page.reading_positions
    assert not controller._disposed
    if legacy != "actual":
        controller.close()
        if legacy == "missing":
            del window.reader_page.reading_positions
        else:
            window.reader_page.reading_positions = None
    before = _kv(owner.b)
    opened = capture_connections(monkeypatch)
    monkeypatch.setattr(store, "DB_PATH", owner.b)
    assert window.close()
    assert not window.isVisible()
    assert window.workspace_changes.disposed
    assert controller._disposed and not controller.poll.isActive()
    assert _kv(owner.b) == before
    assert str(owner.b) not in [row["path"] for row in opened]


@pytest.mark.parametrize(
    "field",
    [
        "_research_inbox_dialog",
        "_research_activity_dialog",
        "_audit_dialog",
        "_claim_dialog",
        "_offline_dialog",
        "_workspace_dialog",
    ],
)
@pytest.mark.parametrize("accepted", [False, True])
def test_context_change_inside_child_close_preserves_actual_window_drafts(
    owner, monkeypatch, field, accepted
):
    window, reader = owner.window, owner.window.reader_page
    before = _kv(owner.b)
    closes = []

    def close():
        closes.append(True)
        monkeypatch.setattr(store, "DB_PATH", owner.b)
        return accepted

    dialog = SimpleNamespace(disposed=False, close=close)
    setattr(window, field, dialog)
    try:
        assert not window.close()
        assert closes == [True]
        assert window.isVisible() and window._workspace_drafts()
        assert "original workspace" in window.ready_banner.label.text()
        assert reader.note_edit.toPlainText() == "Unsent Alpha note"
        assert reader.ask_box.text() == "Unsent Alpha question"
        assert not reader.reading_positions._disposed
        assert _kv(owner.b) == before
    finally:
        setattr(window, field, None)


@pytest.mark.parametrize("field", ["_research_inbox_dialog", "_research_activity_dialog"])
@pytest.mark.parametrize("accepted", [False, True])
def test_context_change_inside_restart_child_close_cannot_persist_to_B(
    owner, monkeypatch, field, accepted
):
    window = owner.window
    before = _kv(owner.b)

    def close():
        monkeypatch.setattr(store, "DB_PATH", owner.b)
        return accepted

    setattr(window, field, SimpleNamespace(disposed=False, close=close))
    try:
        assert not window._prepare_restart()
        assert _kv(owner.b) == before
        assert "original workspace" in window.ready_banner.label.text()
        assert window.reader_page.ask_box.text() == "Unsent Alpha question"
        assert not window.reader_page.reading_positions._disposed
    finally:
        setattr(window, field, None)


def test_stale_window_still_waits_for_actual_native_position_worker_before_close(
    native_position_reader, monkeypatch, tmp_path
):
    window, app, reader, controller, database = native_position_reader
    _clear_drafts(window)
    foreign = tmp_path / "foreign.sqlite"
    with closing(sqlite3.connect(foreign)) as conn:
        conn.execute("CREATE TABLE marker(value)")
        conn.execute("INSERT INTO marker VALUES('untouched')")
    before = foreign.read_bytes()
    started, release = Event(), Event()
    actual = operations.prepare

    def held(*args, **kwargs):
        started.set()
        assert release.wait(20)
        return actual(*args, **kwargs)

    monkeypatch.setattr(operations, "prepare", held)
    try:
        assert controller.remember()
        until(app, started.is_set)
        monkeypatch.setattr(store, "DB_PATH", foreign)
        assert not window.close()
        assert window.isVisible()
        assert not controller._disposed and not window.workspace_changes.disposed
    finally:
        release.set()
        idle(app, controller)
    assert records(database, positions.TABLE) == []
    assert window.close()
    assert controller._disposed and not controller.poll.isActive()
    assert window.workspace_changes.disposed
    assert foreign.read_bytes() == before
    replacement = foreign.with_suffix(".replacement")
    replacement.write_bytes(before)
    os.replace(replacement, foreign)
    assert foreign.read_bytes() == before
