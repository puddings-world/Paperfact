"""External goal edits invalidate list displays only after a committed change."""

import sqlite3

import pytest

from paper_daily import store


@pytest.fixture
def database():
    conn = sqlite3.connect(":memory:")
    conn.executescript(store.SCHEMA)
    conn.execute("INSERT INTO lists VALUES('a','Study',NULL,'now')")
    conn.commit()
    yield conn
    conn.close()


def revision(conn):
    return conn.execute("SELECT revision FROM workspace_revision WHERE id=1").fetchone()[0]


def test_goal_edits_and_deletion_invalidate_existing_list(database):
    before = revision(database)
    database.execute("INSERT INTO list_reading_goals VALUES('a','Compare methods','now')")
    database.commit()
    assert revision(database) > before
    before = revision(database)
    database.execute("UPDATE list_reading_goals SET body='Assess limitations' WHERE list_id='a'")
    database.commit()
    assert revision(database) > before
    before = revision(database)
    database.execute("DELETE FROM list_reading_goals WHERE list_id='a'")
    database.commit()
    assert revision(database) > before


def test_rolled_back_goal_never_becomes_a_visible_change(database):
    before = revision(database)
    database.execute("INSERT INTO list_reading_goals VALUES('a','Cancelled edit','now')")
    database.rollback()
    assert revision(database) == before
    assert database.execute("SELECT COUNT(*) FROM list_reading_goals").fetchone()[0] == 0


def test_reopening_database_schema_does_not_create_refresh_loop(database):
    before = revision(database)
    database.executescript(store.SCHEMA)
    assert revision(database) == before
