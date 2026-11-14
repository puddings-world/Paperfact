"""Closed Lineage payload codec; native admission additionally requires source pins."""

from __future__ import annotations

import json

from paper_daily import lineage_address, lineage_sets
from paper_daily.claim_content import closed
from paper_daily.sync_content import FIELDS, content_id
from paper_daily.sync_schema_v2 import _encode, _header, _identifier

MAX_INLINE_BYTES = 240 * 1024


def validate_payload(payload):
    """Validate one full portable report and its exact focal/corpus/source hashes."""
    closed(payload, FIELDS)
    closed(payload["scope"], {"kind", "id"})
    if payload["feature"] != "lineage" or payload["scope"]["kind"] != "paper":
        raise ValueError("Incorrect Lineage content scope")
    lineage_sets.uuid(payload["scope"]["id"])
    lineage_sets.uuid(payload["key"])
    data = payload["data"]
    closed(data, lineage_sets.FIELDS.split())
    body = lineage_sets.validate(data["body_json"], portable=True)
    row = dict(
        paper_id=payload["scope"]["id"],
        corpus_key=payload["key"],
        **{k: data[k] for k in ("source_hash", "document_hash", "written_at")},
        body_json=lineage_sets.canonical(body),
    )
    lineage_sets.validate_row(row)
    if payload["source_document_hash"] != row["document_hash"]:
        raise ValueError("Lineage wire source differs from its focal original")
    if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_INLINE_BYTES:
        raise ValueError("Lineage content exceeds its inline budget")
    return payload


def parent_identities(payload):
    validate_payload(payload)
    return [("paper", b["paper_id"]) for b in payload["data"]["body_json"]["bindings"]]


def encode_row(conn, row):
    """Convert registered local identities only; no SQL/file writes or identity minting."""
    lineage_sets.validate_row(row)
    body = lineage_sets.convert(conn, lineage_sets.decode(row["body_json"]), portable=True)
    payload = dict(
        scope=dict(kind="paper", id=body["bindings"][0]["paper_id"]),
        feature="lineage",
        key=row["corpus_key"],
        source_document_hash=row["document_hash"],
        data=dict(
            body_json=body, **{k: row[k] for k in ("source_hash", "document_hash", "written_at")}
        ),
    )
    validate_payload(payload)
    return payload


def decode_row(conn, payload):
    """Map only exact existing receiver owners; this is data, not a write permission."""
    validate_payload(payload)
    body = lineage_sets.convert(conn, payload["data"]["body_json"], portable=False)
    row = dict(
        paper_id=body["bindings"][0]["paper_id"],
        corpus_key=body["corpus_id"],
        body_json=lineage_sets.canonical(body),
        **{k: payload["data"][k] for k in ("source_hash", "document_hash", "written_at")},
    )
    lineage_sets.validate_row(row)
    return row


def required_originals(payload):
    """Keep every actual paper/hash binding, including distinct owners of equal bytes."""
    validate_payload(payload)
    body = payload["data"]["body_json"]
    return [
        dict(paper_id=b["paper_id"], source_id=s["id"], document_hash=s["document_hash"])
        for b, s in zip(body["bindings"], body["report"]["sources"], strict=True)
        if s["availability"] == "available"
    ]


def canonical_operation(operation):
    """Validate the staged full v2 envelope without registering a live operation kind."""
    kind, action, payload = _header(
        operation, additional={"content_address", "source_dependencies"}
    )
    if kind != "research_content" or not lineage_address.validate(operation):
        raise ValueError("A Lineage operation requires its explicit typed corpus address")
    for parent in operation["parents"]:
        _identifier(parent["incarnation"])
    if action == "put":
        validate_payload(payload)
        if operation["entity_id"] != content_id(payload["scope"], "lineage", payload["key"]):
            raise ValueError("Lineage operation differs from its corpus identity")
        if parent_identities(payload) != [(p["kind"], p["id"]) for p in operation["parents"]]:
            raise ValueError("Lineage operation differs from its ordered selected parents")
    if "source_dependencies" in operation:
        from paper_daily.lineage_dependencies import validate

        validate(operation)
    return _encode(operation)
