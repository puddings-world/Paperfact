"""Retained highlight analyses gain durable private variants, never implicit Apply."""

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_annotation_review import candidate, state
from test_highlight_generation import ready as ready
from test_highlight_generation import workspace as workspace
from test_research_generation import rows

from paper_daily import (
    annotation_content,
    enrollment_history,
    research_review_drafts,
    sync_capture,
)
from paper_daily import research_generation as generation
from paper_daily.research_review import ResearchReview, encode

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


@pytest.fixture
def scene(ready, monkeypatch):
    job, review = candidate(ready, monkeypatch)
    preview = review.preview("generation", job.context.request_id)
    value = dict(path=ready[0], client=ready[1], document=ready[2], review=review, original=preview)
    yield value
    review.close()


def selected(scene):
    review = scene["review"]
    assert review.highlight_draft_targets(scene["original"]) == dict(
        items=[dict(id="paper", title="Paper")], next=None
    )
    view, raw = review.select_highlight_draft(scene["original"], "paper")
    value = json.loads(raw)
    value["items"][0]["reason"] = "A private human explanation, not a model verdict."
    return view, encode(value)


def test_two_private_highlight_variants_survive_restart_without_formal_writes(scene):
    view, raw = selected(scene)
    before, pending = state(scene["path"]), scene["client"].journal.pending(1000)
    request = str(uuid4())
    one = scene["review"].save_highlight_draft(view, raw, request, draft_id=str(uuid4()))
    alternate = json.loads(raw)
    alternate["items"][0]["kind"] = "limitation"
    two = scene["review"].save_highlight_draft(
        view, encode(alternate), request, draft_id=str(uuid4())
    )
    assert one["draft_id"] != two["draft_id"]
    scene["review"].close()
    reopened = ResearchReview(scene["path"])
    try:
        for saved, body in ((one, raw), (two, encode(alternate))):
            loaded = reopened.load_highlight_draft(view.data["id"], draft_id=saved["draft_id"])
            assert loaded["body"] == body and loaded["request_id"] == request
            assert loaded["state"] == "verification_required"
            assert loaded["preview"].data["expected"] == view.data["expected"]
            assert not loaded["preview"].data["apply"]
        assert state(scene["path"]) == before
        assert scene["client"].journal.pending(1000) == pending
    finally:
        reopened.close()


def test_concurrent_identical_private_saves_create_one_variant(scene):
    view, raw = selected(scene)
    draft_id, request = str(uuid4()), str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: scene["review"].save_highlight_draft(
                    view, raw, request, draft_id=draft_id
                ),
                range(10),
            )
        )
    assert results == [dict(draft_id=draft_id, revision=1)] * 10
    assert len(rows(scene["path"], "SELECT * FROM research_review_drafts")) == 1


def test_second_window_cannot_overwrite_newer_private_highlight_text(scene):
    view, raw = selected(scene)
    draft_id, request = str(uuid4()), str(uuid4())
    scene["review"].save_highlight_draft(view, raw, request, draft_id=draft_id)
    other = ResearchReview(scene["path"])
    try:
        loaded = other.load_highlight_draft(view.data["id"])
        newer = json.loads(raw)
        newer["items"][0]["reason"] = "A newer saved explanation."
        scene["review"].save_highlight_draft(
            view, encode(newer), request, draft_id=draft_id, revision=1
        )
        with pytest.raises(research_review_drafts.DraftConflict):
            other.save_highlight_draft(
                loaded["preview"], raw, request, draft_id=draft_id, revision=1
            )
        assert other.load_highlight_draft(view.data["id"])["body"] == encode(newer)
        assert loaded["body"] == raw
    finally:
        other.close()


@pytest.mark.parametrize("change", ["hidden", "deleted", "manual", "analysis"])
def test_saved_draft_retains_old_group_when_any_curated_layer_changes(scene, change):
    view, raw = selected(scene)
    scene["review"].save_highlight_draft(view, raw, str(uuid4()), draft_id=str(uuid4()))
    with (
        closing(generation._connect(scene["path"])) as conn,
        conn,
        sync_capture.suppress_capture(conn),
    ):
        if change == "hidden":
            conn.execute("UPDATE pdf_ai_highlights SET hidden=0")
        elif change == "deleted":
            conn.execute("DELETE FROM pdf_ai_highlights")
        elif change == "analysis":
            conn.execute(
                "UPDATE paper_highlight_analysis SET written_at='2026-11-02T12:00:00+00:00'"
            )
        else:
            mark = conn.execute("SELECT * FROM pdf_ai_highlights LIMIT 1").fetchone()
            conn.execute(
                "INSERT INTO pdf_highlights(paper_id,document_hash,anchor,quote,created_at) "
                "VALUES(?,?,?,?,?)",
                (
                    mark["paper_id"],
                    mark["document_hash"],
                    mark["anchor"],
                    mark["quote"],
                    "2026-11-02T12:00:00+00:00",
                ),
            )
    before = state(scene["path"])
    loaded = scene["review"].load_highlight_draft(view.data["id"])
    assert loaded["state"] == "stale" and loaded["body"] == raw
    assert loaded["preview"].data["expected"] == view.data["expected"]
    assert not loaded["preview"].data["apply"] and state(scene["path"]) == before


def test_unrelated_note_does_not_rebase_highlight_observations(scene):
    view, raw = selected(scene)
    scene["review"].save_highlight_draft(view, raw, str(uuid4()), draft_id=str(uuid4()))
    with closing(generation._connect(scene["path"])) as conn, conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) "
            "VALUES('paper','Unrelated note','2026-11-02T12:00:00+00:00')"
        )
    loaded = scene["review"].load_highlight_draft(view.data["id"])
    assert loaded["state"] == "verification_required" and loaded["body"] == raw
    assert loaded["preview"].data["expected"] == view.data["expected"]


@pytest.mark.parametrize("keep", [False, True])
def test_generic_decisions_cannot_publish_private_highlight_groups(scene, keep):
    view, raw = selected(scene)
    before, pending = state(scene["path"]), scene["client"].journal.pending(1000)
    with pytest.raises(ValueError, match="typed highlight"):
        scene["review"].decide(view, body=raw, keep=keep, confirm_target=True)
    assert state(scene["path"]) == before and scene["client"].journal.pending(1000) == pending
    assert not rows(
        scene["path"], "SELECT name FROM sqlite_master WHERE name='research_review_receipts'"
    )


def test_closed_or_missing_target_never_creates_a_private_record(scene):
    for target in ("", "missing"):
        with pytest.raises(ValueError):
            scene["review"].select_highlight_draft(scene["original"], target)
    view, raw = selected(scene)
    scene["review"].close()
    with pytest.raises(ValueError, match="closed"):
        scene["review"].save_highlight_draft(view, raw, str(uuid4()), draft_id=str(uuid4()))
    assert not rows(
        scene["path"], "SELECT name FROM sqlite_master WHERE name='research_review_drafts'"
    )


def test_typed_private_body_over_200k_is_kept_without_truncating_the_220k_budget(scene):
    view, raw = selected(scene)
    value = json.loads(raw)
    value["items"] = [
        dict(
            text=str(index) + " " + "q" * 3790,
            page=1,
            anchor=None,
            kind="method",
            reason="理" * 1000,
        )
        for index in range(32)
    ]
    large = encode(value)
    assert research_review_drafts.MAX_BODY < len(large.encode()) <= annotation_content.MAX_BYTES
    receipt = scene["review"].save_highlight_draft(view, large, str(uuid4()), draft_id=str(uuid4()))
    assert (
        scene["review"].load_highlight_draft(view.data["id"], draft_id=receipt["draft_id"])["body"]
        == large
    )
    value["items"][0]["reason"] = "理" * 1601
    with pytest.raises(ValueError):
        scene["review"].save_highlight_draft(
            view, encode(value), str(uuid4()), draft_id=str(uuid4())
        )
    assert len(rows(scene["path"], "SELECT * FROM research_review_drafts")) == 1


def test_private_history_codec_reads_no_historical_paths_and_keeps_all_declared_sources(
    scene, monkeypatch
):
    view, raw = selected(scene)
    scene["review"].save_highlight_draft(view, raw, str(uuid4()), draft_id=str(uuid4()))
    row = rows(scene["path"], "SELECT * FROM research_review_drafts")[0]
    monkeypatch.setattr(
        Path, "open", lambda *a, **k: pytest.fail("Historical metadata must not open paths")
    )
    wrapped = enrollment_history.wrap("research_review_drafts", row)
    value, sources = enrollment_history.validate(wrapped)
    assert value == row and view.data["source_hash"] in sources
    assert {
        mark["document_hash"] for mark in view.data["expected"]["highlights"]["marks"]
    } <= sources


@pytest.mark.parametrize(
    "field",
    [
        "unknown",
        "owner",
        "paper",
        "current",
        "tokens",
        "manual",
        "parent",
        "source",
        "confirmation",
        "body",
        "empty_manual",
        "conflict",
        "apply",
        "hidden",
    ],
)
def test_private_codec_rejects_inconsistent_group_metadata_even_with_a_new_fingerprint(
    scene, field
):
    view, raw = selected(scene)
    scene["review"].save_highlight_draft(view, raw, str(uuid4()), draft_id=str(uuid4()))
    row = rows(scene["path"], "SELECT * FROM research_review_drafts")[0]
    snapshot = json.loads(row["preview_json"])
    expected = snapshot["expected"]
    if field == "unknown":
        expected["can_apply"] = True
    elif field == "owner":
        expected["binding"]["device_id"] = "foreign"
    elif field == "paper":
        expected["paper_sync_id"] = str(uuid4())
    elif field == "current":
        expected["current"]["written_at"] = "2026-11-02T12:00:00+00:00"
    elif field == "tokens":
        expected["highlights"]["tokens"] = {}
    elif field == "manual":
        expected["manual"]["count"] = True
    elif field == "parent":
        snapshot["parent_row"] = None
    elif field == "source":
        snapshot["source_hash"] = "f" * 64
    elif field == "confirmation":
        snapshot["requires_confirmation"] = False
    elif field == "body":
        body = json.loads(row["body"])
        body["baseline_digest"] = "f" * 64
        row["body"] = encode(body)
    elif field == "empty_manual":
        expected["manual"]["digest"] = "f" * 64
    elif field == "conflict":
        expected["conflict"] = {}
    elif field == "apply":
        snapshot["apply"] = True
    else:
        expected["highlights"]["marks"][0]["hidden"] = 2
    row["preview_json"] = encode(snapshot)
    row["fingerprint"] = research_review_drafts._fingerprint(row)
    with pytest.raises((ValueError, TypeError)):
        enrollment_history.wrap("research_review_drafts", row)


def test_explicit_reselection_preserves_unsaved_human_fields(scene):
    view, raw = selected(scene)
    next_view, next_raw = scene["review"].select_highlight_draft(view, "paper", body=raw)
    assert next_raw == raw
    assert next_view.data["expected"]["highlights"] == view.data["expected"]["highlights"]


def test_native_database_replacement_refuses_save_without_touching_the_replacement(scene):
    view, raw = selected(scene)
    path = scene["path"]
    replacement = path.with_name("replacement.sqlite")
    with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(replacement)) as target:
        source.backup(target)
    for suffix in ("-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)
    replacement.replace(path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="replaced"):
        scene["review"].save_highlight_draft(view, raw, str(uuid4()), draft_id=str(uuid4()))
    assert path.read_bytes() == before and json.loads(raw)["items"][0]["reason"].startswith(
        "A private human"
    )


def test_invalid_private_body_preserves_the_previously_saved_variant(scene):
    view, raw = selected(scene)
    request, draft_id = str(uuid4()), str(uuid4())
    scene["review"].save_highlight_draft(view, raw, request, draft_id=draft_id)
    invalid = copy.deepcopy(json.loads(raw))
    invalid["items"] = []
    with pytest.raises(ValueError):
        scene["review"].save_highlight_draft(
            view, encode(invalid), request, draft_id=draft_id, revision=1
        )
    assert scene["review"].load_highlight_draft(view.data["id"])["body"] == raw


@pytest.mark.parametrize(
    "column,prefix", [("owner_json", '{"binding":null,'), ("preview_json", '{"apply":true,')]
)
def test_live_private_codec_rejects_duplicate_metadata_keys(scene, column, prefix):
    view, raw = selected(scene)
    scene["review"].save_highlight_draft(view, raw, str(uuid4()), draft_id=str(uuid4()))
    row = rows(scene["path"], "SELECT * FROM research_review_drafts")[0]
    row[column] = prefix + row[column][1:]
    row["fingerprint"] = research_review_drafts._fingerprint(row)
    with pytest.raises(ValueError, match="Duplicate"):
        research_review_drafts.validate_record(row)


def test_failed_private_save_rolls_back_and_same_identity_can_retry(scene, monkeypatch):
    view, raw = selected(scene)
    request, draft_id = str(uuid4()), str(uuid4())
    before, pending = state(scene["path"]), scene["client"].journal.pending(1000)
    original = research_review_drafts.DraftStore.save_in

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic failure after private write")

    with monkeypatch.context() as patch:
        patch.setattr(research_review_drafts.DraftStore, "save_in", fail_after_write)
        with pytest.raises(RuntimeError):
            scene["review"].save_highlight_draft(view, raw, request, draft_id=draft_id)
    assert not rows(
        scene["path"], "SELECT name FROM sqlite_master WHERE name='research_review_drafts'"
    )
    saved = scene["review"].save_highlight_draft(view, raw, request, draft_id=draft_id)
    assert saved == dict(draft_id=draft_id, revision=1)
    assert scene["review"].load_highlight_draft(view.data["id"])["body"] == raw
    assert state(scene["path"]) == before and scene["client"].journal.pending(1000) == pending


def test_private_highlight_save_requires_the_editors_stable_variant_identity(scene):
    view, raw = selected(scene)
    with pytest.raises(ValueError, match="stable highlight"):
        research_review_drafts.DraftStore(scene["review"]).save(view, raw, str(uuid4()))
    assert not rows(
        scene["path"], "SELECT name FROM sqlite_master WHERE name='research_review_drafts'"
    )


@pytest.mark.parametrize("table", ["pdf_ai_highlights", "pdf_highlights"])
def test_oversized_current_marks_refuse_before_full_rows_are_loaded(scene, monkeypatch, table):
    from paper_daily import highlight_publication

    with (
        closing(generation._connect(scene["path"])) as conn,
        conn,
        sync_capture.suppress_capture(conn),
    ):
        if table == "pdf_ai_highlights":
            conn.execute("UPDATE pdf_ai_highlights SET quote=?", ("x" * (5 * 1024 * 1024),))
        else:
            mark = conn.execute("SELECT * FROM pdf_ai_highlights LIMIT 1").fetchone()
            conn.execute(
                "INSERT INTO pdf_highlights(paper_id,document_hash,anchor,quote,created_at) "
                "VALUES(?,?,?,?,?)",
                (
                    mark["paper_id"],
                    mark["document_hash"],
                    mark["anchor"],
                    "x" * (5 * 1024 * 1024),
                    "2026-11-02T12:00:00+00:00",
                ),
            )
    if table == "pdf_ai_highlights":
        monkeypatch.setattr(
            highlight_publication,
            "inputs",
            lambda *a: pytest.fail("Oversized mark rows were loaded"),
        )
    else:
        original = sync_capture.CaptureConnection.execute

        def bounded(conn, statement, *args, **kwargs):
            assert not statement.startswith("SELECT * FROM pdf_highlights")
            return original(conn, statement, *args, **kwargs)

        monkeypatch.setattr(sync_capture.CaptureConnection, "execute", bounded)
    with pytest.raises(ValueError, match="bound"):
        scene["review"].select_highlight_draft(scene["original"], "paper")
    assert not rows(
        scene["path"], "SELECT name FROM sqlite_master WHERE name='research_review_drafts'"
    )


def test_owned_sidecar_analysis_can_continue_privately_without_another_model_call(scene):
    record = rows(
        scene["path"], "SELECT * FROM research_generation_requests WHERE status='candidate'"
    )[0]
    context = generation.GenerationContext(record["context_json"])
    path = generation._recovery_path(context)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encode(record), encoding="utf-8")
    before, pending = state(scene["path"]), scene["client"].journal.pending(1000)
    item = next(
        item for item in scene["review"].page(limit=100)["items"] if item["origin"] == "sidecar"
    )
    original = scene["review"].preview("sidecar", item["id"])
    view, raw = scene["review"].select_highlight_draft(original, "paper")
    draft = json.loads(raw)
    draft["items"][0]["reason"] = "A private review of the retained sidecar result."
    body = encode(draft)
    saved = scene["review"].save_highlight_draft(view, body, str(uuid4()), draft_id=str(uuid4()))
    scene["review"].close()
    receiver = ResearchReview(scene["path"])
    try:
        loaded = receiver.load_highlight_draft(view.data["id"], draft_id=saved["draft_id"])
        assert loaded["body"] == body and loaded["state"] == "verification_required"
        assert not loaded["preview"].data["apply"]
        assert state(scene["path"]) == before and scene["client"].journal.pending(1000) == pending
        assert path.read_text("utf-8") == encode(record)
    finally:
        receiver.close()
