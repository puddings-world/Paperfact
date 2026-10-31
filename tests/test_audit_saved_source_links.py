"""Audit associations come from saved note/QA sources, never today's open PDF."""

import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_research_evidence import source as source_fixture

from paper_daily import audit_inputs, research_chat, research_generation

source = source_fixture
STAMP = "2026-10-30T00:00:00+00:00"


@pytest.mark.parametrize("version", ["same", "different", "unknown"])
def test_note_uses_only_explicit_anchor_document_identity(source, version):
    digest = source.sha256 if version == "same" else "a" * 64 if version == "different" else None
    anchor = dict(p0=1, o0=0, p1=1, o1=8)
    if digest is not None:
        anchor["document_hash"] = digest
    database = source._owner.db_path
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,kind,page,anchor,created_at) VALUES(?,?,?,?,?,?)",
            ("paper", "50 participants", "note", 2, json.dumps(anchor), STAMP),
        )
    before = database.read_bytes()
    report = audit_inputs.AuditCapture.capture(database, "paper", document=source).run()
    item = next(row for row in report["items"] if row["feature"] == "note")
    assert item["document_hash"] == digest
    assert item["passages"] == []  # A note's prose is not automatically an original quote.
    assert database.read_bytes() == before


def actual_answer(source):
    database = source._owner.db_path
    with closing(research_generation._connect(database)) as conn:
        request = research_chat.begin_chat(
            conn,
            paper_id="paper",
            question="PRIVATE QUESTION",
            document=source,
            request_id=str(uuid4()),
        )
    request, _prompt = research_chat.prepare_chat(request)
    assert research_chat.publish_answer(request, "50 participants").status == "accepted"
    return database


def test_actual_chat_source_survives_audit_without_relabelling_or_including_question(source):
    database = actual_answer(source)
    before = database.read_bytes()
    report = audit_inputs.AuditCapture.capture(database, "paper", document=source).run()
    item = next(row for row in report["items"] if row["feature"] == "answer")
    assert item["document_hash"] == source.sha256
    assert "PRIVATE QUESTION" not in json.dumps(report)
    assert database.read_bytes() == before


def test_saved_chat_source_stays_old_after_loaded_original_changes(source):
    import pymupdf

    database = actual_answer(source)
    original = source.sha256
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((50, 50), "A replacement study used 80 participants.")
        data = pdf.tobytes()
    source.path.write_bytes(data)
    source._owner.invalidate()
    current = source._owner.resolve("paper")
    assert current.sha256 != original
    report = audit_inputs.AuditCapture.capture(database, "paper", document=current).run()
    item = next(row for row in report["items"] if row["feature"] == "answer")
    assert item["document_hash"] == original
    assert any(row["binding"] == "different" for row in report["checks"])


@pytest.mark.parametrize("digest", [None, "not-a-hash", "x" * 513])
def test_missing_or_invalid_chat_version_never_becomes_current_pdf(source, digest):
    from paper_daily.research_audit import AuditError

    database = actual_answer(source)
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("UPDATE research_chat_links SET source_hash=?", (digest,))
    if digest is None:
        report = audit_inputs.AuditCapture.capture(database, "paper", document=source).run()
        item = next(row for row in report["items"] if row["feature"] == "answer")
        assert item["document_hash"] is None
    else:
        with pytest.raises(AuditError, match="invalid_saved_content|input_limit"):
            audit_inputs.AuditCapture.capture(database, "paper", document=source)


@pytest.mark.parametrize("anchor", ["{", '{"document_hash":"not-a-hash"}', "[]"])
def test_malformed_note_source_is_never_assigned_todays_original(source, anchor):
    from paper_daily.research_audit import AuditError

    database = source._owner.db_path
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,anchor,created_at) VALUES(?,?,?,?)",
            ("paper", "Saved interpretation", anchor, STAMP),
        )
    before = database.read_bytes()
    with pytest.raises(AuditError, match="invalid_saved_content"):
        audit_inputs.AuditCapture.capture(database, "paper", document=source)
    assert database.read_bytes() == before
