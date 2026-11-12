"""Actual CLI processes and official MCP SDK use the durable native review boundary."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from test_archived_draft_resumption import copied as copied
from test_archived_draft_resumption import decision as decision
from test_archived_draft_resumption import draft_variants as draft_variants
from test_archived_draft_resumption import source as source
from test_note_draft_resumption import recovered_note as recovered_note
from test_note_draft_resumption_edges import note_rows, stored

from paper_daily import local_operations as ops


def command(value, operation, arguments):
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "paper_daily",
            "integration",
            "review.notes." + operation,
            "--workspace",
            str(value["path"].parent),
        ],
        input=json.dumps(arguments),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    )
    response = json.loads(completed.stdout)
    assert completed.returncode == (0 if response["ok"] else 2), completed.stderr
    return response


def test_json_cli_survives_process_restart_and_refuses_paths_without_mutation(recovered_note):
    value = recovered_note
    before = stored(value)
    listed = command(value, "list", {})["result"]["items"]
    assert len(listed) == 2
    origin = value["archived"].data["id"]
    targets = command(value, "targets", dict(origin_id=origin))["result"]["items"]
    target = next(item for item in targets if "Current anchored note B" in item["title"])
    request = dict(origin_id=origin, target_id=target["id"], operation_id="cli-note-open")
    opened = command(value, "open", request)["result"]
    assert command(value, "open", request)["result"] == opened
    ref = {key: opened[key] for key in ("draft_id", "revision")}
    bad = command(value, "page", dict(**ref, source={"path": str(value["path"])}, page_index=0))
    assert bad["error"]["code"] == "invalid_input"
    cleared = command(value, "clear", dict(**ref, operation_id="cli-note-clear"))["result"]
    saved = command(
        value,
        "save",
        dict(
            draft_id=ref["draft_id"],
            revision=cleared["revision"],
            body="CLI human continuation",
            operation_id="cli-note-save",
        ),
    )["result"]
    assert stored(value) == before
    read = command(value, "read", dict(draft_id=ref["draft_id"]))["result"]
    assert (
        read["retained"]["body"] == "CLI human continuation" and read["retained"]["anchor"] is None
    )
    request = dict(
        draft_id=ref["draft_id"],
        revision=saved["revision"],
        operation_id="cli-note-apply",
        confirm=True,
    )
    applied = command(value, "decide", request)["result"]
    assert command(value, "decide", request)["result"] == applied
    assert note_rows(value, "body,page,anchor") == [("CLI human continuation", None, None)]
    assert str(value["path"].parent) not in json.dumps(read)
    value["review"].close()


def test_official_sdk_discovers_and_continues_note_review_after_server_restart(recovered_note):
    from mcp import Client, StdioServerParameters

    value = recovered_note
    before = stored(value)
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

            async def call(name, args):
                reply = await client.call_tool("review.notes." + name, args)
                assert not reply.is_error, reply.content
                return reply.structured_content["result"]

            listed = await call("list", {})
            assert len(listed["items"]) == 2
            origin = value["archived"].data["id"]
            targets = await call("targets", dict(origin_id=origin))
            target = next(
                item for item in targets["items"] if "Current anchored note B" in item["title"]
            )
            opened = await call(
                "open", dict(origin_id=origin, target_id=target["id"], operation_id="mcp-note-open")
            )
            ref = {key: opened[key] for key in ("draft_id", "revision")}
            sources = await call("sources", ref)
            source = next(
                item["reference"]
                for item in sources["items"]
                if item["reference"]["kind"] == "recorded"
            )
            page = await call("page", dict(**ref, source=source, page_index=0))
            assert [word["text"] for word in page["words"]] == ["A", "verified", "source", "paper"]
            mapped = await call(
                "map",
                dict(
                    **ref,
                    source=source,
                    anchor=dict(p0=0, o0=0, p1=0, o1=3),
                    operation_id="mcp-note-map",
                ),
            )
            saved = await call(
                "save",
                dict(
                    draft_id=ref["draft_id"],
                    revision=mapped["revision"],
                    body="MCP human continuation",
                    operation_id="mcp-note-save",
                ),
            )
            malformed = await client.call_tool(
                "review.notes.sources", dict(draft_id=ref["draft_id"], revision=True)
            )
            assert malformed.is_error
            assert stored(value) == before
        async with Client(params) as restarted:
            read = await restarted.call_tool("review.notes.read", dict(draft_id=ref["draft_id"]))
            assert read.structured_content["result"]["retained"]["body"] == "MCP human continuation"
            args = dict(
                draft_id=ref["draft_id"],
                revision=saved["revision"],
                operation_id="mcp-note-apply",
                confirm=True,
            )
            applied = await restarted.call_tool("review.notes.decide", args)
            assert not applied.is_error, applied.content
            repeat = await restarted.call_tool("review.notes.decide", args)
            assert repeat.structured_content == applied.structured_content
            changed = await restarted.call_tool("review.notes.decide", {**args, "decision": "keep"})
            assert changed.is_error and "conflict" in str(changed.content)

    asyncio.run(exercise())
    assert note_rows(value, "body") == [("MCP human continuation",)]
    value["review"].close()
