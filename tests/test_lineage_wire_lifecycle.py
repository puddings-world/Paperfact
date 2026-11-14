"""Ordered multi-paper scope is stable across pending/accepted lifecycles."""

import copy
import json
from uuid import uuid4

import pytest
from test_lineage_content_stage import valid_set as valid_set
from test_lineage_wire import operation, payload

from paper_daily import lineage_content, lineage_sets, lineage_wire, sync_graph
from paper_daily.sync_client import SyncClient


def graph(value):
    entities = {
        ("paper", p["id"]): dict(
            incarnation=p["incarnation"], parents=[], active=True, structure_revision=0
        )
        for p in value["parents"]
    }

    def get(kind, identity):
        return copy.deepcopy(entities.get((kind, identity)))

    def put(kind, identity, state):
        entities[kind, identity] = copy.deepcopy(state)

    sync_graph.apply_accepted(get, put, value, 1)
    return entities, get, put


def test_optimistic_put_delete_keep_address_and_invalid_retry_changes_nothing(valid_set):
    value = operation(valid_set)
    state = ({}, {}, {})
    SyncClient._overlay_optimistic(state, value)
    assert (
        state[0]["research_content", value["entity_id"]]["content_address"]
        == (value["content_address"])
    )
    deleted = dict(value, operation_id="delete", action="delete", payload={})
    SyncClient._overlay_optimistic(state, deleted)
    assert not state[0]["research_content", value["entity_id"]]["active"]
    before = copy.deepcopy(state)
    stripped = copy.deepcopy(deleted)
    stripped.pop("content_address")
    with pytest.raises(ValueError, match="address"):
        SyncClient._overlay_optimistic(state, stripped)
    assert state == before


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("change", ["deleted", "recreated"])
def test_every_selected_parent_lifetime_participates_in_conflict_check(valid_set, index, change):
    value = operation(valid_set)
    entities, get, _put = graph(value)
    key = ("paper", value["parents"][index]["id"])
    if change == "deleted":
        entities[key]["active"] = False
    else:
        entities[key]["incarnation"] = "new-parent-epoch"
    edit = dict(value, operation_id="edit")
    before = copy.deepcopy(entities)
    assert not sync_graph.check_preconditions(get, lambda _identity: None, edit)
    assert entities == before


def test_known_empty_delete_cannot_reorder_selected_corpus_under_same_address(valid_set):
    value = operation(valid_set)
    entities, get, _put = graph(value)
    deleted = copy.deepcopy(value)
    deleted.update(action="delete", payload={}, operation_id="delete", structure_revision=1)
    deleted["parents"][1:] = reversed(deleted["parents"][1:])
    before = copy.deepcopy(entities)
    with pytest.raises(ValueError, match="parents"):
        sync_graph.check_preconditions(get, lambda _identity: None, deleted)
    assert entities == before


def test_missing_original_peer_still_has_parent_but_never_an_invented_file(valid_set):
    body = copy.deepcopy(valid_set)
    report = body["report"]
    source = dict(
        identity=dict(title="Unavailable selected work", doi=None, arxiv_id=None, s2_id=None),
        identity_authority="selected_workspace_record",
        availability="unavailable",
        document_hash=None,
        page_count=None,
    )
    source["id"] = lineage_content.source_id(source["identity"], None)
    report["sources"].append(source)
    body["bindings"].append(dict(source_id=source["id"], paper_id=str(uuid4())))
    report["id"] = lineage_content.hashed({k: v for k, v in report.items() if k != "id"})
    value = operation(body)
    assert len(json.loads(lineage_wire.canonical_operation(value))["parents"]) == 4
    assert len(lineage_wire.required_originals(value["payload"])) == 3
    assert (
        lineage_wire.parent_identities(value["payload"])[-1][1]
        == (body["bindings"][-1]["paper_id"])
    )
    assert lineage_sets.validate(body, portable=True) == body


def test_utf8_inline_limit_refuses_instead_of_truncating_record(valid_set, monkeypatch):
    content = payload(valid_set)
    amount = len(json.dumps(content, ensure_ascii=False).encode())
    monkeypatch.setattr(lineage_wire, "MAX_INLINE_BYTES", amount)
    before = copy.deepcopy(content)
    assert lineage_wire.validate_payload(content) == before
    monkeypatch.setattr(lineage_wire, "MAX_INLINE_BYTES", amount - 1)
    with pytest.raises(ValueError, match="inline"):
        lineage_wire.validate_payload(content)
    assert content == before
