"""Retained analysis and exact PDF marks are reviewed and applied as one unit."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_highlight_generation import capture, change_mark, marks
from test_highlight_generation import ready as _ready
from test_highlight_generation import workspace as _workspace
from test_research_generation import rows
from test_research_review import remote_graph as _remote_graph

from paper_daily import llm, manual_highlight_ops, sync_capture, sync_recovery
from paper_daily import research_generation as generation
from paper_daily.research_review import ResearchReview

workspace = _workspace
ready = _ready
remote_graph = _remote_graph


def candidate(ready, monkeypatch):
    assert capture(ready).run().status == "accepted"
    ready[6][:] = [0, 1]
    complete = llm.complete_result

    def during_model(*args, **kwargs):
        result = complete(*args, **kwargs)
        change_mark(ready[0])
        return result

    monkeypatch.setattr(llm, "complete_result", during_model)
    job = capture(ready)
    result = job.run()
    assert result.status == "candidate"
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **kw: pytest.fail("Review must not invoke AI")
    )
    return job, ResearchReview(ready[0])


def state(path):
    return (
        rows(path, "SELECT * FROM paper_highlight_analysis"),
        marks(path),
        rows(path, "SELECT * FROM pdf_highlights"),
    )


def receipt_count(path):
    with closing(sqlite3.connect(path)) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_review_receipts'"
        ).fetchone():
            return 0
        return conn.execute("SELECT count(*) FROM research_review_receipts").fetchone()[0]


def test_grouped_review_applies_analysis_marks_and_receipt_once_preserving_user_marks(
    ready,
    monkeypatch,
):
    job, review = candidate(ready, monkeypatch)
    path = ready[0]
    mark = marks(path)[0]
    owner = manual_highlight_ops.capture_owner(path, "paper")
    view = manual_highlight_ops.load(owner, ready[2].path, ready[2].sha256, document=ready[2])
    manual_highlight_ops.add(view, json.loads(mark["anchor"]), mark["quote"])
    manual_before = rows(path, "SELECT * FROM pdf_highlights")
    original = rows(path, "SELECT * FROM research_generation_requests ORDER BY request_id")
    shown = review.preview("generation", job.context.request_id)
    assert shown.data["apply"] and not shown.data["editable"]
    assert set(shown.data["retained"]) == {"analysis", "marks", "unmatched"}
    assert len(shown.data["retained"]["marks"]) == 2
    before_calls = len(ready[5])
    result = review.decide(shown, request_id="grouped-review")
    assert result["decision"] == "applied"
    after = state(path)
    pending = ready[1].journal.pending() if ready[1] else []
    assert len(after[1]) == 2 and sum(mark["hidden"] for mark in after[1]) == 1
    assert after[2] == manual_before
    assert json.loads(after[0][0]["body_json"]) == json.loads(job.result["body_json"])
    assert receipt_count(path) == 1
    assert rows(path, "SELECT * FROM research_generation_requests ORDER BY request_id") == original
    for _ in range(5):
        assert review.decide(shown, request_id="grouped-review") == result
    assert state(path) == after and receipt_count(path) == 1 and len(ready[5]) == before_calls
    if ready[1]:
        assert ready[1].journal.pending() == pending


def test_generic_text_rewrite_and_changed_retry_never_apply_partial_group(ready, monkeypatch):
    job, review = candidate(ready, monkeypatch)
    shown = review.preview("generation", job.context.request_id)
    before = state(ready[0])
    with pytest.raises(ValueError, match="typed grouped"):
        review.decide(shown, body="edited analysis only", request_id="no-partial")
    assert state(ready[0]) == before and receipt_count(ready[0]) == 0
    review.decide(shown, request_id="one-decision")
    with pytest.raises(ValueError, match="retry changed"):
        review.decide(shown, keep=True, request_id="one-decision")


def test_stale_hidden_choice_rejects_exact_displayed_group_without_losing_candidate(
    ready,
    monkeypatch,
):
    job, review = candidate(ready, monkeypatch)
    shown = review.preview("generation", job.context.request_id)
    mark = marks(ready[0])[0]
    with closing(generation._connect(ready[0])) as conn:
        token = sync_capture.observe_target(
            conn, "paper", "paper", "ai_highlight", mark["document_hash"] + ":" + mark["source_key"]
        )
        with sync_capture.expecting(conn, [token]):
            conn.execute("UPDATE pdf_ai_highlights SET hidden=0 WHERE id=?", (mark["id"],))
            conn.commit()
    before = state(ready[0])
    with pytest.raises(ValueError, match="Displayed highlight group"):
        review.decide(shown, request_id="stale")
    assert state(ready[0]) == before and receipt_count(ready[0]) == 0
    assert rows(
        ready[0], "SELECT status FROM research_generation_requests WHERE status='candidate'"
    )


def test_missing_or_replaced_original_pdf_never_enables_group_application(ready, monkeypatch):
    job, review = candidate(ready, monkeypatch)
    shown = review.preview("generation", job.context.request_id)
    before = state(ready[0])
    ready[2].path.write_bytes(b"changed source bytes")
    with pytest.raises(ValueError, match="original verified PDF"):
        review.decide(shown, request_id="changed-pdf")
    assert state(ready[0]) == before
    unavailable = review.preview("generation", job.context.request_id)
    assert not unavailable.data["apply"]
    explicit = review.target_preview(unavailable, "paper")
    assert not explicit.data["apply"] and not explicit.data["editable"]


def test_write_failure_rolls_back_entire_group_then_same_displayed_retry_succeeds(
    ready,
    monkeypatch,
):
    job, review = candidate(ready, monkeypatch)
    shown = review.preview("generation", job.context.request_id)
    before = state(ready[0])
    pending = ready[1].journal.pending() if ready[1] else []
    with closing(sqlite3.connect(ready[0])) as conn, conn:
        conn.execute(
            "CREATE TRIGGER fail_group BEFORE INSERT ON pdf_ai_highlights "
            "BEGIN SELECT RAISE(ABORT,'fixture failure'); END"
        )
    with pytest.raises(sqlite3.DatabaseError):
        review.decide(shown, request_id="retry-after-failure")
    assert state(ready[0]) == before and receipt_count(ready[0]) == 0
    if ready[1]:
        assert ready[1].journal.pending() == pending
    with closing(sqlite3.connect(ready[0])) as conn, conn:
        conn.execute("DROP TRIGGER fail_group")
    assert review.decide(shown, request_id="retry-after-failure")["decision"] == "applied"
    assert len(marks(ready[0])) == 2 and receipt_count(ready[0]) == 1


def test_deleted_mark_requires_explicit_complete_group_restoration(ready, monkeypatch):
    job, review = candidate(ready, monkeypatch)
    change_mark(ready[0], delete=True)
    shown = review.preview("generation", job.context.request_id)
    assert not shown.data["apply"] and not shown.data["editable"]
    explicit = review.target_preview(shown, "paper")
    assert explicit.data["apply"] and explicit.data["requires_confirmation"]
    with pytest.raises(ValueError, match="Confirm"):
        review.decide(explicit, request_id="restore")
    assert (
        review.decide(explicit, request_id="restore", confirm_target=True)["decision"] == "applied"
    )
    assert len(marks(ready[0])) == 2
    if ready[1]:
        operations = ready[1].journal.pending()
        restored = [
            op
            for op in operations
            if op.get("payload", {}).get("feature") == "ai_highlight"
            and op["payload"]["key"] in shown.data["expected"]["context"]["inputs"]["tokens"]
        ]
        assert restored
        last = restored[-1]
        history = [op for op in operations if op["entity_id"] == last["entity_id"]]
        assert history[-1]["action"] == "put"
        assert history[-1]["incarnation"] != history[0]["incarnation"]


def test_grouped_review_receipt_and_complete_source_survive_detached_backup(
    ready,
    monkeypatch,
    tmp_path,
):
    job, review = candidate(ready, monkeypatch)
    shown = review.preview("generation", job.context.request_id)
    review.decide(shown, request_id="review-before-backup")
    package = tmp_path / "grouped-review.zip"
    sync_recovery.create(ready[0], package)
    destination = tmp_path / "detached"
    sync_recovery.restore_detached(package, destination)
    restored = destination / "papers.db"
    assert state(restored) == state(ready[0])
    assert (
        rows(
            restored,
            "SELECT count(*) AS n FROM recovery_records WHERE "
            "table_name='research_review_receipts'",
        )[0]["n"]
        == 1
    )


def test_write_abort_sidecar_is_reviewed_as_complete_group_without_another_model(
    ready, monkeypatch
):
    path = ready[0]
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "CREATE TRIGGER broken_marks BEFORE INSERT ON pdf_ai_highlights "
            "BEGIN SELECT RAISE(ABORT,'fixture failure'); END"
        )
    job = capture(ready)
    assert job.run().status == "candidate"
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("DROP TRIGGER broken_marks")
    monkeypatch.setattr(llm, "complete_result", lambda *a, **kw: pytest.fail("No AI review"))
    review = ResearchReview(path)
    item = next(item for item in review.page()["items"] if item["origin"] == "sidecar")
    shown = review.preview("sidecar", item["id"])
    assert shown.data["apply"] and not shown.data["editable"]
    review.decide(shown, request_id="sidecar-group")
    assert len(marks(path)) == 1 and len(rows(path, "SELECT * FROM paper_highlight_analysis")) == 1
    assert len(ready[5]) == 1 and receipt_count(path) == 1
    assert generation.list_recovery_requests(path)


def test_pdf_change_during_receipt_rolls_back_group_outbox_and_receipt(ready, monkeypatch):
    job, review = candidate(ready, monkeypatch)
    shown = review.preview("generation", job.context.request_id)
    before = state(ready[0])
    pending = ready[1].journal.pending() if ready[1] else []
    original = review._receipt

    def change_source(*args):
        original(*args)
        ready[2].path.write_bytes(b"replacement during publication")

    monkeypatch.setattr(review, "_receipt", change_source)
    with pytest.raises(ValueError, match="PDF changed during"):
        review.decide(shown, request_id="source-race")
    assert state(ready[0]) == before and receipt_count(ready[0]) == 0
    if ready[1]:
        assert ready[1].journal.pending() == pending


def test_parent_edit_after_preview_requires_fresh_review_and_export_omits_private_paths(
    ready, monkeypatch
):
    job, review = candidate(ready, monkeypatch)
    shown = review.preview("generation", job.context.request_id)
    text = review.export_text(shown)
    assert str(ready[0]) not in text and str(ready[2].path) not in text
    assert "database_identity" not in text and "highlight_plan" not in text
    with closing(generation._connect(ready[0])) as conn:
        conn.execute("UPDATE papers SET title='Changed paper metadata' WHERE id='paper'")
        conn.commit()
    before = state(ready[0])
    with pytest.raises(ValueError, match="Displayed highlight group changed"):
        review.decide(shown, request_id="parent-race")
    assert state(ready[0]) == before
    assert review.preview("generation", job.context.request_id).data["apply"]


@pytest.mark.parametrize("feature", ["highlight_analysis", "ai_highlight"])
def test_remote_single_row_highlight_conflicts_cannot_bypass_group_review(
    remote_graph, monkeypatch, feature
):
    from paper_daily.sync_client import SyncClient

    _a, receiver, *_ = remote_graph
    original = SyncClient.conflict_observation_in

    def observation(self, *args, **kwargs):
        state = original(self, *args, **kwargs)
        # The service boundary supplies a valid unresolved research-content
        # observation; highlight singletons must stay blocked regardless of body.
        state["event"]["operation"]["payload"]["feature"] = feature
        return state

    monkeypatch.setattr(SyncClient, "conflict_observation_in", observation)
    review = ResearchReview(receiver.journal.path)
    item = review.page()["items"][0]
    shown = review.preview("remote", item["id"])
    assert not shown.data["apply"] and not shown.data["editable"]
    assert "complete grouped source review" in shown.data["reason"]
    before = receiver.journal.pending()
    with pytest.raises(ValueError, match="complete grouped source review"):
        review.decide(shown, request_id="no-singleton")
    assert receiver.journal.pending() == before
    assert review.decide(shown, keep=True, request_id="retain") == {
        "decision": "kept",
        "operation_id": None,
    }


def test_explicit_other_paper_requires_confirmation_and_identical_source_pdf(ready, monkeypatch):
    from paper_daily import store

    job, review = candidate(ready, monkeypatch)
    shown = review.preview("generation", job.context.request_id)
    with closing(generation._connect(ready[0])) as conn:
        store.upsert_papers(
            conn,
            [
                {
                    "id": "other",
                    "title": "Other paper",
                    "year": 2026,
                    "venue": "Fixture",
                    "source": "fixture",
                }
            ],
        )
        conn.commit()
    other_pdf = ready[2].path.parent / "other.pdf"
    other_pdf.write_bytes(b"different document")
    assert not review.target_preview(shown, "other").data["apply"]
    other_pdf.write_bytes(ready[2].path.read_bytes())
    target = review.target_preview(shown, "other")
    assert target.data["apply"] and target.data["requires_confirmation"]
    before = state(ready[0])
    with pytest.raises(ValueError, match="Confirm"):
        review.decide(target, request_id="other-target")
    assert state(ready[0]) == before
    review.decide(target, request_id="other-target", confirm_target=True)
    saved = rows(ready[0], "SELECT * FROM paper_highlight_analysis WHERE paper_id='other'")
    placed = rows(ready[0], "SELECT * FROM pdf_ai_highlights WHERE paper_id='other'")
    assert len(saved) == 1 and len(placed) == 2
    assert all(mark["document_hash"] == ready[2].sha256 for mark in placed)
    assert len(rows(ready[0], "SELECT * FROM pdf_ai_highlights WHERE paper_id='paper'")) == 1
