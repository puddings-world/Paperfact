"""Public note operations survive private recovery and real local peer continuation."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from test_archived_draft_resumption import copied as copied
from test_archived_draft_resumption import decision as decision
from test_archived_draft_resumption import draft_variants as draft_variants
from test_archived_draft_resumption import source as source
from test_enrollment_history_peer import peer
from test_note_draft_resumption import recovered_note as recovered_note
from test_note_draft_resumption_edges import note_rows, stored
from test_note_review_operations import invoke, start
from test_note_review_transports import command

from paper_daily import local_operations as ops
from paper_daily import research_generation as generation
from paper_daily import store, sync_recovery, sync_source_files
from paper_daily.document_reader import DocumentReader
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.sync_artifacts import paths
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import research_writer


def rows(path, sql, args=()):
    with closing(generation._connect(path)) as conn:
        return [tuple(row) for row in conn.execute(sql, args)]


def mapped(value, monkeypatch, body):
    ref = start(value, monkeypatch)
    source = next(
        item["reference"]
        for item in invoke("sources", **ref)["items"]
        if item["reference"]["kind"] == "recorded"
    )
    selected = invoke(
        "map",
        **ref,
        source=source,
        anchor=dict(p0=0, o0=0, p1=0, o1=3),
        operation_id="continuity-map",
    )
    saved = invoke(
        "save",
        draft_id=ref["draft_id"],
        revision=selected["revision"],
        body=body,
        operation_id="continuity-save",
    )
    return dict(draft_id=ref["draft_id"], revision=saved["revision"])


def backup(path, output):
    with closing(generation._connect(path)) as conn:
        blobs, _versions = paths(conn)
    sync_recovery.create(path, output, blob_store=blobs, pdf_roots=[path.parent / "pdf"])


def live_count(path, table):
    assert table in {"integration_operations", "research_review_drafts"}
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
            return 0
        return conn.execute("SELECT count(*) FROM " + table).fetchone()[0]


def test_private_public_draft_can_be_adopted_rechecked_applied_and_backed_up_again(
    recovered_note, monkeypatch, tmp_path
):
    value = recovered_note
    body = "External private draft before switching computers"
    original_before = stored(value)
    ref = mapped(value, monkeypatch, body)
    assert stored(value) == original_before
    output = tmp_path / "private-public-note.zip"
    backup(value["path"], output)
    detached = tmp_path / "private-public-detached"
    sync_recovery.restore_detached(output, detached)
    detached_path = detached / "papers.db"
    assert rows(detached_path, "SELECT body,page,anchor FROM notes") == rows(
        value["path"], "SELECT body,page,anchor FROM notes"
    )
    assert live_count(detached_path, "integration_operations") == 0
    assert live_count(detached_path, "research_review_drafts") == 0
    historical_receipts = rows(
        detached_path, "SELECT data FROM recovery_records WHERE table_name='integration_operations'"
    )
    assert {json.loads(row[0])["id"] for row in historical_receipts} == {
        "external-open",
        "continuity-map",
        "continuity-save",
    }
    listed = command(dict(path=detached_path), "list", {})["result"]
    assert not listed["editable"] and body in json.dumps(listed, ensure_ascii=False)
    adoption = RecoveryAdoptionService(detached_path)
    inspected = adoption.inspect()
    assert inspected.report["supported"], inspected.report
    result = adoption.prepare(
        inspected,
        tmp_path / "private-public-adopted",
        backup_output=tmp_path / "private-public-adopted.zip",
        request_id=str(uuid4()),
    )
    adopted = Path(result["database"])
    assert live_count(adopted, "integration_operations") == 0
    assert live_count(adopted, "research_review_drafts") == 0
    assert (detached / "objects" / value["source_a"]).read_bytes() == (
        value["original"]["value"]["original_bytes"]
    )
    monkeypatch.setattr(store, "DB_PATH", adopted)
    assert ops.inspect_operation("continuity-save")["state"] == "not_committed"
    unavailable = ops.dispatch("review.notes.read", dict(draft_id=ref["draft_id"]))
    assert unavailable["error"]["code"] == "not_found"
    item = next(item for item in invoke("list", limit=100)["items"] if body in item["summary"])
    target = next(
        item
        for item in invoke("targets", origin_id=item["origin_id"])["items"]
        if "Current anchored note B" in item["title"]
    )
    opened = invoke(
        "open", origin_id=item["origin_id"], target_id=target["id"], operation_id="external-open"
    )
    assert opened["draft_id"] != ref["draft_id"]
    current = {key: opened[key] for key in ("draft_id", "revision")}
    read = invoke("read", draft_id=current["draft_id"])
    assert read["retained"]["body"] == body and read["position_evidence"] == "reviewed_passage"
    native_open, native_connect = Path.open, sqlite3.connect
    blocked = [value["path"].parent.resolve(), value["original"]["path"].parent.resolve()]

    def guarded_open(path, *args, **kwargs):
        assert not any(path.resolve().is_relative_to(folder) for folder in blocked)
        return native_open(path, *args, **kwargs)

    def guarded_connect(path, *args, **kwargs):
        candidate = str(path).replace(chr(92), "/").lower()
        assert not any(folder.as_posix().lower() in candidate for folder in blocked)
        return native_connect(path, *args, **kwargs)

    with monkeypatch.context() as guarded:
        guarded.setattr(Path, "open", guarded_open)
        guarded.setattr(sqlite3, "connect", guarded_connect)
        source = next(
            item["reference"]
            for item in invoke("sources", **current)["items"]
            if item["reference"]["kind"] == "reviewed"
        )
        page = invoke("page", **current, source=source, page_index=0)
        assert [word["text"] for word in page["words"]] == ["A", "verified", "source", "paper"]
        saved = invoke(
            "save",
            **current,
            body=body + "; continued on recovered copy",
            operation_id="continuity-save",
        )
        request = dict(
            draft_id=current["draft_id"],
            revision=saved["revision"],
            operation_id="continuity-apply",
            confirm=True,
        )
        outcome = invoke("decide", **request)
        assert invoke("decide", **request) == outcome
    assert stored(value) == original_before
    row = rows(
        adopted,
        "SELECT body,page,anchor,paper_id FROM notes WHERE body=?",
        (body + "; continued on recovered copy",),
    )[0]
    assert row[1] == 1 and json.loads(row[2])["selection"]["quote"] == "A verified source paper"
    assert json.loads(row[2])["document_hash"] == value["source_a"]
    assert DocumentReader.from_workspace(adopted).resolve(row[3]).sha256 == value["source_b"]
    again = tmp_path / "continued-public-note.zip"
    backup(adopted, again)
    final = tmp_path / "continued-public-detached"
    sync_recovery.restore_detached(again, final)
    final_notes = rows(final / "papers.db", "SELECT body,page,anchor FROM notes")
    assert final_notes == rows(adopted, "SELECT body,page,anchor FROM notes")
    again_list = command(dict(path=final / "papers.db"), "list", {})["result"]
    assert body + "; continued on recovered copy" in json.dumps(again_list, ensure_ascii=False)
    assert (final / "objects" / value["source_a"]).read_bytes() == (
        value["original"]["value"]["original_bytes"]
    )
    assert live_count(final / "papers.db", "integration_operations") == 0
    value["review"].close()


def test_peer_offline_edit_survives_restart_sync_old_apply_retry_and_backup(
    recovered_note, monkeypatch, tmp_path
):
    value = recovered_note
    body = "Agent-reviewed note before laptop trip"
    ref = mapped(value, monkeypatch, body)
    request = dict(**ref, operation_id="continuity-apply", confirm=True)
    applied = invoke("decide", **request)
    peer_root = tmp_path / "public-peer"
    peer_root.mkdir()
    a, b, service, ta, tb, portable, local, _files = peer(value["result"], peer_root)
    record = rows(
        b.journal.path,
        "SELECT id,body,page,anchor,kind,created_at FROM notes WHERE body=?",
        (body,),
    )[0]
    assert (
        record[2] == 1 and json.loads(record[3])["selection"]["quote"] == "A verified source paper"
    )
    with b.journal.transaction() as conn:
        original = sync_source_files.resolved(conn, portable, value["source_a"])
        assert original.read_bytes() == value["original"]["value"]["original_bytes"]
        identity = conn.execute(
            "SELECT sync_id FROM research_note_identity WHERE local_id=?", (record[0],)
        ).fetchone()[0]
    assert live_count(b.journal.path, "integration_operations") == 0
    assert live_count(b.journal.path, "research_review_drafts") == 0
    assert DocumentReader.from_workspace(b.journal.path).resolve(local).sha256 == value["source_b"]
    offline_body = "Human note edited offline on the laptop"
    b.save(
        b.new_graph_operation(
            "note",
            identity,
            dict(
                paper_id=portable,
                body=offline_body,
                page=record[2],
                anchor=json.loads(record[3]),
                kind=record[4],
                created_at=record[5],
            ),
        )
    )
    assert note_rows(value, "body") == [(body,)]
    assert len(b.journal.pending(1000)) == 1
    restarted = SyncClient(
        Journal(b.journal.path, workspace_id=a.journal.workspace_id, device_id="peer"),
        research_writer,
    )
    assert len(restarted.journal.pending(1000)) == 1
    restarted.sync_once(service, tb, limit=1000)
    a.sync_once(service, ta, limit=1000)
    assert not restarted.journal.pending(1000)
    received = note_rows(value, "body,page,anchor")[0]
    assert received[:2] == (offline_body, record[2])
    assert json.loads(received[2]) == json.loads(record[3])
    pending = a.journal.pending(1000)
    assert invoke("decide", **request) == applied
    assert a.journal.pending(1000) == pending
    assert note_rows(value, "body") == [(offline_body,)]
    assert invoke("read", draft_id=ref["draft_id"])["retained"]["body"] == body
    current = rows(
        value["path"], "SELECT paper_id FROM notes WHERE id=?", (value["target_note_id"],)
    )[0][0]
    assert DocumentReader.from_workspace(value["path"]).resolve(current).sha256 == value["source_b"]
    archive = tmp_path / "public-peer-returned.zip"
    backup(value["path"], archive)
    final = tmp_path / "public-peer-detached"
    sync_recovery.restore_detached(archive, final)
    assert rows(final / "papers.db", "SELECT body,page,anchor FROM notes") == rows(
        value["path"], "SELECT body,page,anchor FROM notes"
    )
    assert (final / "objects" / value["source_a"]).read_bytes() == value["original"]["value"][
        "original_bytes"
    ]
    final_list = command(dict(path=final / "papers.db"), "list", {})["result"]
    text = json.dumps(final_list, ensure_ascii=False)
    assert (
        body in text
        and "First human note interpretation" in text
        and "Second human note interpretation" in text
    )
    assert live_count(final / "papers.db", "integration_operations") == 0
    value["review"].close()
