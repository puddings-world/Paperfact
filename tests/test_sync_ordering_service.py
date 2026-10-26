"""Ordering CAS against isolated reference-authority fixtures."""

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from test_sync_reading_state_service import (
    MEMBER,
    member,
    metadata,
    op,
    reading,
    ref,
)
from test_sync_reading_state_service import (
    ready as ready,
)

from paper_daily.sync_ordering import active_items, observed_set
from paper_daily.sync_schema_v2 import membership_id
from paper_daily.sync_service import ReferenceService

PAPER_TWO = "00000000-0000-0000-0000-000000000002"


def graph(service):
    with closing(sqlite3.connect(service.path)) as conn:
        return {
            (kind, identity): json.loads(value)
            for kind, identity, value in conn.execute(
                "SELECT entity_type,entity_id,metadata FROM sync_graph WHERE workspace='workspace'"
            )
        }


def order(service, identity="order-create", *, kind="list_order", **kwargs):
    entity = "list" if kind == "list_order" else "workspace-lists"
    parents = (
        [ref("list", "list", kwargs.pop("list_inc", "list-create"))] if kind == "list_order" else []
    )
    operation = op(identity, kind, entity, {}, parents=parents, **kwargs)
    items = active_items(operation, graph(service))
    payload = {"items": list(reversed(items)), "observed_set": observed_set(operation, items)}
    if kind == "list_order":
        payload["list_id"] = entity
    operation["payload"] = payload
    return operation


def second_member(service, token):
    paper = next(
        e["operation"]
        for e in service.pull(token)
        if e["operation"]["operation_id"] == "paper-create"
    )
    paper = copy.deepcopy(paper)
    paper.update(operation_id="paper-two", incarnation="paper-two", entity_id=PAPER_TWO)
    service.push(token, paper)
    added = member("member-two")
    added["entity_id"] = membership_id("list", PAPER_TWO)
    added["parents"][1] = ref("paper", PAPER_TWO, "paper-two")
    added["payload"]["paper_id"] = PAPER_TWO
    return service.push(token, added)


def change_set(service, token, kind, mutation):
    if mutation == "add":
        if kind == "list_order":
            return second_member(service, token)
        return service.push(
            token, op("list-two", "list", "list-two", {"name": "Second", "note": ""})
        )
    if kind == "list_order":
        removed = service.push(
            token,
            member(
                f"remove-{kind}",
                incarnation="member-create",
                base=3,
                structure=metadata(service, "membership", MEMBER)["structure_revision"],
                action="delete",
                payload={},
            ),
        )
        if mutation == "restore":
            return service.push(token, member("restored-member", base=removed["sequence"]))
    else:
        removed = service.push(
            token,
            op(
                f"remove-{kind}",
                "list",
                "list",
                {},
                incarnation="list-create",
                base=1,
                structure=metadata(service, "list", "list")["structure_revision"],
                action="delete",
            ),
        )
        if mutation == "restore":
            return service.push(
                token,
                op(
                    "restored-list",
                    "list",
                    "list",
                    {"name": "Restored", "note": ""},
                    base=removed["sequence"],
                ),
            )
    return removed


@pytest.mark.parametrize("kind", ["list_order", "workspace_list_order"])
def test_order_receipts_survive_restart_and_enforce_auth_exact_retry(ready, kind):
    service, a, b = ready
    operation = order(service, kind=kind)
    event = service.push(a, operation)
    assert event["outcome"] == "accepted"
    restarted = ReferenceService(service.path)
    assert restarted.push(a, operation) == event
    assert restarted.pull(a)[-1] == event
    with pytest.raises(PermissionError):
        restarted.push(b, operation)
    other = restarted.enroll("other-workspace", "a")
    with pytest.raises(PermissionError):
        restarted.push(other, operation)
    changed = copy.deepcopy(operation)
    changed["payload"]["observed_set"] = "0" * 64
    with pytest.raises(ValueError, match="reused"):
        restarted.push(a, changed)
    restarted.revoke(a)
    with pytest.raises(PermissionError):
        restarted.push(a, operation)


@pytest.mark.parametrize("kind", ["list_order", "workspace_list_order"])
@pytest.mark.parametrize("mutation", ["add", "delete", "restore"])
@pytest.mark.parametrize("order_first", [False, True])
def test_set_lifecycle_races_preserve_order_intent(ready, kind, mutation, order_first):
    service, a, b = ready
    operation = order(service, kind=kind, device="b")
    if order_first:
        event = service.push(b, operation)
    mutation_event = change_set(service, a, kind, mutation)
    assert mutation_event["outcome"] == "accepted"
    if not order_first:
        event = service.push(b, operation)
    assert event["outcome"] == ("accepted" if order_first else "conflict")
    assert event["operation"] == operation
    assert ReferenceService(service.path).pull(a)[event["sequence"] - 1] == event


@pytest.mark.parametrize("mutation", ["rename", "citation", "read"])
def test_metadata_changes_do_not_invalidate_observed_set(ready, mutation):
    service, a, b = ready
    operation = order(service, device="b")
    if mutation == "rename":
        changed = op(
            "rename",
            "list",
            "list",
            {"name": "Renamed", "note": "Background"},
            incarnation="list-create",
            base=1,
        )
    elif mutation == "citation":
        changed = member("cite", incarnation="member-create", base=3)
        changed["payload"]["citation"] = "Updated citation"
    else:
        changed = reading()
        changed["payload"]["state"] = "read"
    assert service.push(a, changed)["outcome"] == "accepted"
    assert service.push(b, operation)["outcome"] == "accepted"


@pytest.mark.parametrize("kind", ["list_order", "workspace_list_order"])
def test_concurrent_reorders_have_one_head_and_preserve_loser(ready, kind):
    service, a, b = ready
    change_set(service, a, kind, "add")
    first = order(service, "first-order", kind=kind)
    second = order(service, "second-order", kind=kind, device="b")
    second["payload"]["items"].reverse()
    with ThreadPoolExecutor(max_workers=2) as pool:
        events = list(pool.map(lambda item: service.push(*item), [(a, first), (b, second)]))
    assert sorted(event["outcome"] for event in events) == ["accepted", "conflict"]
    accepted = next(event for event in events if event["outcome"] == "accepted")
    conflict = next(event for event in events if event["outcome"] == "conflict")
    assert conflict["head"] == accepted["head"]
    assert {event["operation"]["operation_id"] for event in events} == {
        "first-order",
        "second-order",
    }


@pytest.mark.parametrize("order_first", [False, True])
def test_order_and_parent_list_delete_keep_generic_child_protection(ready, order_first):
    service, a, b = ready
    operation = order(service, device="b")
    deletion = op(
        "delete-list",
        "list",
        "list",
        {},
        incarnation="list-create",
        base=1,
        structure=3,
        action="delete",
    )
    first, second = (
        ((b, operation), (a, deletion)) if order_first else ((a, deletion), (b, operation))
    )
    assert service.push(*first)["outcome"] == "accepted"
    assert service.push(*second)["outcome"] == "conflict"


def test_same_device_order_then_parent_delete_uses_structural_dependency(ready):
    service, a, _ = ready
    service.push(a, order(service))
    deletion = op(
        "delete-list",
        "list",
        "list",
        {},
        incarnation="list-create",
        base=1,
        structure=3,
        action="delete",
    )
    deletion["structure_depends_on"] = "order-create"
    assert service.push(a, deletion)["outcome"] == "accepted"


def test_deleted_empty_list_cannot_accept_matching_empty_digest(ready):
    service, a, _ = ready
    change_set(service, a, "list_order", "delete")
    operation = order(service)
    assert operation["payload"]["items"] == []
    change_set(service, a, "workspace_list_order", "delete")
    assert service.push(a, operation)["outcome"] == "conflict"
    assert metadata(service, "list_order", "list") is None


def test_restore_list_requires_new_order_incarnation_and_scope(ready):
    service, a, _ = ready
    first = service.push(a, order(service))
    change_set(service, a, "workspace_list_order", "restore")
    stale = order(service, "stale-order", incarnation="order-create", base=first["sequence"])
    assert service.push(a, stale)["outcome"] == "conflict"
    silent = order(
        service,
        "silent-order",
        incarnation="order-create",
        base=first["sequence"],
        list_inc="restored-list",
    )
    assert service.push(a, silent)["outcome"] == "conflict"
    restored = order(service, "restored-order", base=first["sequence"], list_inc="restored-list")
    assert service.push(a, restored)["outcome"] == "accepted"


def test_transient_add_then_remove_with_identical_active_set_accepts_old_intent(ready):
    service, a, _ = ready
    operation = order(service)
    added = second_member(service, a)
    removal = copy.deepcopy(added["operation"])
    removal.update(
        operation_id="remove-two",
        action="delete",
        payload={},
        base_revision=added["sequence"],
        structure_revision=added["sequence"],
    )
    assert service.push(a, removal)["outcome"] == "accepted"
    assert service.push(a, operation)["outcome"] == "accepted"


def test_offline_create_then_order_needs_no_predicted_server_sequences(tmp_path):
    service = ReferenceService(tmp_path / "authority.sqlite")
    token = service.enroll("workspace", "a")
    creation = op("offline-list", "list", "list", {"name": "Offline", "note": ""})
    order_op = op("offline-order", "workspace_list_order", "workspace-lists", {})
    items = [{"id": "list", "incarnation": "offline-list"}]
    order_op["payload"] = {"items": items, "observed_set": observed_set(order_op, items)}
    service.push(token, creation)
    assert service.push(token, order_op)["outcome"] == "accepted"
    update = copy.deepcopy(order_op)
    update.update(operation_id="offline-order-edit", depends_on="offline-order")
    assert service.push(token, update)["outcome"] == "accepted"


@pytest.mark.parametrize("kind", ["list_order", "workspace_list_order"])
def test_matching_digest_incomplete_order_rejects_without_event_or_graph_changes(ready, kind):
    service, a, _ = ready
    operation = order(service, kind=kind)
    operation["payload"]["items"] = []
    before = service.pull(a), graph(service)
    with pytest.raises(ValueError, match="complete permutation"):
        service.push(a, operation)
    assert (service.pull(a), graph(service)) == before


def test_static_duplicate_rejected_even_if_set_digest_is_stale(ready):
    service, a, _ = ready
    operation = order(service)
    operation["payload"]["items"] *= 2
    operation["payload"]["observed_set"] = "0" * 64
    with pytest.raises(ValueError, match="duplicate"):
        service.push(a, operation)
    assert len(service.pull(a)) == 3


@pytest.mark.parametrize("kind", ["list_order", "workspace_list_order"])
def test_order_reset_delete_and_explicit_restore(ready, kind):
    service, a, _ = ready
    first = service.push(a, order(service, kind=kind))
    reset = copy.deepcopy(first["operation"])
    reset.update(
        operation_id="reset",
        action="delete",
        payload={},
        base_revision=first["sequence"],
        structure_revision=first["sequence"],
    )
    removed = service.push(a, reset)
    assert removed["outcome"] == "accepted"
    stale = order(service, "stale", kind=kind, incarnation="order-create", base=removed["sequence"])
    assert service.push(a, stale)["outcome"] == "conflict"
    restored = order(service, "new-order", kind=kind, base=removed["sequence"])
    assert service.push(a, restored)["outcome"] == "accepted"
