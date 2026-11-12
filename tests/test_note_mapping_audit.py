"""The existing research audit accepts reviewed-note provenance without upgrading prose."""

import json
import sqlite3
from contextlib import closing

import pymupdf
import pytest
from test_research_evidence import source as source

from paper_daily import audit_inputs, note_positions
from paper_daily.research_audit import AuditError


def test_audit_reads_reviewed_note_source_without_treating_human_prose_as_a_quote(source):
    with pymupdf.open(source.path) as document:
        anchor = note_positions.select(document, dict(p0=1, o0=0, p1=1, o1=8), source.sha256)
    database = source._owner.db_path
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,kind,page,anchor,created_at) VALUES(?,?,?,?,?,?)",
            (
                "paper",
                "My interpretation of 50 participants",
                "note",
                2,
                json.dumps(anchor),
                "2026-11-01T00:00:00+00:00",
            ),
        )
    before = database.read_bytes()
    report = audit_inputs.AuditCapture.capture(database, "paper", document=source).run()
    item = next(item for item in report["items"] if item["feature"] == "note")
    assert item["document_hash"] == source.sha256
    assert item["text"] == "My interpretation of 50 participants" and item["passages"] == []
    assert report["semantics"] == "not_checked" and database.read_bytes() == before
    with closing(sqlite3.connect(database)) as conn, conn:
        anchor["selection"]["extractor"]["engine"] = "model"
        conn.execute("UPDATE notes SET anchor=?", (json.dumps(anchor),))
    with pytest.raises(AuditError, match="invalid_saved_content"):
        audit_inputs.AuditCapture.capture(database, "paper", document=source)
