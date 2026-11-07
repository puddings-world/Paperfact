"""Researcher-visible note recovery safety, without accounts or owner data."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from uuid import uuid4

import pytest
from test_archived_draft_resumption import client_for, rows
from test_archived_draft_resumption import copied as copied
from test_archived_draft_resumption import decision as decision
from test_archived_draft_resumption import draft_variants as draft_variants
from test_archived_draft_resumption import source as source
from test_note_draft_resumption import recovered_note as recovered_note

from paper_daily import research_generation as generation
from paper_daily import sync_capture
from paper_daily.research_review import ResearchReview
from paper_daily.research_review_drafts import DraftConflict
from paper_daily.sync_artifacts import paths


def note_rows(value, fields):
    with closing(generation._connect(value["path"])) as conn:
        return [
            tuple(row)
            for row in conn.execute(
                "SELECT " + fields + " FROM notes WHERE id=?", (value["target_note_id"],)
            )
        ]


def selected(value):
    review, archived = value["review"], value["archived"]
    target = next(
        item
        for item in review.resume_targets(archived)["items"]
        if "Current anchored note B" in item["title"]
    )
    return review.resume_draft(archived, target["id"])


def stored(value):
    with closing(generation._connect(value["path"])) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        return {
            table: [tuple(row) for row in conn.execute("SELECT * FROM " + table)]
            if table in tables
            else None
            for table in ("notes", "research_file_versions", "research_review_receipts")
        }


@pytest.mark.parametrize("target", ["", "missing"])
def test_empty_or_missing_note_target_leaves_archive_notes_and_queue_unchanged(
    recovered_note, target
):
    value, review = recovered_note, recovered_note["review"]
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    original = review.export_text(value["archived"])
    with pytest.raises(ValueError):
        review.resume_draft(value["archived"], str(uuid4()) if target else target)
    assert stored(value) == before
    assert client_for(value["path"]).journal.pending(1000) == pending
    assert review.export_text(value["archived"]) == original
    review.close()


def test_note_receipt_failure_rolls_back_note_source_and_queue_then_retry_saves_once(
    recovered_note, monkeypatch
):
    value, review = recovered_note, recovered_note["review"]
    ready = review.verify_resumed_draft(selected(value))
    request = str(uuid4())
    review.save_draft(ready, "Human note survives failed commit", request)
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    receipt = review._receipt

    def fail(*args):
        raise RuntimeError("Synthetic receipt write failure")

    monkeypatch.setattr(review, "_receipt", fail)
    with pytest.raises(RuntimeError, match="receipt write"):
        review.decide(
            ready, body="Human note survives failed commit", request_id=request, confirm_target=True
        )
    assert stored(value) == before
    assert client_for(value["path"]).journal.pending(1000) == pending
    assert review.load_draft(ready.data["origin"], ready.data["id"])["body"] == (
        "Human note survives failed commit"
    )
    monkeypatch.setattr(review, "_receipt", receipt)
    result = review.decide(
        ready, body="Human note survives failed commit", request_id=request, confirm_target=True
    )
    assert result["decision"] == "applied"
    assert len(client_for(value["path"]).journal.pending(1000)) == len(pending) + 2
    assert note_rows(value, "body") == [("Human note survives failed commit",)]
    review.close()


def test_eight_simultaneous_note_applies_preserve_identity_and_create_one_change(recovered_note):
    value, review = recovered_note, recovered_note["review"]
    ready = review.verify_resumed_draft(selected(value))
    pending = client_for(value["path"]).journal.pending(1000)
    request = str(uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: review.decide(
                    ready, body="One reviewed note", request_id=request, confirm_target=True
                ),
                range(8),
            )
        )
    assert results == [results[0]] * 8
    assert len(client_for(value["path"]).journal.pending(1000)) == len(pending) + 2
    assert rows(value["path"], "SELECT count(*) FROM research_review_receipts") == [(1,)]
    row = note_rows(value, "id,paper_id,created_at,body,anchor")[0]
    expected = ready.data["expected"]
    assert row[:3] == (expected["note_id"], expected["paper_id"], expected["current"]["created_at"])
    assert row[3] == "One reviewed note"
    assert json.loads(row[4])["document_hash"] == value["source_a"]
    with pytest.raises(ValueError, match="changed"):
        review.decide(ready, body="Changed retry", request_id=request, confirm_target=True)
    review.close()


def test_two_note_windows_keep_winning_private_edit_and_export_losing_text(recovered_note):
    value, review = recovered_note, recovered_note["review"]
    preview = selected(value)
    first = review.save_draft(preview, "First private edit", "first-note-save")
    other = ResearchReview(value["path"])
    try:
        loaded = other.load_draft(preview.data["origin"], preview.data["id"])
        winner = other.save_draft(
            loaded["preview"], "Second window wins", "second-note-save", **first
        )
        with pytest.raises(DraftConflict):
            review.save_draft(preview, "First window losing text", "losing-note-save", **first)
        latest = review.load_draft(preview.data["origin"], preview.data["id"])
        assert latest["body"] == "Second window wins" and latest["revision"] == winner["revision"]
        assert "First window losing text" in review.export_text(
            preview, body="First window losing text"
        )
        assert note_rows(value, "body") == [("Current anchored note B",)]
    finally:
        other.close()
        review.close()


@pytest.mark.parametrize("change", ["note", "paper", "recreate"])
def test_changed_note_or_parent_never_silently_rebases_saved_recovered_draft(
    recovered_note, change
):
    value, review = recovered_note, recovered_note["review"]
    preview = selected(value)
    review.save_draft(preview, "Retain my reviewed interpretation", "stale-note")
    expected = preview.data["expected"]
    with closing(generation._connect(value["path"])) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with sync_capture.expecting(conn, [expected["observation"]]):
            if change == "note":
                conn.execute(
                    "UPDATE notes SET body='Other human edit' WHERE id=?", (expected["note_id"],)
                )
            elif change == "paper":
                conn.execute(
                    "UPDATE papers SET title='Renamed parent' WHERE id=?", (expected["paper_id"],)
                )
            else:
                conn.execute("DELETE FROM notes WHERE id=?", (expected["note_id"],))
            conn.commit()
    if change == "recreate":
        # Restoring a deleted note is explicit; raw INSERT is intentionally
        # retained as a stale candidate by the maintained capture boundary.
        payload = {
            key: expected["current"][key]
            for key in ("body", "kind", "created_at", "page", "anchor")
        }
        payload["paper_id"] = expected["paper_sync_id"]
        payload["anchor"] = json.loads(payload["anchor"])
        client = client_for(value["path"])
        client.save(
            client.new_graph_operation("note", expected["note_sync_id"], payload, restore=True)
        )
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    with pytest.raises(ValueError, match="changed|removed|inactive|current"):
        review.verify_resumed_draft(preview)
    assert stored(value) == before
    assert client_for(value["path"]).journal.pending(1000) == pending
    assert review.load_draft(preview.data["origin"], preview.data["id"])["body"] == (
        "Retain my reviewed interpretation"
    )
    review.close()


@pytest.mark.parametrize("change", ["workspace", "device", "research_path", "complete", "bytes"])
def test_recovered_source_cache_refuses_wrong_binding_or_damaged_bytes_and_can_retry(
    recovered_note, change
):
    value, review = recovered_note, recovered_note["review"]
    preview = selected(value)
    review.save_draft(preview, "Keep edit during unavailable A", "cache-note")
    with closing(generation._connect(value["path"])) as conn:
        store, _root = paths(conn)
    index = store.root / "index.sqlite"
    original = store.root / "objects" / value["source_a"]
    content = original.read_bytes()
    with closing(sqlite3.connect(index)) as conn, conn:
        binding = tuple(
            conn.execute("SELECT workspace,device,research_path FROM transfer_binding").fetchone()
        )
        if change in {"workspace", "device", "research_path"}:
            conn.execute("UPDATE transfer_binding SET " + change + "=?", ("another-owner",))
        elif change == "complete":
            conn.execute("UPDATE blobs SET complete=0 WHERE digest=?", (value["source_a"],))
    if change == "bytes":
        original.write_bytes(b"Damaged original")
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    with pytest.raises((ValueError, FileNotFoundError)):
        review.verify_resumed_draft(preview)
    assert stored(value) == before
    assert client_for(value["path"]).journal.pending(1000) == pending
    assert not review._resume_sources and not review._resume_documents
    assert review.load_draft(preview.data["origin"], preview.data["id"])["body"] == (
        "Keep edit during unavailable A"
    )
    original.write_bytes(content)
    with closing(sqlite3.connect(index)) as conn, conn:
        conn.execute("UPDATE transfer_binding SET workspace=?,device=?,research_path=?", binding)
        conn.execute("UPDATE blobs SET complete=1 WHERE digest=?", (value["source_a"],))
    ready = review.verify_resumed_draft(preview)
    assert ready.data["source_hash"] == value["source_a"] != value["source_b"]
    assert stored(value) == before
    assert client_for(value["path"]).journal.pending(1000) == pending
    review.close()
