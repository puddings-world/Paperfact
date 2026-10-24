"""Offline, transactional integration contracts; never use real research/accounts."""

import asyncio
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from paper_daily import local_operations as ops
from paper_daily import store


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    return tmp_path


def papers():
    return [
        {
            "title": "研究 A",
            "doi": "https://doi.org/10.1234/A",
            "year": 2025,
            "reason": "Background",
            "url": "https://example.org/a",
        },
        {"title": "Research B", "arxiv_id": "https://arxiv.org/abs/2401.12345v3"},
    ]


def preview():
    return ops.propose("研究路線", papers())["preview_id"]


def test_preview_is_not_a_list_then_atomic_ordered_commit_and_recovery(workspace):
    staged = preview()
    assert ops.list_collections()["total"] == 0
    value = ops.commit(staged, "request-1", ["1", "0"])
    saved = ops.read_collection(value["list_id"])
    assert [p["title"] for p in saved["papers"]] == ["Research B", "研究 A"]
    assert saved["papers"][0]["arxiv_id"] == "2401.12345"
    assert saved["papers"][1]["doi"] == "10.1234/a"
    with store.connect() as conn:
        assert (
            conn.execute("SELECT citation FROM list_papers ORDER BY position DESC").fetchone()[0]
            == "Background"
        )
    ops.discard(staged)
    assert ops.commit(staged, "request-1", ["1", "0"]) == value
    assert ops.inspect_operation("request-1")["result"] == value
    assert ops.inspect_operation("absent")["state"] == "not_committed"
    assert ops.list_collections()["total"] == 1


def test_changed_retry_is_conflict_and_parallel_retry_writes_once(workspace):
    staged = preview()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: ops.commit(staged, "repeat", ["0", "1"]), range(20)))
    assert all(r == results[0] for r in results)
    assert ops.list_collections()["total"] == 1
    with pytest.raises(ops.OperationError, match="different request"):
        ops.commit(staged, "repeat", ["1"])
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM integration_changes").fetchone()[0] == 1


def test_append_deduplicates_identifiers_and_preserves_notes_metadata_order(workspace):
    first = ops.commit(preview(), "first", ["0"])
    with store.connect() as conn:
        conn.execute(
            "UPDATE papers SET title='Curated title',pdf_url='https://example.org/kept.pdf'"
        )
        conn.execute(
            "INSERT INTO dives(paper_id,body,written_at) VALUES(?,?,?)",
            (first["paper_ids"][0], "My explanation", "now"),
        )
    staged = ops.propose("Ignored new name", papers(), first["list_id"])
    assert staged["items"][0]["identity_matches"] == first["paper_ids"]
    second = ops.commit(staged["preview_id"], "append", ["1", "0"])
    assert second["added"] == 1
    saved = ops.read_collection(first["list_id"])
    assert saved["name"] == "研究路線"
    assert [p["title"] for p in saved["papers"]] == ["Curated title", "Research B"]
    with store.connect() as conn:
        assert conn.execute("SELECT body FROM dives").fetchone()[0] == "My explanation"
        assert (
            conn.execute("SELECT pdf_url FROM papers WHERE id=?", first["paper_ids"]).fetchone()[0]
            == "https://example.org/kept.pdf"
        )


def test_duplicate_candidates_share_identity_but_titles_alone_require_explicit_reuse(workspace):
    staged = ops.propose("Duplicate", [papers()[0], papers()[0]])
    first = ops.commit(staged["preview_id"], "dup", ["0", "1"])
    assert first["added"] == 1
    staged = ops.propose("Title only", [{"title": "研究 A"}])
    assert staged["items"][0]["title_matches"] == first["paper_ids"][:1]
    assert not staged["items"][0]["identity_matches"]
    value = ops.commit(staged["preview_id"], "reuse", ["0"], {"0": first["paper_ids"][0]})
    assert value["paper_ids"] == first["paper_ids"][:1]
    separate = ops.commit(staged["preview_id"], "separate", ["0"])
    assert separate["paper_ids"] != value["paper_ids"]
    assert separate["warnings"]


def test_identity_conflict_rolls_back_entire_list_and_retry_can_succeed(workspace, monkeypatch):
    staged = preview()
    real = store.upsert_papers
    attempts = []

    def failing(conn, rows):
        attempts.append(1)
        if len(attempts) == 2:
            raise RuntimeError("simulated disk failure")
        return real(conn, rows)

    monkeypatch.setattr(store, "upsert_papers", failing)
    with pytest.raises(RuntimeError):
        ops.commit(staged, "atomic", ["0", "1"])
    assert ops.list_collections()["total"] == 0
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
    monkeypatch.setattr(store, "upsert_papers", real)
    assert ops.commit(staged, "atomic", ["0", "1"])["added"] == 2


@pytest.mark.parametrize("selected", [[], ["0", "0"], ["99"], [0], None, ["-1"]])
def test_invalid_selection_never_creates_list(workspace, selected):
    result = ops.dispatch(
        "imports.commit", dict(preview_id=preview(), operation_id="bad", selected=selected)
    )
    assert not result["ok"] and result["error"]["code"] == "invalid_input"
    assert ops.list_collections()["total"] == 0


@pytest.mark.parametrize(
    "paper",
    [
        {},
        {"title": " "},
        {"title": "A", "year": "2025"},
        {"title": "A", "doi": "wrong"},
        {"title": "A", "arxiv_id": "../../file"},
        {"title": "A", "pdf_url": "file:///secret"},
        {"title": "A", "url": "https://secret:password@example.org"},
        {"title": "A", "run": "shell"},
        {"title": "A", "authors": [""]},
    ],
)
def test_untrusted_fields_rejected_without_writes(workspace, paper):
    result = ops.dispatch("imports.propose", {"name": "Test", "papers": [paper]})
    assert not result["ok"] and result["error"]["code"] == "invalid_input"
    assert ops.list_collections()["total"] == 0


def test_cancel_expiry_deleted_target_and_pagination(workspace):
    staged = preview()
    ops.discard(staged)
    ops.discard(staged)
    with pytest.raises(ops.OperationError, match="expired"):
        ops.commit(staged, "cancelled", ["0"])
    staged = preview()
    with store.connect() as conn:
        conn.execute("UPDATE integration_previews SET expires_at=0")
    assert (
        ops.dispatch(
            "imports.commit", dict(preview_id=staged, operation_id="expired", selected=["0"])
        )["error"]["code"]
        == "expired_preview"
    )
    first = ops.commit(preview(), "one", ["0", "1"])
    assert ops.read_collection(first["list_id"], limit=1)["next_offset"] == 1
    assert len(ops.read_collection(first["list_id"], limit=1, offset=1)["papers"]) == 1
    staged = ops.propose("Append", papers(), first["list_id"])
    with store.connect() as conn:
        conn.execute("DELETE FROM lists WHERE id=?", (first["list_id"],))
    result = ops.dispatch(
        "imports.commit", dict(preview_id=staged["preview_id"], operation_id="gone", selected=["0"])
    )
    assert result["error"]["code"] == "not_found"


def test_conflicting_identifiers_do_not_merge_research(workspace):
    one = ops.commit(preview(), "seed", ["0", "1"])
    staged = ops.propose("Conflict", [{**papers()[0], "arxiv_id": "2401.12345"}])
    assert len(staged["items"][0]["identity_matches"]) == 2
    result = ops.dispatch(
        "imports.commit",
        dict(preview_id=staged["preview_id"], operation_id="conflict", selected=["0"]),
    )
    assert result["error"]["code"] == "identity_conflict"
    assert ops.list_collections()["total"] == 1
    assert ops.read_collection(one["list_id"])["total"] == 2


def test_dispatch_rejects_unknown_operations_and_arguments(workspace):
    assert ops.dispatch("shell.run", {})["error"]["code"] == "unknown_operation"
    assert (
        ops.dispatch("lists.list", {"sql": "DELETE FROM papers"})["error"]["code"]
        == "invalid_input"
    )
    assert not ops.dispatch("lists.list", {"limit": True})["ok"]


def test_cli_workspace_isolation_unicode_json_and_retries(tmp_path):
    selected, ignored = tmp_path / "selected folder", tmp_path / "wrong folder"
    env = dict(os.environ, PAPERFACT_DATA=str(ignored))

    def call(operation, arguments):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "paper_daily",
                "integration",
                operation,
                "--workspace",
                str(selected),
            ],
            input=json.dumps(arguments, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            capture_output=True,
            env=env,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        return json.loads(result.stdout)["result"]

    staged = call("imports.propose", {"name": "跨專案", "papers": papers()})
    args = dict(preview_id=staged["preview_id"], operation_id="cli", selected=["0", "1"])
    first = call("imports.commit", args)
    assert call("imports.commit", args) == first
    assert call("lists.list", {})["lists"][0]["name"] == "跨專案"
    assert not ignored.exists()
    bad = subprocess.run(
        [
            sys.executable,
            "-m",
            "paper_daily",
            "integration",
            "imports.propose",
            "--workspace",
            str(selected),
        ],
        input="broken",
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
    )
    assert bad.returncode == 2 and not json.loads(bad.stdout)["ok"]


def test_official_sdk_stdio_discovery_commit_errors_and_disconnect(tmp_path):
    from mcp import Client, StdioServerParameters

    async def exercise():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "paper_daily", "mcp", "--workspace", str(tmp_path / "mcp")],
        )
        async with Client(params) as client:
            tools = await client.list_tools()
            assert {t.name for t in tools.tools} == set(ops.OPERATIONS)
            proposed = await client.call_tool(
                "imports.propose", {"name": "MCP", "papers": papers()}
            )
            assert not proposed.is_error
            preview_id = proposed.structured_content["result"]["preview_id"]
            args = dict(preview_id=preview_id, operation_id="mcp", selected=["0"])
            first = await client.call_tool("imports.commit", args)
            assert first.structured_content["result"]["added"] == 1
            assert (
                await client.call_tool("imports.commit", args)
            ).structured_content == first.structured_content
            conflict = await client.call_tool("imports.commit", {**args, "selected": ["1"]})
            assert conflict.is_error and "conflict" in str(conflict.content)
        # A new helper recovers committed state after the original process exited.
        async with Client(params) as second:
            result = await second.call_tool("operations.inspect", {"operation_id": "mcp"})
            assert result.structured_content["result"]["state"] == "committed"

    asyncio.run(exercise())


def test_helper_imports_neither_qt_nor_ai():
    code = (
        "import sys; from paper_daily.mcp_server import create_server; create_server(); "
        "assert not any(k.startswith('PySide6') for k in sys.modules); "
        "assert 'paper_daily.llm' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_packaged_acceptance_contract_also_runs_against_source(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from verify_local_integration import verify

    report = verify(
        [sys.executable, "-m", "paper_daily"], tmp_path / "acceptance", dict(os.environ)
    )
    assert report == {"mcp_tools": 6, "retry_preserved": True, "restart_recovery": True}


def test_distinct_concurrent_operations_share_strong_paper_identity(workspace):
    staged = preview()
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(
            pool.map(lambda i: ops.commit(staged, f"independent-{i}", ["0", "1"]), range(6))
        )
    assert len({r["list_id"] for r in results}) == 6
    assert all(r["paper_ids"] == results[0]["paper_ids"] for r in results)
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 2


def test_busy_workspace_returns_retryable_error(workspace):
    staged = preview()
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        result = ops.dispatch(
            "imports.commit", dict(preview_id=staged, operation_id="locked", selected=["0"])
        )
        assert result["error"]["code"] == "storage_unavailable"
    assert ops.commit(staged, "locked", ["0"])["added"] == 1


def test_host_config_uses_console_python_and_persistent_appimage_path(tmp_path, monkeypatch):
    from paper_daily import integration_config as config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config.runtime, "FROZEN", False)
    monkeypatch.setattr(
        config.runtime,
        "cli_command",
        lambda *args: [str(tmp_path / "pythonw.exe"), "-m", "paper_daily", *args],
    )
    source = config.host_config()["mcpServers"]["paperfact"]
    assert source["command"] == str(tmp_path / "python.exe")
    monkeypatch.setattr(config.runtime, "FROZEN", True)
    image = str(tmp_path / "Paperfact.AppImage")
    monkeypatch.setenv("APPIMAGE", image)
    packaged = config.host_config()["mcpServers"]["paperfact"]
    assert packaged == {
        "command": image,
        "args": ["--cli", "mcp", "--workspace", str(tmp_path.resolve())],
    }


def test_process_cannot_rebind_an_imported_workspace(workspace):
    from paper_daily.integration_entry import main

    with pytest.raises(SystemExit) as exc:
        main(["integration", "lists.list", "--workspace", str(workspace / "different")])
    assert exc.value.code == 2 and not (workspace / "different").exists()
