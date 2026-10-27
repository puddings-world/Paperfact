"""View state is remembered without the window waiting on the database."""

import sqlite3
import threading
import time

import pytest

from paper_daily import store
from paper_daily.desktop import ui_state


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    return tmp_path / "papers.db"


def _stored(key):
    with store.connect() as conn:
        return store.get_kv(conn, key)


def test_a_saved_value_is_readable_at_once_and_lands_in_the_background(db):
    ui_state.save("ui.list", "cataract")
    with store.connect() as conn:
        assert ui_state.read(conn, "ui.list") == "cataract"
    deadline = time.monotonic() + 5
    while _stored("ui.list") != "cataract" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert _stored("ui.list") == "cataract"


def test_a_locked_database_does_not_block_the_caller(db):
    # Another writer holds the lock, as a PDF download or analysis does.
    holder = sqlite3.connect(db)
    holder.execute("BEGIN IMMEDIATE")
    try:
        started = time.monotonic()
        for value in ("a", "b", "c"):
            ui_state.save("ui.sort.mode", value)
        assert time.monotonic() - started < 0.1
        with store.connect(timeout=0.05) as conn:
            assert ui_state.read(conn, "ui.sort.mode") == "c"
    finally:
        holder.rollback()
        holder.close()
    assert ui_state.flush()
    assert _stored("ui.sort.mode") == "c"


def test_flush_writes_the_latest_value_on_the_calling_thread(db):
    ui_state.save("ui.restart", "first")
    ui_state.save("ui.restart", "second")
    assert ui_state.flush() and _stored("ui.restart") == "second"


def test_state_goes_to_the_workspace_open_when_it_was_saved(db, tmp_path, monkeypatch):
    holder = sqlite3.connect(db)
    holder.execute("BEGIN IMMEDIATE")
    ui_state.save("ui.list", "first-workspace")
    other = tmp_path / "other.db"
    monkeypatch.setattr(store, "DB_PATH", other)
    store.init_db()
    holder.rollback()
    holder.close()
    assert ui_state.flush()
    assert _stored("ui.list") is None
    monkeypatch.setattr(store, "DB_PATH", db)
    assert _stored("ui.list") == "first-workspace"


def test_prefixed_merges_stored_and_queued_values(db):
    with store.connect() as conn:
        store.set_kv(conn, "ui.paper.opened:p1", "2026-10-27T01:00:00")
        store.set_kv(conn, "ui.paper.openedX", "not this")
    holder = sqlite3.connect(db)
    holder.execute("BEGIN IMMEDIATE")
    try:
        ui_state.save("ui.paper.opened:p2", "2026-10-27T02:00:00")
        with store.connect(timeout=0.05) as conn:
            assert ui_state.prefixed(conn, "ui.paper.opened:") == {
                "p1": "2026-10-27T01:00:00",
                "p2": "2026-10-27T02:00:00",
            }
    finally:
        holder.rollback()
        holder.close()


def test_the_writer_thread_survives_a_failed_write(db, monkeypatch):
    calls = threading.Event()
    original = store.connect

    def flaky(**kw):
        # Only the queue's writes name a database; the test's own reads do not.
        if "path" in kw and not calls.is_set():
            calls.set()
            raise sqlite3.OperationalError("database is locked")
        return original(**kw)

    monkeypatch.setattr(store, "connect", flaky)
    monkeypatch.setattr(ui_state, "RETRY_SECONDS", 0.01)
    ui_state.save("ui.auto_pdf", False)
    deadline = time.monotonic() + 5
    while _stored("ui.auto_pdf") is not False and time.monotonic() < deadline:
        time.sleep(0.01)
    assert calls.is_set() and _stored("ui.auto_pdf") is False
