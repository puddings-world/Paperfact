"""A nonempty unsupported source-bound position table must never vanish in snapshots."""

import hashlib
import sqlite3
from contextlib import closing

import pytest

from paper_daily import store
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_projection import read_manifest
from paper_daily.sync_research import prepare, research_writer

STAMP = "2026-10-30T12:00:00+00:00"


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "research.db"
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(store.SCHEMA)
        conn.execute(
            "INSERT INTO papers(id,title,title_key,venue,year,source) "
            "VALUES('paper','Fixture','fixture','Fixture',2026,'fixture')"
        )
        conn.execute("INSERT INTO pins VALUES('queue','paper',?)", (STAMP,))
    prepare(path, workspace_id="workspace", device_id="fixture-device")
    SyncClient(Journal(path, workspace_id="workspace", device_id="fixture-device"), research_writer)
    return path


def position_table(path, row=None):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS reading_positions(paper_id TEXT,document_hash TEXT,"
            "page INTEGER,recorded_at TEXT,method TEXT)"
        )
        if row is not None:
            conn.execute("INSERT INTO reading_positions VALUES(?,?,?,?,?)", row)


def before(path):
    return {
        item.name: hashlib.sha256(item.read_bytes()).hexdigest()
        for item in path.parent.iterdir()
        if item.is_file()
    }


@pytest.mark.parametrize("schema", [1, 2])
@pytest.mark.parametrize("kind", ["position", "orphan", "malformed", "oversized"])
def test_nonempty_position_table_refuses_snapshot_without_changing_data_or_cursor(
    database, schema, kind
):
    row = ["paper", "a" * 64, 2, STAMP, "entered"]
    if kind == "orphan":
        row[0] = "absent-paper"
    elif kind == "malformed":
        row[2:] = [0, "unverified legacy time", "unknown"]
    elif kind == "oversized":
        row[1] = "x" * (1024 * 1024)
    position_table(database, row)
    original = before(database)
    with pytest.raises(ValueError, match="Source-bound reading positions are not supported"):
        read_manifest(database, workspace_id="workspace", schema_version=schema)
    assert before(database) == original
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT * FROM reading_positions").fetchone() == tuple(row)
        assert conn.execute("SELECT sequence FROM paperfact_sync_cursor").fetchone()[0] == 0


@pytest.mark.parametrize("schema", [1, 2])
@pytest.mark.parametrize("empty_table", [False, True])
def test_absent_or_empty_table_keeps_exact_queue_pin_capability_without_read_DDL(
    database, schema, empty_table
):
    if empty_table:
        position_table(database)
    else:
        with closing(sqlite3.connect(database)) as conn, conn:
            conn.execute("DROP TABLE IF EXISTS reading_positions")
    original = before(database)
    result = read_manifest(database, workspace_id="workspace", schema_version=schema)
    assert result["required_capabilities"] == ["queue_pin"]
    assert result["cursor"] == 0
    assert before(database) == original
    with closing(sqlite3.connect(database)) as conn:
        present = bool(
            conn.execute("SELECT 1 FROM sqlite_master WHERE name='reading_positions'").fetchone()
        )
        assert present is empty_table


def test_foreign_workspace_still_fails_at_binding_before_unsupported_content(database):
    position_table(database, ["paper", "a" * 64, 2, STAMP, "entered"])
    with pytest.raises(ValueError, match="workspace does not match"):
        read_manifest(database, workspace_id="foreign")
