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
        conn.commit()
        before = conn.execute("SELECT id,title FROM papers ORDER BY id").fetchall()
    intake = prepare_selected(source, ["list"], tmp_path / "intake", Ticket(), lambda _: None)
    with closing(sqlite3.connect(intake)) as conn:
        assert conn.execute("SELECT id FROM lists").fetchall() == [("list",)]
        assert conn.execute("SELECT id FROM papers").fetchall() == [("paper",)]
        assert conn.execute("SELECT body FROM notes").fetchall() == [("A research note",)]
        assert conn.execute("SELECT value FROM kv WHERE key='auth.secret'").fetchone() is None
    with closing(sqlite3.connect(source)) as conn:
        assert conn.execute("SELECT id,title FROM papers ORDER BY id").fetchall() == before
    assert (intake.parent / "pdf" / "paper.pdf").read_bytes() == original.read_bytes()
    # Reusing the same staged scope does not duplicate notes.
    prepare_selected(source, ["list"], intake.parent, Ticket(), lambda _: None)
    with closing(sqlite3.connect(intake)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM notes").fetchone() == (1,)
    ticket = Ticket()
    ticket.cancel()
    with pytest.raises(Cancelled):
        prepare_selected(source, ["list"], tmp_path / "cancelled", ticket, lambda _: None)
    assert not (tmp_path / "cancelled").exists()
