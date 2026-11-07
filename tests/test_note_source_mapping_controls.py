"""Private choices do not bypass current ownership, CAS or atomic publication."""

import sqlite3
from contextlib import closing

import pytest
from test_archived_draft_resumption import client_for
from test_archived_draft_resumption import copied as copied
from test_archived_draft_resumption import decision as decision
from test_archived_draft_resumption import draft_variants as draft_variants
from test_archived_draft_resumption import source as source
from test_note_draft_resumption import recovered_note as recovered_note
from test_note_draft_resumption_edges import note_rows, selected, stored
from test_note_source_mapping import UNKNOWN, picked

from paper_daily import resumed_draft_originals, source_snapshots
from paper_daily.research_review_drafts import DraftConflict


@pytest.mark.parametrize("recovered_note", [UNKNOWN], indirect=True)
def test_chosen_source_receipt_changes_revoke_view_and_apply_then_retry_commits_once(
    recovered_note, tmp_path, monkeypatch
):
    value, review = recovered_note, recovered_note["review"]
    preview = selected(value)
    source = review.inspect_note_source(preview, picked(value, tmp_path))
    chosen = review.choose_note_source(preview, source, dict(p0=0, o0=0, p1=0, o1=3))
    review.save_draft(chosen, "Retained after receipt failure", "chosen-before-failure")
    ready = review.verify_resumed_draft(chosen)
    original = resumed_draft_originals.prepare(review, ready, value["source_a"])
    assert (
        original.data == source.content and resumed_draft_originals.gui_status(original) == "ready"
    )
    receipt = source_snapshots.receipt_path(
        value["path"], chosen.data["expected"]["source_choice"]["receipt"]
    )
    saved = receipt.read_bytes()
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    receipt.write_bytes(b"{}")
    assert resumed_draft_originals.gui_status(original) == "revoked"
    with pytest.raises(ValueError, match="changed"):
        review.decide(
            ready,
            body="Retained after receipt failure",
            request_id="chosen-apply",
            confirm_target=True,
        )
    assert stored(value) == before and client_for(value["path"]).journal.pending(1000) == pending
    receipt.write_bytes(saved)
    ready = review.verify_resumed_draft(chosen)
    index = review._resume_sources[next(iter(review._resume_sources))].store.root / "index.sqlite"
    with closing(sqlite3.connect(index)) as conn:
        actual_device = conn.execute("SELECT device FROM transfer_binding WHERE id=1").fetchone()[0]
    for damage, repair, error in (
        (
            "UPDATE transfer_binding SET device='another-device' WHERE id=1",
            "UPDATE transfer_binding SET device=? WHERE id=1",
            "another workspace/device/database",
        ),
        (
            "UPDATE blobs SET complete=0 WHERE digest=?",
            "UPDATE blobs SET complete=1 WHERE digest=?",
            "complete exact source",
        ),
    ):
        args = (value["source_a"],) if "digest=?" in damage else ()
        with closing(sqlite3.connect(index)) as conn, conn:
            conn.execute(damage, args)
        with pytest.raises(ValueError, match=error):
            review.decide(
                ready,
                body="Retained after receipt failure",
                request_id="chosen-apply",
                confirm_target=True,
            )
        assert (
            stored(value) == before and client_for(value["path"]).journal.pending(1000) == pending
        )
        repair_args = args if args else (actual_device,)
        with closing(sqlite3.connect(index)) as conn, conn:
            conn.execute(repair, repair_args)
        ready = review.verify_resumed_draft(chosen)
    native = review._receipt

    def fail(*args):
        raise RuntimeError("Synthetic chosen-source receipt failure")

    monkeypatch.setattr(review, "_receipt", fail)
    with pytest.raises(RuntimeError, match="receipt failure"):
        review.decide(
            ready,
            body="Retained after receipt failure",
            request_id="chosen-apply",
            confirm_target=True,
        )
    assert stored(value) == before and client_for(value["path"]).journal.pending(1000) == pending
    assert (
        review.load_draft(chosen.data["origin"], chosen.data["id"])["body"]
        == "Retained after receipt failure"
    )
    monkeypatch.setattr(review, "_receipt", native)
    result = review.decide(
        ready, body="Retained after receipt failure", request_id="chosen-apply", confirm_target=True
    )
    assert (
        review.decide(
            ready,
            body="Retained after receipt failure",
            request_id="chosen-apply",
            confirm_target=True,
        )
        == result
    )
    assert note_rows(value, "body") == [("Retained after receipt failure",)]
    assert len(client_for(value["path"]).journal.pending(1000)) == len(pending) + 2
    review.close()


@pytest.mark.parametrize("recovered_note", [UNKNOWN], indirect=True)
def test_two_window_source_choice_cas_preserves_both_manual_texts_and_current_note(
    recovered_note, tmp_path
):
    value, review = recovered_note, recovered_note["review"]
    preview = selected(value)
    original = review.inspect_note_source(preview, picked(value, tmp_path))
    chosen = review.choose_note_source(preview, original, dict(p0=0, o0=1, p1=0, o1=2))
    first = review.save_draft(chosen, "First human choice", "window-one")
    plain = review.clear_note_position(chosen)
    latest = review.save_draft(
        plain,
        "Newer plain interpretation",
        "window-two",
        draft_id=first["draft_id"],
        revision=first["revision"],
    )
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    with pytest.raises(DraftConflict):
        review.save_draft(
            chosen,
            "Older unsaved manual text",
            "window-one",
            draft_id=first["draft_id"],
            revision=first["revision"],
        )
    assert chosen.data["retained"]["anchor"]["selection"]["quote"] == "verified source"
    assert "Older unsaved manual text" in review.export_text(
        chosen, body="Older unsaved manual text"
    )
    loaded = review.load_draft(plain.data["origin"], plain.data["id"], draft_id=latest["draft_id"])
    assert loaded["body"] == "Newer plain interpretation"
    assert loaded["preview"].data["expected"]["source_choice"]["action"] == "plain"
    assert stored(value) == before and client_for(value["path"]).journal.pending(1000) == pending
    from paper_daily.archived_note_resume import _row_payload

    data = preview.data
    payload = _row_payload(data["expected"]["current"], data["expected"]["paper_sync_id"])
    payload["body"] = "A concurrent edit in another window"
    client = client_for(value["path"])
    client.save(client.new_graph_operation("note", data["expected"]["note_sync_id"], payload))
    after = stored(value)
    with pytest.raises(ValueError, match="changed"):
        review.choose_note_source(preview, original, dict(p0=0, o0=0, p1=0, o1=3))
    assert stored(value) == after
    assert note_rows(value, "body") == [(payload["body"],)]
    review.close()
