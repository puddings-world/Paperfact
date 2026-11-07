"""Explicit schema installation owns no caller transaction or implicit repair."""

import sqlite3
from contextlib import closing

import pytest

from paper_daily import later_outcomes as outcomes


def test_initializer_requires_transaction_and_rollback_preserves_caller_work():
    with closing(sqlite3.connect(":memory:")) as conn:
        with pytest.raises(ValueError, match="transaction"):
            outcomes.initialize(conn)
        conn.execute("CREATE TABLE unrelated(value)")
        conn.execute("INSERT INTO unrelated VALUES('caller draft')")
        outcomes.initialize(conn)
        assert conn.in_transaction
        assert conn.execute("SELECT * FROM unrelated").fetchall() == [("caller draft",)]
        conn.rollback()
        assert conn.execute("SELECT * FROM unrelated").fetchall() == []
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (outcomes.TABLE,)
        ).fetchone()


def test_missing_parent_can_arrive_later_and_exact_repeats_do_not_repair():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("BEGIN")
        outcomes.initialize(conn)
        assert not conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
        conn.execute("CREATE TABLE papers(id TEXT PRIMARY KEY)")
        outcomes.initialize(conn)
        triggers = conn.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
        ).fetchall()
        assert len(triggers) == 2
        outcomes.initialize(conn)
        assert (
            conn.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
            ).fetchall()
            == triggers
        )
        conn.rollback()
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (outcomes.TABLE,)
        ).fetchone()


@pytest.mark.parametrize("kind", ["columns", "primary-key", "trigger"])
def test_unrecognized_existing_schema_is_refused_without_rewrite(kind):
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("CREATE TABLE papers(id TEXT PRIMARY KEY)")
        conn.execute("BEGIN")
        if kind == "columns":
            conn.execute("CREATE TABLE paper_later_outcomes(paper_id,body_json,unexpected)")
        elif kind == "primary-key":
            conn.execute(
                "CREATE TABLE paper_later_outcomes(paper_id TEXT,body_json TEXT NOT NULL,"
                "document_hash TEXT,written_at TEXT NOT NULL)"
            )
        else:
            outcomes.initialize(conn)
            conn.execute("DROP TRIGGER paperfact_later_outcome_delete")
            conn.execute(
                "CREATE TRIGGER paperfact_later_outcome_delete AFTER DELETE ON papers "
                "BEGIN SELECT 1; END"
            )
        before = conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
        with pytest.raises(ValueError, match="repair"):
            outcomes.initialize(conn)
        assert conn.in_transaction
        assert conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall() == before


def test_protocol_initialization_waits_for_both_real_parents_and_preserves_transaction():
    from paper_daily.sync_content import initialize_content

    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("CREATE TABLE papers(id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE unrelated(value)")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO unrelated VALUES('draft')")
        initialize_content(conn)
        assert conn.in_transaction
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_parent_lifecycle'"
        ).fetchone()
        conn.execute("CREATE TABLE lists(id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO papers VALUES('local-parent')")
        initialize_content(conn)
        token = conn.execute(
            "SELECT token FROM research_parent_lifecycle WHERE kind='paper'"
        ).fetchone()[0]
        assert len(token) == 32
        assert conn.execute("SELECT * FROM unrelated").fetchall() == [("draft",)]
        conn.rollback()
        assert conn.execute("SELECT * FROM unrelated").fetchall() == []
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_parent_lifecycle'"
        ).fetchone()
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='lists'").fetchone()


def test_committed_protocol_lifecycles_survive_rollback_without_new_parent_adoption():
    from paper_daily.sync_content import initialize_content

    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("CREATE TABLE papers(id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE lists(id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO papers VALUES('existing')")
        initialize_content(conn)
        conn.commit()
        baseline = list(conn.iterdump())
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO papers VALUES('imported')")
        assert conn.execute(
            "SELECT active FROM research_parent_lifecycle WHERE entity_id='imported'"
        ).fetchone() == (1,)
        conn.rollback()
        assert list(conn.iterdump()) == baseline
        assert not conn.execute(
            "SELECT 1 FROM research_parent_lifecycle WHERE entity_id='imported'"
        ).fetchone()


def test_protocol_initialization_refuses_malformed_lifecycles_without_repair():
    from paper_daily.sync_content import initialize_content

    with closing(sqlite3.connect(":memory:")) as conn:
        conn.executescript(
            "CREATE TABLE papers(id TEXT PRIMARY KEY); CREATE TABLE lists(id TEXT PRIMARY KEY);"
            "CREATE TABLE research_parent_lifecycle(kind,entity_id,foreign_token);"
        )
        baseline = list(conn.iterdump())
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="repair"):
            initialize_content(conn)
        assert conn.in_transaction
        conn.rollback()
        assert list(conn.iterdump()) == baseline
