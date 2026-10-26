"""DTO2 ordering displays local permutations and truthful graph readiness."""

import json
import sqlite3

import pytest
from test_sync_ordering_research import LIST, seeded
from test_sync_reading_state_research import paper_payload

from paper_daily import sync_projection
from paper_daily.store import SCHEMA
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_operations import ResearchOperations
from paper_daily.sync_projection import read_manifest
from paper_daily.sync_research import prepare, research_order_writer, research_writer
from paper_daily.sync_service import ReferenceService


def read(path):
    return read_manifest(path, workspace_id="workspace", schema_version=2)


def connected(tmp_path):
    path = tmp_path / "research.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
    prepare(path, workspace_id="workspace", device_id="device")
    client = SyncClient(
        Journal(path, workspace_id="workspace", device_id="device"),
        research_writer,
        order_writer=research_order_writer,
    )
    actions = ResearchOperations(client)
    first = actions.create_list(
        "First",
        [{"paper": dict(paper_payload(), title=name)} for name in ("A", "B")],
        request_id="first",
    )
    second = actions.create_list("Second", [], request_id="second")
    service = ReferenceService(tmp_path / "service.db")
    token = service.enroll("workspace", "device")
    client.sync_once(service, token)
    return path, client, actions, first, second, service, token


def reorder(actions, first, second):
    ids = [value["paper_id"] for value in reversed(first["papers"])]
    actions.reorder_papers(first["list_id"], ids, request_id="papers")
    actions.reorder_lists([second["list_id"], first["list_id"]], request_id="lists")
    return ids


def test_local_order_is_displayed_without_claiming_missing_order_graph_or_changing_dto1(tmp_path):
    path = tmp_path / "research.db"
    seeded(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO kv VALUES('lists.order',?)", (json.dumps(["other", LIST]),))
    before = path.read_bytes()
    manifest = read(path)
    assert [value["id"] for value in manifest["lists"]] == ["other", LIST]
    unavailable = {
        "revision": None,
        "sync_state": "local",
        "graph": None,
        "editable": False,
        "read_only_reason": "graph_unavailable",
    }
    assert manifest["list_order"] == unavailable
    assert all(value["order"] == unavailable for value in manifest["lists"])
    assert manifest["capabilities"]["ordering_contract_version"] == 2
    assert "do-not-export" not in json.dumps(manifest)
    legacy = read_manifest(path, workspace_id="workspace")
    assert "list_order" not in legacy and "order" not in legacy["lists"][0]
    assert "ordering_contract_version" not in legacy["capabilities"]
    assert path.read_bytes() == before


def test_order_pending_then_received_preserves_display_and_exposes_exact_ready_scope(tmp_path):
    path, client, actions, first, second, service, token = connected(tmp_path)
    desired = reorder(actions, first, second)
    pending = read(path)
    assert pending["list_order"]["sync_state"] == "pending"
    assert not pending["list_order"]["editable"]
    assert pending["lists"][1]["order"]["sync_state"] == "pending"
    assert [member["paper_id"] for member in pending["lists"][1]["members"]] == desired
    client.sync_once(service, token)
    final = read(path)
    assert [value["id"] for value in final["lists"]] == [second["list_id"], first["list_id"]]
    assert final["list_order"]["editable"] and final["list_order"]["graph"]["parents"] == []
    assert final["list_order"]["read_only_reason"] is None
    order = final["lists"][1]["order"]
    assert order["editable"] and order["sync_state"] == "synced"
    assert order["graph"]["parents"] == [
        {
            "kind": "list",
            "id": first["list_id"],
            "incarnation": final["lists"][1]["graph"]["incarnation"],
        }
    ]
    assert [member["paper_id"] for member in final["lists"][1]["members"]] == desired
    before = path.read_bytes()
    assert read(path) == final and path.read_bytes() == before


@pytest.mark.parametrize(
    "problem",
    ["state_deferred", "parent_deferred", "member_deferred", "root_marker", "member_marker"],
)
def test_unready_scope_or_projection_does_not_advertise_order_editability(tmp_path, problem):
    path, client, actions, first, second, service, token = connected(tmp_path)
    desired = reorder(actions, first, second)
    client.sync_once(service, token)
    with sqlite3.connect(path) as conn:
        if problem.endswith("deferred"):
            kind = {
                "state_deferred": "list_order",
                "parent_deferred": "list",
                "member_deferred": "membership",
            }[problem]
            conn.execute(
                "UPDATE paperfact_sync_heads SET applied_revision=-1 WHERE entity_type=?", (kind,)
            )
        elif problem == "root_marker":
            conn.execute("DELETE FROM research_list_projection")
        else:
            conn.execute("DELETE FROM research_membership_projection")
    manifest = read(path)
    collection = next(value for value in manifest["lists"] if value["id"] == first["list_id"])
    assert [member["paper_id"] for member in collection["members"]] == desired
    assert not collection["order"]["editable"] and collection["order"]["graph"] is None
    expected = {
        "state_deferred": "graph_unavailable",
        "parent_deferred": "parent_graph_unavailable",
        "member_deferred": "item_graph_unavailable",
        "root_marker": "projection_unavailable",
        "member_marker": "projection_unavailable",
    }
    assert collection["order"]["read_only_reason"] == expected[problem]


def test_removed_order_ids_never_hide_current_local_lists(tmp_path):
    path = tmp_path / "research.db"
    seeded(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO kv VALUES('lists.order',?)", (json.dumps(["removed", "other"]),))
    assert [value["id"] for value in read(path)["lists"]] == ["other", LIST]


@pytest.mark.parametrize(
    "raw",
    ["not-json", '["reading","reading"]', '"' + "x" * 300000 + '"'],
    ids=["invalid", "duplicate", "oversize"],
)
def test_invalid_workspace_display_preference_is_bounded_and_never_repaired(tmp_path, raw):
    path = tmp_path / "research.db"
    seeded(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO kv VALUES('lists.order',?)", (raw,))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="workspace list order"):
        read(path)
    assert read_manifest(path, workspace_id="workspace")["schema_version"] == 1
    assert path.read_bytes() == before


def test_order_and_cursor_are_from_the_same_read_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "research.db"
    seeded(path)
    SyncClient(Journal(path, workspace_id="workspace", device_id="device"), research_writer)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("INSERT INTO kv VALUES('lists.order',?)", (json.dumps([LIST, "other"]),))
    original, changed = sqlite3.connect, False

    def connect(*args, **kwargs):
        conn = original(*args, **kwargs)

        def trace(statement):
            nonlocal changed
            if not changed and "FROM kv WHERE key='lists.order'" in statement:
                changed = True
                with original(path) as writer:
                    writer.execute(
                        "UPDATE kv SET value=? WHERE key='lists.order'",
                        (json.dumps(["other", LIST]),),
                    )
                    writer.execute("UPDATE paperfact_sync_cursor SET sequence=1")

        conn.set_trace_callback(trace)
        return conn

    monkeypatch.setattr(sync_projection.sqlite3, "connect", connect)
    before = read(path)
    assert changed and before["cursor"] == 0
    assert [value["id"] for value in before["lists"]] == [LIST, "other"]
    after = read(path)
    assert after["cursor"] == 1
    assert [value["id"] for value in after["lists"]] == ["other", LIST]
