"""Late private changes, replacement and untrusted input cannot cross the local boundary."""

import asyncio
import json
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

from test_archived_draft_resumption import client_for
from test_archived_draft_resumption import copied as copied
from test_archived_draft_resumption import decision as decision
from test_archived_draft_resumption import draft_variants as draft_variants
from test_archived_draft_resumption import source as source
from test_note_draft_resumption import recovered_note as recovered_note
from test_note_draft_resumption_edges import stored
from test_note_review_operations import invoke, start
from test_note_review_transports import command

from paper_daily import local_operations as ops
from paper_daily import store, sync_recovery
from paper_daily.research_review import ResearchReview


def test_invalid_source_capabilities_and_values_never_mutate_or_expose_paths(
    recovered_note, monkeypatch
):
    value = recovered_note
    ref = start(value, monkeypatch)
    before = stored(value)
    source = invoke("sources", **ref)["items"][0]["reference"]
    args = dict(
        **ref, source=source, anchor=dict(p0=0, o0=0, p1=0, o1=1), operation_id="invalid-map"
    )
    malformed = [
        ("map", {**args, "source": {"path": str(value["path"])}}),
        ("map", {**args, "source": {**source, "kind": []}}),
        ("map", {**args, "anchor": {**args["anchor"], "selection": {"quote": "Invented text"}}}),
        ("map", {**args, "anchor": {**args["anchor"], "p0": True}}),
        ("map", {**args, "revision": True}),
        ("save", dict(**ref, body="\ud800", operation_id="invalid-text")),
        ("decide", dict(**ref, decision={}, operation_id="invalid-decision")),
        ("page", dict(**ref, source=source, page_index=-1)),
    ]
    for operation, request in malformed:
        result = ops.dispatch("review.notes." + operation, request)
        assert result["error"]["code"] == "invalid_input", result
        assert str(value["path"].parent) not in json.dumps(result)
    unknown = ops.dispatch(
        "review.notes.page", dict(**ref, source={**source, "document_hash": "e" * 64}, page_index=0)
    )
    assert unknown["error"]["code"] == "review_unavailable"
    assert stored(value) == before
    value["review"].close()


def test_held_source_mapping_cannot_replace_a_newer_private_draft(recovered_note, monkeypatch):
    value = recovered_note
    ref = start(value, monkeypatch)
    source = invoke("sources", **ref)["items"][0]["reference"]
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    entered, release = threading.Event(), threading.Event()
    actual = ResearchReview.inspect_note_source_reference

    def held(self, *args, **kwargs):
        inspected = actual(self, *args, **kwargs)
        entered.set()
        assert release.wait(20)
        return inspected

    monkeypatch.setattr(ResearchReview, "inspect_note_source_reference", held)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            ops.dispatch,
            "review.notes.map",
            dict(
                **ref, source=source, anchor=dict(p0=0, o0=0, p1=0, o1=3), operation_id="held-map"
            ),
        )
        try:
            assert entered.wait(20)
            newer = invoke(
                "save", **ref, body="Newer private edit in the app", operation_id="other-window"
            )
        finally:
            release.set()
        result = future.result(timeout=30)
    assert result["error"]["code"] == "conflict"
    read = invoke("read", draft_id=ref["draft_id"])
    assert (
        read["revision"] == newer["revision"]
        and read["retained"]["body"] == "Newer private edit in the app"
    )
    assert ops.inspect_operation("held-map")["state"] == "not_committed"
    assert stored(value) == before and client_for(value["path"]).journal.pending(1000) == pending
    value["review"].close()


def test_native_database_replacement_during_reference_work_never_writes_the_replacement(
    recovered_note, monkeypatch, tmp_path
):
    value = recovered_note
    ref = start(value, monkeypatch)
    source = invoke("sources", **ref)["items"][0]["reference"]
    before = stored(value)
    entered, release = threading.Event(), threading.Event()
    actual = ResearchReview.inspect_note_source_reference

    def held(self, *args, **kwargs):
        inspected = actual(self, *args, **kwargs)
        entered.set()
        assert release.wait(20)
        return inspected

    monkeypatch.setattr(ResearchReview, "inspect_note_source_reference", held)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            ops.dispatch,
            "review.notes.map",
            dict(
                **ref,
                source=source,
                anchor=dict(p0=0, o0=0, p1=0, o1=3),
                operation_id="replaced-map",
            ),
        )
        try:
            assert entered.wait(20)
            replacement = tmp_path / "fresh-native.sqlite"
            with (
                closing(sqlite3.connect(value["path"])) as original,
                closing(sqlite3.connect(replacement)) as target,
            ):
                original.backup(target)
            os.replace(replacement, value["path"])
            with closing(sqlite3.connect(value["path"].as_uri() + "?mode=ro", uri=True)) as conn:
                replacement_before = tuple(conn.iterdump())
        finally:
            release.set()
        result = future.result(timeout=30)
    assert result["error"]["code"] == "review_unavailable"
    assert stored(value) == before
    unavailable = ops.dispatch("review.notes.read", dict(draft_id=ref["draft_id"]))
    assert unavailable["error"]["code"] == "review_unavailable"
    assert ops.inspect_operation("replaced-map")["state"] == "not_committed"
    with closing(sqlite3.connect(value["path"].as_uri() + "?mode=ro", uri=True)) as conn:
        assert tuple(conn.iterdump()) == replacement_before
    value["review"].close()


def test_recovery_workspace_stays_read_only_through_real_cli_and_shared_dispatch(
    recovered_note, monkeypatch, tmp_path
):
    value = recovered_note
    output = tmp_path / "api-readonly"
    sync_recovery.restore_detached(tmp_path / "note-source.zip", output)
    readonly = dict(path=output / "papers.db")
    before = readonly["path"].read_bytes()
    listed = command(readonly, "list", {})
    assert listed["ok"] and len(listed["result"]["items"]) == 2 and not listed["result"]["editable"]
    monkeypatch.setattr(store, "DB_PATH", readonly["path"])
    assert ops.dispatch("lists.list", {})["ok"]
    rejected = ops.dispatch("imports.propose", dict(name="No mutation", papers=[{"title": "Test"}]))
    assert rejected["error"]["code"] == "read_only_workspace"
    assert readonly["path"].read_bytes() == before

    import sys
    from pathlib import Path

    from mcp import Client, StdioServerParameters

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "paper_daily", "mcp", "--workspace", str(output)],
        env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )

    async def exercise_readonly_mcp():
        async with Client(params) as client:
            response = await client.call_tool("review.notes.list", {})
            assert not response.is_error, response.content
            result = response.structured_content["result"]
            assert len(result["items"]) == 2 and not result["editable"]
            rejected = await client.call_tool(
                "imports.propose", dict(name="No mutation", papers=[{"title": "Test"}])
            )
            assert rejected.is_error and "read_only_workspace" in str(rejected.content)

    asyncio.run(exercise_readonly_mcp())
    assert readonly["path"].read_bytes() == before
    value["review"].close()
