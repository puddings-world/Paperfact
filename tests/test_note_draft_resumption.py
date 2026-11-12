"""Real archived rich-note drafts resume against fresh receiver note identities."""

import json
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_archived_draft_resumption import copied as copied
from test_archived_draft_resumption import decision as decision
from test_archived_draft_resumption import draft_variants as draft_variants
from test_archived_draft_resumption import source as source
from test_enrollment_history_peer import peer

from paper_daily import research_generation as generation
from paper_daily import sync_recovery
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.research_review import ResearchReview
from paper_daily.sync_artifacts import paths

STAMP = "2026-11-01T00:00:00+00:00"


def note(client, identity, paper, body, document_hash, **changes):
    payload = dict(
        paper_id=paper,
        body=body,
        kind="note",
        created_at=STAMP,
        page=1 if document_hash else None,
        anchor=(
            dict(p0=0, o0=0, p1=0, o1=3, document_hash=document_hash) if document_hash else None
        ),
    )
    payload.update(changes)
    client.save(client.new_graph_operation("note", identity, payload))
    return payload


@pytest.fixture
def recovered_note(copied, tmp_path, request):
    value = copied
    value["review"].close()
    a, b, service, ta, tb, portable, _local, _artifacts = peer(value["result"], tmp_path)
    identity = str(uuid4())
    source_a, source_b = value["value"]["source_hash"], value["current"].sha256
    note(a, identity, portable, "Original anchored note A", source_a)
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    current = note(a, identity, portable, "Current anchored note B", source_b)
    changes = dict(request.param) if isinstance(getattr(request, "param", None), dict) else {}
    if isinstance(changes.get("anchor"), dict):
        changes["anchor"] = dict(changes["anchor"])
        if changes["anchor"].get("document_hash") == "source-a":
            changes["anchor"]["document_hash"] = source_a
    retained = note(
        b,
        identity,
        portable,
        "Retained interpretation of A",
        None if getattr(request, "param", None) == "plain" else source_a,
        **changes,
    )
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    a.sync_once(service, ta)
    review = ResearchReview(a.journal.path)
    conflicts = [item for item in review.page()["items"] if item["origin"] == "remote"]
    assert len(conflicts) == 1
    preview = review.preview("remote", conflicts[0]["id"])
    assert preview.data["retained"] == retained and preview.data["current"] == current
    request = str(uuid4())
    one = review.save_draft(preview, "First human note interpretation", request)
    two = review.save_draft(preview, "Second human note interpretation", request)
    assert one["draft_id"] != two["draft_id"]
    review.close()
    with closing(generation._connect(a.journal.path)) as conn:
        store, _versions = paths(conn)
    backup = tmp_path / "note-source.zip"
    sync_recovery.create(
        a.journal.path, backup, blob_store=store, pdf_roots=[a.journal.path.parent / "pdf"]
    )
    detached = tmp_path / "note-detached"
    sync_recovery.restore_detached(backup, detached)
    adoption = RecoveryAdoptionService(detached / "papers.db")
    inspection = adoption.inspect()
    assert inspection.report["supported"], inspection.report
    result = adoption.prepare(
        inspection,
        tmp_path / "note-receiver",
        backup_output=tmp_path / "note-receiver.zip",
        request_id=str(uuid4()),
    )
    receiver = ResearchReview(result["database"])
    items = [
        item
        for item in receiver.page(limit=100)["items"]
        if item["origin"] == "archived_draft" and "human note interpretation" in item["summary"]
    ]
    assert len(items) == 2
    archived = receiver.preview("archived_draft", items[0]["id"])
    with closing(generation._connect(result["database"])) as conn:
        target_note_id = conn.execute(
            "SELECT id FROM notes WHERE body='Current anchored note B'"
        ).fetchone()[0]
    return dict(
        target_note_id=target_note_id,
        original=value,
        path=Path(result["database"]),
        result=result,
        review=receiver,
        archived=archived,
        items=items,
        source_a=source_a,
        source_b=source_b,
        original_note=identity,
    )


def test_rich_note_draft_survives_real_conflict_backup_adoption_resume_and_retry(recovered_note):
    value = recovered_note
    review = value["review"]
    archived = value["archived"]
    old_text = review.export_text(archived)
    targets = review.resume_targets(archived)["items"]
    selected = next(item for item in targets if "Current anchored note B" in item["title"])
    preview = review.resume_draft(archived, selected["id"])
    assert preview.data["origin"] == "archived_note_resume"
    assert preview.data["source_hash"] == value["source_a"]
    assert preview.data["current"]["body"] == "Current anchored note B"
    assert preview.data["retained"]["anchor"]["document_hash"] == value["source_a"]
    expected = preview.data["expected"]
    request = str(uuid4())
    saved = review.save_draft(preview, "Reviewed human note on receiver", request)
    review.close()
    reopened = ResearchReview(value["path"])
    try:
        loaded = reopened.load_draft("archived_note_resume", archived.data["id"])
        assert loaded["body"] == "Reviewed human note on receiver"
        assert (
            loaded["draft_id"] == saved["draft_id"]
            and loaded["preview"].data["expected"] == expected
        )
        assert not loaded["preview"].data["apply"]
        ready = reopened.verify_resumed_draft(loaded["preview"])
        result = reopened.decide(
            ready, body=loaded["body"], request_id=request, confirm_target=True
        )
        with closing(generation._connect(value["path"])) as conn:
            row = dict(
                conn.execute("SELECT * FROM notes WHERE id=?", (expected["note_id"],)).fetchone()
            )
            binding = generation._binding(conn)
        assert row["id"] == expected["note_id"] and row["paper_id"] == expected["paper_id"]
        assert row["created_at"] == expected["current"]["created_at"]
        assert row["body"] == loaded["body"] and row["page"] == 1
        assert json.loads(row["anchor"])["document_hash"] == value["source_a"]
        from paper_daily.sync_client import SyncClient
        from paper_daily.sync_journal import Journal
        from paper_daily.sync_research import research_writer

        client = SyncClient(
            Journal(
                value["path"], workspace_id=binding["workspace_id"], device_id=binding["device_id"]
            ),
            research_writer,
        )
        pending = client.journal.pending(1000)
        assert pending[-1]["entity_type"] == "note"
        assert pending[-1]["payload"]["anchor"]["document_hash"] == value["source_a"]
        assert pending[-1]["payload"]["body"] == loaded["body"]
        assert (
            reopened.decide(ready, body=loaded["body"], request_id=request, confirm_target=True)
            == result
        )
        assert client.journal.pending(1000) == pending
        assert (
            reopened.export_text(reopened.preview("archived_draft", archived.data["id"]))
            == old_text
        )
    finally:
        reopened.close()


def test_adopted_note_drafts_are_readable_without_old_jobs_or_old_folder_access(
    recovered_note, monkeypatch
):
    import sqlite3

    value = recovered_note
    review = value["review"]
    old_root = value["original"]["path"].parent.resolve()
    native_open, native_connect = Path.open, sqlite3.connect
    with closing(generation._connect(value["path"])) as conn:
        before = [tuple(row) for row in conn.execute("SELECT * FROM research_recovery_provenance")]

    def opened(path, *args, **kwargs):
        if path.resolve().is_relative_to(old_root):
            pytest.fail("Adopted note reader followed the old folder")
        return native_open(path, *args, **kwargs)

    def connected(path, *args, **kwargs):
        if old_root.as_posix().lower() in str(path).replace(chr(92), "/").lower():
            pytest.fail("Adopted note reader followed the old database")
        return native_connect(path, *args, **kwargs)

    with monkeypatch.context() as patches:
        patches.setattr(Path, "open", opened)
        patches.setattr(sqlite3, "connect", connected)
        exports = [
            review.export_text(review.preview("archived_draft", item["id"]))
            for item in value["items"]
        ]
        assert any("First human note interpretation" in text for text in exports)
        assert any("Second human note interpretation" in text for text in exports)
        with closing(generation._connect(value["path"])) as conn:
            assert [
                tuple(row) for row in conn.execute("SELECT * FROM research_recovery_provenance")
            ] == before
            assert not conn.execute(
                "SELECT name FROM sqlite_master WHERE name='research_review_drafts'"
            ).fetchone()
    review.close()
