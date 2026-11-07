"""Source-less notes and accepted source-aware notes remain portable research."""

import copy
import json
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_archived_draft_resumption import client_for, rows
from test_archived_draft_resumption import copied as copied
from test_archived_draft_resumption import decision as decision
from test_archived_draft_resumption import draft_variants as draft_variants
from test_archived_draft_resumption import source as source
from test_enrollment_history_peer import peer
from test_note_draft_resumption import recovered_note as recovered_note
from test_note_draft_resumption_edges import note_rows, selected

from paper_daily import research_generation as generation
from paper_daily import research_review_drafts as drafts
from paper_daily import sync_recovery, sync_source_files
from paper_daily.document_reader import DocumentReader
from paper_daily.research_review import ResearchReview, encode
from paper_daily.sync_artifacts import paths


@pytest.mark.parametrize("recovered_note", ["plain"], indirect=True)
def test_plain_note_never_borrows_current_pdf_or_keeps_its_anchor(recovered_note):
    value, review = recovered_note, recovered_note["review"]
    preview = selected(value)
    assert preview.data["source_hash"] is None
    assert preview.data["retained"]["anchor"] is None and preview.data["retained"]["page"] is None
    assert preview.data["expected"]["document"]["sha256"] == value["source_b"]
    pending = client_for(value["path"]).journal.pending(1000)
    ready = review.verify_resumed_draft(preview)
    review.decide(
        ready, body="A source-less manual note", request_id=str(uuid4()), confirm_target=True
    )
    assert note_rows(value, "body,page,anchor") == [("A source-less manual note", None, None)]
    added = client_for(value["path"]).journal.pending(1000)[len(pending) :]
    assert len(added) == 1 and added[0]["entity_type"] == "note"
    assert added[0]["payload"]["anchor"] is None and added[0]["payload"]["page"] is None
    review.close()


def test_accepted_note_and_exact_originals_reach_peer_and_survive_second_backup(
    recovered_note, tmp_path
):
    value, review = recovered_note, recovered_note["review"]
    ready = review.verify_resumed_draft(selected(value))
    private = review.save_draft(ready, "Continued note for peer", "peer-note-draft")
    review.decide(
        ready, body="Continued note for peer", request_id="peer-note-apply", confirm_target=True
    )
    peer_root = tmp_path / "new-device"
    peer_root.mkdir()
    _a, b, _service, _ta, _tb, portable, local, _files = peer(value["result"], peer_root)
    note = rows(
        b.journal.path, "SELECT body,page,anchor FROM notes WHERE body='Continued note for peer'"
    )[0]
    assert note[0] == "Continued note for peer" and note[1] == 1
    assert json.loads(note[2])["document_hash"] == value["source_a"]
    with b.journal.transaction() as conn:
        original = sync_source_files.resolved(conn, portable, value["source_a"])
        assert original.read_bytes() == value["original"]["value"]["original_bytes"]
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='research_review_drafts'"
        ).fetchone()
    current = DocumentReader.from_workspace(b.journal.path).resolve(local)
    assert current.sha256 == value["source_b"] and current.sha256 != value["source_a"]
    with closing(generation._connect(value["path"])) as conn:
        store, _versions = paths(conn)
        saved = dict(
            conn.execute(
                "SELECT * FROM research_review_drafts WHERE draft_id=?", (private["draft_id"],)
            ).fetchone()
        )
    backup = tmp_path / "continued-note.zip"
    sync_recovery.create(
        value["path"], backup, blob_store=store, pdf_roots=[value["path"].parent / "pdf"]
    )
    destination = tmp_path / "continued-note-detached"
    sync_recovery.restore_detached(backup, destination)
    recovered = ResearchReview(destination / "papers.db")
    try:
        texts = [
            recovered.export_text(recovered.preview(item["origin"], item["id"]))
            for item in recovered.page(limit=100)["items"]
            if item["origin"] == "archived_draft"
        ]
        assert any("Continued note for peer" in body for body in texts)
        assert any("First human note interpretation" in body for body in texts)
        assert any("Second human note interpretation" in body for body in texts)
        assert rows(destination / "papers.db", "SELECT body,page,anchor FROM notes") == (
            rows(value["path"], "SELECT body,page,anchor FROM notes")
        )
        with closing(generation._connect(destination / "papers.db")) as conn:
            raw = conn.execute(
                "SELECT data FROM recovery_records WHERE table_name=?", ("research_review_drafts",)
            ).fetchone()[0]
        assert json.loads(raw) == saved
        assert (
            Path(destination / "objects" / value["source_a"]).read_bytes() == original.read_bytes()
        )
    finally:
        recovered.close()
        review.close()


def test_note_draft_codec_rejects_changed_protected_identity_source_and_observation(recovered_note):
    value, review = recovered_note, recovered_note["review"]
    preview = selected(value)
    saved = review.save_draft(preview, "Preserved edit despite broken metadata", "codec-note")
    with closing(generation._connect(value["path"])) as conn:
        row = dict(
            conn.execute(
                "SELECT * FROM research_review_drafts WHERE draft_id=?", (saved["draft_id"],)
            ).fetchone()
        )
    drafts.validate_record(row)
    changes = [
        lambda data: data["expected"].update(extra=True),
        lambda data: data["expected"].update(version=True),
        lambda data: data["expected"].update(note_id=True),
        lambda data: data["retained"].update(created_at="2001-01-01T00:00:00+00:00"),
        lambda data: data["retained"]["anchor"].update(document_hash=value["source_b"]),
        lambda data: data["expected"].update(paper_sync_id="not-a-paper"),
        lambda data: data["expected"]["observation"].update(kind="research_content"),
        lambda data: data["expected"]["observation"]["parents"][0].update(active=False),
        lambda data: data.update(parent_token="0" * 32),
    ]
    for mutate in changes:
        changed = copy.deepcopy(row)
        data = json.loads(changed["preview_json"])
        mutate(data)
        changed["preview_json"] = encode(data)
        changed["fingerprint"] = drafts._fingerprint(changed)
        with pytest.raises(ValueError):
            drafts.validate_record(changed)
    assert review.load_draft(preview.data["origin"], preview.data["id"])["body"] == (
        "Preserved edit despite broken metadata"
    )
    review.close()
