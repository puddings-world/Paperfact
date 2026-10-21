"""Notes and chat rows written before they could remember where they came from.

The columns that make a note lead back to its passage were added to tables that
already held months of reading. `CREATE TABLE IF NOT EXISTS` leaves an older table
alone, so without the migration the reader opens against a database whose notes
table has no `anchor` and every query fails.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from paper_daily import store

OLD_SCHEMA = """
CREATE TABLE notes (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL,
    body     TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE chat (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id   TEXT NOT NULL,
    role       TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE dives (paper_id TEXT PRIMARY KEY, body TEXT, written_at TEXT);
CREATE TABLE cites (paper_id TEXT, ref_key TEXT);
"""


@pytest.fixture
def old_db(tmp_path):
    conn = sqlite3.connect(tmp_path / "papers.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO notes(paper_id, body, created_at) VALUES ('p:1','> 引文\n\n想法','2026-01-01')"
    )
    conn.execute(
        "INSERT INTO chat(paper_id, role, body, created_at) "
        "VALUES ('p:1','user','這段在說什麼','2026-01-01')"
    )
    conn.commit()
    return conn


def test_migration_adds_anchors_and_keeps_what_was_written(old_db):
    store._migrate(old_db)

    notes = {r[1] for r in old_db.execute("PRAGMA table_info(notes)")}
    assert {"kind", "page", "anchor"} <= notes
    chat = {r[1] for r in old_db.execute("PRAGMA table_info(chat)")}
    assert {"page", "anchor"} <= chat

    row = old_db.execute("SELECT * FROM notes").fetchone()
    assert row["body"].endswith("想法")
    # An old note has no passage to point at, and must not pretend otherwise.
    assert row["anchor"] is None
    assert row["kind"] == "note"


def test_migration_runs_twice(old_db):
    store._migrate(old_db)
    store._migrate(old_db)
    assert old_db.execute("SELECT count(*) FROM notes").fetchone()[0] == 1


def test_an_anchor_survives_the_round_trip(old_db):
    store._migrate(old_db)
    anchor = json.dumps({"p0": 4, "o0": 40, "p1": 4, "o1": 57})
    old_db.execute(
        "INSERT INTO notes(paper_id, body, created_at, kind, page, anchor) "
        "VALUES ('p:1','答案','2026-02-02','ask',5,?)",
        (anchor,),
    )
    row = old_db.execute("SELECT * FROM notes WHERE kind='ask'").fetchone()
    assert json.loads(row["anchor"])["o1"] == 57
    assert row["page"] == 5
