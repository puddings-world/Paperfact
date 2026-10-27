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
