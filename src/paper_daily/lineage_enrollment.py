"""Explicit first-enrollment Lineage baseline: fresh source/parent authority, no AI."""

from __future__ import annotations

import json
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from uuid import UUID, uuid5

from paper_daily import (
    lineage_dependencies,
    lineage_projection,
    lineage_sets,
    lineage_source_reader,
    lineage_wire,
    sync_artifacts,
    sync_capture,
)
from paper_daily import research_generation as generation
from paper_daily.manual_highlight_ops import _readonly_connection, observe_owner
from paper_daily.sync_content import content_id
from paper_daily.sync_files import file_id
from paper_daily.sync_journal import MAX_BYTES


def sources(database, rows, ticket):
    """Read exact existing current originals; return paths, never portable grants.

    Library callers may plan on the main thread; byte verification is isolated
    in one worker in that case. Desktop callers already run planning off the GUI.
    """
    if not rows:
        return {}
    if threading.current_thread() is threading.main_thread():
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="lineage-enroll") as pool:
            return pool.submit(sources, database, rows, ticket).result()
    result = {}
    native = generation._identity(database)
    for row in rows:
        ticket.check()
        lineage_sets.validate_row(row)
        owner = observe_owner(database, row["paper_id"], expected_native=native)
        with closing(_readonly_connection(database)) as conn:
            conn.execute("BEGIN")
            reader = lineage_source_reader.reader_in(conn, owner, row)
        body = lineage_sets.decode(row["body_json"])
        for binding, selected in zip(body["bindings"], body["report"]["sources"], strict=True):
            if selected["availability"] == "unavailable":
                continue
            proof = reader.prepare(owner, row, selected["id"], cancelled=lambda: ticket.cancelled)
            ticket.check()
            if proof is None:
                raise ValueError("Lineage enrollment requires every exact selected original")
            data = reader.for_delivery(proof, owner, row, selected["id"])
            result.setdefault(
                (binding["paper_id"], selected["document_hash"]),
                dict(path=str(proof._source), sha256=selected["document_hash"], size=len(data)),
            )
    return result


def publish_in(conn, client, rows, *, request_id, ticket):
    """Enroll observed copied rows in the fresh candidate's caller transaction.

    This is not a general import/overwrite API. It requires the exact workspace
    and device derived by EnrollmentService for this explicit request, existing
    fresh original-file grants, unchanged copied rows and absent scientific heads.
    Temporary unowned rows are removed only within the same savepoint as the real
    native scientific write/outbox. Failure preserves earlier caller work.
    """
    request = UUID(request_id)
    if str(request) != request_id or not conn.in_transaction:
        raise ValueError("Lineage enrollment requires its canonical request transaction")
    if (client.journal.workspace_id, client.journal.device_id) != (
        str(uuid5(request, "workspace")),
        str(uuid5(request, "device")),
    ) or generation._path(conn) != str(client.journal.path.resolve()):
        raise ValueError("Lineage enrollment belongs to another candidate")
    client.journal._binding(conn)
    point = "lineage_enroll_" + secrets.token_hex(8)
    conn.execute("SAVEPOINT " + point)
    operations = []
    try:
        for row in rows:
            ticket.check()
            lineage_sets.validate_row(row)
            payload = lineage_wire.encode_row(conn, row)
            identity = content_id(payload["scope"], "lineage", row["corpus_key"])
            operation_id = str(uuid5(request, "lineage:" + identity))
            graph = client._optimistic_graph(conn)[0]
            parents = []
            for kind, parent_id in lineage_wire.parent_identities(payload):
                parent = graph.get((kind, parent_id))
                if parent is None or not parent["active"]:
                    raise ValueError("Lineage enrollment selected paper changed")
                parents.append(dict(kind=kind, id=parent_id, incarnation=parent["incarnation"]))
            pins = []
            for selected in lineage_wire.required_originals(payload):
                file = file_id(selected["paper_id"], "original_source", selected["document_hash"])
                original = sync_artifacts.desired_file(conn, file)
                if original is None or not sync_artifacts.paper_current(conn, original):
                    raise ValueError("Lineage enrollment exact original grant is missing")
                pins.append(
                    dict(
                        source_id=selected["source_id"],
                        paper_id=selected["paper_id"],
                        file_id=file,
                        incarnation=original["incarnation"],
                    )
                )
            operation = dict(
                version=2,
                operation_id=operation_id,
                workspace_id=client.journal.workspace_id,
                device_id=client.journal.device_id,
                entity_type="research_content",
                entity_id=identity,
                action="put",
                base_revision=0,
                depends_on=None,
                incarnation=operation_id,
                parents=parents,
                structure_revision=0,
                content_address=dict(feature="lineage", key=row["corpus_key"]),
                payload=payload,
                source_dependencies=pins,
            )
            encoded = lineage_dependencies.canonical_operation(operation)
            if not lineage_dependencies.active(
                lambda kind, key, graph=graph: graph.get((kind, key)), operation
            ):
                raise ValueError("Lineage enrollment original lifetime changed")
            prior = conn.execute(
                "SELECT CASE WHEN length(CAST(envelope AS BLOB))<=? THEN envelope END "
                "FROM paperfact_sync_operations WHERE operation_id=?",
                (MAX_BYTES, operation_id),
            ).fetchone()
            current = lineage_projection._current(conn, row["paper_id"], row["corpus_key"])
            if prior is not None:
                marker, actual = lineage_projection._marker(conn, identity)
                if (
                    prior[0] != encoded
                    or current != row
                    or actual != operation
                    or not marker["active"]
                ):
                    raise ValueError("Lineage enrollment retry no longer owns its exact result")
            else:
                if current != row or graph.get(("research_content", identity)) is not None:
                    raise ValueError("Lineage enrollment copied row or scientific head changed")
                with sync_capture.suppress_capture(conn):
                    conn.execute(
                        "DELETE FROM paper_lineage_sets WHERE paper_id=? AND corpus_key=?",
                        (row["paper_id"], row["corpus_key"]),
                    )

                def write(c, value):
                    client._guard_content_parent(c, value)
                    client.writer(c, value)

                client.journal.apply_in(conn, json.loads(encoded), write)
                if hasattr(conn, "_capture_graph_cache"):
                    conn._capture_graph_cache = None
                if lineage_projection._current(conn, row["paper_id"], row["corpus_key"]) != row:
                    raise ValueError("Lineage enrollment changed copied scientific content")
            operations.append(operation_id)
        ticket.check()
        conn.execute("RELEASE " + point)
    except BaseException:
        conn.execute("ROLLBACK TO " + point)
        conn.execute("RELEASE " + point)
        if hasattr(conn, "_capture_graph_cache"):
            conn._capture_graph_cache = None
        raise
    return dict(lineage_reports=len(operations), operation_ids=operations)
