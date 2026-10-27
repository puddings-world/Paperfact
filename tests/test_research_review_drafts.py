"""Durable drafts retain their displayed base and never become implicit writes."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_research_review import candidate, context, output, query
from test_research_review import remote as remote  # noqa: F401
from test_research_review import workspace as workspace  # noqa: F401

from paper_daily import research_generation as generation
from paper_daily import research_review_drafts as drafts
from paper_daily import sync_recovery
from paper_daily.research_review import ResearchReview


def setup(path, *, source_hash=None):
    review = ResearchReview(path)
    identity = candidate(path, source_hash=source_hash)
    preview = review.preview("generation", identity)
    saved = review.save_draft(preview, "My edited draft", "draft-request")
    return review, identity, preview, saved


def records(path):
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM research_review_drafts")]


def test_restart_restores_exact_base_source_text_and_repeat_identity(workspace):
    path, client = workspace
    first, identity, preview, saved = setup(path, source_hash="a" * 64)
    pending = client.journal.pending()
    first.close()
    reopened = ResearchReview(path)
    restored = reopened.load_draft("generation", identity)
    assert restored["state"] == "ready"
    assert restored["body"] == "My edited draft"
    assert restored["request_id"] == "draft-request"
    assert restored["preview"].data["expected"] == preview.data["expected"]
    assert restored["preview"].data["source_hash"] == "a" * 64
    assert restored["preview"].data["session"] != preview.data["session"]
    assert client.journal.pending() == pending
    result = reopened.decide(
        restored["preview"], body=restored["body"], request_id=restored["request_id"]
    )
    assert query(path, "SELECT body FROM close_readings") == [("My edited draft",)]
    assert client.journal.pending()[-1]["payload"]["source_document_hash"] == "a" * 64
    third = ResearchReview(path)
    decided = third.load_draft("generation", identity)
    assert decided["state"] == "decided"
    assert (
        third.decide(decided["preview"], body=decided["body"], request_id="draft-request") == result
    )
    assert len(client.journal.pending()) == len(pending) + 1
    assert records(path)[0]["revision"] == saved["revision"]


def test_changed_research_never_silently_rebases_restored_draft(workspace):
    path, client = workspace
    old, identity, preview, saved = setup(path)
    generation.publish_generation(context(path), row=output("New saved research"))
    old.close()
    review = ResearchReview(path)
    restored = review.load_draft("generation", identity)
    assert restored["state"] == "stale"
    assert restored["preview"].data["expected"] == preview.data["expected"]
    before = client.journal.pending()
    with pytest.raises(ValueError, match="refreshed review"):
        review.decide(restored["preview"], body=restored["body"], request_id="must-not-rebase")
    assert query(path, "SELECT body FROM close_readings") == [("New saved research",)]
    assert client.journal.pending() == before
    changed = review.save_draft(
        restored["preview"], "Still editable but stale", "new-draft-request", **saved
    )
    again = review.load_draft("generation", identity)
    assert again["state"] == "stale" and again["body"] == "Still editable but stale"
    fresh = review.preview("generation", identity)
    review.save_draft(fresh, again["body"], "explicit-review", **changed)
    assert review.load_draft("generation", identity)["state"] == "ready"


def test_two_windows_cannot_overwrite_each_other_and_can_save_separate_copy(workspace):
    path, _ = workspace
    first, identity, preview, saved = setup(path)
    second = ResearchReview(path)
    other = second.load_draft("generation", identity)
    newer = first.save_draft(preview, "First window new text", "first-window", **saved)
    with pytest.raises(drafts.DraftConflict, match="another window"):
        second.save_draft(other["preview"], "Second window text", "second-window", **saved)
    assert first.load_draft("generation", identity)["body"] == "First window new text"
    separate = second.save_draft(other["preview"], "Second window text", "separate")
    assert separate["draft_id"] != newer["draft_id"]
    assert {row["body"] for row in records(path)} == {"First window new text", "Second window text"}
    assert second.load_draft("generation", identity)["body"] == "Second window text"


def test_exact_save_retry_is_idempotent(workspace):
    path, _ = workspace
    review, _identity, preview, saved = setup(path)
    assert review.save_draft(preview, "My edited draft", "draft-request", **saved) == saved
    assert len(records(path)) == 1
    assert records(path)[0]["revision"] == 1


def test_integrity_damage_preserves_recoverable_text_and_original_record(workspace):
    path, _ = workspace
    review, identity, preview, saved = setup(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("UPDATE research_review_drafts SET preview_json='broken json'")
        conn.commit()
    damaged = records(path)
    result = ResearchReview(path).load_draft("generation", identity)
    assert result["state"] == "corrupt" and result["body"] == "My edited draft"
    assert result["preview"] is None
    with pytest.raises(ValueError):
        review.save_draft(preview, "Do not overwrite damage", "new", **saved)
    assert records(path) == damaged


def test_replaced_database_blocks_flush_and_reopen_requires_explicit_target(workspace, tmp_path):
    path, _ = workspace
    review, identity, preview, saved = setup(path)
    archive = tmp_path / "previous.db"
    path.rename(archive)
    path.write_bytes(archive.read_bytes())
    unchanged = path.read_bytes()
    with pytest.raises(ValueError, match="replaced"):
        review.save_draft(preview, "Unsaved in old window", "old-window", **saved)
    assert path.read_bytes() == unchanged
    assert "Unsaved in old window" in review.export_text(preview, body="Unsaved in old window")
    reopened = ResearchReview(path)
    result = reopened.load_draft("generation", identity)
    assert result["state"] == "foreign"
    with pytest.raises(ValueError, match="earlier workspace"):
        reopened.decide(result["preview"], body=result["body"], request_id="foreign")
    selected = reopened.target_preview(result["preview"], "paper")
    reopened.save_draft(selected, result["body"], "explicit-new-owner")
    assert reopened.load_draft("generation", identity)["state"] == "ready"


def test_parent_lifecycle_change_does_not_discard_saved_offline_text(tmp_path):
    from test_research_lifecycle import legacy

    path = tmp_path / "offline.db"
    legacy(path)
    review = ResearchReview(path)
    identity = candidate(path)
    selected = review.target_preview(review.preview("generation", identity), "paper")
    review.save_draft(selected, "Offline retained text", "offline")
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM papers").fetchone())
        conn.execute(
            "INSERT OR REPLACE INTO papers("
            + ",".join(row)
            + ") VALUES("
            + ",".join("?" for _ in row)
            + ")",
            tuple(row.values()),
        )
        conn.commit()
    result = ResearchReview(path).load_draft("generation", identity)
    assert result["state"] == "stale" and result["body"] == "Offline retained text"
    assert result["preview"].data["parent_token"] == selected.data["parent_token"]


def test_failed_commit_rolls_back_private_revision(workspace, monkeypatch):
    path, _ = workspace
    review, _identity, preview, saved = setup(path)
    before = records(path)
    original = drafts.DraftStore._check
    calls = 0

    def fail_before_commit(self, conn):
        nonlocal calls
        calls += 1
        original(self, conn)
        if calls == 2:
            raise OSError("fixture commit boundary failure")

    monkeypatch.setattr(drafts.DraftStore, "_check", fail_before_commit)
    with pytest.raises(OSError, match="boundary failure"):
        review.save_draft(preview, "Do not claim saved", "failure", **saved)
    assert records(path) == before


def test_limits_do_not_evict_existing_drafts(workspace, monkeypatch):
    path, _ = workspace
    review, _identity, preview, saved = setup(path)
    before = records(path)
    with pytest.raises(ValueError, match="size"):
        review.save_draft(preview, "x" * (drafts.MAX_BODY + 1), "too-big", **saved)
    monkeypatch.setattr(drafts, "MAX_DRAFTS", 1)
    with pytest.raises(ValueError, match="limit"):
        review.save_draft(preview, "Separate", "quota")
    assert records(path) == before


def test_saved_order_does_not_depend_on_wall_clock(workspace):
    path, _ = workspace
    review, identity, preview, first = setup(path)
    second = review.save_draft(preview, "Second draft", "second")
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(
            conn.execute(
                "SELECT * FROM research_review_drafts WHERE draft_id=?", (first["draft_id"],)
            ).fetchone()
        )
        row["updated_at"] = "2099-01-01T00:00:00+00:00"
        row["fingerprint"] = drafts._fingerprint(row)
        conn.execute(
            "UPDATE research_review_drafts SET updated_at=?,fingerprint=? WHERE draft_id=?",
            (row["updated_at"], row["fingerprint"], first["draft_id"]),
        )
        conn.commit()
    result = review.load_draft("generation", identity)
    assert result["draft_id"] == second["draft_id"]


def test_backup_archives_drafts_as_readable_provenance_not_live_edit_state(workspace, tmp_path):
    path, _ = workspace
    _review, _identity, _preview, _saved = setup(path)
    before = records(path)
    package = tmp_path / "drafts.zip"
    sync_recovery.create(path, package)
    sync_recovery.restore_detached(package, tmp_path / "restore")
    restored = tmp_path / "restore" / "papers.db"
    with closing(sqlite3.connect(restored)) as conn:
        rowid, encoded = conn.execute(
            "SELECT rowid,data FROM recovery_records WHERE table_name='research_review_drafts'"
        ).fetchone()
        assert json.loads(encoded) == before[0]
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='research_review_drafts'"
        ).fetchone()
    review = ResearchReview(restored)
    preview = review.preview("recovery", str(rowid))
    assert preview.data["retained"]["body"] == "My edited draft"
    assert not preview.data["apply"]
    assert review.load_draft(before[0]["origin"], before[0]["origin_id"]) is None


def test_corrupt_record_blocks_backup_without_overwriting_source_or_publishing(workspace, tmp_path):
    path, _ = workspace
    setup(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("UPDATE research_review_drafts SET fingerprint=?", ("f" * 64,))
        conn.commit()
    before = records(path)
    package = tmp_path / "invalid.zip"
    with pytest.raises((ValueError, sync_recovery.RecoveryError)):
        sync_recovery.create(path, package)
    assert records(path) == before
    assert not package.exists()


def test_variant_pages_are_bounded_and_older_draft_remains_openable(workspace):
    path, _ = workspace
    review, identity, preview, first = setup(path)
    identities = [first["draft_id"]]
    for number in range(4):
        identities.append(
            review.save_draft(preview, f"Variant {number}", f"variant-{number}")["draft_id"]
        )
    found, cursor = [], None
    while True:
        page = review.list_drafts("generation", identity, before=cursor, limit=2)
        assert len(page["items"]) <= 2
        found.extend(row["draft_id"] for row in page["items"])
        cursor = page["next"]
        if cursor is None:
            break
    assert found == list(reversed(identities))
    assert (
        review.load_draft("generation", identity, draft_id=first["draft_id"])["body"]
        == "My edited draft"
    )
    with pytest.raises(ValueError):
        review.list_drafts("generation", identity, limit=1000)


def test_simultaneous_save_cas_preserves_one_winner_without_overwrite(workspace):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path, _ = workspace
    review, _identity, preview, saved = setup(path)
    barrier = Barrier(2)

    def save(number):
        barrier.wait()
        try:
            review.save_draft(preview, f"Window {number}", f"concurrent-{number}", **saved)
            return "saved"
        except drafts.DraftConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        result = list(executor.map(save, range(2)))
    assert sorted(result) == ["conflict", "saved"]
    assert records(path)[0]["revision"] == 2
    assert records(path)[0]["body"] in {"Window 0", "Window 1"}


def test_remote_draft_keeps_observed_conflict_after_restart(remote):
    from test_sync_research_roundtrip import save_note

    a, b, service, ta, tb = remote
    review = ResearchReview(b.journal.path)
    identity = review.page()["items"][0]["id"]
    preview = review.preview("remote", identity)
    review.save_draft(preview, "Edited remote answer", "saved-remote")
    save_note(a, "New head after draft")
    a.sync_once(service, ta)
    b.sync_once(service, tb)
    reopened = ResearchReview(b.journal.path)
    result = reopened.load_draft("remote", identity)
    assert result["body"] == "Edited remote answer" and result["state"] == "stale"
    assert result["preview"].data["expected"] == preview.data["expected"]
    with pytest.raises(ValueError, match="refreshed review"):
        reopened.decide(result["preview"], body=result["body"], request_id="saved-remote")
    assert not b.journal.pending()
