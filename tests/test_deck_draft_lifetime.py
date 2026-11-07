"""Late deck drafts release their original database on success and failure."""

import json
import os
import sqlite3
from contextlib import closing

import pytest
from test_sync_files import deck as make_deck

from paper_daily import sync_deck_publication as publication


@pytest.fixture
def original(tmp_path, monkeypatch):
    database = tmp_path / "research.sqlite"
    connect = sqlite3.connect
    with closing(connect(database)) as conn, conn:
        conn.execute(
            "CREATE TABLE research_sync_binding(id INTEGER PRIMARY KEY,workspace TEXT,origin TEXT)"
        )
        conn.execute(
            "INSERT INTO research_sync_binding VALUES(1,'fixture-workspace','fixture-device')"
        )
        conn.execute(
            "CREATE TABLE research_file_drafts(candidate_id TEXT PRIMARY KEY,"
            "entity_id TEXT,deck TEXT,observation TEXT)"
        )
    info = database.stat()
    observed = dict(
        database=str(database),
        database_identity=[info.st_dev, info.st_ino],
        workspace_id="fixture-workspace",
        device_id="fixture-device",
        entity_id="fixture-deck",
    )
    handles = []

    def tracked(*args, **kwargs):
        conn = connect(*args, **kwargs)
        handles.append(conn)
        return conn

    # Keep the real owned handle observable after return; no fake connection or
    # gc.collect() can disguise an open database on native Windows.
    monkeypatch.setattr(publication.sqlite3, "connect", tracked)
    return database, observed, handles, connect


@pytest.mark.parametrize("outcome", ["saved", "binding_changed", "write_failed"])
def test_retained_draft_closes_original_database_and_preserves_atomic_result(original, outcome):
    database, observed, handles, connect = original
    value = make_deck()
    if outcome == "binding_changed":
        observed["device_id"] = "another-device"
    elif outcome == "write_failed":
        with closing(connect(database)) as conn, conn:
            conn.execute(
                "CREATE TRIGGER refuse_draft BEFORE INSERT ON research_file_drafts "
                "BEGIN SELECT RAISE(ABORT,'fixture write refusal'); END"
            )
    identity = None
    if outcome == "saved":
        identity = publication._retain_original_draft(observed, value)
    else:
        error = ValueError if outcome == "binding_changed" else sqlite3.IntegrityError
        with pytest.raises(error):
            publication._retain_original_draft(observed, value)
    assert len(handles) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        handles[0].execute("SELECT 1")

    moved = database.with_name("research-moved.sqlite")
    assert database.resolve().is_relative_to(database.parent.resolve())
    assert moved.resolve().is_relative_to(database.parent.resolve())
    os.replace(database, moved)
    os.replace(moved, database)
    with closing(connect(database)) as conn:
        rows = conn.execute(
            "SELECT candidate_id,entity_id,deck,observation FROM research_file_drafts"
        ).fetchall()
    if outcome == "saved":
        assert len(rows) == 1 and rows[0][0] == identity
        assert rows[0][1] == observed["entity_id"]
        assert json.loads(rows[0][2]) == value.to_dict()
        assert json.loads(rows[0][3]) == observed
    else:
        assert rows == []


def test_replaced_original_refuses_without_opening_or_mutating_replacement(original):
    database, observed, handles, connect = original
    held = database.with_name("original-held.sqlite")
    os.replace(database, held)
    with closing(connect(database)) as conn, conn:
        conn.execute("CREATE TABLE marker(value TEXT)")
        conn.execute("INSERT INTO marker VALUES('replacement')")
    before = database.read_bytes()
    with pytest.raises(ValueError, match="replaced"):
        publication._retain_original_draft(observed, make_deck())
    assert handles == [] and database.read_bytes() == before
    with closing(connect(held)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_file_drafts").fetchone()[0] == 0
