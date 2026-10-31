"""The JSON CLI and official MCP tool share the local evidence audit boundary."""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing

import pymupdf
import pytest

from paper_daily import local_operations as operations
from paper_daily import store


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    database = root / "papers.db"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(store.SCHEMA)
        conn.execute(
            "INSERT INTO papers(id,title,title_key,year,venue,source) "
            "VALUES('paper','Fixture study','fixture study',2026,'Fixture','fixture')"
        )
        conn.execute("INSERT INTO dives VALUES('paper','50 participants','now',NULL)")
    pdfs = root / "pdf"
    pdfs.mkdir()
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 50), "A cohort of 50 participants.")
        pdf.save(pdfs / "paper.pdf")
    from paper_daily import config

    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(config, "PDF_DIR", pdfs)
    return root


def test_operation_has_no_provider_or_network_calls_and_does_not_mutate_database(
    corpus, monkeypatch
):
    import httpx

    from paper_daily import llm

    def forbidden(*a, **kw):
        raise AssertionError("No network, provider or login in an audit")

    monkeypatch.setattr(llm, "complete_result", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    database = corpus / "papers.db"
    original = database.read_bytes()
    first = operations.dispatch("analysis.audit", {"paper_id": "paper"})
    second = operations.dispatch("analysis.audit", {"paper_id": "paper"})
    assert first["ok"] and first == second
    assert first["result"]["checks"][0]["state"] == "source_unknown"
    assert first["result"]["semantics"] == "not_checked"
    assert database.read_bytes() == original


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"paper_id": True},
        {"paper_id": ""},
        {"paper_id": "paper", "sql": "DELETE FROM papers"},
        {"paper_id": "not-present"},
    ],
)
def test_invalid_and_missing_targets_are_closed_errors(corpus, arguments):
    result = operations.dispatch("analysis.audit", arguments)
    assert result["ok"] is False
    assert str(corpus) not in json.dumps(result)


def test_json_cli_works_in_selected_workspace_and_does_not_create_missing_store(corpus, tmp_path):
    env = {**os.environ, "PAPERFACT_DATA": str(tmp_path / "unrelated")}
    command = [
        sys.executable,
        "-m",
        "paper_daily",
        "integration",
        "analysis.audit",
        "--workspace",
        str(corpus),
    ]
    result = subprocess.run(
        command,
        input=json.dumps({"paper_id": "paper"}),
        text=True,
        capture_output=True,
        env=env,
        timeout=40,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["result"]["semantics"] == "not_checked"
    missing = tmp_path / "absent"
    command[-1] = str(missing)
    failed = subprocess.run(
        command,
        input=json.dumps({"paper_id": "paper"}),
        text=True,
        capture_output=True,
        env=env,
        timeout=40,
    )
    assert failed.returncode == 2 and not json.loads(failed.stdout)["ok"]
    assert not missing.exists() and not (tmp_path / "unrelated").exists()


def test_real_official_mcp_client_discovers_and_calls_readonly_audit(corpus):
    from mcp import Client, StdioServerParameters

    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "paper_daily", "mcp", "--workspace", str(corpus)],
            env={"PYTHONPATH": os.environ.get("PYTHONPATH", "")},
        )
        async with Client(params) as client:
            tools = await client.list_tools()
            tool = next(t for t in tools.tools if t.name == "analysis.audit")
            assert tool.annotations.read_only_hint is True
            result = await client.call_tool("analysis.audit", {"paper_id": "paper"})
            assert not result.is_error
            report = result.structured_content["result"]
            assert report["semantics"] == "not_checked"
            assert report["checks"][0]["state"] == "source_unknown"
            bad = await client.call_tool("analysis.audit", {"paper_id": "absent"})
            assert bad.is_error

    asyncio.run(run())
