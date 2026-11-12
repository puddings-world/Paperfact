"""Explicit native source/position choice across real conflict and recovery."""

import json
from contextlib import closing
from uuid import uuid4

import pytest
from test_archived_draft_resumption import client_for
from test_archived_draft_resumption import copied as copied
from test_archived_draft_resumption import decision as decision
from test_archived_draft_resumption import draft_variants as draft_variants
from test_archived_draft_resumption import source as source
from test_enrollment_history_peer import peer
from test_note_draft_resumption import recovered_note as recovered_note
from test_note_draft_resumption_edges import note_rows, selected, stored

from paper_daily import research_generation as generation
from paper_daily import source_snapshots, sync_recovery, sync_source_files
from paper_daily.document_reader import DocumentReader
from paper_daily.research_review import ResearchReview
from paper_daily.sync_artifacts import paths

UNKNOWN = {"page": 1, "anchor": dict(p0=0, o0=0, p1=0, o1=3)}


def picked(value, tmp_path):
    path = tmp_path / "explicitly-picked.pdf"
    path.write_bytes(value["original"]["value"]["original_bytes"])
    return path


@pytest.mark.parametrize("recovered_note", [UNKNOWN], indirect=True)
def test_unknown_source_can_be_mapped_saved_reopened_applied_transferred_and_rebacked_up(
    recovered_note, tmp_path
):
    value, review = recovered_note, recovered_note["review"]
    preview = selected(value)
    assert preview.data["source_hash"] is None
    archive = review.export_text(value["archived"])
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    with pytest.raises(ValueError, match="recorded PDF"):
        review.verify_resumed_draft(preview)
    inspected = review.inspect_note_source(preview, picked(value, tmp_path))
    page = review.note_source_page(preview, inspected, 0)
    assert [w["text"] for w in page["words"]] == ["A", "verified", "source", "paper"]
    chosen = review.choose_note_source(preview, inspected, dict(p0=0, o0=0, p1=0, o1=3))
    assert chosen.data["expected"]["version"] == 2 and not chosen.data["apply"]
    choice = chosen.data["expected"]["source_choice"]
    assert choice["recorded_source"] is None and choice["source"] == value["source_a"]
    assert choice["anchor"]["selection"]["quote"] == "A verified source paper"
    assert stored(value) == before and client_for(value["path"]).journal.pending(1000) == pending
    assert len(source_snapshots.list_owned(value["path"])) == 1
    again = review.choose_note_source(preview, inspected, dict(p0=0, o0=0, p1=0, o1=3))
    assert again.data == chosen.data and len(source_snapshots.list_owned(value["path"])) == 1
    saved = review.save_draft(chosen, "My reviewed passage interpretation", "source-mapped-draft")
    review.close()
    review = value["review"] = ResearchReview(value["path"])
    loaded = review.load_draft(chosen.data["origin"], chosen.data["id"], draft_id=saved["draft_id"])
    assert loaded["state"] == "verification_required" and not loaded["preview"].data["apply"]
    assert loaded["body"] == "My reviewed passage interpretation"
    ready = review.verify_resumed_draft(loaded["preview"])
    result = review.decide(
        ready, body=loaded["body"], request_id="mapped-apply", confirm_target=True
    )
    assert (
        review.decide(ready, body=loaded["body"], request_id="mapped-apply", confirm_target=True)
        == result
    )
    row = note_rows(value, "body,page,anchor")[0]
    assert row[:2] == (loaded["body"], 1) and json.loads(row[2]) == choice["anchor"]
    assert (
        review.export_text(review.preview("archived_draft", value["archived"].data["id"]))
        == archive
    )
    current = DocumentReader.from_workspace(value["path"]).resolve(
        ready.data["expected"]["paper_id"]
    )
    assert current.sha256 == value["source_b"]
    peer_root = tmp_path / "mapped-peer"
    peer_root.mkdir()
    _a, b, _service, _ta, _tb, portable, _local, _files = peer(value["result"], peer_root)
    with b.journal.transaction() as conn:
        other = conn.execute("SELECT anchor FROM notes WHERE body=?", (loaded["body"],)).fetchone()
        assert json.loads(other[0]) == choice["anchor"]
        original = sync_source_files.resolved(conn, portable, value["source_a"])
        assert original.read_bytes() == inspected.content
    with closing(generation._connect(value["path"])) as conn:
        store, _versions = paths(conn)
    backup = tmp_path / "mapped-source.zip"
    sync_recovery.create(
        value["path"], backup, blob_store=store, pdf_roots=[value["path"].parent / "pdf"]
    )
    destination = tmp_path / "mapped-detached"
    sync_recovery.restore_detached(backup, destination)
    with closing(generation._connect(destination / "papers.db")) as conn:
        rows = conn.execute(
            "SELECT data FROM recovery_records WHERE table_name='research_review_drafts'"
        ).fetchall()
        snapshots = [json.loads(json.loads(row[0])["preview_json"]) for row in rows]
        mapped = next(s for s in snapshots if s["origin"] == "archived_note_resume")
        assert mapped["expected"]["source_choice"] == choice
        assert (destination / "objects" / value["source_a"]).read_bytes() == inspected.content
    from paper_daily.recovery_adoption import RecoveryAdoptionService

    adoption = RecoveryAdoptionService(destination / "papers.db")
    inspection = adoption.inspect()
    assert inspection.report["supported"], inspection.report
    adopted = adoption.prepare(
        inspection,
        tmp_path / "mapped-again",
        backup_output=tmp_path / "mapped-again.zip",
        request_id=str(uuid4()),
    )
    with_review = ResearchReview(adopted["database"])
    try:
        item = next(
            item
            for item in with_review.page(limit=100)["items"]
            if item["origin"] == "archived_draft" and loaded["body"] in item["summary"]
        )
        draft = with_review.preview(item["origin"], item["id"])
        target = next(
            target
            for target in with_review.resume_targets(draft)["items"]
            if loaded["body"] in target["title"]
        )
        resumed = with_review.resume_draft(draft, target["id"])
        inherited = resumed.data["expected"]["source_choice"]
        assert inherited["action"] == "retained" and inherited["receipt"] is None
        assert inherited["recorded_source"] is None and inherited["source"] == value["source_a"]
        # Readability of old receipts is not authority to follow their old paths.
        verified = with_review.verify_resumed_draft(resumed)
        assert verified.data["apply"] and verified.data["retained"]["anchor"] == choice["anchor"]
    finally:
        with_review.close()
    review.close()


@pytest.mark.parametrize(
    "recovered_note",
    [{"page": 99, "anchor": dict(p0=98, o0=0, p1=98, o1=3, document_hash="source-a")}],
    indirect=True,
)
def test_bad_position_can_be_removed_without_erasing_recorded_provenance(recovered_note):
    value, review = recovered_note, recovered_note["review"]
    preview = selected(value)
    with pytest.raises(ValueError, match="outside"):
        review.verify_resumed_draft(preview)
    cleared = review.clear_note_position(preview)
    choice = cleared.data["expected"]["source_choice"]
    assert choice["recorded_source"] == value["source_a"] and choice["source"] is None
    assert choice["action"] == "plain" and cleared.data["retained"]["anchor"] is None
    saved = review.save_draft(
        cleared, "Manual interpretation without source position", "plain-choice"
    )
    loaded = review.load_draft(
        cleared.data["origin"], cleared.data["id"], draft_id=saved["draft_id"]
    )
    ready = review.verify_resumed_draft(loaded["preview"])
    review.decide(ready, body=loaded["body"], request_id="plain-choice-apply", confirm_target=True)
    assert note_rows(value, "body,page,anchor") == [(loaded["body"], None, None)]
    original = review.preview("archived_draft", value["archived"].data["id"])
    assert original.data["record_hash"] == preview.data["record_hash"]
    with closing(review._connect()) as conn:
        from paper_daily.archived_note_resume import _historical

        old, old_source, _snapshot = _historical(
            review._record(conn, original.data["origin"], original.data["id"])
        )
    assert old["page"] == 99 and old["anchor"]["p0"] == 98
    assert old_source == value["source_a"]
    review.close()


@pytest.mark.parametrize("recovered_note", [UNKNOWN], indirect=True)
def test_cancel_changed_file_and_stale_or_closed_owner_do_not_publish_research(
    recovered_note, tmp_path
):
    value, review = recovered_note, recovered_note["review"]
    preview, source = selected(value), picked(value, tmp_path)
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    with pytest.raises(InterruptedError):
        review.inspect_note_source(preview, source, cancelled=lambda: True)
    inspected = review.inspect_note_source(preview, source)
    with pytest.raises(InterruptedError):
        review.choose_note_source(
            preview, inspected, dict(p0=0, o0=0, p1=0, o1=3), cancelled=lambda: True
        )
    assert source_snapshots.list_owned(value["path"]) == []
    source.write_bytes(b"Not a PDF")
    with pytest.raises(ValueError, match="changed"):
        review.choose_note_source(preview, inspected, dict(p0=0, o0=0, p1=0, o1=3))
    with pytest.raises(ValueError, match="not readable"):
        review.inspect_note_source(preview, source)
    assert stored(value) == before and client_for(value["path"]).journal.pending(1000) == pending
    review.close()
    with pytest.raises(ValueError):
        review.clear_note_position(preview)
