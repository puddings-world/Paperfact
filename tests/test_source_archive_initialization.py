"""Private archive state is lazy and obeys the caller transaction."""

import json
import sqlite3
from contextlib import closing

import pytest

from paper_daily import source_provenance, store


def record():
    return source_provenance.wrap({
        "request_id": "original-request",
        "owner_json": json.dumps({
            "format": "paperfact.source-owner.v1", "database_identity": [1, 2],
            "binding": None, "paper_id": "paper", "parent_lifecycle": "a" * 32,
            "source_owner_id": "paper",
        }),
        "sha256": "b" * 64, "size": 4, "media_type": "application/pdf",
    })


def test_fresh_research_schema_has_no_archive_or_old_job_authority():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.executescript(store.SCHEMA)
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'research_%'"
        ).fetchall() == []


def test_empty_or_invalid_archive_request_does_not_initialize_private_tables():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("BEGIN")
        source_provenance.retain_in(conn, [])
        assert conn.execute("SELECT name FROM sqlite_master").fetchall() == []
        with pytest.raises(ValueError):
            source_provenance.retain_in(conn, [{"record_id": "bad"}])
        assert conn.in_transaction
        assert conn.execute("SELECT name FROM sqlite_master").fetchall() == []


def test_valid_archive_is_idempotent_and_rollback_removes_only_uncommitted_state():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("BEGIN")
        value = record()
        source_provenance.retain_in(conn, [value])
        assert source_provenance.archived(conn) == [value]
        conn.rollback()
        assert conn.execute("SELECT name FROM sqlite_master").fetchall() == []
        conn.execute("BEGIN")
        source_provenance.retain_in(conn, [value])
        conn.commit()
        conn.execute("BEGIN")
        source_provenance.retain_in(conn, [value])
        conn.rollback()
        assert source_provenance.archived(conn) == [value]
