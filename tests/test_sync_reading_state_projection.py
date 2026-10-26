"""DTO2 makes reading-state readiness explicit without altering DTO1."""

import json
import sqlite3

import pytest
from test_sync_reading_state_research import (
    LATER,
    LIST,
    MEMBER,
    PAPER,
    STAMP,
    database,
    paper_payload,
)

from paper_daily.store import SCHEMA
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_projection import read_manifest
from paper_daily.sync_research import prepare, research_writer
from paper_daily.sync_service import ReferenceService


def read(path):
    return read_manifest(path, workspace_id="workspace", schema_version=2)


def state(path):
    return read(path)["lists"][0]["members"][0]["reading_state"]


def connected(path, service_path):
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
    prepare(path, workspace_id="workspace", device_id="device")
    client = SyncClient(
        Journal(path, workspace_id="workspace", device_id="device"), research_writer
    )
    service = ReferenceService(service_path)
    token = service.enroll("workspace", "device")
    for kind, identity, payload in (
        ("paper", PAPER, paper_payload()),
        ("list", LIST, {"name": "Reading", "note": ""}),
        (
            "membership",
            MEMBER,
            {"list_id": LIST, "paper_id": PAPER, "citation": None, "added_at": STAMP},
        ),
    ):
        client.save(client.new_graph_operation(kind, identity, payload))
    client.sync_once(service, token)
    return client, service, token


def change(client, state="read"):
    return client.new_graph_operation(
        "reading_state",
        MEMBER,
        {
            "list_id": LIST,
            "paper_id": PAPER,
            "state": state,
            "delivered_at": STAMP,
            "read_at": LATER if state == "read" else None,
        },
    )


def test_missing_state_is_visible_local_read_only_and_dto1_is_unchanged(tmp_path):
    path = tmp_path / "research.db"
    database(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE list_papers SET state='read',delivered_at=?,read_at=?", (STAMP, LATER))
    before = path.read_bytes()
    projected = read(path)
    member = projected["lists"][0]["members"][0]
    assert member["state"] == "read"
    assert member["reading_state"] == {
        "id": member["id"],
        "state": "read",
        "delivered_at": STAMP,
        "read_at": LATER,
        "revision": None,
        "sync_state": "local",
        "graph": None,
        "editable": False,
        "read_only_reason": "graph_unavailable",
    }
    assert projected["capabilities"]["reading_state_contract_version"] == 2
    assert projected["capabilities"]["sync_bootstrap"] is False
    old = read_manifest(path, workspace_id="workspace")
    assert "reading_state" not in old["lists"][0]["members"][0]
    assert "reading_state_contract_version" not in old["capabilities"]
    assert path.read_bytes() == before


def test_progress_pending_acknowledged_applied_and_reopen(tmp_path):
    path = tmp_path / "research.db"
    client, service, token = connected(path, tmp_path / "service.db")
    assert not state(path)["editable"]
    op = change(client)
    client.save(op)
    pending = state(path)
    assert (pending["state"], pending["read_at"], pending["sync_state"], pending["editable"]) == (
        "read",
        LATER,
        "pending",
        False,
    )
    event = service.push(token, op)
    client.journal.acknowledge(op["operation_id"], event["sequence"])
    assert state(path)["sync_state"] == "awaiting"
    assert state(path)["graph"] is None
    client.receive(service.pull(token, after=client.status()["cursor"]))
    complete = state(path)
    assert complete["editable"] and complete["read_only_reason"] is None
    assert complete["revision"] == event["sequence"]
    assert {ref["kind"] for ref in complete["graph"]["parents"]} == {"membership", "list", "paper"}
    before = path.read_bytes()
    assert state(path) == complete
    assert path.read_bytes() == before
    assert "sync:" not in json.dumps(read(path))


@pytest.mark.parametrize("kind", ["list", "paper", "membership", "reading_state"])
def test_deferred_dependency_never_advertises_readiness(tmp_path, kind):
    path = tmp_path / "research.db"
    client, service, token = connected(path, tmp_path / "service.db")
    client.save(change(client))
    client.sync_once(service, token)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE paperfact_sync_heads SET applied_revision=-1 WHERE entity_type=?", (kind,)
        )
    projected = state(path)
    assert projected["state"] == "read" and projected["read_at"] == LATER
    assert projected["graph"] is None and not projected["editable"]
    assert projected["read_only_reason"] == (
        "graph_unavailable" if kind == "reading_state" else "parent_graph_unavailable"
    )
    if kind == "reading_state":
        assert projected["revision"] is None and projected["sync_state"] == "deferred"


def test_replaced_membership_incarnation_does_not_enable_old_state(tmp_path):
    path = tmp_path / "research.db"
    client, service, token = connected(path, tmp_path / "service.db")
    client.save(change(client))
    client.sync_once(service, token)
    with sqlite3.connect(path) as conn:
        data = json.loads(
            conn.execute(
                "SELECT metadata FROM paperfact_sync_graph WHERE entity_type='membership'"
            ).fetchone()[0]
        )
        data["incarnation"] = "replacement"
        conn.execute(
            "UPDATE paperfact_sync_graph SET metadata=? WHERE entity_type='membership'",
            (json.dumps(data),),
        )
    projected = state(path)
    assert projected["state"] == "read"
    assert projected["graph"] is None and not projected["editable"]
    assert projected["read_only_reason"] == "parent_graph_unavailable"


@pytest.mark.parametrize("problem", ["missing", "different", "legacy_table"])
def test_missing_or_wrong_adapter_projection_marker_disables_writes(tmp_path, problem):
    path = tmp_path / "research.db"
    client, service, token = connected(path, tmp_path / "service.db")
    client.save(change(client))
    client.sync_once(service, token)
    with sqlite3.connect(path) as conn:
        if problem == "missing":
            conn.execute("DELETE FROM research_membership_projection")
        elif problem == "different":
            conn.execute("UPDATE research_membership_projection SET incarnation='older'")
        else:
            conn.execute("DROP TABLE research_membership_projection")
    before = path.read_bytes()
    projected = state(path)
    assert projected["state"] == "read" and projected["read_at"] == LATER
    assert projected["graph"] is None and not projected["editable"]
    assert projected["read_only_reason"] == "membership_projection_unavailable"
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "timestamp", ["invalid", "2026-01-01", "x" * 100000], ids=["invalid", "naive", "oversize"]
)
def test_invalid_or_unbounded_timestamp_is_rejected_without_affecting_dto1(tmp_path, timestamp):
    path = tmp_path / "research.db"
    database(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE list_papers SET delivered_at=?", (timestamp,))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="timestamp"):
        read(path)
    assert read_manifest(path, workspace_id="workspace")["schema_version"] == 1
    assert path.read_bytes() == before
