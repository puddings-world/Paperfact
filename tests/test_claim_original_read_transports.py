"""Actual restarted CLI/MCP keep source inspection independent of an old decision."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from test_claim_draft_application import claims as claims
from test_claim_draft_application import ready as ready
from test_claim_draft_application import receiver as receiver
from test_claim_draft_application import scene as scene
from test_claim_draft_application import source_pair as source_pair
from test_claim_draft_application import workspace as workspace
from test_claim_draft_storage import rows
from test_claim_review_transports import command

from paper_daily.document_reader import DocumentReader

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


def test_cli_reads_original_after_apply_without_new_decision_and_rejects_bad_reference(receiver):
    value = receiver
    target = value["preview"].data["expected"]["paper_id"]
    opened = command(
        value,
        "open",
        dict(
            origin_id=value["preview"].data["id"],
            target_id=target,
            operation_id="original-cli-open",
        ),
    )["result"]
    arguments = dict(
        draft_id=opened["draft_id"], revision=opened["revision"], page_index=0, limit=3
    )
    original = command(value, "page", arguments)
    assert original["ok"] and len(original["result"]["words"]) == 3
    request = dict(
        draft_id=opened["draft_id"],
        revision=opened["revision"],
        operation_id="original-cli-apply",
        confirm=True,
    )
    accepted = command(value, "apply", request)
    assert accepted["ok"], accepted
    assert command(value, "apply", request) == accepted
    before = rows(value["path"], "SELECT * FROM paper_claim_sets")
    receipt = rows(value["path"], "SELECT * FROM research_review_receipts")
    arguments["revision"] = accepted["result"]["revision"]
    after = command(value, "page", arguments)
    assert after["ok"], after
    assert after["result"] == original["result"]
    assert str(value["path"]) not in json.dumps(after)
    bad = command(value, "page", {**arguments, "restore_deleted": 1})
    assert not bad["ok"] and bad["error"]["code"] == "invalid_input"
    stale = command(value, "page", {**arguments, "revision": opened["revision"]})
    assert not stale["ok"] and stale["error"]["code"] == "conflict"
    denied = command(
        value,
        "apply",
        {**request, "revision": arguments["revision"], "operation_id": "another-decision"},
    )
    assert not denied["ok"]
    assert rows(value["path"], "SELECT * FROM paper_claim_sets") == before
    assert rows(value["path"], "SELECT * FROM research_review_receipts") == receipt
    assert (
        DocumentReader.from_workspace(value["path"]).resolve(target).sha256
        == value["current"].sha256
    )


def test_official_mcp_restarts_and_reads_decided_original_without_reapplying(receiver):
    from mcp import Client, StdioServerParameters

    value = receiver
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "paper_daily", "mcp", "--workspace", str(value["path"].parent)],
        env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )

    async def exercise():
        async with Client(params) as client:
            opened = await client.call_tool(
                "review.claims.open",
                dict(
                    origin_id=value["preview"].data["id"],
                    target_id=value["preview"].data["expected"]["paper_id"],
                    operation_id="original-mcp-open",
                ),
            )
            assert not opened.is_error, opened.content
            draft = opened.structured_content["result"]
            args = dict(
                draft_id=draft["draft_id"], revision=draft["revision"], page_index=0, limit=3
            )
            original = await client.call_tool("review.claims.page", args)
            assert not original.is_error, original.content
            accepted = await client.call_tool(
                "review.claims.apply",
                dict(
                    draft_id=draft["draft_id"],
                    revision=draft["revision"],
                    operation_id="original-mcp-apply",
                    confirm=True,
                ),
            )
            assert not accepted.is_error, accepted.content
        before = rows(value["path"], "SELECT * FROM paper_claim_sets")
        receipts = rows(value["path"], "SELECT * FROM research_review_receipts")
        async with Client(params) as restarted:
            args["revision"] = accepted.structured_content["result"]["revision"]
            result = await restarted.call_tool("review.claims.page", args)
            assert not result.is_error, result.content
            assert result.structured_content == original.structured_content
            assert (
                result.structured_content["result"]["source_document_hash"] == value["source_hash"]
            )
        assert rows(value["path"], "SELECT * FROM paper_claim_sets") == before
        assert rows(value["path"], "SELECT * FROM research_review_receipts") == receipts

    asyncio.run(exercise())
