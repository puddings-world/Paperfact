"""Closed ordering schema and cross-language observed-set digest fixtures."""

import copy

import pytest
from test_sync_reading_state_service import MEMBER, PAPER, op, ref, roots

from paper_daily.sync_journal import canonical_operation
from paper_daily.sync_ordering import (
    active_items,
    canonical_set_bytes,
    observed_set,
    validate_order,
)


def workspace_order(items=None):
    operation = op("order-create", "workspace_list_order", "workspace-lists", {})
    items = items if items is not None else [{"id": "list", "incarnation": "list-create"}]
    operation["payload"] = {"items": items, "observed_set": observed_set(operation, items)}
    return operation


def test_literal_cross_language_canonical_bytes_and_digest():
    operation = workspace_order(
        [
            {"id": "zeta", "incarnation": "create-z"},
            {"id": "alpha", "incarnation": "create-a"},
        ]
    )
    expected = (
        b'{"domain":"paperfact.sync.ordering","items":[{"id":"alpha","incarnation":"create-a"},'
        b'{"id":"zeta","incarnation":"create-z"}],"scope":{"id":"workspace-lists",'
        b'"incarnation":null,"kind":"workspace_list_order"},"version":1,"workspace_id":"workspace"}'
    )
    assert canonical_set_bytes(operation, operation["payload"]["items"]) == expected
    assert operation["payload"]["observed_set"] == (
        "d85d98550510b7ab1b18f5f129fb74daee0964ce3e4bc90c76b384b7bb77c4b0"
    )
    reversed_items = list(reversed(operation["payload"]["items"]))
    assert canonical_set_bytes(operation, reversed_items) == expected


def test_digest_separates_workspace_scope_and_incarnations_without_mutating_input():
    operation = op("order", "list_order", "list", {}, parents=[roots()[0]])
    items = [{"id": MEMBER, "incarnation": "member-create"}]
    original = copy.deepcopy((operation, items))
    values = {observed_set(operation, items)}
    for field, value in [("workspace_id", "other"), ("entity_id", "other-list")]:
        changed = copy.deepcopy(operation)
        changed[field] = value
        if field == "entity_id":
            changed["parents"][0]["id"] = value
        values.add(observed_set(changed, items))
    changed = copy.deepcopy(operation)
    changed["parents"][0]["incarnation"] = "new-list-incarnation"
    values.add(observed_set(changed, items))
    values.add(observed_set(operation, [{"id": MEMBER, "incarnation": "restored-member"}]))
    assert len(values) == 5
    assert (operation, items) == original


def test_active_membership_set_requires_exact_active_ancestors():
    operation = op("order", "list_order", "list", {}, parents=[roots()[0]])
    graph = {
        ("list", "list"): {"active": True, "incarnation": "list-create", "parents": []},
        ("paper", PAPER): {"active": True, "incarnation": "paper-create", "parents": []},
        ("membership", MEMBER): {
            "active": True,
            "incarnation": "member-create",
            "parents": roots(),
        },
    }
    assert active_items(operation, graph) == [{"id": MEMBER, "incarnation": "member-create"}]
    for parent in [("list", "list"), ("paper", PAPER)]:
        for mutation in ["inactive", "restored", "missing"]:
            changed = copy.deepcopy(graph)
            if mutation == "inactive":
                changed[parent]["active"] = False
            elif mutation == "restored":
                changed[parent]["incarnation"] = "new-incarnation"
            else:
                del changed[parent]
            assert active_items(operation, changed) == []


def test_matching_set_requires_complete_permutation_but_changed_set_is_conflict():
    operation = workspace_order()
    graph = {("list", "list"): {"active": True, "incarnation": "list-create", "parents": []}}
    operation["payload"]["items"] = []
    with pytest.raises(ValueError, match="complete permutation"):
        validate_order(operation, graph)
    graph["list", "list"]["incarnation"] = "new-incarnation"
    assert validate_order(operation, graph) is False


@pytest.mark.parametrize(
    "invalid",
    [
        "duplicate",
        "duplicate-other-incarnation",
        "item-extra",
        "item-missing",
        "item-type",
        "invalid-id",
        "invalid-incarnation",
        "items-type",
        "extra-payload",
        "missing-payload",
        "digest-upper",
        "digest-short",
        "digest-type",
        "wrong-fixed-id",
        "unexpected-parent",
    ],
)
def test_intrinsic_order_schema_rejects_malformed_payload(invalid):
    operation = workspace_order()
    payload = operation["payload"]
    if invalid in ("duplicate", "duplicate-other-incarnation"):
        item = copy.deepcopy(payload["items"][0])
        if invalid.endswith("incarnation"):
            item["incarnation"] = "different"
        payload["items"].append(item)
    elif invalid == "item-extra":
        payload["items"][0]["extra"] = True
    elif invalid == "item-missing":
        del payload["items"][0]["incarnation"]
    elif invalid == "item-type":
        payload["items"][0] = "list"
    elif invalid == "invalid-id":
        payload["items"][0]["id"] = "invalid id"
    elif invalid == "invalid-incarnation":
        payload["items"][0]["incarnation"] = None
    elif invalid == "items-type":
        payload["items"] = {}
    elif invalid == "extra-payload":
        payload["extra"] = True
    elif invalid == "missing-payload":
        del payload["observed_set"]
    elif invalid == "digest-upper":
        payload["observed_set"] = "A" * 64
    elif invalid == "digest-short":
        payload["observed_set"] = "a" * 63
    elif invalid == "digest-type":
        payload["observed_set"] = 0
    elif invalid == "wrong-fixed-id":
        operation["entity_id"] = "other"
    else:
        operation["parents"] = [roots()[0]]
    with pytest.raises(ValueError):
        canonical_operation(operation)


def test_order_item_and_envelope_bounds_are_independent():
    operation = workspace_order(
        [{"id": f"list-{i}", "incarnation": f"create-{i}"} for i in range(2000)]
    )
    canonical_operation(operation)
    operation["payload"]["items"].append({"id": "overflow", "incarnation": "overflow"})
    with pytest.raises(ValueError, match="2000"):
        canonical_operation(operation)
    operation = workspace_order(
        [{"id": f"{i:04d}" + "x" * 124, "incarnation": "y" * 128} for i in range(2000)]
    )
    with pytest.raises(ValueError, match="256 KiB"):
        canonical_operation(operation)


@pytest.mark.parametrize("invalid", ["wrong-list", "wrong-entity", "wrong-parent", "nonuuid-item"])
def test_list_order_identity_is_its_scope_and_items_are_memberships(invalid):
    operation = op("order", "list_order", "list", {}, parents=[roots()[0]])
    items = [{"id": MEMBER, "incarnation": "member-create"}]
    operation["payload"] = {
        "list_id": "list",
        "items": items,
        "observed_set": observed_set(operation, items),
    }
    if invalid == "wrong-list":
        operation["payload"]["list_id"] = "other"
    elif invalid == "wrong-entity":
        operation["entity_id"] = "other"
    elif invalid == "wrong-parent":
        operation["parents"] = [ref("paper", PAPER, "paper-create")]
    else:
        operation["payload"]["items"][0]["id"] = "not-a-uuid"
    with pytest.raises(ValueError):
        canonical_operation(operation)
