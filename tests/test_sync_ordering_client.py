"""Order convergence with synthetic writers and an isolated reference peer."""

import json
import sqlite3
from uuid import NAMESPACE_URL, uuid5

import pytest

from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_ordering import ORDER_KINDS
from paper_daily.sync_schema_v2 import membership_id
from paper_daily.sync_service import ReferenceService


def order_writer(conn, scope, items):
    assert set(scope) == {"kind", "id", "incarnation", "workspace_id"}
    conn.execute(
        "INSERT INTO research_orders VALUES(?,?,?) ON CONFLICT(kind,id) "
        "DO UPDATE SET items=excluded.items",
        (scope["kind"], scope["id"], json.dumps(items)),
    )


def writer(conn, op):
    kind, identity = op["entity_type"], op["entity_id"]
    if kind in ORDER_KINDS:
        if op["action"] == "put":
            order_writer(
                conn,
                {
                    "kind": kind,
                    "id": identity,
                    "incarnation": op["parents"][0]["incarnation"] if op["parents"] else None,
                    "workspace_id": op["workspace_id"],
                },
                op["payload"]["items"],
            )
        return
    if op["action"] == "delete":
        conn.execute("DELETE FROM research WHERE kind=? AND id=?", (kind, identity))
        return
    conn.execute(
        "INSERT INTO research VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET op=excluded.op",
        (kind, identity, json.dumps(op)),
    )


def client(path, device, *, callback=order_writer):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS research(kind,id,op,PRIMARY KEY(kind,id))")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_orders(kind,id,items,PRIMARY KEY(kind,id))"
        )
    return SyncClient(
        Journal(path, workspace_id="workspace", device_id=device), writer, order_writer=callback
    )


def order(side, kind="list_order", identity="reading"):
    with sqlite3.connect(side.journal.path) as conn:
        row = conn.execute(
            "SELECT items FROM research_orders WHERE kind=? AND id=?", (kind, identity)
        ).fetchone()
    return [item["id"] for item in json.loads(row[0])] if row else None


def save(side, kind, identity, payload, **kwargs):
    op = side.new_graph_operation(kind, identity, payload, **kwargs)
    side.save(op)
    return op


def add(side, index, *, list_id="reading", restore=False):
    paper_id = str(uuid5(NAMESPACE_URL, "order-fixture-" + str(index)))
    body = {
        "title": "Synthetic " + str(index),
        "authors": [],
        "year": 2026,
        **{
            key: None
            for key in (
                "venue",
                "abstract",
                "doi",
                "arxiv_id",
                "s2_id",
                "page_url",
                "pdf_url",
                "source",
            )
        },
    }
    if not restore:
        save(side, "paper", paper_id, body)
    return save(
        side,
        "membership",
        membership_id(list_id, paper_id),
        {
            "list_id": list_id,
            "paper_id": paper_id,
            "citation": None,
            "added_at": "2026-10-26T00:00:00Z",
        },
        restore=restore,
    )


@pytest.fixture
def pair(tmp_path):
    service = ReferenceService(tmp_path / "service.db")
    a, b = client(tmp_path / "a.db", "a"), client(tmp_path / "b.db", "b")
    ta, tb = service.enroll("workspace", "a"), service.enroll("workspace", "b")
    save(a, "list", "reading", {"name": "Reading", "note": ""})
    items = [add(a, index) for index in range(3)]
    return service, a, b, ta, tb, items


def sync(pair):
    server, a, b, ta, tb, _ = pair
    a.sync_once(server, ta)
    b.sync_once(server, tb)


@pytest.mark.parametrize("phase", ["pending", "acknowledged", "received"])
def test_builder_and_empty_peer_preserve_offline_permutation(pair, phase):
    server, a, b, ta, _, members = pair
    if phase == "acknowledged":
        for op in a.journal.pending():
            event = server.push(ta, op)
            a.journal.acknowledge(op["operation_id"], event["sequence"])
    elif phase == "received":
        sync(pair)
    desired = [op["entity_id"] for op in reversed(members)]
    a.save(a.new_order_operation("list_order", "reading", desired))
    sync(pair)
    assert order(a) == order(b) == desired
    assert b.status()["deferred"] == 0


def test_default_creation_order_ignores_late_metadata_and_unchanged_receives(pair):
    server, a, b, ta, tb, members = pair
    body = dict(members[0]["payload"], citation="New citation")
    save(a, "membership", members[0]["entity_id"], body)
    sync(pair)
    assert order(a) == order(b) == [op["entity_id"] for op in members]
    calls = []
    original = b.order_writer
    b.order_writer = lambda conn, scope, items: (calls.append(scope), original(conn, scope, items))
    save(a, "membership", members[1]["entity_id"], dict(members[1]["payload"], citation="Later"))
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert calls == []


def test_same_order_head_filters_old_incarnation_and_appends_restore(pair):
    server, a, b, ta, tb, members = pair
    desired = [op["entity_id"] for op in members]
    a.save(a.new_order_operation("list_order", "reading", desired))
    sync(pair)
    save(a, "membership", desired[0], {}, action="delete")
    a.sync_once(server, ta)
    restored = add(a, 0, restore=True)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert restored["incarnation"] != members[0]["incarnation"]
    assert order(a) == order(b) == desired[1:] + desired[:1]


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "stale_set", "parent"])
def test_invalid_raw_or_builder_order_does_not_mutate_local_rows(pair, mutation):
    _, a, _, _, _, members = pair
    desired = [op["entity_id"] for op in members]
    before = a.journal.pending()
    if mutation in ("missing", "duplicate"):
        bad = desired[:-1] if mutation == "missing" else desired + desired[:1]
        with pytest.raises(ValueError, match="permutation"):
            a.new_order_operation("list_order", "reading", bad)
    else:
        op = a.new_order_operation("list_order", "reading", desired)
        if mutation == "parent":
            op["parents"][0]["incarnation"] = "wrong"
        else:
            op["payload"]["observed_set"] = "0" * 64
        with pytest.raises(ValueError):
            a.save(op)
    assert a.journal.pending() == before
    assert order(a) is None


def test_pending_reorder_and_ack_gap_prevent_remote_projection(pair):
    server, a, b, ta, tb, members = pair
    sync(pair)
    desired = [op["entity_id"] for op in reversed(members)]
    op = a.new_order_operation("list_order", "reading", desired)
    a.save(op)
    save(b, "list", "reading", {"name": "Renamed", "note": ""})
    b.sync_once(server, tb)
    a.receive(server.pull(ta, after=a.status()["cursor"]))
    assert order(a) == desired
    event = server.push(ta, op)
    a.journal.acknowledge(op["operation_id"], event["sequence"])
    a.receive([])
    assert order(a) == desired
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert order(b) == desired


def test_order_callback_failure_rolls_back_cursor_history_and_content(pair):
    server, a, b, ta, tb, members = pair
    desired = [op["entity_id"] for op in reversed(members)]
    a.save(a.new_order_operation("list_order", "reading", desired))
    a.sync_once(server, ta)

    def fail(conn, scope, items):
        order_writer(conn, scope, items)
        raise RuntimeError("projection failed")

    b.order_writer = fail
    with pytest.raises(RuntimeError, match="projection failed"):
        b.sync_once(server, tb)
    assert b.status()["cursor"] == 0
    assert b.history() == []
    assert order(b) is None
    b.order_writer = order_writer
    b.sync_once(server, tb)
    assert order(b) == desired


def test_missing_callback_defers_explicit_order_and_can_retry(pair):
    server, a, b, _, tb, members = pair
    desired = [op["entity_id"] for op in reversed(members)]
    a.save(a.new_order_operation("list_order", "reading", desired))
    b.order_writer = None
    sync(pair)
    assert order(b) is None
    assert any(row["reason"] == "order_writer_unavailable" for row in b.deferred_reasons())
    b.order_writer = order_writer
    b.sync_once(server, tb)
    assert order(b) == desired
    assert b.status()["deferred"] == 0


def test_concurrent_reorders_preserve_conflict_and_canonical_order(pair):
    server, a, b, ta, tb, members = pair
    sync(pair)
    first = [op["entity_id"] for op in reversed(members)]
    second = first[1:] + first[:1]
    a.save(a.new_order_operation("list_order", "reading", first))
    b.save(b.new_order_operation("list_order", "reading", second))
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    a.sync_once(server, ta)
    assert order(a) == order(b) == first
    assert b.status()["conflicts"] == 1
    conflict = b.history(conflicts_only=True)[0]
    b.resolve_conflict(conflict["sequence"], choice="incoming")
    b.sync_once(server, tb)
    a.sync_once(server, ta)
    assert order(a) == order(b) == second


def test_stale_set_resolution_requires_fresh_complete_payload(pair):
    server, a, b, ta, tb, members = pair
    sync(pair)
    desired = [op["entity_id"] for op in reversed(members)]
    b.save(b.new_order_operation("list_order", "reading", desired))
    add(a, 4)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    conflict = b.history(conflicts_only=True)[0]
    before = b.journal.pending()
    with pytest.raises(ValueError, match="set changed"):
        b.resolve_conflict(conflict["sequence"])
    assert b.journal.pending() == before


def test_same_transaction_builder_observes_own_uncommitted_creations(pair):
    _, a, _, _, _, members = pair
    desired = [op["entity_id"] for op in reversed(members)]
    with a.journal.transaction() as conn:
        root = a.new_graph_operation_in(conn, "list", "extra", {"name": "Extra", "note": ""})
        a.journal.apply_in(conn, root, writer)
        op = a.new_order_operation_in(
            conn, "workspace_list_order", "workspace-lists", ["extra", "reading"]
        )
        a.journal.apply_in(conn, op, writer)
        child = a.new_order_operation_in(conn, "list_order", "reading", desired)
        a.journal.apply_in(conn, child, writer)
    assert order(a, "workspace_list_order", "workspace-lists") == ["extra", "reading"]
    assert order(a) == desired


def projection(side, kind="list_order", identity="reading"):
    with sqlite3.connect(side.journal.path) as conn:
        row = conn.execute(
            "SELECT active,operation FROM paperfact_sync_graph_projection "
            "WHERE entity_type=? AND entity_id=?",
            (kind, identity),
        ).fetchone()
    return bool(row[0]), json.loads(row[1])


def test_deleted_list_order_stays_inactive_after_root_restore(pair):
    server, a, b, ta, tb, members = pair
    desired = [op["entity_id"] for op in reversed(members)]
    original = a.new_order_operation("list_order", "reading", desired)
    a.save(original)
    sync(pair)
    save(a, "list", "reading", {}, action="delete")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert projection(a) == projection(b) == (False, original)
    save(a, "list", "reading", {"name": "Restored", "note": ""}, restore=True)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert order(a) == order(b) == []
    assert projection(a) == projection(b) == (False, original)
    for side in (a, b):
        assert side.deferred_reasons() == [
            {"entity_type": "membership", "entity_id": identity, "reason": "parent_incarnation"}
            for identity in sorted(op["entity_id"] for op in members)
        ]


def test_rejected_first_order_is_inactive_and_preserves_original_in_history(pair):
    server, a, b, ta, tb, members = pair
    sync(pair)
    original = b.new_order_operation(
        "list_order", "reading", [op["entity_id"] for op in reversed(members)]
    )
    b.save(original)
    added = add(a, 9)
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert projection(b) == (False, original)
    assert order(b) == [op["entity_id"] for op in members] + [added["entity_id"]]
    assert b.history(conflicts_only=True)[0]["operation"] == original


def test_accepted_event_with_forged_order_digest_rolls_back_receive(pair):
    server, a, b, ta, tb, members = pair
    sync(pair)
    a.save(
        a.new_order_operation(
            "list_order", "reading", [op["entity_id"] for op in reversed(members)]
        )
    )
    a.sync_once(server, ta)
    events = server.pull(tb, after=b.status()["cursor"])
    events[0]["operation"]["payload"]["observed_set"] = "0" * 64
    events[0]["head"]["operation"]["payload"]["observed_set"] = "0" * 64
    before = b.status()
    with pytest.raises(ValueError, match="observed set"):
        b.receive(events)
    assert b.status() == before
    assert order(b) == [op["entity_id"] for op in members]


@pytest.mark.parametrize("kind", ["list", "membership"])
def test_pending_lifecycle_defers_order_and_unchanged_head_reprojects_after_conflict(pair, kind):
    server, a, b, ta, tb, members = pair
    sync(pair)
    original = [op["entity_id"] for op in reversed(members)]
    a.save(a.new_order_operation("list_order", "reading", original))
    sync(pair)
    identity = "reading" if kind == "list" else members[0]["entity_id"]
    save(b, kind, identity, {}, action="delete")
    payload = (
        {"name": "Concurrent rename", "note": ""}
        if kind == "list"
        else dict(members[0]["payload"], citation="Concurrent citation")
    )
    save(a, kind, identity, payload)
    a.sync_once(server, ta)
    b.receive(server.pull(tb, after=b.status()["cursor"]))
    assert order(b) == original
    assert b.status()["pending"] == 1
    b.sync_once(server, tb)
    assert b.status()["conflicts"] == 1
    assert order(b) == original


def test_other_list_metadata_does_not_invoke_unrelated_scope_callback(pair):
    server, a, b, ta, tb, _ = pair
    save(a, "list", "other", {"name": "Other", "note": ""})
    sync(pair)
    calls = []
    original = b.order_writer
    b.order_writer = lambda conn, scope, items: (calls.append(scope), original(conn, scope, items))
    add(a, 12, list_id="other")
    a.sync_once(server, ta)
    b.sync_once(server, tb)
    assert [scope["id"] for scope in calls] == ["other"]
