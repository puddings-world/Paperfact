"""Saved-input audit is read-only and never upgrades unversioned legacy content."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_research_evidence import source as source_fixture

from paper_daily import audit_inputs, research_audit

source = source_fixture


def insert(source, sql, args=()):
    with closing(sqlite3.connect(source._owner.db_path)) as conn, conn:
        conn.execute(sql, args)


def test_saved_outputs_keep_unversioned_and_original_owned_marks_distinct(source):
    insert(source, "INSERT INTO dives VALUES('paper','50 participants','now',NULL)")
    insert(
        source,
        "INSERT INTO notes(paper_id,body,kind,created_at) "
        "VALUES('paper','Personal view','note','now')",
    )
    insert(
        source,
        "INSERT INTO chat(paper_id,role,body,created_at) "
        "VALUES('paper','user','PRIVATE QUESTION','now')",
    )
    insert(
        source,
        "INSERT INTO chat(paper_id,role,body,created_at) "
        "VALUES('paper','assistant','50 participants','now')",
    )
    anchor = dict(p0=1, o0=0, p1=1, o1=11)
    insert(
        source,
        "INSERT INTO pdf_highlights(paper_id,document_hash,anchor,quote,created_at) "
        "VALUES(?,?,?,?,?)",
        (
            "paper",
            source.sha256,
            json.dumps(anchor),
            "Replication used a held-out cohort of 50 participants.",
            "now",
        ),
    )
    database = source._owner.db_path
    before = database.read_bytes()
    captured = audit_inputs.AuditCapture.capture(database, "paper", document=source)
    report = captured.run()
    assert {v["feature"] for v in report["items"]} == {"dive", "note", "answer", "highlights"}
    assert "PRIVATE QUESTION" not in json.dumps(report)
    assert report["items"][0]["document_hash"] is None
    assert any(c["state"] == "source_unknown" for c in report["checks"])
    assert database.read_bytes() == before
    assert captured.current()
    with closing(sqlite3.connect(database)) as conn:
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE '%audit%'"
        ).fetchall()


def test_saved_change_invalidates_capture_without_mutating_prior_report(source):
    captured = audit_inputs.AuditCapture.capture(source._owner.db_path, "paper", document=source)
    report = captured.run()
    insert(source, "INSERT INTO dives VALUES('paper','new research','now',NULL)")
    assert not captured.current() and report["items"] == []
    with pytest.raises(research_audit.AuditError, match="saved_content_changed"):
        captured.run()


def test_replaced_database_invalidates_capture(source):
    captured = audit_inputs.AuditCapture.capture(source._owner.db_path, "paper", document=source)
    database = source._owner.db_path
    replacement = database.with_name("replacement")
    replacement.write_bytes(database.read_bytes())
    replacement.replace(database)
    assert not captured.current()


def test_audit_does_not_create_missing_database_or_accept_different_paper(source, tmp_path):
    missing = tmp_path / "absent.sqlite"
    with pytest.raises(FileNotFoundError):
        audit_inputs.AuditCapture.capture(missing, "paper", document=source)
    assert not missing.exists()
    with pytest.raises(research_audit.AuditError, match="source_identity_mismatch"):
        audit_inputs.AuditCapture.capture(source._owner.db_path, "another", document=source)


def test_large_saved_row_fails_without_truncation(source):
    insert(
        source,
        "INSERT INTO dives VALUES('paper',?,'now',NULL)",
        ("x" * (research_audit.MAX_TEXT + 1),),
    )
    with pytest.raises(research_audit.AuditError):
        audit_inputs.AuditCapture.capture(source._owner.db_path, "paper", document=source)


def test_late_mutation_during_pdf_capture_rejects_all_results(source, monkeypatch):
    from paper_daily import research_evidence

    actual = research_evidence.capture

    def changed(document):
        result = actual(document)
        insert(source, "INSERT INTO dives VALUES('paper','changed','now',NULL)")
        return result

    monkeypatch.setattr(research_evidence, "capture", changed)
    with pytest.raises(research_audit.AuditError, match="saved_content_changed"):
        audit_inputs.AuditCapture.capture(source._owner.db_path, "paper", document=source)


@pytest.fixture(params=[False, True], ids=["unbound", "enrolled"])
def actual_workspace(request, tmp_path, monkeypatch):
    from test_research_generation import pdf

    from paper_daily import store
    from paper_daily.document_reader import from_workspace
    from paper_daily.sync_client import SyncClient
    from paper_daily.sync_journal import Journal
    from paper_daily.sync_research import prepare, research_writer

    database = tmp_path / "actual.sqlite"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(store.SCHEMA)
    if request.param:
        prepare(database, workspace_id="workspace", device_id="device")
        SyncClient(Journal(database, workspace_id="workspace", device_id="device"), research_writer)
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    with store.connect() as conn:
        if request.param:
            from paper_daily.sync_capture import install

            conn.execute("BEGIN IMMEDIATE")
            install(conn, workspace_id="workspace", device_id="device")
        store.upsert_papers(
            conn, [dict(id="paper", title="Fixture", year=2026, venue="Fixture", source="fixture")]
        )
    root = tmp_path / "pdf"
    root.mkdir()
    pdf(root / "paper.pdf", "Known original source")
    reader = from_workspace(database, legacy_root=root)
    document = reader.resolve("paper")
    return database, document, request.param


def test_actual_loaded_owner_preserves_enrolled_binding_and_research_on_read(actual_workspace):
    from paper_daily import manual_highlight_ops

    database, document, enrolled = actual_workspace
    owner = manual_highlight_ops.capture_owner(database, "paper")
    with closing(sqlite3.connect(database)) as conn:
        before = list(conn.iterdump())
    captured = audit_inputs.AuditCapture.capture(database, "paper", document=document, owner=owner)
    assert captured.current() and captured.run()["source"]["document_hash"] == document.sha256
    state = json.loads(captured._state_json)
    assert state["binding"] == (
        dict(workspace_id="workspace", device_id="device") if enrolled else None
    )
    with closing(sqlite3.connect(database)) as conn:
        assert list(conn.iterdump()) == before


def test_checkpoint_during_capture_is_not_confused_with_changed_research(source, monkeypatch):
    from paper_daily import research_evidence

    database = source._owner.db_path
    original = research_evidence.capture
    observed = []
    with closing(sqlite3.connect(database)) as keeper:
        keeper.execute("PRAGMA journal_mode=WAL")
        keeper.execute("UPDATE papers SET title=title WHERE id='paper'")
        keeper.commit()

        def checkpoint(document):
            snapshot = original(document)
            before = audit_inputs._versions(database)
            keeper.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            observed.append(before != audit_inputs._versions(database))
            return snapshot

        monkeypatch.setattr(research_evidence, "capture", checkpoint)
        capture = audit_inputs.AuditCapture.capture(database, "paper", document=source)
        assert capture.current() and capture.run()["items"] == []
    assert observed == [True]


def test_final_read_witness_rejects_concurrent_new_research(source, monkeypatch):
    database = source._owner.db_path
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    original = audit_inputs.read_items
    calls = []

    def changed(conn, paper):
        items = original(conn, paper)
        calls.append(1)
        if len(calls) == 2:
            insert(source, "INSERT INTO dives VALUES('paper','new real content','now',NULL)")
        return items

    monkeypatch.setattr(audit_inputs, "read_items", changed)
    with pytest.raises(research_audit.AuditError, match="saved_content_changed"):
        audit_inputs.AuditCapture.capture(database, "paper", document=source)
    assert calls == [1, 1]
