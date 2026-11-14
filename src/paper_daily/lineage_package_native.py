"""Typed compiler hooks for source-complete PackageImporter actions, never raw adoption."""

from __future__ import annotations

import json
from pathlib import Path

from paper_daily import (
    claim_content,
    lineage_dependencies,
    lineage_package_targets,
    lineage_sets,
    lineage_wire,
)
from paper_daily.sync_artifacts import desired_file
from paper_daily.sync_content import content_id
from paper_daily.sync_files import file_id
from paper_daily.sync_journal import canonical_operation


def payloads(validated, identities):
    """Convert only receiver identities from an actual byte-validated package lease."""
    content = lineage_package_targets._validated(validated)
    result = []
    for row in content["rows"]:
        lineage_sets.validate_row(row)
        body = lineage_sets.decode(row["body_json"])
        before = json.loads(lineage_sets.canonical(body))
        for binding in body["bindings"]:
            binding["paper_id"] = identities[binding["paper_id"]]
        if body["report"] != before["report"]:
            raise ValueError("Lineage import altered scientific evidence")
        payload = dict(
            scope=dict(kind="paper", id=identities[row["paper_id"]]),
            feature="lineage",
            key=row["corpus_key"],
            source_document_hash=row["document_hash"],
            data=dict(
                body_json=body,
                **{k: row[k] for k in ("source_hash", "document_hash", "written_at")},
            ),
        )
        lineage_wire.validate_payload(payload)
        result.append(payload)
    return result


def build_in(conn, client, validated, identities, payload, request_id, originals):
    """Build against the observed/planned graph; byte grants are published separately.

    PackageImporter owns target observations, sealed source staging and the action
    transaction. The validated archive fixes the scientific payload; original-file
    operations fix native lifetimes. This creates no source or scientific rows.
    """
    if not conn.in_transaction:
        raise ValueError("Lineage package compilation needs its caller transaction")
    main = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), None)
    if not main or Path(main).resolve() != client.journal.path.resolve():
        raise ValueError("Lineage package belongs to another receiver database")
    client.journal._binding(conn)
    expected = {
        content_id(p["scope"], "lineage", p["key"]): p for p in payloads(validated, identities)
    }
    identity = content_id(payload["scope"], "lineage", payload["key"])
    if expected.get(identity) != payload:
        raise ValueError("Lineage import differs from its byte-validated scientific package")
    graph = client._optimistic_graph(conn)[0]
    parents = []
    for kind, key in lineage_wire.parent_identities(payload):
        parent = graph.get((kind, key))
        if not parent or not parent["active"]:
            raise ValueError("Lineage import selected paper changed")
        parents.append(dict(kind=kind, id=key, incarnation=parent["incarnation"]))
    pins = []
    for selected in lineage_wire.required_originals(payload):
        identity_file = file_id(selected["paper_id"], "original_source", selected["document_hash"])
        original = originals.get(identity_file)
        if original is None:
            raise ValueError("Lineage package needs every exact prepared original")
        canonical_operation(original)
        parent = next(p for p in parents if p["id"] == selected["paper_id"])
        if (
            original["workspace_id"] != client.journal.workspace_id
            or original["entity_type"] != "research_file"
            or original["action"] != "put"
            or original["entity_id"] != identity_file
            or original["parents"] != [parent]
            or original["payload"]["feature"] != "original_source"
            or original["payload"]["slot"] != selected["document_hash"]
        ):
            raise ValueError("Lineage package original differs from its selected receiver")
        pins.append(
            dict(
                source_id=selected["source_id"],
                paper_id=selected["paper_id"],
                file_id=identity_file,
                incarnation=original["incarnation"],
            )
        )
    template = dict(
        version=2,
        operation_id=request_id,
        workspace_id=client.journal.workspace_id,
        device_id=client.journal.device_id,
        entity_type="research_content",
        entity_id=identity,
        action="put",
        base_revision=0,
        depends_on=None,
        incarnation=request_id,
        parents=parents,
        structure_revision=0,
        content_address=dict(feature="lineage", key=payload["key"]),
        source_dependencies=pins,
        payload=payload,
    )
    lineage_dependencies.canonical_operation(template)
    return client._new_graph_operation(
        conn,
        "research_content",
        identity,
        payload,
        operation_id=request_id,
        lineage_template=template,
    )


def rebuild_in(conn, client, validated, identities, operation):
    """Recheck actual same-transaction source publication before a scientific write."""
    originals = {}
    for selected in lineage_wire.required_originals(operation["payload"]):
        key = file_id(selected["paper_id"], "original_source", selected["document_hash"])
        originals[key] = desired_file(conn, key)
    return build_in(
        conn,
        client,
        validated,
        identities,
        operation["payload"],
        operation["operation_id"],
        originals,
    )


def saved_in(conn, local, corpus):
    """Bounded scientific read; absence is observed without creating storage."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name=?", (lineage_sets.TABLE,)
    ).fetchone()
    if not exists:
        return None
    from paper_daily.lineage_projection import _current

    return _current(conn, local, corpus)


def target_in(conn, local, corpus):
    row = saved_in(conn, local, corpus)
    return dict(
        paper_id=local,
        corpus_key=corpus,
        fingerprint=claim_content.hashed(row) if row is not None else None,
    )


def check_targets_in(conn, expected):
    """Recheck actual scientific content, including absence and reused native rows."""
    if expected is None:
        return
    for target in expected:
        claim_content.closed(target, {"paper_id", "corpus_key", "fingerprint"})
        if target_in(conn, target["paper_id"], target["corpus_key"]) != target:
            raise ValueError("Lineage import targets changed after preview; prepare again")
