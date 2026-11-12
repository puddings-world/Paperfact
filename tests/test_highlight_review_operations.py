"""Public highlight revisions share the actual atomic desktop publication boundary."""

import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from test_highlight_draft_verification import ready as ready
from test_highlight_draft_verification import scene as scene
from test_highlight_draft_verification import source_pair as source_pair
from test_highlight_draft_verification import workspace as workspace
from test_research_generation import rows

from paper_daily import local_operations as ops
from paper_daily.document_reader import DocumentReader

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


def invoke(action, **arguments):
    response = ops.dispatch("review.highlights." + action, arguments)
    assert response["ok"], response
    return response["result"]


def start(value, operation="highlight-open"):
    return invoke(
        "open",
        origin_id="generation:" + value["original"].data["id"],
        target_id="paper",
        operation_id=operation,
        draft=json.loads(value["body"]),
    )


def test_public_highlight_list_inspect_save_independent_words_verify_confirm_and_retry(source_pair):
    value = source_pair
    origin = "generation:" + value["original"].data["id"]
    listing = invoke("list", limit=1)
    assert listing["items"][0]["origin_id"] == origin and len(listing["items"]) == 1
    inspected = invoke("inspect", origin_id=origin)
    assert inspected["draft"]["source"]["document_hash"] == value["preview"].data["source_hash"]
    assert not inspected["can_apply"] and not inspected["fresh_source_checked"]
    assert invoke("targets", origin_id=origin)["items"] == [dict(id="paper", title="Paper")]
    opened = start(value)
    assert start(value) == opened
    current = invoke("read", draft_id=opened["draft_id"])
    assert current["draft"] == json.loads(value["body"]) and not current["can_apply"]
    current["draft"]["items"][0]["reason"] = "External agent's explicit manual highlight appraisal."
    saved = invoke(
        "save",
        draft_id=opened["draft_id"],
        revision=1,
        draft=current["draft"],
        operation_id="highlight-save",
    )
    assert saved["revision"] == 2
    before = rows(value["path"], "SELECT * FROM paper_highlight_analysis")
    words = invoke("page", draft_id=opened["draft_id"], revision=2, page_index=0, limit=3)
    assert words["source_document_hash"] == value["preview"].data["source_hash"]
    assert len(words["words"]) == 3 and words["next_offset"] == 3
    assert words["words"][0]["text"] == "The"
    checked = invoke("verify", draft_id=opened["draft_id"], revision=2)
    assert checked["report"]["all_quotes_located"]
    assert checked["report"]["generation"]["backend"] == "manual" and not checked["can_apply"]
    request = dict(draft_id=opened["draft_id"], revision=2, operation_id="highlight-apply")
    denied = ops.dispatch("review.highlights.apply", request)
    assert denied["error"]["code"] == "confirmation_required"
    assert rows(value["path"], "SELECT * FROM paper_highlight_analysis") == before
    result = invoke("apply", **dict(request, confirm=True))
    assert result["status"] == "applied" and result["revision"] == 3
    assert invoke("apply", **dict(request, confirm=True)) == result
    body = json.loads(
        rows(value["path"], "SELECT body_json FROM paper_highlight_analysis")[0]["body_json"]
    )
    assert body["items"][0]["reason"] == current["draft"]["items"][0]["reason"]
    assert len(rows(value["path"], "SELECT * FROM pdf_ai_highlights")) == 2
    assert rows(value["path"], "SELECT count(*) AS n FROM research_review_receipts") == [dict(n=1)]
    assert rows(value["path"], "SELECT count(*) AS n FROM integration_operations") == [dict(n=3)]
    assert (
        DocumentReader.from_workspace(value["path"]).resolve("paper").sha256
        == value["current"].sha256
    )
    output = json.dumps([listing, inspected, current, words, checked, result])
    assert (
        str(value["path"]) not in output and "owner_json" not in output and "db_path" not in output
    )


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
        results = list(
            pool.map(lambda _: ops.dispatch("review.highlights.apply", request), range(4))
        )
    assert all(result["ok"] for result in results), results
    assert results == [results[0]] * 4
    assert rows(value["path"], "SELECT revision FROM research_review_drafts") == [dict(revision=2)]
    assert rows(value["path"], "SELECT count(*) AS n FROM research_review_receipts") == [dict(n=1)]


@pytest.mark.parametrize("action", ["open", "save", "apply"])
def test_public_receipt_failure_rolls_back_private_and_canonical_state(
    source_pair, monkeypatch, action
):
    from paper_daily import highlight_review_operations

    value = source_pair
    opened = None if action == "open" else start(value)
    tables = ("paper_highlight_analysis", "paperfact_sync_operations")
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
            highlight_review_operations,
            "_receipt",
            lambda *a: (_ for _ in ()).throw(OSError("receipt full")),
        )
        result = ops.dispatch("review.highlights." + action, arguments)
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
    verify = ResearchReview.verify_highlight_draft
    changed = []

    def race(self, *args, **kwargs):
        ready = verify(self, *args, **kwargs)
        if not changed:
            current = invoke("read", draft_id=opened["draft_id"])
            current["draft"]["items"][0]["reason"] = "Later private text from another agent."
            invoke(
                "save",
                draft_id=opened["draft_id"],
                revision=1,
                draft=current["draft"],
                operation_id="late-save",
            )
            changed.append(True)
        return ready

    before = rows(value["path"], "SELECT * FROM paper_highlight_analysis")
    pending = rows(value["path"], "SELECT * FROM paperfact_sync_operations")
    monkeypatch.setattr(ResearchReview, "verify_highlight_draft", race)
    result = ops.dispatch(
        "review.highlights.apply",
        dict(draft_id=opened["draft_id"], revision=1, operation_id="late-apply", confirm=True),
    )
    assert not result["ok"] and result["error"]["code"] == "conflict"
    assert rows(value["path"], "SELECT * FROM paper_highlight_analysis") == before
    assert rows(value["path"], "SELECT * FROM paperfact_sync_operations") == pending
    assert (
        invoke("read", draft_id=opened["draft_id"])["draft"]["items"][0]["reason"]
        == "Later private text from another agent."
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
    result = ops.dispatch("review.highlights." + action, args)
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
        "paper_highlight_analysis",
        "research_review_drafts",
        "integration_operations",
        "research_review_receipts",
        "paperfact_sync_operations",
    )
    before = {name: rows(value["path"], "SELECT * FROM " + name) for name in tables}
    with claim(value["path"], "local-claim-review", "sources") as held:
        assert held
        repeated = ops.dispatch("review.highlights.apply", request)
        changed = ops.dispatch("review.highlights.apply", dict(request, restore_deleted=True))
    assert repeated == dict(ok=True, result=accepted)
    assert not changed["ok"] and changed["error"]["code"] == "conflict"
    assert {name: rows(value["path"], "SELECT * FROM " + name) for name in tables} == before


def test_unresolved_quote_can_be_read_and_corrected_without_partial_publication(source_pair):
    value = source_pair
    opened = start(value)
    current = invoke("read", draft_id=opened["draft_id"])["draft"]
    original_text = current["items"][0]["text"]
    current["items"][0]["text"] = "A plausible conclusion absent from the exact original."
    invoke(
        "save",
        draft_id=opened["draft_id"],
        revision=1,
        draft=current,
        operation_id="missing-quote-save",
    )
    tables = (
        "paper_highlight_analysis",
        "pdf_ai_highlights",
        "paperfact_sync_operations",
        "research_review_drafts",
        "integration_operations",
    )
    before = {name: rows(value["path"], "SELECT * FROM " + name) for name in tables}
    words = invoke("page", draft_id=opened["draft_id"], revision=2, page_index=0)
    assert words["words"][0]["text"] == "The"
    report = invoke("verify", draft_id=opened["draft_id"], revision=2)["report"]
    assert not report["all_quotes_located"] and report["analysis"] is None
    assert report["marks"] == []
    denied = ops.dispatch(
        "review.highlights.apply",
        dict(
            draft_id=opened["draft_id"],
            revision=2,
            operation_id="missing-quote-apply",
            confirm=True,
        ),
    )
    assert not denied["ok"]
    assert {name: rows(value["path"], "SELECT * FROM " + name) for name in tables} == before
    current["items"][0]["text"] = original_text
    invoke(
        "save",
        draft_id=opened["draft_id"],
        revision=2,
        draft=current,
        operation_id="repaired-quote-save",
    )
    accepted = invoke(
        "apply",
        draft_id=opened["draft_id"],
        revision=3,
        operation_id="repaired-quote-apply",
        confirm=True,
    )
    assert accepted["status"] == "applied" and accepted["revision"] == 4
    assert len(rows(value["path"], "SELECT * FROM pdf_ai_highlights")) == 2
