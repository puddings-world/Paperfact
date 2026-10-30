"""Initialization preserves research/schema; obsolete triggers upgrade once."""

import sqlite3
from contextlib import closing

from paper_daily import annotation_content as annotations
from paper_daily import store


def test_repeated_database_initialization_is_an_exact_noop(tmp_path, monkeypatch):
    database = tmp_path / "papers.db"
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    store.init_db()
    with closing(sqlite3.connect(database)) as conn:
        conn.execute(
            "INSERT INTO paper_research_questions VALUES(?,?,?,?,?)",
            ("p", '{"items":[]}', "a" * 64, None, "2026-10-30T00:00:00+00:00"),
        )
        conn.commit()
        before = list(conn.iterdump())
        version = conn.execute("PRAGMA schema_version").fetchone()[0]
        for _ in range(3):
            store.init_db()
            assert list(conn.iterdump()) == before
            assert conn.execute("PRAGMA schema_version").fetchone()[0] == version


def old_trigger(conn):
    name = "paperfact_annotation_research_questions_update"
    conn.execute(f'DROP TRIGGER "{name}"')
    conn.execute(
        f"CREATE TRIGGER {name} AFTER UPDATE ON paper_research_questions BEGIN "
        "INSERT OR IGNORE INTO paper_annotation_known "
        "VALUES('research_questions',NEW.paper_id); END"
    )
    return name


def test_obsolete_marker_upgrade_is_transactional_and_only_once():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.executescript(store.SCHEMA)
        name = old_trigger(conn)
        conn.commit()
        original = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()[0]
        conn.execute("BEGIN")
        annotations.initialize(conn)
        upgraded = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()[0]
        assert upgraded != original
        conn.rollback()
        assert (
            conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()[0]
            == original
        )
        conn.execute("BEGIN")
        annotations.initialize(conn)
        conn.execute("CREATE INDEX keep_schema_order ON paper_research_questions(written_at)")
        conn.commit()
        before = list(conn.iterdump())
        version = conn.execute("PRAGMA schema_version").fetchone()[0]
        conn.execute("BEGIN")
        annotations.initialize(conn)
        conn.commit()
        assert list(conn.iterdump()) == before
        assert conn.execute("PRAGMA schema_version").fetchone()[0] == version
        # The upgraded marker handles an outer UPSERT without inheriting a
        # conflicting IGNORE policy or creating duplicate authority markers.
        for body in ('{"items":[]}', '{"items":[]} '):
            conn.execute(
                "INSERT INTO paper_research_questions VALUES(?,?,?,?,?) "
                "ON CONFLICT(paper_id) DO UPDATE SET body_json=excluded.body_json",
                ("p", body, "a" * 64, None, "2026-10-30T00:00:00+00:00"),
            )
        assert conn.execute("SELECT feature,paper_id FROM paper_annotation_known").fetchall() == [
            ("research_questions", "p")
        ]
