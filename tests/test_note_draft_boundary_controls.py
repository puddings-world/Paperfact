"""Exact source locations and live receiver ownership during note continuation."""

import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_archived_draft_resumption import client_for
from test_archived_draft_resumption import copied as copied
from test_archived_draft_resumption import decision as decision
from test_archived_draft_resumption import draft_variants as draft_variants
from test_archived_draft_resumption import source as source
from test_note_draft_resumption import recovered_note as recovered_note
from test_note_draft_resumption_edges import note_rows, selected, stored

from paper_daily import research_generation as generation
from paper_daily.desktop import original_version
from paper_daily.research_review import ResearchReview
from paper_daily.sync_artifacts import paths


@pytest.mark.parametrize(
    "recovered_note",
    [{"anchor": {"p0": 0, "o0": 0, "p1": 0, "o1": 8, "document_hash": "source-a"}}],
    indirect=True,
)
def test_note_word_anchor_outside_actual_original_refuses_without_writes(recovered_note):
    value, review = recovered_note, recovered_note["review"]
    preview = selected(value)
    assert preview.data["retained"]["anchor"]["o1"] == 8
    review.save_draft(preview, "Keep human text with unresolved position", "invalid-word-note")
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    try:
        with pytest.raises(ValueError, match="word|anchor|position"):
            review.verify_resumed_draft(preview)
        assert stored(value) == before
        assert client_for(value["path"]).journal.pending(1000) == pending
        assert not review._resume_sources and not review._resume_documents
        assert review.load_draft(preview.data["origin"], preview.data["id"])["body"] == (
            "Keep human text with unresolved position"
        )
    finally:
        review.close()


@pytest.mark.parametrize("change", ["device", "incomplete", "missing-binding", "replaced-index"])
def test_late_recovered_store_rebind_revokes_apply_and_original_revalidation(
    recovered_note, change
):
    value, review = recovered_note, recovered_note["review"]
    ready = review.verify_resumed_draft(selected(value))
    review.save_draft(ready, "Keep text through store rebind", "rebound-note")
    snapshot = original_version.prepare_resumed_draft(review, ready, value["source_a"])
    assert snapshot is not None
    with closing(generation._connect(value["path"])) as conn:
        store, _versions = paths(conn)
    index = store.root / "index.sqlite"
    with closing(sqlite3.connect(index)) as conn, conn:
        binding = tuple(
            conn.execute("SELECT workspace,device,research_path FROM transfer_binding").fetchone()
        )
        if change == "device":
            conn.execute("UPDATE transfer_binding SET device='different-device'")
        elif change == "incomplete":
            conn.execute("UPDATE blobs SET complete=0 WHERE digest=?", (value["source_a"],))
        elif change == "missing-binding":
            conn.execute("DELETE FROM transfer_binding")
    saved_index = index.with_name("original-index.sqlite")
    if change == "replaced-index":
        copied_index = index.with_name("replacement-index.sqlite")
        with (
            closing(sqlite3.connect(index)) as source,
            closing(sqlite3.connect(copied_index)) as target,
        ):
            source.backup(target)
        index.replace(saved_index)
        copied_index.replace(index)
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    try:
        with pytest.raises(ValueError, match="store|binding|owner|device"):
            review.decide(
                ready,
                body="Keep text through store rebind",
                request_id=str(uuid4()),
                confirm_target=True,
            )
        with pytest.raises(original_version.OriginalUnavailable):
            original_version.refresh_draft(snapshot, lambda: False)
        assert stored(value) == before
        assert client_for(value["path"]).journal.pending(1000) == pending
        assert review.load_draft(ready.data["origin"], ready.data["id"])["body"] == (
            "Keep text through store rebind"
        )
        if change == "replaced-index":
            index.unlink()
            saved_index.replace(index)
        with closing(sqlite3.connect(index)) as conn, conn:
            conn.execute("DELETE FROM transfer_binding")
            conn.execute("INSERT INTO transfer_binding VALUES(1,?,?,?)", binding)
            conn.execute("UPDATE blobs SET complete=1 WHERE digest=?", (value["source_a"],))
        retry = review.verify_resumed_draft(ready)
        assert retry.data["source_hash"] == value["source_a"]
    finally:
        review.close()


@pytest.mark.parametrize("change", ["missing-manifest", "changed-row"])
def test_incomplete_or_changed_provenance_refuses_then_repair_restores_both_variants(
    recovered_note, change
):
    value, review = recovered_note, recovered_note["review"]
    original = [
        review.export_text(review.preview("archived_draft", item["id"])) for item in value["items"]
    ]
    with closing(sqlite3.connect(value["path"])) as conn:
        saved = [tuple(row) for row in conn.execute("SELECT * FROM research_recovery_provenance")]
    victim = next(
        row
        for row in saved
        if json.loads(row[1])["kind"] == ("manifest" if change == "missing-manifest" else "row")
    )
    with closing(sqlite3.connect(value["path"])) as conn, conn:
        if change == "missing-manifest":
            conn.execute("DELETE FROM research_recovery_provenance WHERE record_id=?", (victim[0],))
        else:
            conn.execute(
                "UPDATE research_recovery_provenance SET body_json=? WHERE record_id=?",
                (victim[1] + " ", victim[0]),
            )
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    try:
        with pytest.raises(ValueError):
            review.page(limit=100)
        assert stored(value) == before
        assert client_for(value["path"]).journal.pending(1000) == pending
        with closing(sqlite3.connect(value["path"])) as conn, conn:
            conn.execute("DELETE FROM research_recovery_provenance")
            conn.executemany("INSERT INTO research_recovery_provenance VALUES(?,?)", saved)
        reopened = ResearchReview(value["path"])
        try:
            assert [
                reopened.export_text(reopened.preview("archived_draft", item["id"]))
                for item in value["items"]
            ] == original
        finally:
            reopened.close()
    finally:
        review.close()


@pytest.mark.parametrize(
    "recovered_note",
    [
        {"anchor": {"p0": 0, "o0": 0, "p1": 0, "o1": 3}, "page": 1},
        {"anchor": None, "page": 1},
    ],
    indirect=True,
)
def test_position_without_a_recorded_pdf_remains_a_private_unresolved_draft(recovered_note):
    value, review = recovered_note, recovered_note["review"]
    preview = selected(value)
    assert preview.data["source_hash"] is None
    review.save_draft(preview, "Retain unresolved note position", "unresolved-position")
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    try:
        with pytest.raises(ValueError, match="recorded PDF version"):
            review.verify_resumed_draft(preview)
        assert (
            stored(value) == before and client_for(value["path"]).journal.pending(1000) == pending
        )
        assert not review._resume_sources and not review._resume_cache_owners
        assert review.load_draft(preview.data["origin"], preview.data["id"])["body"] == (
            "Retain unresolved note position"
        )
    finally:
        review.close()


@pytest.mark.parametrize(
    "recovered_note",
    [{"anchor": {"p0": 1, "o0": 0, "p1": 1, "o1": 3, "document_hash": "source-a"}, "page": 2}],
    indirect=True,
)
def test_note_page_outside_exact_a_never_uses_current_b_instead(recovered_note):
    value, review = recovered_note, recovered_note["review"]
    preview = selected(value)
    assert preview.data["source_hash"] == value["source_a"] != value["source_b"]
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    try:
        with pytest.raises(ValueError, match="page.*outside"):
            review.verify_resumed_draft(preview)
        assert (
            stored(value) == before and client_for(value["path"]).journal.pending(1000) == pending
        )
        assert not review._resume_sources and not review._resume_cache_owners
    finally:
        review.close()


def test_unrelated_cache_write_allows_same_source_revalidation_and_note_apply(recovered_note):
    import hashlib

    from paper_daily import resumed_draft_originals
    from paper_daily.sync_artifacts import stage_bytes

    value, review = recovered_note, recovered_note["review"]
    ready = review.verify_resumed_draft(selected(value))
    snapshot = original_version.prepare_resumed_draft(review, ready, value["source_a"])
    with closing(generation._connect(value["path"])) as conn:
        store, _versions = paths(conn)
    data = b"Unrelated cached research asset"
    stage_bytes(store, {hashlib.sha256(data).hexdigest(): data})
    try:
        assert resumed_draft_originals.gui_status(snapshot.draft_proof) == "recheck"
        refreshed = original_version.refresh_draft(snapshot, lambda: False)
        assert refreshed.document_hash == snapshot.document_hash == value["source_a"]
        assert refreshed.data == snapshot.data
        result = review.decide(
            ready,
            body="Same source after unrelated cache write",
            request_id=str(uuid4()),
            confirm_target=True,
        )
        assert result["decision"] == "applied"
        assert note_rows(value, "body") == [("Same source after unrelated cache write",)]
    finally:
        review.close()


def test_failed_reverification_revokes_old_apply_proof_and_retry_preserves_private_text(
    recovered_note, monkeypatch
):
    from paper_daily import review_cached_source

    value, review = recovered_note, recovered_note["review"]
    ready = review.verify_resumed_draft(selected(value))
    review.save_draft(ready, "Private text after failed recheck", "private-recheck")
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    check = review_cached_source.check

    def failed(*args):
        raise ValueError("Synthetic final source-owner check failure")

    try:
        monkeypatch.setattr(review_cached_source, "check", failed)
        with pytest.raises(ValueError, match="final source-owner"):
            review.verify_resumed_draft(ready)
        assert (
            not review._resume_sources
            and not review._resume_documents
            and not review._resume_cache_owners
        )
        with pytest.raises(ValueError, match="Verify"):
            review.decide(
                ready,
                body="Private text after failed recheck",
                request_id=str(uuid4()),
                confirm_target=True,
            )
        assert (
            stored(value) == before and client_for(value["path"]).journal.pending(1000) == pending
        )
        assert review.load_draft(ready.data["origin"], ready.data["id"])["body"] == (
            "Private text after failed recheck"
        )
        monkeypatch.setattr(review_cached_source, "check", check)
        retry = review.verify_resumed_draft(ready)
        assert retry.data["apply"] and retry.data["source_hash"] == value["source_a"]
    finally:
        review.close()


def test_explicit_other_note_target_preserves_its_creation_identity_and_original_target(
    recovered_note,
):
    value, review = recovered_note, recovered_note["review"]
    target = next(
        item
        for item in review.resume_targets(value["archived"])["items"]
        if "A research note" in item["title"]
    )
    preview = review.resume_draft(value["archived"], target["id"])
    expected = preview.data["expected"]
    original = note_rows(value, "id,paper_id,created_at,body,anchor")
    assert expected["note_id"] != value["target_note_id"]
    assert expected["current"]["created_at"] != "2026-11-01T00:00:00+00:00"
    assert preview.data["retained"]["created_at"] == expected["current"]["created_at"]
    try:
        ready = review.verify_resumed_draft(preview)
        review.decide(
            ready,
            body="Explicitly reviewed into another note",
            request_id=str(uuid4()),
            confirm_target=True,
        )
        with closing(generation._connect(value["path"])) as conn:
            actual = dict(
                conn.execute("SELECT * FROM notes WHERE id=?", (expected["note_id"],)).fetchone()
            )
        assert actual["id"] == expected["note_id"] and actual["paper_id"] == expected["paper_id"]
        assert actual["created_at"] == expected["current"]["created_at"]
        assert actual["body"] == "Explicitly reviewed into another note"
        assert json.loads(actual["anchor"])["document_hash"] == value["source_a"]
        assert note_rows(value, "id,paper_id,created_at,body,anchor") == original
    finally:
        review.close()
