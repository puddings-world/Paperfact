"""Staged multi-paper wire data keeps exact owners without activating live sync."""

import copy
import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_lineage_content_stage import valid_set as valid_set
from test_lineage_sets_stage import local_body, mapping_database, row

from paper_daily import lineage_content, lineage_sets, lineage_wire, sync_content
from paper_daily.sync_journal import canonical_operation as active_operation


def payload(body):
    return dict(
        scope=dict(kind="paper", id=body["bindings"][0]["paper_id"]),
        feature="lineage",
        key=body["corpus_id"],
        source_document_hash=body["report"]["sources"][0]["document_hash"],
        data=dict(
            body_json=body,
            source_hash=lineage_sets.source_hash(body),
            document_hash=body["report"]["sources"][0]["document_hash"],
            written_at="2026-11-13T00:00:00+00:00",
        ),
    )


def operation(body):
    content = payload(body)
    return dict(
        version=2,
        operation_id="lineage-new",
        workspace_id="workspace",
        device_id="device",
        entity_type="research_content",
        entity_id=sync_content.content_id(content["scope"], "lineage", body["corpus_id"]),
        action="put",
        base_revision=0,
        depends_on=None,
        incarnation="lineage-new",
        structure_revision=0,
        parents=[
            dict(kind="paper", id=b["paper_id"], incarnation="parent-" + str(i))
            for i, b in enumerate(body["bindings"])
        ],
        payload=content,
        content_address=dict(feature="lineage", key=body["corpus_id"]),
    )


def test_real_registered_sender_receiver_roundtrip_preserves_report_and_writes_nothing(
    valid_set, tmp_path
):
    path = tmp_path / "research.sqlite"
    mapping_database(path, valid_set)
    local = row(local_body(valid_set))
    before = path.read_bytes()
    original = copy.deepcopy(local)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        outgoing = lineage_wire.encode_row(conn, local)
        incoming = lineage_wire.decode_row(conn, outgoing)
        assert incoming == local and outgoing["data"]["body_json"] == valid_set
        assert conn.total_changes == 0 and not conn.in_transaction
    assert local == original and path.read_bytes() == before
    value = operation(valid_set)
    value["payload"] = outgoing
    encoded = lineage_wire.canonical_operation(value)
    assert json.loads(encoded)["payload"] == outgoing
    assert all(
        s["requirements"]["semantic_validation"] == "not_performed"
        for s in outgoing["data"]["body_json"]["report"]["statements"]
    )
    with pytest.raises(ValueError):
        active_operation(json.loads(encoded))
    assert "lineage" not in sync_content.FEATURES


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "wrong-scope",
        "wrong-key",
        "local-owner",
        "source",
        "source-hash",
        "data-extra",
        "date",
        "source-document",
        "secret",
    ],
)
def test_wire_payload_refuses_mismatched_body_metadata_without_mutation(valid_set, change):
    data = payload(valid_set)
    if change == "extra":
        data["account"] = "untrusted"
    elif change == "wrong-scope":
        data["scope"]["id"] = valid_set["bindings"][1]["paper_id"]
    elif change == "wrong-key":
        data["key"] = str(uuid4())
    elif change == "local-owner":
        data["data"]["body_json"]["bindings"][1]["paper_id"] = "local-id"
    elif change == "source":
        data["source_document_hash"] = "a" * 64
    elif change == "source-hash":
        data["data"]["source_hash"] = "b" * 64
    elif change == "data-extra":
        data["data"]["unknown"] = "untrusted"
    elif change == "date":
        data["data"]["written_at"] = "2026-11-13"
    elif change == "source-document":
        data["data"]["document_hash"] = "b" * 64
    else:
        data["data"]["body_json"]["generation"]["api_key"] = "fixture-not-a-credential"
    before = copy.deepcopy(data)
    with pytest.raises(ValueError):
        lineage_wire.validate_payload(data)
    assert data == before


@pytest.mark.parametrize(
    "change",
    [
        "no-address",
        "address-null",
        "extra",
        "bool-version",
        "negative-revision",
        "self-dependency",
        "self-resolution",
        "self-structure",
        "parents-order",
        "parents-duplicate",
        "parents-empty",
        "parent-incarnation",
        "delete-content",
        "entity",
    ],
)
def test_full_staged_envelope_keeps_existing_header_and_typed_corpus_limits(valid_set, change):
    value = operation(valid_set)
    if change == "no-address":
        value.pop("content_address")
    elif change == "address-null":
        value["content_address"] = None
    elif change == "extra":
        value["unknown"] = True
    elif change == "bool-version":
        value["version"] = True
    elif change == "negative-revision":
        value["base_revision"] = -1
    elif change == "self-dependency":
        value["depends_on"] = value["operation_id"]
    elif change == "self-resolution":
        value["resolution_of"] = value["operation_id"]
    elif change == "self-structure":
        value["structure_depends_on"] = value["operation_id"]
    elif change == "parents-order":
        value["parents"][1:] = reversed(value["parents"][1:])
    elif change == "parents-duplicate":
        value["parents"][1] = copy.deepcopy(value["parents"][0])
    elif change == "parents-empty":
        value["parents"] = []
    elif change == "parent-incarnation":
        value["parents"][0]["incarnation"] = "invalid space"
    elif change == "delete-content":
        value["action"] = "delete"
    else:
        value["entity_id"] = str(uuid4())
    before = copy.deepcopy(value)
    with pytest.raises(ValueError):
        lineage_wire.canonical_operation(value)
    assert value == before


@pytest.mark.parametrize("direction", ["send", "receive"])
def test_missing_registered_peer_refuses_whole_conversion_without_minting(
    valid_set, tmp_path, direction
):
    path = tmp_path / "research.sqlite"
    mapping_database(path, valid_set)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("DELETE FROM research_paper_identity WHERE local_id='local-1'")
    before = path.read_bytes()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        with pytest.raises(ValueError, match="registered"):
            if direction == "send":
                lineage_wire.encode_row(conn, row(local_body(valid_set)))
            else:
                lineage_wire.decode_row(conn, payload(valid_set))
        assert conn.total_changes == 0 and not conn.in_transaction
    assert path.read_bytes() == before


def test_equal_pdf_bytes_keep_distinct_actual_paper_owners(valid_set):
    body = copy.deepcopy(valid_set)
    report = body["report"]
    digest = report["sources"][0]["document_hash"]
    for source, binding in zip(report["sources"], body["bindings"], strict=True):
        source["document_hash"] = digest
        source["id"] = lineage_content.source_id(source["identity"], digest)
        binding["source_id"] = source["id"]
    report["focal"] = report["sources"][0]["id"]
    report["statements"] = []
    report["coverage"] = dict.fromkeys(lineage_content.STAGES, "no_statement")
    report["id"] = lineage_content.hashed({k: v for k, v in report.items() if k != "id"})
    originals = lineage_wire.required_originals(payload(body))
    assert len(originals) == 3 and len({r["document_hash"] for r in originals}) == 1
    assert len({r["paper_id"] for r in originals}) == 3


def test_typed_deletion_keeps_explicit_corpus_and_complete_ordered_parents(valid_set):
    value = operation(valid_set)
    value.update(action="delete", payload={})
    assert json.loads(lineage_wire.canonical_operation(value)) == value
    assert len(value["parents"]) == 3
    assert value["content_address"]["key"] == valid_set["corpus_id"]


def test_generic_graph_lifecycle_retains_typed_address_and_refuses_stripping(valid_set):
    from paper_daily import sync_graph

    value = operation(valid_set)
    entities = {
        ("paper", p["id"]): dict(
            incarnation=p["incarnation"], parents=[], active=True, structure_revision=0
        )
        for p in value["parents"]
    }

    def get(kind, identity):
        return copy.deepcopy(entities.get((kind, identity)))

    def put(kind, identity, metadata):
        entities[kind, identity] = copy.deepcopy(metadata)

    assert sync_graph.check_preconditions(get, lambda _identity: None, value)
    sync_graph.apply_accepted(get, put, value, 1)
    state = entities["research_content", value["entity_id"]]
    assert state["content_address"] == value["content_address"]
    assert all(entities["paper", p["id"]]["structure_revision"] == 1 for p in value["parents"])
    deleted = dict(
        value, operation_id="lineage-delete", action="delete", payload={}, structure_revision=1
    )
    stripped = copy.deepcopy(deleted)
    stripped.pop("content_address")
    before = copy.deepcopy(entities)
    with pytest.raises(ValueError, match="address"):
        sync_graph.check_preconditions(get, lambda _identity: None, stripped)
    assert entities == before
    assert sync_graph.check_preconditions(get, lambda _identity: None, deleted)
    sync_graph.apply_accepted(get, put, deleted, 2)
    assert not entities["research_content", value["entity_id"]]["active"]
    assert (
        entities["research_content", value["entity_id"]]["content_address"]
        == (value["content_address"])
    )
