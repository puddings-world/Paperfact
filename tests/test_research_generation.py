"""Actual close-reading publication preserves inputs, drafts and retry outcomes."""

import json
import sqlite3
from contextlib import closing

import pymupdf
import pytest

from paper_daily import brief, closeread, store
from paper_daily import research_generation as generation
from paper_daily.document_reader import from_workspace
from paper_daily.sync_capture import install
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare, research_writer

ORIGINAL_PACK = brief.pack_text
STAMP = "2026-10-26T00:00:00+00:00"
BODY = "## Methods\n" + "An informative result. " * 200


def pdf(path, text="Original experiment"):
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 50), text)
        document.save(path)


@pytest.fixture(params=[False, True], ids=["unbound", "enrolled"])
def workspace(tmp_path, monkeypatch, request):
    path = tmp_path / "research.sqlite"
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(store.SCHEMA)
    client = None
    if request.param:
        prepare(path, workspace_id="workspace", device_id="device")
        client = SyncClient(
            Journal(path, workspace_id="workspace", device_id="device"), research_writer
        )
    monkeypatch.setattr(store, "DB_PATH", path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    with store.connect() as conn:
        if request.param:
            conn.execute("BEGIN IMMEDIATE")
            install(conn, workspace_id="workspace", device_id="device")
        store.upsert_papers(
            conn,
            [
                {
                    "id": "paper",
                    "title": "Paper",
                    "year": 2026,
                    "venue": "Fixture",
                    "source": "fixture",
                }
            ],
        )
    root = tmp_path / "pdf"
    root.mkdir()
    pdf(root / "paper.pdf")
    reader = from_workspace(path, legacy_root=root)
    document = reader.resolve("paper")
    assert document.available

    def pack(conn, row):
        return brief.PreparedPack(
            "prompt from original PDF",
            document.path,
            snapshot=brief.input_snapshot(conn, row["id"]),
            document=document,
        )

    monkeypatch.setattr(brief, "pack_text", pack)
    monkeypatch.setattr(closeread.llm, "complete", lambda *args, **kwargs: (BODY, "ok"))
    return path, client, document


def rows(path, sql):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql)]


def context(path, reader="brief"):
    with closing(generation._connect(path)) as conn:
        return generation.begin_generation(
            conn, table="close_readings", owner_id="paper", input_reader=reader
        )


def output(body=BODY):
    return {"paper_id": "paper", "body": body, "spec": closeread.CLOSE_SPEC, "written_at": STAMP}


def test_actual_first_generation_and_retry_preserve_exact_source(workspace):
    path, client, document = workspace
    assert closeread.write("paper") == (BODY, "ok")
    saved = rows(path, "SELECT * FROM close_readings")[0]
    assert saved["body"] == BODY
    receipt = rows(path, "SELECT * FROM research_generation_requests")[0]
    assert generation.retry_publication(path, receipt["request_id"]).status == "accepted"
    assert generation.validate_request_record(receipt) == receipt
    if client:
        operations = [
            op for op in client.journal.pending() if op["entity_type"] == "research_content"
        ]
        assert len(operations) == 1
        assert operations[0]["payload"]["source_document_hash"] == document.sha256
    assert len(rows(path, "SELECT * FROM research_generation_requests")) == 1


def test_target_edit_during_model_preserves_newer_content_and_candidate(workspace, monkeypatch):
    path, _client, _document = workspace

    def complete(*args, **kwargs):
        newer = context(path, "target")
        assert generation.publish_generation(newer, row=output("Manual edit")).status == "accepted"
        return BODY, "ok"

    monkeypatch.setattr(closeread.llm, "complete", complete)
    body, reason = closeread.write("paper")
    assert body is None and "retained" in reason
    assert rows(path, "SELECT body FROM close_readings") == [{"body": "Manual edit"}]
    candidate = rows(path, "SELECT * FROM research_generation_requests WHERE status='candidate'")[0]
    assert json.loads(candidate["row_json"])["body"] == BODY
    assert (
        generation.retry_publication(path, candidate["request_id"]).candidate_id
        == candidate["candidate_id"]
    )


def test_actual_input_change_without_target_edit_is_not_rebased(workspace, monkeypatch):
    path, _client, _document = workspace

    def complete(*args, **kwargs):
        with store.connect() as conn:
            conn.execute("UPDATE papers SET abstract='Changed evidence' WHERE id='paper'")
        return BODY, "ok"

    monkeypatch.setattr(closeread.llm, "complete", complete)
    assert closeread.write("paper")[0] is None
    assert rows(path, "SELECT * FROM close_readings") == []
    assert rows(path, "SELECT status FROM research_generation_requests") == [
        {"status": "candidate"}
    ]


def test_pdf_changed_during_model_is_retained(workspace, monkeypatch):
    path, _client, document = workspace

    def complete(*args, **kwargs):
        document.path.unlink()
        pdf(document.path, "Different experiment")
        return BODY, "ok"

    monkeypatch.setattr(closeread.llm, "complete", complete)
    assert closeread.write("paper")[0] is None
    candidate = rows(path, "SELECT * FROM research_generation_requests")[0]
    assert candidate["status"] == "candidate"
    assert json.loads(candidate["context_json"])["document"]["sha256"] == document.sha256
    assert rows(path, "SELECT * FROM close_readings") == []


def test_original_database_survives_global_workspace_switch(workspace, monkeypatch, tmp_path):
    path, _client, _document = workspace
    other = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(other)) as conn, conn:
        conn.executescript(store.SCHEMA)

    def complete(*args, **kwargs):
        monkeypatch.setattr(store, "DB_PATH", other)
        return BODY, "ok"

    monkeypatch.setattr(closeread.llm, "complete", complete)
    assert closeread.write("paper") == (BODY, "ok")
    assert rows(path, "SELECT body FROM close_readings") == [{"body": BODY}]
    assert rows(other, "SELECT * FROM close_readings") == []


def test_repeated_publish_is_one_receipt_and_changed_output_rejected(workspace):
    path, _client, _document = workspace
    captured = context(path)
    first = generation.publish_generation(captured, row=output())
    assert generation.publish_generation(captured, row=output()) == first
    with pytest.raises(ValueError, match="reused"):
        generation.publish_generation(captured, row=output("Different"))
    assert len(rows(path, "SELECT * FROM research_generation_requests")) == 1


def test_defensive_input_snapshot_cannot_bless_changed_metadata(workspace):
    path, _client, _document = workspace
    captured = context(path)
    captured.inputs["paper"]["title"] = "Forged"
    with store.connect() as conn:
        conn.execute("UPDATE papers SET title='Forged'")
    assert generation.publish_generation(captured, row=output()).status == "candidate"


@pytest.mark.parametrize("reply", [None, "too short"])
def test_failed_generation_has_no_success_receipt(workspace, monkeypatch, reply):
    path, _client, _document = workspace
    monkeypatch.setattr(closeread.llm, "complete", lambda *args, **kwargs: (reply, "failure"))
    assert closeread.write("paper")[0] is None
    assert rows(path, "SELECT * FROM close_readings") == []
    assert (
        rows(path, "SELECT name FROM sqlite_master WHERE name='research_generation_requests'") == []
    )


def test_rapid_repeated_actual_launch_does_not_call_model_twice(workspace, monkeypatch):
    calls = []

    def complete(*args, **kwargs):
        calls.append(1)
        result = closeread.write("paper")
        assert result[0] is None and "progress" in result[1]
        return BODY, "ok"

    monkeypatch.setattr(closeread.llm, "complete", complete)
    assert closeread.write("paper") == (BODY, "ok")
    assert calls == [1]


def test_survey_snapshot_and_target_only_editor_contract(workspace):
    path, _client, _document = workspace
    with store.connect() as conn:
        conn.execute("INSERT INTO lists VALUES('reading','Reading','',?)", (STAMP,))
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
            "VALUES('reading','paper',0,?)",
            (STAMP,),
        )
    with store.connect() as conn:
        captured = generation.begin_generation(conn, table="list_surveys", owner_id="reading")
    assert set(captured.inputs) == {"list", "papers"}
    assert captured.inputs["papers"][0]["dive"] is None
    assert captured.inputs["papers"][0]["later"] == 0
    with store.connect() as conn:
        conn.execute("UPDATE list_papers SET position=5")
    row = {
        "list_id": "reading",
        "body": BODY,
        "papers": 1,
        "spec": "fixture",
        "written_at": STAMP,
        "edited": 0,
    }
    assert generation.publish_generation(captured, row=row).status == "candidate"
    with store.connect() as conn:
        edit = generation.begin_generation(
            conn, table="list_surveys", owner_id="reading", input_reader="target"
        )
    assert edit.target is None and edit.inputs is None
    row["edited"] = 1
    assert generation.publish_generation(edit, row=row).status == "accepted"


def test_replaced_database_never_receives_old_result_or_candidate(workspace, tmp_path):
    path, _client, _document = workspace
    captured = context(path)
    old = tmp_path / "original.sqlite"
    path.rename(old)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(store.SCHEMA)
    before = rows(path, "SELECT name FROM sqlite_master ORDER BY name")
    result = generation.publish_generation(captured, row=output())
    assert result.status == "candidate"
    assert rows(path, "SELECT * FROM close_readings") == []
    assert rows(path, "SELECT name FROM sqlite_master ORDER BY name") == before
    assert generation.retry_publication(captured) == result
    assert generation.publish_generation(captured, row=output()) == result
    retained = list((tmp_path / ".paperfact-generation").rglob("*.json"))
    assert len(retained) == 1
    recovered = generation.list_recovery_requests(path)
    assert len(recovered) == (0 if _client else 1)
    assert (
        json.loads(json.loads(retained[0].read_text(encoding="utf-8"))["row_json"])["body"] == BODY
    )


def test_rebound_workspace_never_receives_old_result(workspace):
    path, client, _document = workspace
    if client is None:
        with store.connect() as conn:
            captured = generation.begin_generation(conn, table="close_readings", owner_id="paper")
        prepare(path, workspace_id="different", device_id="other")
        SyncClient(Journal(path, workspace_id="different", device_id="other"), research_writer)
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            install(conn, workspace_id="different", device_id="other")
    else:
        captured = context(path)
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute("UPDATE research_capture_binding SET workspace='different'")
    before = rows(path, "SELECT name FROM sqlite_master ORDER BY name")
    result = generation.publish_generation(captured, row=output())
    assert result.status == "candidate"
    assert rows(path, "SELECT * FROM close_readings") == []
    assert rows(path, "SELECT name FROM sqlite_master ORDER BY name") == before
    assert generation.retry_publication(captured) == result


def test_actual_pack_uses_verified_bytes_not_stale_alias_text(workspace, monkeypatch):
    from paper_daily import fetch, figures

    path, _client, document = workspace
    monkeypatch.setattr(brief, "pack_text", ORIGINAL_PACK)
    monkeypatch.setattr(brief, "_backfill_from_conference_page", lambda conn, row: row)
    monkeypatch.setattr(fetch, "PDF_DIR", document.path.parent)
    monkeypatch.setattr(fetch, "ensure_pdf", lambda row: document.path)
    monkeypatch.setattr(figures, "extract", lambda *args, **kwargs: [])
    with closing(generation._connect(path)) as conn:
        row = conn.execute("SELECT * FROM papers WHERE id='paper'").fetchone()
        prepared = brief.pack_text(conn, row)
    assert "Original experiment" in prepared[0]
    assert prepared.document.sha256 == document.sha256
    assert prepared[1] == document.path


def test_managed_replacement_retains_original_pdf_source(tmp_path, monkeypatch):
    from test_document_reader import LOCAL, prepared, register
    from test_sync_document_research import document, pdf_bytes
    from test_sync_reading_state_research import save

    path, journal, blob_store, reader, _alias, _data = prepared(tmp_path)
    register(path, journal, blob_store, reader)
    monkeypatch.setattr(store, "DB_PATH", path)
    captured_document = reader.resolve(LOCAL)
    with closing(generation._connect(path)) as conn:
        captured = generation.begin_generation(conn, table="close_readings", owner_id=LOCAL)
    captured = generation.bind_inputs(captured, document=captured_document)
    save(journal, document(pdf_bytes("Replacement"), op_id="replacement"))
    row = output()
    row["paper_id"] = LOCAL
    result = generation.publish_generation(captured, row=row)
    assert result.status == "candidate"
    assert rows(path, "SELECT * FROM close_readings") == []
    versions = generation.input_versions(captured)
    assert not versions["complete"]
    assert versions["documents"][0]["sha256"] == captured_document.sha256
    assert "path" not in json.dumps(versions)


def test_candidate_recovery_records_are_bounded_and_closed(workspace, tmp_path):
    path, _client, _document = workspace
    captured = context(path)
    result = generation.publish_generation(captured, row=output())
    assert result.status == "accepted"
    record = rows(path, "SELECT * FROM research_generation_requests")[0]
    context_data = json.loads(record["context_json"])
    context_data["unexpected"] = "not allowed"
    record["context_json"] = json.dumps(context_data)
    with pytest.raises(ValueError, match="context fields"):
        generation.validate_request_record(record)
    assert generation.list_recovery_requests(path) == []


def test_deleted_owner_preserves_candidate_without_recreating_paper(workspace):
    path, client, _document = workspace
    captured = context(path)
    # Public graph paper deletion is deliberately unsupported. A local removed
    # owner must still not be recreated by an in-flight result in either mode.
    with closing(sqlite3.connect(path)) as conn, conn:
        if client:
            conn.create_function("paperfact_capture", 3, lambda *_: 0)
        conn.execute("DELETE FROM papers WHERE id='paper'")
    result = generation.publish_generation(captured, row=output())
    assert result.status == "candidate"
    assert rows(path, "SELECT * FROM papers") == []
    assert rows(path, "SELECT * FROM close_readings") == []


def test_missing_pdf_keeps_result_without_raising(workspace):
    path, _client, document = workspace
    captured = generation.bind_inputs(context(path), document=document)
    document.path.unlink()
    result = generation.publish_generation(captured, row=output())
    assert result.status == "candidate"
    assert rows(path, "SELECT * FROM close_readings") == []
    assert rows(path, "SELECT row_json FROM research_generation_requests")
