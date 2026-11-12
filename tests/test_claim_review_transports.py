"""Actual JSON CLI processes and official MCP SDK share restartable claim operations."""

import asyncio
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest
from test_claim_draft_application import claims as claims
from test_claim_draft_application import ready as ready
from test_claim_draft_application import receiver as receiver
from test_claim_draft_application import scene as scene
from test_claim_draft_application import source_pair as source_pair
from test_claim_draft_application import workspace as workspace
from test_claim_draft_storage import rows

from paper_daily import local_operations as ops
from paper_daily import research_generation as generation
from paper_daily import sync_recovery
from paper_daily.document_reader import DocumentReader
from paper_daily.sync_artifacts import paths

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


def command(value, operation, arguments):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "paper_daily",
            "integration",
            "review.claims." + operation,
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


def test_cli_process_restart_preserves_claim_fields_and_apply_receipt(receiver):
    value = receiver
    origin = value["preview"].data["id"]
    inspected = command(value, "inspect", dict(origin_id=origin))["result"]
    assert not inspected["fresh_source_checked"] and not inspected["can_apply"]
    target = value["preview"].data["expected"]["paper_id"]
    opened = command(
        value, "open", dict(origin_id=origin, target_id=target, operation_id="cli-claim-open")
    )["result"]
    read = command(value, "read", dict(draft_id=opened["draft_id"]))["result"]
    read["draft"]["claims"][0]["text"] = "Manual claim from an external CLI agent."
    saved = command(
        value,
        "save",
        dict(
            draft_id=opened["draft_id"],
            revision=1,
            draft=read["draft"],
            operation_id="cli-claim-save",
        ),
    )["result"]
    check = command(value, "verify", dict(draft_id=opened["draft_id"], revision=saved["revision"]))[
        "result"
    ]
    assert check["fresh_source_checked"] and not check["can_apply"]
    page = command(
        value,
        "page",
        dict(draft_id=opened["draft_id"], revision=saved["revision"], page_index=0, limit=3),
    )["result"]
    assert len(page["words"]) == 3 and page["source_document_hash"] == value["source_hash"]
    bad = command(
        value,
        "verify",
        dict(
            draft_id=opened["draft_id"], revision=saved["revision"], source_path=str(value["path"])
        ),
    )
    assert bad["error"]["code"] == "invalid_input"
    request = dict(
        draft_id=opened["draft_id"],
        revision=saved["revision"],
        operation_id="cli-claim-apply",
        confirm=True,
    )
    first = command(value, "apply", request)
    assert first["ok"], first
    assert command(value, "apply", request) == first
    body = json.loads(rows(value["path"], "SELECT body_json FROM paper_claim_sets")[0]["body_json"])
    assert body["report"]["claims"][0]["text"] == "Manual claim from an external CLI agent."
    assert (
        DocumentReader.from_workspace(value["path"]).resolve(target).sha256
        == value["current"].sha256
    )
    assert str(value["path"]) not in json.dumps(read)


def test_parallel_cli_processes_share_the_source_job_and_one_decision(receiver):
    value = receiver
    opened = command(
        value,
        "open",
        dict(
            origin_id=value["preview"].data["id"],
            target_id=value["preview"].data["expected"]["paper_id"],
            operation_id="parallel-cli-open",
        ),
    )["result"]
    request = dict(
        draft_id=opened["draft_id"], revision=1, operation_id="parallel-cli-apply", confirm=True
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: command(value, "apply", request), range(2)))
    assert results[0]["ok"] and results[1] == results[0]
    assert rows(value["path"], "SELECT count(*) AS n FROM research_review_receipts") == [dict(n=1)]


def test_detached_cli_inspection_preserves_database_bytes_and_schema(receiver):
    value = receiver
    folder = value["path"].parent.parent
    output = folder / "claim-cli-snapshot.zip"
    with closing(generation._connect(value["path"])) as conn:
        blobs, _versions = paths(conn)
    sync_recovery.create(
        value["path"], output, blob_store=blobs, pdf_roots=[value["path"].parent / "pdf"]
    )
    detached = folder / "claim-cli-detached"
    sync_recovery.restore_detached(output, detached)
    recovered = dict(path=detached / "papers.db")
    before = recovered["path"].read_bytes()
    schema = rows(recovered["path"], "SELECT name,sql FROM sqlite_master ORDER BY name")
    listed = command(recovered, "list", dict(limit=1))["result"]
    assert not listed["editable"]
    origin = listed["items"][0]["origin_id"]
    inspected = command(recovered, "inspect", dict(origin_id=origin))["result"]
    assert inspected["draft"]["source"]["document_hash"] == value["source_hash"]
    assert not inspected["editable"] and not inspected["fresh_source_checked"]
    denied = command(
        recovered, "open", dict(origin_id=origin, target_id="paper", operation_id="readonly-open")
    )
    assert not denied["ok"]
    assert recovered["path"].read_bytes() == before
    assert rows(recovered["path"], "SELECT name,sql FROM sqlite_master ORDER BY name") == schema


def test_official_mcp_discovers_claim_tools_and_rechecks_after_server_restart(receiver):
    from mcp import Client, StdioServerParameters

    value = receiver
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "paper_daily", "mcp", "--workspace", str(value["path"].parent)],
        env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )

    async def exercise():
        async with Client(params) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools.tools} == set(ops.OPERATIONS)
            assert len(tools.tools) == 38
            for tool in tools.tools:
                if tool.name in {
                    "review.claims.list",
                    "review.claims.inspect",
                    "review.claims.targets",
                    "review.claims.read",
                    "review.claims.verify",
                    "review.claims.page",
                }:
                    assert tool.annotations.read_only_hint is True

            async def call(action, args):
                reply = await client.call_tool("review.claims." + action, args)
                assert not reply.is_error, reply.content
                return reply.structured_content["result"]

            origin = value["preview"].data["id"]
            inspected = await call("inspect", dict(origin_id=origin))
            target = value["preview"].data["expected"]["paper_id"]
            opened = await call(
                "open", dict(origin_id=origin, target_id=target, operation_id="mcp-claim-open")
            )
            draft = inspected["draft"]
            draft["claims"][0]["text"] = "MCP manual claim, continued after reconnect."
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
                "review.claims.verify", dict(draft_id=opened["draft_id"], revision=True)
            )
            assert malformed.is_error
        async with Client(params) as restarted:
            loaded = await restarted.call_tool(
                "review.claims.read", dict(draft_id=opened["draft_id"])
            )
            assert (
                loaded.structured_content["result"]["draft"]["claims"][0]["text"]
                == draft["claims"][0]["text"]
            )
            args = dict(
                draft_id=opened["draft_id"],
                revision=saved["revision"],
                operation_id="mcp-claim-apply",
                confirm=True,
            )
            result = await restarted.call_tool("review.claims.apply", args)
            assert not result.is_error, result.content
            assert (
                await restarted.call_tool("review.claims.apply", args)
            ).structured_content == result.structured_content
            altered = await restarted.call_tool(
                "review.claims.apply", {**args, "restore_deleted": True}
            )
            assert altered.is_error and "conflict" in str(altered.content)

    asyncio.run(exercise())
    body = json.loads(rows(value["path"], "SELECT body_json FROM paper_claim_sets")[0]["body_json"])
    assert body["report"]["claims"][0]["text"] == "MCP manual claim, continued after reconnect."
