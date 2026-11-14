"""One owner transaction for verified native Lineage sources, report and outbox.

The real journal request is the local action receipt. No unbound publication
receipt is reused and no remote acceptance is inferred from local publication.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from paper_daily import (
    file_change,
    lineage_candidates,
    lineage_dependencies,
    lineage_observation,
    lineage_operations,
    lineage_peer_sources,
    lineage_wire,
    research_lineage,
)
from paper_daily.lineage_jobs import _worker
from paper_daily.sync_journal import MAX_BYTES


def publish_in(conn, client, prepared_sources, candidate, *, cancelled=lambda: False):
    """Publish locally once; caller owns commit/rollback and source staging is off-lock."""
    _worker()
    record = lineage_candidates.checked(candidate)
    if (
        not isinstance(prepared_sources, lineage_peer_sources.PreparedPeerSources)
        or candidate._target is None
        or candidate._target._observation is not prepared_sources._observation
        or record["reason"] != "pending_lineage_publication"
    ):
        raise ValueError("Shared Lineage publication requires its original native candidate")
    data = lineage_observation.checked(prepared_sources._observation)
    main = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), None)
    if (
        not conn.in_transaction
        or data["binding"] is None
        or not main
        or Path(main).resolve() != client.journal.path.resolve()
        or str(client.journal.path.resolve()) != data["database"]
        or data["binding"]
        != dict(workspace_id=client.journal.workspace_id, device_id=client.journal.device_id)
    ):
        raise ValueError("Shared Lineage publication belongs to another workspace/database")
    client.journal._binding(conn)
    if cancelled():
        raise research_lineage.LineageError("cancelled")
    savepoint = "lineage_shared_" + secrets.token_hex(8)
    conn.execute("SAVEPOINT " + savepoint)
    try:
        prior = conn.execute(
            "SELECT CASE WHEN length(CAST(envelope AS BLOB))<=? THEN envelope END,sequence "
            "FROM paperfact_sync_operations WHERE operation_id=?",
            (MAX_BYTES, record["request_id"]),
        ).fetchone()
        if prior is not None:
            if prior[0] is None:
                raise ValueError("Shared Lineage journal receipt exceeds its bound")
            operation = json.loads(prior[0])
            lineage_dependencies.canonical_operation(operation)
            sources = {}
            for source in data["sources"]:
                if source["document_hash"] is None:
                    continue
                identity = (
                    source["source_operation"]["operation_id"]
                    if source["source_operation"] is not None
                    else lineage_observation.source_request_id(
                        prepared_sources._observation, source["source_id"]
                    )
                )
                found = conn.execute(
                    "SELECT CASE WHEN length(CAST(operation AS BLOB))<=? THEN operation END "
                    "FROM research_file_versions WHERE operation_id=?",
                    (MAX_BYTES, identity),
                ).fetchone()
                if found is None or found[0] is None:
                    raise ValueError("Shared Lineage original receipt is missing")
                sources[source["source_id"]] = json.loads(found[0])
            pins = lineage_peer_sources.pins_in(
                conn, client, prepared_sources, sources, publication=operation
            )
            if (
                operation["payload"]
                != lineage_wire.encode_row(conn, json.loads(record["row_json"]))
                or operation["source_dependencies"] != pins
            ):
                raise ValueError("Shared Lineage retry changed its candidate or original intent")
            result = dict(applied=False, sequence=prior[1])
        else:
            sources = lineage_peer_sources.publish_in(conn, client, prepared_sources)
            operation = lineage_operations.from_candidate_in(
                conn, client, prepared_sources, sources, candidate
            )

            def write(c, value):
                client._guard_content_parent(c, value)
                client.writer(c, value)

            result = client.journal.apply_in(conn, operation, write)
            if hasattr(conn, "_capture_graph_cache"):
                conn._capture_graph_cache = None
            lineage_peer_sources.pins_in(
                conn, client, prepared_sources, sources, publication=operation
            )
        for entry in prepared_sources._entries:
            if file_change.version(entry.path) != entry.version:
                raise ValueError("Shared Lineage staged original changed before publication")
        if cancelled():
            raise research_lineage.LineageError("cancelled")
        conn.execute("RELEASE " + savepoint)
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK TO " + savepoint)
            conn.execute("RELEASE " + savepoint)
        if hasattr(conn, "_capture_graph_cache"):
            conn._capture_graph_cache = None
        raise
    return dict(
        state="published_local",
        request_id=record["request_id"],
        operation_id=operation["operation_id"],
        **result,
    )
