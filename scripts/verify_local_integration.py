"""Verify a built CLI's JSON and MCP boundary in an isolated fixture workspace."""

import asyncio
import json
import subprocess

from mcp import Client, StdioServerParameters


def verify(command, workspace, env):
    workspace = str(workspace.resolve())
    args = [*map(str, command), "integration", "imports.propose", "--workspace", workspace]
    response = subprocess.run(
        args,
        input=json.dumps(
            {
                "name": "Integration acceptance",
                "papers": [{"title": "Fixture paper", "doi": "10.1234/test"}],
            }
        ),
        encoding="utf-8",
        capture_output=True,
        env=env,
        timeout=60,
    )
    if response.returncode:
        raise RuntimeError("Frozen JSON CLI failed: " + response.stderr)
    preview = json.loads(response.stdout)["result"]["preview_id"]

    async def exercise():
        params = StdioServerParameters(
            command=str(command[0]),
            args=[*map(str, command[1:]), "mcp", "--workspace", workspace],
            env=env,
        )
        async with Client(params) as client:
            tools = await client.list_tools()
            assert {t.name for t in tools.tools} == {
                "lists.list",
                "lists.read",
                "imports.propose",
                "imports.commit",
                "imports.discard",
                "operations.inspect",
            }
            arguments = dict(preview_id=preview, operation_id="acceptance", selected=["0"])
            first = await client.call_tool("imports.commit", arguments)
            assert not first.is_error and first.structured_content["result"]["added"] == 1
            repeat = await client.call_tool("imports.commit", arguments)
            assert repeat.structured_content == first.structured_content
            result = await client.call_tool("lists.list", {})
            assert result.structured_content["result"]["total"] == 1
        async with Client(params) as restarted:
            receipt = await restarted.call_tool(
                "operations.inspect", {"operation_id": "acceptance"}
            )
            assert receipt.structured_content["result"]["state"] == "committed"
        return {"mcp_tools": 6, "retry_preserved": True, "restart_recovery": True}

    return asyncio.run(exercise())
