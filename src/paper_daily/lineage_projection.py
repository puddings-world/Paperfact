"""Caller-transaction Lineage projection for strict native shared operations.

The caller validates accepted event/source dependencies before materialization.
This stores scientific metadata and pinned provenance, never original-byte grants.
Trusted schema setup and the explicit native graph projector call this module.
Public analysis UI and reviewed archive adoption are separate integration work.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from paper_daily import claim_content, lineage_dependencies, lineage_sets, lineage_wire
from paper_daily.sync_content import _local_scope
from paper_daily.sync_journal import MAX_BYTES

TABLE = "research_lineage_sync_sources"
COLUMNS = "entity_id paper_id corpus_key operation_json active fingerprint"
HISTORY = "research_lineage_sync_history"
HISTORY_COLUMNS = "operation_id entity_id operation_json"
HISTORY_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS research_lineage_sync_history("
    "operation_id TEXT PRIMARY KEY,entity_id TEXT NOT NULL,operation_json TEXT NOT NULL)"
)
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS research_lineage_sync_sources("
    "entity_id TEXT PRIMARY KEY,paper_id TEXT NOT NULL,corpus_key TEXT NOT NULL,"
    "operation_json TEXT NOT NULL,active INTEGER NOT NULL CHECK(active IN (0,1)),fingerprint TEXT,"
    "UNIQUE(paper_id,corpus_key))"
)


def initialize_in(conn, *, include_report=True):
    """Caller-owned setup; generic enrollment may initialize only sync metadata."""
    if not conn.in_transaction or type(include_report) is not bool:
        raise ValueError("Lineage initialization requires a caller transaction and report choice")
    if include_report:
        conn.execute(lineage_sets.SCHEMA)
    conn.execute(SCHEMA)
    conn.execute(HISTORY_SCHEMA)


def initialize_receive_in(conn, client, operation):
    """Trusted full receive boundary; restricted projection itself still has no DDL."""
    lineage_dependencies.canonical_operation(operation)
    journal = client.journal
    if not conn.in_transaction or client.projection_writer is None:
        raise ValueError("Typed Lineage receive requires an explicit projection writer")
    main = next((row[2] for row in conn.execute("PRAGMA database_list")
                 if row[1] == "main"), None)
    if (not main or Path(main).resolve() != journal.path.resolve()
            or operation["workspace_id"] != journal.workspace_id):
        raise ValueError("Lineage schema receive belongs to another workspace/database")
    journal._binding(conn)
    binding = conn.execute(
        "SELECT workspace,origin FROM research_sync_binding WHERE id=1"
    ).fetchone()
    if binding is None or tuple(binding) != (journal.workspace_id, journal.device_id):
        raise ValueError("Lineage schema receive requires the local research binding")
    # The operation sender may be a peer; only the local adapter binds this device.
    initialize_in(conn)



def _retain_received_in(conn, client, event):
    """Retain validated accepted metadata before heads are coalesced; never grant bytes."""
    import json

    operation = event["operation"]
    encoded = lineage_dependencies.canonical_operation(operation)
    if event["outcome"] != "accepted":
        raise ValueError("Only accepted Lineage events enter native version history")
    stored = conn.execute(
        "SELECT event FROM paperfact_sync_inbox WHERE sequence=? AND outcome='accepted'",
        (event["sequence"],),
    ).fetchone()
    receipt = conn.execute(
        "SELECT event FROM paperfact_sync_graph_receipts WHERE operation_id=?",
        (operation["operation_id"],),
    ).fetchone()
    if stored is None or receipt is None or any(
        json.loads(row[0]) != event for row in (stored, receipt)
    ):
        raise ValueError("Lineage history needs its actual validated receive event")
    initialize_receive_in(conn, client, operation)
    prior = conn.execute(
        "SELECT operation_json FROM " + HISTORY + " WHERE operation_id=?",
        (operation["operation_id"],),
    ).fetchone()
    if prior is not None and prior[0] != encoded:
        raise ValueError("Lineage history operation identity cannot be reused")
    return conn.execute(
        "INSERT INTO " + HISTORY + " VALUES(?,?,?) ON CONFLICT(operation_id) DO NOTHING",
        (operation["operation_id"], operation["entity_id"], encoded),
    ).rowcount == 1

def validate_record(row):
    """Closed stored provenance, not event acceptance or source authority."""
    claim_content.closed(row, COLUMNS.split())
    lineage_sets.uuid(row["entity_id"])
    lineage_sets.uuid(row["corpus_key"])
    claim_content.text(row["paper_id"], 4096)
    if type(row["active"]) is not int or row["active"] not in (0, 1):
        raise ValueError("Invalid Lineage projection visibility")
    if row["fingerprint"] is not None:
        claim_content.digest(row["fingerprint"])
    if row["active"] == 1 and row["fingerprint"] is None:
        raise ValueError("Visible Lineage projection requires its exact materialized fingerprint")
    encoded = row["operation_json"]
    if not isinstance(encoded, str) or len(encoded.encode()) > MAX_BYTES:
        raise ValueError("Lineage projection provenance exceeds its bound")
    from paper_daily.sync_files import read_json

    operation = read_json(encoded.encode())
    if (
        lineage_dependencies.canonical_operation(operation) != encoded
        or operation["entity_id"] != row["entity_id"]
        or operation["content_address"]["key"] != row["corpus_key"]
        or (row["active"] == 1 and operation["action"] != "put")
    ):
        raise ValueError("Lineage projection differs from its exact operation")
    return operation


def validate_history(row):
    """Closed immutable scientific operation evidence, never replay authority."""
    claim_content.closed(row, HISTORY_COLUMNS.split())
    from paper_daily.sync_files import read_json

    encoded = row["operation_json"]
    if not isinstance(encoded, str) or len(encoded.encode()) > MAX_BYTES:
        raise ValueError("Lineage history exceeds its bound")
    operation = read_json(encoded.encode())
    if (
        lineage_dependencies.canonical_operation(operation) != encoded
        or row["operation_id"] != operation["operation_id"]
        or row["entity_id"] != operation["entity_id"]
    ):
        raise ValueError("Lineage history differs from its exact operation")
    return operation


def _marker(conn, entity_id):
    raw = conn.execute(
        "SELECT entity_id,paper_id,corpus_key,CASE WHEN length(CAST(operation_json AS BLOB))<=? "
        "THEN operation_json END,active,fingerprint FROM " + TABLE + " WHERE entity_id=?",
        (MAX_BYTES, entity_id),
    ).fetchone()
    if raw is None:
        return None, None
    row = dict(zip(COLUMNS.split(), raw, strict=True))
    return row, validate_record(row)


def _current(conn, local, corpus_id):
    raw = conn.execute(
        "SELECT paper_id,corpus_key,CASE WHEN length(CAST(body_json AS BLOB))<=? "
        "THEN body_json END,source_hash,document_hash,written_at FROM paper_lineage_sets "
        "WHERE paper_id=? AND corpus_key=?",
        (lineage_sets.MAX_BYTES, local, corpus_id),
    ).fetchone()
    if raw is None:
        return None
    return lineage_sets.validate_row(dict(zip(lineage_sets.COLUMNS.split(), raw, strict=True)))


def write_in(conn, operation, *, visible=True):
    """Own a savepoint for standalone callers; never commit their transaction."""
    if not conn.in_transaction:
        raise ValueError("Lineage projection requires a caller transaction")
    savepoint = "lineage_projection_" + secrets.token_hex(8)
    conn.execute("SAVEPOINT " + savepoint)
    try:
        result = apply_in(conn, operation, visible=visible)
        conn.execute("RELEASE " + savepoint)
        return result
    except BaseException:
        conn.execute("ROLLBACK TO " + savepoint)
        conn.execute("RELEASE " + savepoint)
        raise


def _originals_in(conn, operation):
    """Read exact desired-file metadata only; byte verification stays off-lock."""
    from paper_daily.sync_artifacts import desired_file
    from paper_daily.sync_journal import canonical_operation

    parents = {p["id"]: p for p in operation["parents"]}
    for pin in operation["source_dependencies"]:
        original = desired_file(conn, pin["file_id"])
        if original is None:
            raise ValueError("Lineage projection requires its current exact original metadata")
        canonical_operation(original)
        if (
            original["entity_type"] != "research_file"
            or original["action"] != "put"
            or original["workspace_id"] != operation["workspace_id"]
            or original["incarnation"] != pin["incarnation"]
            or original["parents"] != [parents[pin["paper_id"]]]
            or original["payload"]["feature"] != "original_source"
        ):
            raise ValueError("Lineage projection original lifetime or ownership changed")


def _visible_inputs_in(conn, operation):
    _originals_in(conn, operation)
    for parent in operation["parents"]:
        _local_scope(conn, dict(kind="paper", id=parent["id"]), required=True)
        projected = conn.execute(
            "SELECT incarnation FROM research_paper_projection WHERE sync_id=?", (parent["id"],)
        ).fetchone()
        if projected is None or projected[0] != parent["incarnation"]:
            raise ValueError("Lineage projection requires every exact materialized paper lifetime")


def apply_in(conn, operation, *, visible=True):
    """Stage one exact metadata projection atomically in a caller-owned transaction.

    The caller owns the transaction/savepoint, including rollback on failure.
    This is compatible with the journal's existing restricted writer: no DDL,
    transaction control, filesystem/PDF read or commit occurs here. Exact desired
    original metadata is required for visibility, not permission to access bytes.
    Event acceptance, graph CAS and blob verification remain separate mandatory
    boundaries. Hidden projections retain the original put provenance without
    reactivating retired sources. This creates no journal entry or cursor.
    """
    encoded = lineage_dependencies.canonical_operation(operation)
    if not conn.in_transaction or type(visible) is not bool:
        raise ValueError("Lineage projection requires a caller transaction and visibility choice")
    bound = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
    if bound is None or bound[0] != operation["workspace_id"]:
        raise ValueError("Lineage projection belongs to another workspace")
    for name in (lineage_sets.TABLE, TABLE, HISTORY):
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone():
            raise ValueError("Initialize the staged Lineage projection explicitly first")
    prior = conn.execute(
        "SELECT CASE WHEN length(CAST(operation_json AS BLOB))<=? THEN operation_json END "
        "FROM " + HISTORY + " WHERE operation_id=?",
        (MAX_BYTES, operation["operation_id"]),
    ).fetchone()
    if prior is not None and prior[0] != encoded:
        raise ValueError("Lineage history operation identity cannot be reused")
    marker, previous = _marker(conn, operation["entity_id"])
    scope = dict(kind="paper", id=operation["parents"][0]["id"])
    local = _local_scope(conn, scope, required=False)
    key = operation["content_address"]["key"]
    if previous is not None:
        if (
            marker["corpus_key"] != key
            or [(p["kind"], p["id"]) for p in previous["parents"]]
            != [(p["kind"], p["id"]) for p in operation["parents"]]
            or (local is not None and marker["paper_id"] != local)
        ):
            raise ValueError("Lineage projection cannot move its known corpus/source owners")
        local = marker["paper_id"]
    if local is None:
        raise ValueError("Lineage projection requires its actual registered focal paper")
    current = _current(conn, local, key)
    if marker is None and current is not None:
        raise ValueError("Existing unowned Lineage requires observed enrollment before projection")
    if marker is not None and (
        bool(marker["active"]) != (current is not None)
        or (current is not None and claim_content.hashed(current) != marker["fingerprint"])
    ):
        raise ValueError("Lineage content changed outside its projection; retain it for review")
    active = visible and operation["action"] == "put"
    row = None
    if active:
        from paper_daily.lineage_capacity import local_room_in

        if not local_room_in(conn, local, key):
            raise ValueError("Lineage projection capacity reached; retire a corpus first")
        _visible_inputs_in(conn, operation)
        row = lineage_wire.decode_row(conn, operation["payload"])
    elif (
        previous is not None
        and operation["action"] == "delete"
        and operation["incarnation"] != previous["incarnation"]
    ):
        return {"state": "ignored_stale_retirement", "entity_id": operation["entity_id"]}
    record = dict(
        entity_id=operation["entity_id"],
        paper_id=local,
        corpus_key=key,
        operation_json=encoded,
        active=int(active),
        fingerprint=claim_content.hashed(row)
        if row is not None
        else (marker["fingerprint"] if marker is not None else None),
    )
    validate_record(record)
    conn.execute(
        "INSERT INTO " + HISTORY + " VALUES(?,?,?) ON CONFLICT(operation_id) DO NOTHING",
        (operation["operation_id"], operation["entity_id"], encoded),
    )
    if row is not None:
        conn.execute(
            "INSERT INTO paper_lineage_sets VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(paper_id,corpus_key) "
            "DO UPDATE SET body_json=excluded.body_json,source_hash=excluded.source_hash,"
            "document_hash=excluded.document_hash,written_at=excluded.written_at",
            tuple(row[name] for name in lineage_sets.COLUMNS.split()),
        )
    else:
        conn.execute(
            "DELETE FROM paper_lineage_sets WHERE paper_id=? AND corpus_key=?", (local, key)
        )
    conn.execute(
        "INSERT INTO " + TABLE + " VALUES(?,?,?,?,?,?) ON CONFLICT(entity_id) DO UPDATE SET "
        "operation_json=excluded.operation_json,active=excluded.active,"
        "fingerprint=excluded.fingerprint",
        tuple(record[name] for name in COLUMNS.split()),
    )
    if active:
        _visible_inputs_in(conn, operation)
    return {"state": "projected" if active else "hidden", "entity_id": operation["entity_id"]}
