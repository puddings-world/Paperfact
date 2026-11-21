"""Selected sync intake uses offline package operations, not a catalog-wide copy."""

import sqlite3
from contextlib import closing

import pytest
from test_workspace_enrollment import pdf
from test_workspace_enrollment import source as source_fixture

from paper_daily.drive_sync_scope import prepare_selected
from paper_daily.workspace_service import Cancelled, Ticket

source = source_fixture


def test_selected_intake_keeps_research_and_reading_state_without_unrelated_catalog(
    source, tmp_path
):
    original = pdf(source)
    with closing(sqlite3.connect(source)) as conn:
        conn.execute(
            "INSERT INTO papers(id,title,title_key,venue,year,source) VALUES"
            "('catalog-only','Unrelated catalog row','unrelated','Fixture',2026,'fixture')"
        )
        conn.execute("INSERT INTO refs VALUES('paper','catalog-only',0)")
        conn.execute("INSERT INTO queue(paper_id,rank) VALUES('catalog-only',1),('paper',2)")
        conn.executemany(
            "INSERT INTO reading_log(paper_id,delivered_at) VALUES(?,'yesterday')",
            [("catalog-only",), ("paper",)],
        )
        conn.execute(
            "UPDATE list_papers SET state='read',delivered_at='yesterday',read_at='today' "
            "WHERE list_id='list' AND paper_id='paper'"
        )
        conn.commit()
        before = conn.execute("SELECT id,title FROM papers ORDER BY id").fetchall()
    intake = prepare_selected(source, ["list"], tmp_path / "intake", Ticket(), lambda _: None)
    with closing(sqlite3.connect(intake)) as conn:
        assert conn.execute("SELECT id FROM lists").fetchall() == [("list",)]
        assert conn.execute("SELECT id FROM papers ORDER BY id").fetchall() == [
            ("catalog-only",), ("paper",)
        ]
        assert conn.execute("SELECT state,delivered_at,read_at FROM list_papers").fetchall() == [
            ("read", "yesterday", "today")
        ]
        for table in ("reading_log", "queue"):
            assert conn.execute(f"SELECT paper_id FROM {table}").fetchall() == [("paper",)]
        assert conn.execute("SELECT body FROM notes").fetchall() == [("A research note",)]
        assert conn.execute("SELECT value FROM kv WHERE key='auth.secret'").fetchone() is None
    with closing(sqlite3.connect(source)) as conn:
        assert conn.execute("SELECT id,title FROM papers ORDER BY id").fetchall() == before
    assert (intake.parent / "pdf" / "paper.pdf").read_bytes() == original.read_bytes()
    # Reusing the same staged scope does not duplicate notes.
    prepare_selected(source, ["list"], intake.parent, Ticket(), lambda _: None)
    with closing(sqlite3.connect(intake)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM notes").fetchone() == (1,)
    # A stale package must never enroll a paper removed from the selected list.
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("DELETE FROM list_papers WHERE list_id='list' AND paper_id='paper'")
    with pytest.raises(ValueError, match="membership changed"):
        prepare_selected(source, ["list"], intake.parent, Ticket(), lambda _: None)
    with closing(sqlite3.connect(source)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM list_papers").fetchone() == (0,)
    ticket = Ticket()
    ticket.cancel()
    with pytest.raises(Cancelled):
        prepare_selected(source, ["list"], tmp_path / "cancelled", ticket, lambda _: None)
    assert not (tmp_path / "cancelled").exists()
