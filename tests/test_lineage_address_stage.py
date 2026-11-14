"""Typed address helpers preserve optional storage and known corpus identity."""

import copy

import pytest
from test_lineage_content_stage import valid_set as valid_set


def put(body):
    from paper_daily.sync_content import content_id

    scope = dict(kind="paper", id=body["bindings"][0]["paper_id"])
    return dict(
        entity_type="research_content",
        entity_id=content_id(scope, "lineage", body["corpus_id"]),
        action="put",
        content_address=dict(feature="lineage", key=body["corpus_id"]),
        parents=[
            dict(kind="paper", id=b["paper_id"], incarnation="parent-" + str(index))
            for index, b in enumerate(body["bindings"])
        ],
        payload=dict(
            scope=scope, feature="lineage", key=body["corpus_id"], data=dict(body_json=body)
        ),
    )


def state_and_delete(body):
    operation = put(body)
    state = dict(
        incarnation="lineage-head",
        parents=copy.deepcopy(operation["parents"]),
        active=True,
        structure_revision=7,
        content_address=copy.deepcopy(operation["content_address"]),
    )
    deletion = {**copy.deepcopy(operation), "action": "delete", "payload": {}}
    return state, deletion


def test_known_address_cannot_be_stripped_or_reparented_and_inputs_stay_intact(valid_set):
    from paper_daily import lineage_address

    operation = put(valid_set)
    original = copy.deepcopy(operation)
    assert lineage_address.validate(operation)
    assert operation == original
    state, deletion = state_and_delete(valid_set)
    original_state = copy.deepcopy(state)
    assert (
        lineage_address.check_known("research_content", operation["entity_id"], state, deletion)
        is None
    )
    stripped = copy.deepcopy(deletion)
    stripped.pop("content_address")
    with pytest.raises(ValueError, match="address"):
        lineage_address.check_known("research_content", operation["entity_id"], state, stripped)
    assert state == original_state and deletion["content_address"] == original["content_address"]


@pytest.mark.parametrize(
    "change",
    [
        "missing-address",
        "null-address",
        "address-extra",
        "address-domain",
        "wrong-kind",
        "wrong-action",
        "zero-parents",
        "five-parents",
        "duplicate-parent",
        "nonpaper-parent",
        "wrong-entity",
        "wrong-focal",
        "wrong-key",
        "wrong-owner-order",
        "body-local-id",
    ],
)
def test_typed_address_refuses_malformed_scope_without_mutating_operation(valid_set, change):
    from paper_daily import lineage_address

    operation = put(valid_set)
    if change == "missing-address":
        operation.pop("content_address")
    elif change == "null-address":
        operation["content_address"] = None
    elif change == "address-extra":
        operation["content_address"]["authority"] = "sender"
    elif change == "address-domain":
        operation["content_address"]["feature"] = "claims"
    elif change == "wrong-kind":
        operation["entity_type"] = "paper"
    elif change == "wrong-action":
        operation["action"] = "edit"
    elif change == "zero-parents":
        operation["parents"] = []
    elif change == "five-parents":
        operation["parents"] *= 2
    elif change == "duplicate-parent":
        operation["parents"][1] = copy.deepcopy(operation["parents"][0])
    elif change == "nonpaper-parent":
        operation["parents"][1]["kind"] = "list"
    elif change == "wrong-entity":
        operation["entity_id"] = "wrong"
    elif change == "wrong-focal":
        operation["payload"]["scope"]["id"] = operation["parents"][1]["id"]
    elif change == "wrong-key":
        operation["payload"]["key"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    elif change == "wrong-owner-order":
        operation["parents"][1:] = reversed(operation["parents"][1:])
    else:
        operation["payload"]["data"]["body_json"]["bindings"][1]["paper_id"] = "local-alias"
    before = copy.deepcopy(operation)
    with pytest.raises(ValueError):
        lineage_address.validate(operation)
    assert operation == before


def test_known_single_parent_empty_delete_requires_address_and_retains_it(valid_set):
    from paper_daily import claim_content, lineage_address

    body = copy.deepcopy(valid_set)
    report = body["report"]
    report["sources"] = report["sources"][:1]
    report["statements"] = [s for s in report["statements"] if s["stage"] == "current_change"]
    report["coverage"] = dict(
        prior_gap="no_statement", current_change="proposed", later_development="no_statement"
    )
    report["id"] = claim_content.hashed({k: v for k, v in report.items() if k != "id"})
    body["bindings"] = body["bindings"][:1]
    state, deletion = state_and_delete(body)
    assert len(deletion["parents"]) == 1 and deletion["payload"] == {}
    original = copy.deepcopy(state)
    assert (
        lineage_address.retained("research_content", deletion["entity_id"], state, deletion)
        == state
    )
    stripped = copy.deepcopy(deletion)
    stripped.pop("content_address")
    with pytest.raises(ValueError):
        lineage_address.check_known("research_content", deletion["entity_id"], state, stripped)
    assert state == original


def test_same_kind_id_restoration_is_not_reparenting_but_new_paper_id_is(valid_set):
    from paper_daily import lineage_address

    state, deletion = state_and_delete(valid_set)
    for parent in deletion["parents"]:
        parent["incarnation"] += "-restored"
    assert (
        lineage_address.check_known("research_content", deletion["entity_id"], state, deletion)
        is None
    )
    # This helper checks address/parent identity only, not live graph incarnation authority.
    deletion["parents"][1]["id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    with pytest.raises(ValueError, match="different paper parents"):
        lineage_address.check_known("research_content", deletion["entity_id"], state, deletion)


@pytest.mark.parametrize(
    "change",
    [
        "stripped",
        "wrong-key",
        "nonempty-delete",
        "state-extra",
        "state-bool-revision",
        "state-invalid-incarnation",
    ],
)
def test_retained_known_address_rejects_stripping_and_invalid_metadata(valid_set, change):
    from paper_daily import lineage_address

    state, deletion = state_and_delete(valid_set)
    if change == "stripped":
        deletion.pop("content_address")
    elif change == "wrong-key":
        deletion["content_address"]["key"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    elif change == "nonempty-delete":
        deletion["payload"] = {"text": "not empty"}
    elif change == "state-extra":
        state["unregistered"] = True
    elif change == "state-bool-revision":
        state["structure_revision"] = True
    else:
        state["incarnation"] = None
    with pytest.raises(ValueError):
        lineage_address.retained("research_content", deletion["entity_id"], state, deletion)


def test_unknown_untyped_empty_delete_is_not_globally_classified_as_lineage(valid_set):
    from paper_daily import lineage_address

    state, deletion = state_and_delete(valid_set)
    state.pop("content_address")
    deletion.pop("content_address")
    assert lineage_address.validate(deletion) is False
    before = copy.deepcopy(state)
    assert (
        lineage_address.retained("research_content", deletion["entity_id"], state, deletion)
        == before
    )
    assert state == before


def test_importing_helpers_does_not_register_store_producer_routes_or_wire_domain(
    valid_set, tmp_path
):
    import sqlite3
    from contextlib import closing

    from paper_daily import ai_profiles, research_generation, store, sync_content
    from paper_daily.sync_journal import canonical_operation
    from paper_daily.sync_schema_v2 import OPTIONAL

    # The enabled task-routing contract is separate from helper side effects.
    # The fresh-process boundary case checks all registries before/after import.
    assert "lineage" not in sync_content.FEATURES
    assert "lineage" in ai_profiles.TASKS
    assert "paper_lineage_sets" not in research_generation.REGISTRY
    assert "paper_lineage_sets" not in store.SCHEMA and "content_address" not in OPTIONAL
    path = tmp_path / "unactivated.sqlite"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(store.SCHEMA)
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='paper_lineage_sets'"
        ).fetchone()
    _, deletion = state_and_delete(valid_set)
    operation = dict(
        deletion,
        version=2,
        operation_id="unregistered-delete",
        workspace_id="workspace",
        device_id="device",
        base_revision=None,
        depends_on=[],
        incarnation="head",
        structure_revision=None,
    )
    before = path.read_bytes()
    with pytest.raises(ValueError):
        canonical_operation(operation)
    assert path.read_bytes() == before
