"""Actual retained claim proposals gain private drafts, never implicit write grants."""

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_claim_jobs import claims as _claims
from test_claim_jobs import job
from test_claim_jobs import ready as _ready
from test_claim_jobs import workspace as _workspace

from paper_daily import claim_draft_resume as resumed
from paper_daily import enrollment_history, llm, research_review_drafts, sync_capture
from paper_daily import research_generation as generation
from paper_daily.research_review import ResearchReview, encode

claims = _claims
ready = _ready
workspace = _workspace
pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


def rows(path, sql):
    with closing(generation._connect(path)) as conn:
        return [dict(row) for row in conn.execute(sql)]


@pytest.fixture
def scene(claims, monkeypatch):
    assert job(claims).run().status == "accepted"
    claims[1]["claims"][0]["text"] = "Retained proposal awaiting independent appraisal."
    pending = job(claims)
    complete = llm.complete_result

    def during_work(*args, **kwargs):
        response = complete(*args, **kwargs)
        with (
            closing(generation._connect(claims[0][0])) as conn,
            conn,
            sync_capture.suppress_capture(conn),
        ):
            conn.execute(
                "UPDATE dives SET body='Newer analysis while claim extraction was running'"
            )
        return response

    with monkeypatch.context() as patch:
        patch.setattr(llm, "complete_result", during_work)
        assert pending.run().status == "candidate"
    review = ResearchReview(claims[0][0])
    original = review.preview("generation", pending.context.request_id)
    assert original.data["apply"] is False and original.data["editable"] is False
    value = dict(
        claims=claims, path=claims[0][0], client=claims[0][1], review=review, original=original
    )
    yield value
    review.close()


def selected(scene):
    targets = scene["review"].claim_draft_targets(scene["original"])
    assert targets == dict(items=[dict(id="paper", title="Paper")], next=None)
    preview, raw = scene["review"].select_claim_draft(scene["original"], "paper")
    assert preview.data["origin"] == resumed.ORIGIN
    draft = json.loads(raw)
    draft["claims"][0]["text"] = "Human interpretation of the retained original."
    return preview, encode(draft)


def test_two_variants_restart_with_original_base_without_research_or_outbox_writes(scene):
    view, raw = selected(scene)
    before = rows(scene["path"], "SELECT * FROM paper_claim_sets")
    pending = scene["client"].journal.pending(1000)
    request = str(uuid4())
    one = scene["review"].save_claim_draft(view, raw, request, draft_id=str(uuid4()))
    alternate = json.loads(raw)
    alternate["claims"][0]["judgment"]["reason"] = "An independently edited explanation."
    two = scene["review"].save_claim_draft(view, encode(alternate), request, draft_id=str(uuid4()))
    assert one["draft_id"] != two["draft_id"]
    assert len(rows(scene["path"], "SELECT * FROM research_review_drafts")) == 2
    scene["review"].close()
    reopened = ResearchReview(scene["path"])
    try:
        for saved, expected in ((one, raw), (two, encode(alternate))):
            loaded = reopened.load_claim_draft(view.data["id"], draft_id=saved["draft_id"])
            assert loaded["body"] == expected and loaded["request_id"] == request
            assert loaded["state"] == "verification_required"
            assert loaded["preview"].data["expected"] == view.data["expected"]
            assert loaded["preview"].data["apply"] is False
        assert rows(scene["path"], "SELECT * FROM paper_claim_sets") == before
        assert scene["client"].journal.pending(1000) == pending
    finally:
        reopened.close()


def test_repeated_concurrent_save_uses_the_editors_stable_draft_identity(scene):
    view, raw = selected(scene)
    request, draft_id = str(uuid4()), str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as workers:
        receipts = list(
            workers.map(
                lambda _: scene["review"].save_claim_draft(view, raw, request, draft_id=draft_id),
                range(10),
            )
        )
    assert receipts == [dict(draft_id=draft_id, revision=1)] * 10
    assert len(rows(scene["path"], "SELECT * FROM research_review_drafts")) == 1


def test_a_second_window_cannot_overwrite_newer_private_claim_edits(scene):
    first, raw = selected(scene)
    draft_id, request = str(uuid4()), str(uuid4())
    scene["review"].save_claim_draft(first, raw, request, draft_id=draft_id)
    other = ResearchReview(scene["path"])
    try:
        loaded = other.load_claim_draft(first.data["id"])
        newer = json.loads(raw)
        newer["claims"][0]["text"] = "Saved in the first editor."
        scene["review"].save_claim_draft(
            first, encode(newer), request, draft_id=draft_id, revision=1
        )
        losing = json.loads(raw)
        losing["claims"][0]["text"] = "Still visible in the second editor."
        with pytest.raises(research_review_drafts.DraftConflict):
            other.save_claim_draft(
                loaded["preview"], encode(losing), request, draft_id=draft_id, revision=1
            )
        assert other.load_claim_draft(first.data["id"])["body"] == encode(newer)
        assert losing["claims"][0]["text"] == "Still visible in the second editor."
    finally:
        other.close()


def test_newer_research_keeps_the_private_draft_on_its_old_observation(scene):
    view, raw = selected(scene)
    scene["review"].save_claim_draft(view, raw, str(uuid4()), draft_id=str(uuid4()))
    assert job(scene["claims"]).run().status == "accepted"
    loaded = scene["review"].load_claim_draft(view.data["id"])
    assert loaded["state"] == "stale" and loaded["body"] == raw
    assert loaded["preview"].data["expected"] == view.data["expected"]
    assert loaded["preview"].data["apply"] is False


def test_unrelated_note_does_not_rebase_or_invalidate_the_claim_draft(scene):
    view, raw = selected(scene)
    scene["review"].save_claim_draft(view, raw, str(uuid4()), draft_id=str(uuid4()))
    with closing(generation._connect(scene["path"])) as conn, conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) "
            "VALUES('paper','Unrelated note','2026-11-02T00:00:00+00:00')"
        )
    loaded = scene["review"].load_claim_draft(view.data["id"])
    assert loaded["state"] == "verification_required" and loaded["body"] == raw
    assert loaded["preview"].data["expected"] == view.data["expected"]


def test_unknown_or_empty_target_refuses_and_closed_review_cannot_save(scene):
    for target in ("", "missing-paper"):
        with pytest.raises(ValueError):
            scene["review"].select_claim_draft(scene["original"], target)
    view, raw = selected(scene)
    scene["review"].close()
    with pytest.raises(ValueError, match="closed"):
        scene["review"].save_claim_draft(view, raw, str(uuid4()), draft_id=str(uuid4()))
    assert (
        rows(scene["path"], "SELECT name FROM sqlite_master WHERE name='research_review_drafts'")
        == []
    )


@pytest.mark.parametrize("keep", [False, True])
def test_generic_decisions_cannot_publish_or_create_a_decision_for_structured_drafts(scene, keep):
    view, raw = selected(scene)
    before = rows(scene["path"], "SELECT * FROM paper_claim_sets")
    with pytest.raises(ValueError, match="typed claim"):
        scene["review"].decide(view, body=raw, keep=keep, confirm_target=True)
    assert rows(scene["path"], "SELECT * FROM paper_claim_sets") == before
    assert (
        rows(scene["path"], "SELECT name FROM sqlite_master WHERE name='research_review_receipts'")
        == []
    )


def test_private_history_enumerates_sources_without_opening_historical_paths(scene, monkeypatch):
    view, raw = selected(scene)
    scene["review"].save_claim_draft(view, raw, str(uuid4()), draft_id=str(uuid4()))
    row = rows(scene["path"], "SELECT * FROM research_review_drafts")[0]
    monkeypatch.setattr(
        Path, "open", lambda *args, **kwargs: pytest.fail("history must not open paths")
    )
    wrapped = enrollment_history.wrap("research_review_drafts", row)
    value, sources = enrollment_history.validate(wrapped)
    assert value == row and view.data["source_hash"] in sources


@pytest.mark.parametrize(
    "field",
    ["owner", "paper", "current", "observation", "parent", "source", "confirmation", "body"],
)
def test_saved_claim_codec_rejects_inconsistent_authority_even_with_a_new_fingerprint(scene, field):
    view, raw = selected(scene)
    scene["review"].save_claim_draft(view, raw, str(uuid4()), draft_id=str(uuid4()))
    row = rows(scene["path"], "SELECT * FROM research_review_drafts")[0]
    snapshot = json.loads(row["preview_json"])
    if field == "owner":
        snapshot["expected"]["binding"]["device_id"] = "foreign-device"
    elif field == "paper":
        snapshot["expected"]["paper_sync_id"] = str(uuid4())
    elif field == "current":
        snapshot["expected"]["current"]["written_at"] = "2026-11-02T00:00:00+00:00"
    elif field == "observation":
        snapshot["expected"]["observation"]["kind"] = "note"
    elif field == "parent":
        snapshot["parent_row"] = None
    elif field == "source":
        snapshot["source_hash"] = "f" * 64
    elif field == "confirmation":
        snapshot["requires_confirmation"] = False
    else:
        value = json.loads(row["body"])
        value["baseline_digest"] = "f" * 64
        row["body"] = encode(value)
    row["preview_json"] = encode(snapshot)
    row["fingerprint"] = research_review_drafts._fingerprint(row)
    with pytest.raises(ValueError):
        enrollment_history.wrap("research_review_drafts", row)


def test_reselecting_a_target_preserves_explicit_unsaved_structured_edits(scene):
    view, raw = selected(scene)
    next_view, next_raw = scene["review"].select_claim_draft(view, "paper", body=raw)
    assert next_raw == raw
    assert next_view.data["id"] == view.data["id"]
    assert next_view.data["retained"] == view.data["retained"]
    assert next_view.data["apply"] is False


def test_native_database_copy_is_foreign_until_explicit_receiver_selection(scene, tmp_path):
    import sqlite3

    view, raw = selected(scene)
    draft_id = str(uuid4())
    scene["review"].save_claim_draft(view, raw, str(uuid4()), draft_id=draft_id)
    scene["review"].close()
    replacement = tmp_path / "replacement.sqlite"
    with (
        closing(sqlite3.connect(scene["path"])) as old,
        closing(sqlite3.connect(replacement)) as new,
    ):
        old.backup(new)
    replacement.replace(scene["path"])
    receiver = ResearchReview(scene["path"])
    try:
        loaded = receiver.load_claim_draft(view.data["id"])
        assert loaded["state"] == "foreign" and loaded["body"] == raw
        assert loaded["preview"].data["apply"] is False
        with pytest.raises(ValueError):
            receiver.save_claim_draft(
                loaded["preview"], raw, str(uuid4()), draft_id=draft_id, revision=1
            )
        assert receiver.load_claim_draft(view.data["id"])["body"] == raw
    finally:
        receiver.close()


def test_large_bounded_structured_claim_draft_can_be_saved_and_reopened(scene):
    view, raw = selected(scene)
    base = json.loads(raw)
    base["claims"] = [
        dict(
            text=("Claim " + str(index) + " ") + "x" * 980,
            judgment=dict(status="unresolved", reason="r" * 1000),
            passages=[
                dict(quote=("Quote " + str(part) + " ") + "q" * 3640, page=None, anchor=None)
                for part in range(3)
            ],
        )
        for index in range(16)
    ]
    raw = encode(base)
    assert 200 * 1024 < len(raw.encode("utf-8")) <= 220 * 1024
    saved = scene["review"].save_claim_draft(view, raw, str(uuid4()), draft_id=str(uuid4()))
    loaded = scene["review"].load_claim_draft(view.data["id"], draft_id=saved["draft_id"])
    assert loaded["body"] == raw and loaded["state"] == "verification_required"


def test_private_claim_backup_restores_without_old_folder_and_selects_fresh_receiver(
    scene, tmp_path
):
    from paper_daily import sync_recovery
    from paper_daily.recovery_adoption import RecoveryAdoptionService
    from paper_daily.sync_artifacts import paths

    view, raw = selected(scene)
    scene["review"].save_claim_draft(view, raw, str(uuid4()), draft_id=str(uuid4()))
    source_hash = view.data["source_hash"]
    independent = tmp_path.parent / (tmp_path.name + "-independent")
    independent.mkdir()
    with closing(generation._connect(scene["path"])) as conn:
        store, _versions = paths(conn)
    backup = independent / "private-claims.zip"
    sync_recovery.create(
        scene["path"], backup, blob_store=store, pdf_roots=[scene["path"].parent / "pdf"]
    )
    detached = independent / "detached"
    sync_recovery.restore_detached(backup, detached)
    scene["review"].close()
    tmp_path.rename(tmp_path.with_name(tmp_path.name + "-unavailable"))
    assert not scene["path"].exists()
    detached_bytes = (detached / "papers.db").read_bytes()
    detached_schema = rows(detached / "papers.db", "SELECT name FROM sqlite_master ORDER BY name")
    archived_reader = ResearchReview(detached / "papers.db")
    try:
        items = [
            item
            for item in archived_reader.page(limit=100)["items"]
            if item["origin"] == "archived_draft"
        ]
        assert len(items) == 1
        original = archived_reader.preview("archived_draft", items[0]["id"])
        assert original.data["retained"]["body"] == raw
        assert (detached / "papers.db").read_bytes() == detached_bytes
        assert (
            rows(detached / "papers.db", "SELECT name FROM sqlite_master ORDER BY name")
            == detached_schema
        )
        with pytest.raises(ValueError, match="editable"):
            archived_reader.claim_draft_targets(original)
    finally:
        archived_reader.close()
    adoption = RecoveryAdoptionService(detached / "papers.db")
    inspection = adoption.inspect()
    assert inspection.report["supported"], inspection.report
    result = adoption.prepare(
        inspection,
        independent / "receiver",
        backup_output=independent / "receiver.zip",
        request_id=str(uuid4()),
    )
    receiver = ResearchReview(result["database"])
    try:
        items = [
            item for item in receiver.page(limit=100)["items"] if item["origin"] == "archived_draft"
        ]
        assert len(items) == 1
        archived = receiver.preview("archived_draft", items[0]["id"])
        target = receiver.claim_draft_targets(archived)["items"][0]
        fresh, restored = receiver.select_claim_draft(archived, target["id"])
        assert restored == raw and fresh.data["source_hash"] == source_hash
        assert fresh.data["expected"]["database_identity"] == receiver.identity
        assert fresh.data["expected"]["binding"] == receiver.binding
        assert fresh.data["apply"] is False
        saved = receiver.save_claim_draft(fresh, restored, str(uuid4()), draft_id=str(uuid4()))
        assert (
            receiver.load_claim_draft(fresh.data["id"], draft_id=saved["draft_id"])["body"] == raw
        )
    finally:
        receiver.close()


def test_already_admitted_private_save_finishes_after_review_closes(scene, monkeypatch):
    view, raw = selected(scene)
    pending = scene["client"].journal.pending(1000)
    before = rows(scene["path"], "SELECT * FROM paper_claim_sets")
    save = research_review_drafts.DraftStore.save

    def close_after_admission(store, *args, **kwargs):
        store.review.close()
        return save(store, *args, **kwargs)

    monkeypatch.setattr(research_review_drafts.DraftStore, "save", close_after_admission)
    saved = scene["review"].save_claim_draft(view, raw, str(uuid4()), draft_id=str(uuid4()))
    assert saved["revision"] == 1 and scene["review"].closed
    assert rows(scene["path"], "SELECT body FROM research_review_drafts") == [dict(body=raw)]
    assert rows(scene["path"], "SELECT * FROM paper_claim_sets") == before
    assert scene["client"].journal.pending(1000) == pending
