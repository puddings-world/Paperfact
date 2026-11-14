"""Construct a native operation from its sealed pre-analysis observation.

This builds data only. Common journal/service admission, compound publication
and accepted receipts are independent; construction cannot create any of them.
"""

from __future__ import annotations

import json

from paper_daily import (
    lineage_dependencies,
    lineage_observation,
    lineage_peer_sources,
    lineage_wire,
)
from paper_daily.lineage_jobs import _worker


def build_in(conn, client, prepared_sources, source_operations, payload):
    """Read-only caller-transaction builder; retain this frame for exact retries.

    All selected parent epochs, target revision/predecessor and original-file
    lifetimes come from the actual captured observation and its verified source
    staging. No current-source recapture or arbitrary caller hash grants occur.
    """
    _worker()
    pins = lineage_peer_sources.pins_in(conn, client, prepared_sources, source_operations)
    data = lineage_observation.checked(prepared_sources._observation)
    return _assemble_in(conn, client, prepared_sources, pins, data, payload)


def _assemble_in(conn, client, prepared_sources, pins, data, payload):
    """Shared construction after native source/database checks, without rereading PDFs."""
    lineage_wire.validate_payload(payload)
    parents = [source["parent"] for source in data["sources"]]
    token = data["observation"]
    if (
        data["binding"] is None
        or token is None
        or payload["key"] != data["corpus_id"]
        or payload["scope"] != dict(kind="paper", id=parents[0]["id"])
        or lineage_wire.parent_identities(payload) != [("paper", p["id"]) for p in parents]
        or payload["data"]["body_json"]["report"]["sources"]
        != prepared_sources._observation._corpus.sources
    ):
        raise ValueError("Lineage operation differs from its original observed corpus")
    key = "research_content", token["entity_id"]
    graph, touches, _own = client._optimistic_graph(conn)
    current = graph.get(key)
    if current is not None and not current["active"]:
        raise ValueError("Lineage restoration requires a separate explicit observation")
    accepted = client._graph_entity(conn, *key)
    operation = dict(
        version=2,
        operation_id=data["request_id"],
        workspace_id=data["binding"]["workspace_id"],
        device_id=data["binding"]["device_id"],
        entity_type=key[0],
        entity_id=key[1],
        action="put",
        base_revision=token["revision"],
        depends_on=token["predecessor"],
        incarnation=token["incarnation"] or data["request_id"],
        parents=parents,
        structure_revision=accepted["structure_revision"] if accepted else 0,
        content_address=dict(feature="lineage", key=data["corpus_id"]),
        payload=payload,
        source_dependencies=pins,
    )
    if key in touches:
        operation["structure_depends_on"] = touches[key]
    encoded = lineage_dependencies.canonical_operation(operation)
    from paper_daily.lineage_address import check_known

    if current is not None:
        check_known(*key, current, operation)
    if not lineage_dependencies.active(
        lambda kind, identity: graph.get((kind, identity)), operation
    ):
        raise ValueError("Lineage original dependencies changed after observation")
    return json.loads(encoded)


def from_candidate_in(conn, client, prepared_sources, source_operations, candidate):
    """Use one actual retained completion and its original pre-analysis lease.

    Candidate validation is not publication: source/outbox writes and the final
    scientific action still require one owner transaction and common admission.
    A retained stale/cancelled/route-changed candidate cannot become a new intent.
    """
    from paper_daily import lineage_candidates

    _worker()
    record = lineage_candidates.checked(candidate)
    if (
        not isinstance(prepared_sources, lineage_peer_sources.PreparedPeerSources)
        or candidate._target is None
        or candidate._target._observation is not prepared_sources._observation
        or record["reason"] != "pending_lineage_publication"
    ):
        raise ValueError("Lineage candidate requires its original current publication lease")
    # Refuse a foreign database before mapping any of its private paper IDs.
    # Reuse this proof for assembly rather than repeating source inspection.
    pins = lineage_peer_sources.pins_in(conn, client, prepared_sources, source_operations)
    data = lineage_observation.checked(prepared_sources._observation)
    # The native candidate seal fixes the exact verified report and execution
    # metadata; no second completion or re-verification against newer PDFs.
    payload = lineage_wire.encode_row(conn, json.loads(record["row_json"]))
    return _assemble_in(conn, client, prepared_sources, pins, data, payload)
