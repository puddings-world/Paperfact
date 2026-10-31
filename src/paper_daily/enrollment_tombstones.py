"""Explicit initial known-empty annotation tombstones, without synthetic content."""

from __future__ import annotations

import json

from paper_daily import annotation_content
from paper_daily.sync_journal import _identifier, canonical_operation


def absent_feature(operation):
    """Only four deterministic singleton IDs under their exact paper parent qualify."""
    if (
        operation["entity_type"] != "research_content"
        or operation["action"] != "delete"
        or operation["payload"]
        or len(operation["parents"]) != 1
    ):
        return None
    parent = operation["parents"][0]
    if parent["kind"] != "paper":
        return None
    from paper_daily.sync_content import content_id

    scope = {"kind": "paper", "id": parent["id"]}
    return next(
        (
            feature
            for feature in annotation_content.FEATURES
            if content_id(scope, feature, "main") == operation["entity_id"]
        ),
        None,
    )


def project_absent(conn, operation):
    """No prior content body/projection is needed to retain a known deletion."""
    feature = absent_feature(operation)
    if feature is None:
        return False
    parent = operation["parents"][0]
    found = conn.execute(
        "SELECT m.local_id,g.incarnation FROM research_paper_identity m "
        "JOIN research_paper_projection g ON g.sync_id=m.sync_id "
        "JOIN papers p ON p.id=m.local_id WHERE m.sync_id=?",
        (parent["id"],),
    ).fetchone()
    if found is None or found[1] != parent["incarnation"]:
        raise ValueError("Initial annotation tombstone needs its exact current paper parent")
    table = annotation_content.FEATURES[feature]
    if conn.execute(f'SELECT 1 FROM "{table}" WHERE paper_id=?', (found[0],)).fetchone():
        raise ValueError("Initial annotation tombstone cannot erase untracked current content")
    from paper_daily.sync_content import _record_projection

    conn.execute("INSERT OR IGNORE INTO paper_annotation_known VALUES(?,?)", (feature, found[0]))
    _record_projection(
        conn, operation, feature, {"kind": "paper", "id": parent["id"]}, "main", None
    )
    return True


def establish_in(conn, client, *, feature, paper_id, request_id):
    """Typed first-enrollment declaration; caller owns the whole transaction."""
    from pathlib import Path

    from paper_daily.sync_content import content_id

    if not conn.in_transaction or feature not in annotation_content.FEATURES:
        raise ValueError("Known annotation deletion requires a typed caller transaction")
    _identifier(request_id)
    main = next((row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"), None)
    if main is None or Path(main).resolve() != client.journal.path.resolve():
        raise ValueError("Annotation deletion belongs to another database")
    client.journal._binding(conn)
    found = conn.execute(
        "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (paper_id,)
    ).fetchone()
    if found is None:
        raise ValueError("Known annotation deletion requires its existing paper")
    portable = found[0]
    graph = client._optimistic_graph(conn)[0]
    parent = graph.get(("paper", portable))
    if parent is None or not parent["active"]:
        raise ValueError("Known annotation deletion requires an active paper")
    table = annotation_content.FEATURES[feature]
    if conn.execute(f'SELECT 1 FROM "{table}" WHERE paper_id=?', (paper_id,)).fetchone():
        raise ValueError("Known annotation deletion cannot erase current content")
    identity = content_id({"kind": "paper", "id": portable}, feature, "main")
    operation = {
        "version": 2,
        "operation_id": request_id,
        "workspace_id": client.journal.workspace_id,
        "device_id": client.journal.device_id,
        "entity_type": "research_content",
        "entity_id": identity,
        "action": "delete",
        "base_revision": 0,
        "depends_on": None,
        "payload": {},
        "incarnation": request_id,
        "structure_revision": 0,
        "parents": [{"kind": "paper", "id": portable, "incarnation": parent["incarnation"]}],
    }
    canonical_operation(operation)
    prior = conn.execute(
        "SELECT envelope FROM paperfact_sync_operations WHERE operation_id=?", (request_id,)
    ).fetchone()
    if prior:
        if json.loads(prior[0]) != operation:
            raise ValueError("Annotation deletion request was reused")
        return operation
    if graph.get(("research_content", identity)) is not None:
        raise ValueError("Initial annotation deletion cannot bypass an existing incarnation")
    result = client.journal.apply_in(conn, operation, client.writer)
    if not result["applied"]:
        raise ValueError("Initial annotation deletion was not applied")
    if hasattr(conn, "_capture_graph_cache"):
        conn._capture_graph_cache = None
    return operation
