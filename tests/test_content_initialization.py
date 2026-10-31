"""Initializing optional chat metadata must obey the existing transaction seam."""

import sqlite3
from contextlib import closing

import pytest

from paper_daily.sync_content import initialize_content


def test_rejected_initialization_does_not_create_any_tables():
    with closing(sqlite3.connect(":memory:")) as conn:
        with pytest.raises(ValueError, match="caller transaction"):
            initialize_content(conn)
        assert conn.execute("SELECT name FROM sqlite_master").fetchall() == []


def test_optional_chat_table_rolls_back_with_caller_transaction():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("BEGIN")
        initialize_content(conn)
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE name='research_chat_links'"
        ).fetchone()
        assert conn.in_transaction
        conn.rollback()
        assert conn.execute("SELECT name FROM sqlite_master").fetchall() == []


def test_optional_position_schema_waits_for_paper_parent_and_all_ddl_rolls_back():
    from paper_daily.reading_positions import ready

    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("BEGIN")
        initialize_content(conn)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert "research_chat_links" in names
        assert "papers" not in names and "reading_positions" not in names
        conn.execute("CREATE TABLE papers(id TEXT PRIMARY KEY)")
        initialize_content(conn)
        assert ready(conn) and conn.in_transaction
        conn.rollback()
        assert conn.execute("SELECT name FROM sqlite_master").fetchall() == []


def test_optional_position_schema_failure_keeps_caller_changes_uncommitted_for_retry():
    from paper_daily.reading_positions import ready

    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("CREATE TABLE papers(id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE reading_positions(unrecognized TEXT)")
        conn.execute("CREATE TABLE caller_draft(body TEXT)")
        conn.execute("INSERT INTO caller_draft VALUES('original')")
        conn.commit()
        conn.execute("BEGIN")
        conn.execute("UPDATE caller_draft SET body='uncommitted'")
        with pytest.raises(ValueError, match="explicit migration"):
            initialize_content(conn)
        assert conn.in_transaction
        conn.rollback()
        assert conn.execute("SELECT body FROM caller_draft").fetchone() == ("original",)
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='research_chat_links'"
        ).fetchall()
        assert [row[1] for row in conn.execute("PRAGMA table_info(reading_positions)")] == [
            "unrecognized"
        ]
        # The caller deliberately replaces its known invalid fixture schema.
        conn.execute("BEGIN")
        conn.execute("DROP TABLE reading_positions")
        initialize_content(conn)
        assert ready(conn) and conn.in_transaction
        conn.commit()
        assert conn.execute("SELECT body FROM caller_draft").fetchone() == ("original",)
