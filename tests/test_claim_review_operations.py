"""Public typed claim operations preserve private work and one atomic decision."""

import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from test_claim_draft_application import claims as claims
from test_claim_draft_application import ready as ready
from test_claim_draft_application import receiver as receiver
from test_claim_draft_application import scene as scene
from test_claim_draft_application import source_pair as source_pair
from test_claim_draft_application import workspace as workspace
from test_claim_draft_storage import rows
from test_claim_jobs import job

from paper_daily import local_operations as ops
from paper_daily import store
from paper_daily.document_reader import DocumentReader

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


def invoke(action, **arguments):
    response = ops.dispatch("review.claims." + action, arguments)
    assert response["ok"], response
    return response["result"]


def start(value):
    return invoke(
        "open",
        origin_id="generation:" + value["original"].data["id"],
        target_id="paper",
        operation_id="claim-open",
        draft=json.loads(value["body"]),
    )


def test_public_claim_list_inspect_save_source_words_confirm_and_retry(source_pair):
    value = source_pair
    origin = "generation:" + value["original"].data["id"]
    listing = invoke("list", limit=1)
    assert listing["items"] == [dict(origin_id=origin, summary=listing["items"][0]["summary"])]
    inspected = invoke("inspect", origin_id=origin)
    assert inspected["draft"]["source"]["document_hash"] == value["source_hash"]
    assert inspected["can_apply"] is False
    assert invoke("targets", origin_id=origin)["items"] == [dict(id="paper", title="Paper")]
    opened = start(value)
    assert start(value) == opened
    current = invoke("read", draft_id=opened["draft_id"])
    assert current["draft"] == json.loads(value["body"]) and not current["can_apply"]
    current["draft"]["claims"][0]["text"] = "External agent's explicit manual claim revision."
    saved = invoke(
        "save",
        draft_id=opened["draft_id"],
        revision=1,
        draft=current["draft"],
        operation_id="claim-save",
    )
    assert saved["revision"] == 2
    before = rows(value["path"], "SELECT * FROM paper_claim_sets")
    checked = invoke("verify", draft_id=opened["draft_id"], revision=2)
    assert checked["report"]["claims"][0]["passages"][0]["location"]["state"] == "located"
    assert checked["generation"]["backend"] == "manual" and not checked["can_apply"]
    page = invoke("page", draft_id=opened["draft_id"], revision=2, page_index=0, limit=5)
    assert page["source_document_hash"] == value["source_hash"] and len(page["words"]) == 5
    assert page["next_offset"] == 5 and page["words"][0]["text"] == "The"
    failed = ops.dispatch(
        "review.claims.apply",
        dict(draft_id=opened["draft_id"], revision=2, operation_id="claim-apply"),
    )
    assert failed["error"]["code"] == "confirmation_required"
    assert rows(value["path"], "SELECT * FROM paper_claim_sets") == before
    request = dict(
        draft_id=opened["draft_id"], revision=2, operation_id="claim-apply", confirm=True
    )
    result = invoke("apply", **request)
    assert result["status"] == "applied" and result["revision"] == 3
    assert invoke("apply", **request) == result
    body = json.loads(rows(value["path"], "SELECT body_json FROM paper_claim_sets")[0]["body_json"])
    assert body["report"]["claims"][0]["text"] == current["draft"]["claims"][0]["text"]
    assert (
        DocumentReader.from_workspace(value["path"]).resolve("paper").sha256
        == value["current"].sha256
    )
    assert rows(value["path"], "SELECT count(*) AS n FROM research_review_receipts") == [dict(n=1)]
    assert rows(value["path"], "SELECT count(*) AS n FROM integration_operations") == [dict(n=3)]
    text = json.dumps([listing, inspected, current, checked, page, result])
    assert str(value["path"]) not in text and "owner_json" not in text and "db_path" not in text
    assert job(value["claims"]).run().status == "accepted"
    newer = rows(value["path"], "SELECT * FROM paper_claim_sets")
    assert invoke("apply", **request) == result
    assert rows(value["path"], "SELECT * FROM paper_claim_sets") == newer


def test_concurrent_open_and_apply_reuse_one_private_and_formal_result(source_pair):
    value = source_pair
    with ThreadPoolExecutor(max_workers=2) as pool:
        opened = list(pool.map(lambda _: start(value), range(8)))
    assert opened == [opened[0]] * 8
    request = dict(
        draft_id=opened[0]["draft_id"],
        revision=1,
        operation_id="concurrent-claim-apply",
        confirm=True,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: ops.dispatch("review.claims.apply", request), range(4)))
    assert all(result["ok"] for result in results), results
    assert results == [results[0]] * 4
    assert rows(value["path"], "SELECT revision FROM research_review_drafts") == [dict(revision=2)]
    assert rows(value["path"], "SELECT count(*) AS n FROM research_review_receipts") == [dict(n=1)]


@pytest.mark.parametrize("action", ["open", "save", "apply"])
def test_public_receipt_failure_rolls_back_private_and_canonical_state(
    source_pair, monkeypatch, action
):
    from paper_daily import claim_review_operations

    value = source_pair
    opened = None if action == "open" else start(value)
    tables = ("paper_claim_sets", "paperfact_sync_operations")
    before = {table: rows(value["path"], "SELECT * FROM " + table) for table in tables}
    private = rows(value["path"], "SELECT * FROM research_review_drafts") if opened else None
    if action == "open":
        arguments = dict(
            origin_id="generation:" + value["original"].data["id"],
            target_id="paper",
            operation_id="fail-open",
        )
    elif action == "save":
        arguments = dict(
            draft_id=opened["draft_id"],
            revision=1,
            draft=json.loads(value["body"]),
            operation_id="fail-save",
        )
    else:
        arguments = dict(
            draft_id=opened["draft_id"], revision=1, operation_id="fail-apply", confirm=True
        )
    with monkeypatch.context() as patch:
        patch.setattr(
            claim_review_operations,
            "_receipt",
            lambda *a: (_ for _ in ()).throw(OSError("receipt full")),
        )
        result = ops.dispatch("review.claims." + action, arguments)
        assert not result["ok"]
    assert {table: rows(value["path"], "SELECT * FROM " + table) for table in tables} == before
    if private is not None:
        assert rows(value["path"], "SELECT * FROM research_review_drafts") == private
    result = invoke(action, **arguments)
    assert invoke(action, **arguments) == result


def test_late_private_edit_aborts_the_formal_transaction_without_losing_text(
    source_pair, monkeypatch
):
    from paper_daily.research_review import ResearchReview

    value = source_pair
    opened = start(value)
    verify = ResearchReview.verify_claim_draft
    changed = []

    def race(self, *args, **kwargs):
        ready = verify(self, *args, **kwargs)
        if not changed:
            current = invoke("read", draft_id=opened["draft_id"])
            current["draft"]["claims"][0]["text"] = "Later private text from another agent."
            invoke(
                "save",
                draft_id=opened["draft_id"],
                revision=1,
                draft=current["draft"],
                operation_id="late-save",
            )
            changed.append(True)
        return ready

    before = rows(value["path"], "SELECT * FROM paper_claim_sets")
    pending = rows(value["path"], "SELECT * FROM paperfact_sync_operations")
    monkeypatch.setattr(ResearchReview, "verify_claim_draft", race)
    result = ops.dispatch(
        "review.claims.apply",
        dict(draft_id=opened["draft_id"], revision=1, operation_id="late-apply", confirm=True),
    )
    assert not result["ok"] and result["error"]["code"] == "conflict"
    assert rows(value["path"], "SELECT * FROM paper_claim_sets") == before
    assert rows(value["path"], "SELECT * FROM paperfact_sync_operations") == pending
    assert (
        invoke("read", draft_id=opened["draft_id"])["draft"]["claims"][0]["text"]
        == "Later private text from another agent."
    )


def test_recovered_origins_are_readable_and_editable_only_after_adoption(receiver, monkeypatch):
    value = receiver
    monkeypatch.setattr(store, "DB_PATH", value["path"])
    listed = invoke("list", limit=1)
    assert len(listed["items"]) == 1 and listed["next"] is not None
    second = invoke("list", after=listed["next"], limit=1)
    assert second["items"][0]["origin_id"] != listed["items"][0]["origin_id"]
    origin = value["preview"].data["id"]
    inspected = invoke("inspect", origin_id=origin)
    assert inspected["draft"]["source"]["document_hash"] == value["source_hash"]
    target = value["preview"].data["expected"]["paper_id"]
    opened = invoke("open", origin_id=origin, target_id=target, operation_id="recovered-claim")
    result = invoke(
        "apply",
        draft_id=opened["draft_id"],
        revision=1,
        operation_id="recovered-apply",
        confirm=True,
    )
    assert result["status"] == "applied"
    assert (
        DocumentReader.from_workspace(value["path"]).resolve(target).sha256
        == value["current"].sha256
    )


@pytest.mark.parametrize(
    "action,args",
    [
        ("open", dict(origin_id="not-a-reference", target_id="paper", operation_id="x")),
        ("list", dict(after={"path": "elsewhere"})),
        ("list", dict(limit=True)),
        ("targets", dict(origin_id="generation:absent", source_path="elsewhere")),
        ("read", dict(draft_id="not-uuid")),
        ("save", dict(draft_id=str(uuid4()), revision=True, draft={}, operation_id="x")),
        ("apply", dict(draft_id=str(uuid4()), revision=1, operation_id="x", confirm=1)),
    ],
)
def test_bad_external_shapes_never_start_a_write(source_pair, action, args):
    before = source_pair["path"].read_bytes()
    result = ops.dispatch("review.claims." + action, args)
    assert not result["ok"] and result["error"]["code"] == "invalid_input"
    assert source_pair["path"].read_bytes() == before


def test_accepted_apply_replay_does_not_wait_for_unrelated_source_work(source_pair):
    from paper_daily.research_job_lock import claim

    value = source_pair
    opened = start(value)
    request = dict(
        draft_id=opened["draft_id"], revision=1, operation_id="accepted-before-busy", confirm=True
    )
    accepted = invoke("apply", **request)
    tables = (
        "paper_claim_sets",
        "research_review_drafts",
        "integration_operations",
        "research_review_receipts",
        "paperfact_sync_operations",
    )
    before = {name: rows(value["path"], "SELECT * FROM " + name) for name in tables}
    with claim(value["path"], "local-claim-review", "sources") as held:
        assert held
        repeated = ops.dispatch("review.claims.apply", request)
        changed = ops.dispatch("review.claims.apply", dict(request, restore_deleted=True))
    assert repeated == dict(ok=True, result=accepted)
    assert not changed["ok"] and changed["error"]["code"] == "conflict"
    assert {name: rows(value["path"], "SELECT * FROM " + name) for name in tables} == before


@pytest.mark.parametrize("action", ["verify", "page", "apply"])
def test_busy_source_returns_retryable_error_and_same_request_succeeds_after_release(
    source_pair, action
):
    from paper_daily.research_job_lock import claim

    value = source_pair
    opened = start(value)
    request = dict(draft_id=opened["draft_id"], revision=1)
    if action == "page":
        request["page_index"] = 0
    if action == "apply":
        request.update(operation_id="retry-after-busy", confirm=True)
    tables = (
        "paper_claim_sets",
        "research_review_drafts",
        "integration_operations",
        "paperfact_sync_operations",
    )
    before = {name: rows(value["path"], "SELECT * FROM " + name) for name in tables}
    with claim(value["path"], "local-claim-review", "sources") as held:
        assert held
        result = ops.dispatch("review.claims." + action, request)
    assert not result["ok"] and result["error"]["code"] == "in_progress"
    assert {name: rows(value["path"], "SELECT * FROM " + name) for name in tables} == before
    result = invoke(action, **request)
    assert result.get("fresh_source_checked") is True or result.get("status") == "applied"
    assert (
        DocumentReader.from_workspace(value["path"]).resolve("paper").sha256
        == value["current"].sha256
    )
