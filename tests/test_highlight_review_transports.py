"""Real JSON CLI and official MCP SDK highlight continuation, with fixture PDFs."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_highlight_apply_journeys import recovered as recovered
from test_highlight_draft_verification import ready as ready
from test_highlight_draft_verification import scene as scene
from test_highlight_draft_verification import source_pair as source_pair
from test_highlight_draft_verification import workspace as workspace
from test_research_generation import rows

from paper_daily import local_operations as ops

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


def command(value, operation, arguments):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "paper_daily",
            "integration",
            "review.highlights." + operation,
            "--workspace",
            str(value["path"].parent),
        ],
        input=json.dumps(arguments),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONPATH=str(root / "src")),
        timeout=60,
    )
    try:
        response = json.loads(result.stdout)
    except ValueError:
        pytest.fail("CLI did not return its JSON envelope: " + result.stderr[-1000:])
    assert result.returncode == (0 if response["ok"] else 2), result.stderr
    return response


def test_cli_restart_retains_private_words_and_one_confirmed_decision(recovered):
    value = recovered

    def call(action, **arguments):
        result = command(value, action, arguments)
        assert result["ok"], result
        return result["result"]

    origin = value["preview"].data["id"]
    opened = call(
        "open",
        origin_id=origin,
        target_id=value["preview"].data["expected"]["paper_id"],
        operation_id="cli-open",
        draft=json.loads(value["body"]),
    )
    draft = call("read", draft_id=opened["draft_id"])["draft"]
    draft["items"][0]["reason"] = "CLI private appraisal survives process restart."
    call("save", draft_id=opened["draft_id"], revision=1, draft=draft, operation_id="cli-save")
    assert call("read", draft_id=opened["draft_id"])["draft"] == draft
    words = call("page", draft_id=opened["draft_id"], revision=2, page_index=0, limit=3)
    assert words["words"][0]["text"] == "The" and len(words["words"]) == 3
    request = dict(draft_id=opened["draft_id"], revision=2, operation_id="cli-apply", confirm=True)
    result = call("apply", **request)
    assert result["revision"] == 3 and call("apply", **request) == result
    body = json.loads(
        rows(value["path"], "SELECT body_json FROM paper_highlight_analysis")[0]["body_json"]
    )
    assert body["items"][0]["reason"] == draft["items"][0]["reason"]
    assert rows(value["path"], "SELECT count(*) AS n FROM research_review_receipts") == [dict(n=1)]


def test_official_mcp_discovers_highlight_tools_and_rechecks_after_server_restart(recovered):
    from mcp import Client, StdioServerParameters

    value = recovered
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "paper_daily", "mcp", "--workspace", str(value["path"].parent)],
        env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )

    async def exercise():
        async with Client(params) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools.tools} == set(ops.OPERATIONS)
            assert len(tools.tools) == 35
            for tool in tools.tools:
                if tool.name in {
                    "review.highlights.list",
                    "review.highlights.inspect",
                    "review.highlights.targets",
                    "review.highlights.read",
                    "review.highlights.verify",
                    "review.highlights.page",
                }:
                    assert tool.annotations.read_only_hint is True

            async def call(action, args):
                reply = await client.call_tool("review.highlights." + action, args)
                assert not reply.is_error, reply.content
                return reply.structured_content["result"]

            origin = value["preview"].data["id"]
            inspected = await call("inspect", dict(origin_id=origin))
            target = value["preview"].data["expected"]["paper_id"]
            opened = await call(
                "open", dict(origin_id=origin, target_id=target, operation_id="mcp-claim-open")
            )
            draft = inspected["draft"]
            draft["items"][0]["reason"] = "MCP manual claim, continued after reconnect."
            saved = await call(
                "save",
                dict(
                    draft_id=opened["draft_id"],
                    revision=1,
                    draft=draft,
                    operation_id="mcp-claim-save",
                ),
            )
            malformed = await client.call_tool(
                "review.highlights.verify", dict(draft_id=opened["draft_id"], revision=True)
            )
            assert malformed.is_error
        async with Client(params) as restarted:
            loaded = await restarted.call_tool(
                "review.highlights.read", dict(draft_id=opened["draft_id"])
            )
            assert (
                loaded.structured_content["result"]["draft"]["items"][0]["reason"]
                == draft["items"][0]["reason"]
            )
            args = dict(
                draft_id=opened["draft_id"],
                revision=saved["revision"],
                operation_id="mcp-claim-apply",
                confirm=True,
            )
            result = await restarted.call_tool("review.highlights.apply", args)
            assert not result.is_error, result.content
            assert (
                await restarted.call_tool("review.highlights.apply", args)
            ).structured_content == result.structured_content
            altered = await restarted.call_tool(
                "review.highlights.apply", {**args, "restore_deleted": True}
            )
            assert altered.is_error and "conflict" in str(altered.content)

    asyncio.run(exercise())
    body = json.loads(
        rows(value["path"], "SELECT body_json FROM paper_highlight_analysis")[0]["body_json"]
    )
    assert body["items"][0]["reason"] == "MCP manual claim, continued after reconnect."
