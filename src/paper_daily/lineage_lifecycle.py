"""Explicit observed Lineage retirement/restoration; never an AI or source grant.

The caller owns one capture-aware transaction. Action receipts are local history,
not server acceptance or portable replay permission.
"""

from __future__ import annotations

import json
import secrets
from contextlib import closing

from paper_daily import (
    claim_content,
    lineage_capacity,
    lineage_dependencies,
    lineage_originals,
    lineage_package_publish,
    lineage_projection,
    lineage_publication,
    lineage_sets,
    lineage_wire,
    sync_capture,
)
from paper_daily import research_generation as generation
from paper_daily.lineage_jobs import _worker
from paper_daily.manual_highlight_ops import HighlightOwner, _readonly_connection
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.sync_journal import MAX_BYTES as MAX_OPERATION_BYTES

TABLE = "research_lineage_actions"
COLUMNS = "request_id body_json"
FORMAT = "paperfact.lineage-lifecycle.v1"
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS research_lineage_actions("
    "request_id TEXT PRIMARY KEY,body_json TEXT NOT NULL)"
)
MAX_RECORD = 512 * 1024
MAX_ACTIONS = 4096
MAX_HISTORY = 64 * 1024**2


def validate_record(record):
    """Closed archive data only; native source/operation authority is independent."""
    claim_content.closed(record, COLUMNS.split())
    lineage_sets.uuid(record["request_id"])
    raw = record["body_json"]
    if not isinstance(raw, str) or len(raw.encode()) > MAX_RECORD:
        raise ValueError("Lineage lifecycle receipt exceeds its bound")
    body = lineage_package_publish._load(raw)
    claim_content.closed(
        body,
        {
            "format",
            "request_id",
            "action",
            "row_json",
            "origin",
            "owner_json",
            "operation_id",
            "fingerprint",
        },
    )
    if (
        body["format"] != FORMAT
        or body["request_id"] != record["request_id"]
        or body["action"] not in {"retire", "restore"}
    ):
        raise ValueError("Invalid Lineage lifecycle action")
    row = lineage_sets.validate_row(lineage_package_publish._load(body["row_json"]))
    if generation._json(row) != body["row_json"]:
        raise ValueError("Lineage lifecycle row is not canonical")
    origin = body["origin"]
    claim_content.closed(origin, {"kind", "id"})
    if origin["kind"] not in {"generated", "import", "native"}:
        raise ValueError("Unknown Lineage lifecycle provenance")
    claim_content.text(origin["id"], 128)
    if not origin["id"]:
        raise ValueError("Missing Lineage lifecycle origin")
    owner = lineage_package_publish._load(body["owner_json"])
    claim_content.closed(owner, {"database_identity", "binding", "parent", "graph"})
    native = owner["database_identity"]
    if (
        not isinstance(native, list)
        or len(native) != 2
        or any(type(n) is not int or n < 0 for n in native)
        or native[1] == 0
    ):
        raise ValueError("Invalid Lineage lifecycle database observation")
    token = owner["parent"]
    if (
        not isinstance(token, str)
        or len(token) != 32
        or any(c not in "0123456789abcdef" for c in token)
    ):
        raise ValueError("Invalid Lineage lifecycle parent observation")
    if origin["kind"] == "native":
        claim_content.closed(owner["binding"], {"workspace_id", "device_id"})
        for value in owner["binding"].values():
            claim_content.text(value, 128)
        claim_content.closed(owner["graph"], {"entity_id", "incarnation", "active"})
        if owner["graph"]["active"] is not True:
            raise ValueError("Lineage lifecycle requires its active focal owner")
        for key in ("entity_id", "incarnation"):
            claim_content.text(owner["graph"][key], 128)
        if body["operation_id"] != body["request_id"]:
            raise ValueError("Native Lineage action requires its actual operation identity")
    elif (
        owner["binding"] is not None
        or owner["graph"] is not None
        or body["operation_id"] is not None
    ):
        raise ValueError("Unbound Lineage action cannot claim native authority")
    unsigned = {key: value for key, value in body.items() if key != "fingerprint"}
    if body["fingerprint"] != claim_content.hashed(unsigned) or generation._json(body) != raw:
        raise ValueError("Lineage lifecycle fingerprint differs from its exact action")
    return body


def _exists(conn):
    return lineage_package_publish._schema(conn, TABLE, COLUMNS)


def _read(conn, request_id):
    if not _exists(conn):
        return None
    raw = conn.execute(
        "SELECT CASE WHEN length(CAST(body_json AS BLOB))<=? THEN body_json END FROM "
        + TABLE
        + " WHERE request_id=?",
        (MAX_RECORD, request_id),
    ).fetchone()
    return None if raw is None else validate_record(dict(request_id=request_id, body_json=raw[0]))


def _origin_in(conn, owner, row, origin=None, *, sources=False):
    """Check immutable provenance; sources=True verifies current lifetimes, not bytes."""
    client = getattr(conn, "_capture_client", None)
    if generation._binding(conn) is not None:
        if client is None:
            raise ValueError("Lineage lifecycle requires native capture")
        if origin is None:
            marker = conn.execute(
                "SELECT entity_id FROM research_lineage_sync_sources "
                "WHERE paper_id=? AND corpus_key=?",
                (owner.paper_id, row["corpus_key"]),
            ).fetchone()
            if marker is None:
                raise ValueError("Lineage lifecycle lacks native provenance")
            _record, operation = lineage_projection._marker(conn, marker[0])
            origin = dict(kind="native", id=operation["operation_id"])
        if origin["kind"] != "native":
            raise ValueError("Cannot rebind unbound history to a native workspace")
        raw = conn.execute(
            "SELECT operation_id,entity_id,CASE WHEN length(CAST(operation_json AS BLOB))<=? "
            "THEN operation_json END FROM research_lineage_sync_history WHERE operation_id=?",
            (MAX_OPERATION_BYTES, origin["id"]),
        ).fetchone()
        if raw is None:
            raise ValueError("Lineage lifecycle history operation is missing")
        operation = lineage_projection.validate_history(
            dict(zip(lineage_projection.HISTORY_COLUMNS.split(), raw, strict=True))
        )
        if (
            operation["workspace_id"] != client.journal.workspace_id
            or operation["action"] != "put"
            or lineage_wire.decode_row(conn, operation["payload"]) != row
        ):
            raise ValueError("Lineage history differs from the selected native report")
        if sources and not lineage_dependencies.active(
            lambda kind, identity: client._optimistic_graph(conn)[0].get((kind, identity)),
            operation,
        ):
            raise ValueError("Lineage original or selected paper lifetime changed")
        return origin, operation
    if origin is None:
        imported = lineage_package_publish.current_in(conn, row)
        if imported is not None:
            origin = dict(kind="import", id=imported["request_id"])
        else:
            receipt = lineage_originals._latest(conn, row)
            origin = dict(kind="generated", id=receipt["request_id"])
    if origin["kind"] == "native":
        raise ValueError("Archived native history requires fresh reviewed adoption")
    if origin["kind"] == "generated":
        raw = lineage_publication._receipt(conn, origin["id"])
        if raw is None:
            raise ValueError("Lineage generation publication is missing")
        receipt = dict(
            zip(("request_id", "candidate_id", "row_json", "sources_json"), raw, strict=True)
        )
        candidate = lineage_originals._candidate(conn, origin["id"])
        from paper_daily.lineage_recovery import linked_publication

        saved, originals, context = linked_publication(receipt, candidate)
        if saved != row:
            raise ValueError("Lineage generation history differs from the selected report")
        if sources:
            lineage_originals._parents(conn, owner, context)
            lineage_originals._associations(conn, originals)
    elif origin["kind"] == "import":
        imported = lineage_package_publish._read(conn, origin["id"])
        if imported is None:
            raise ValueError("Lineage import history is missing")
        item = next(
            (r for r in imported["records"] if r["row_json"] == generation._json(row)), None
        )
        if item is None:
            raise ValueError("Lineage import history differs from the selected report")
        if sources:
            selected = {b["paper_id"] for b in lineage_sets.decode(row["body_json"])["bindings"]}
            if imported["database_identity"] != generation._identity(owner.database):
                raise ValueError("Imported history requires fresh reviewed adoption")
            for parent in imported["parents"]:
                if parent["paper_id"] in selected and (
                    parent_lifecycle(conn, "paper", parent["paper_id"])
                    != parent["parent_lifecycle"]
                    or not conn.execute(
                        "SELECT 1 FROM papers WHERE id=?", (parent["paper_id"],)
                    ).fetchone()
                ):
                    raise ValueError("Imported Lineage selected paper lifetime changed")
            for original in item["sources"]:
                if lineage_package_publish._association(conn, original) != original:
                    raise ValueError("Imported Lineage original association changed")
    else:
        raise ValueError("Unknown Lineage lifecycle provenance")
    return origin, None


def apply_in(conn, owner, row, *, request_id, action, origin=None, cancelled=lambda: False):
    """Retire/restore one observed corpus atomically; caller owns commit/rollback."""
    _worker()
    if not isinstance(owner, HighlightOwner) or not conn.in_transaction:
        raise ValueError("Lineage lifecycle requires its loaded owner transaction")
    owner.check(conn)
    lineage_sets.validate_row(row)
    lineage_sets.uuid(request_id)
    if row["paper_id"] != owner.paper_id or action not in {"retire", "restore"}:
        raise ValueError("Invalid Lineage lifecycle target/action")
    if origin is not None:
        claim_content.closed(origin, {"kind", "id"})
    if cancelled():
        raise ValueError("Lineage lifecycle cancelled")
    savepoint = "lineage_action_" + secrets.token_hex(8)
    conn.execute("SAVEPOINT " + savepoint)
    try:
        prior = _read(conn, request_id)
        current = lineage_projection._current(conn, owner.paper_id, row["corpus_key"])
        if prior is not None:
            if (
                prior["row_json"] != generation._json(row)
                or prior["action"] != action
                or prior["owner_json"] != owner._json
                or origin is not None
                and prior["origin"] != origin
            ):
                raise ValueError("Lineage lifecycle request ID reused with different intent")
            if current != (None if action == "retire" else row):
                raise ValueError("Lineage lifecycle target changed after the prior action")
            if prior["operation_id"] is not None:
                marker = conn.execute(
                    "SELECT entity_id FROM research_lineage_sync_sources "
                    "WHERE paper_id=? AND corpus_key=?",
                    (owner.paper_id, row["corpus_key"]),
                ).fetchone()
                _marker, operation = (
                    lineage_projection._marker(conn, marker[0]) if marker else (None, None)
                )
                journal = conn.execute(
                    "SELECT envelope FROM paperfact_sync_operations WHERE operation_id=?",
                    (request_id,),
                ).fetchone()
                if operation is None or operation["operation_id"] != request_id or journal is None:
                    raise ValueError("Native Lineage lifecycle receipt no longer owns the target")
                if json.loads(journal[0]) != operation:
                    raise ValueError("Native Lineage lifecycle journal differs from its receipt")
            if action == "restore":
                _origin_in(conn, owner, row, prior["origin"], sources=True)
            body, applied = prior, False
        else:
            if current != (row if action == "retire" else None):
                raise ValueError("Lineage lifecycle target changed; review before applying")
            if action == "restore" and origin is None:
                raise ValueError("Restoring Lineage requires its selected history origin")
            source, template = _origin_in(conn, owner, row, origin, sources=action == "restore")
            native = generation._binding(conn) is not None
            body = dict(
                format=FORMAT,
                request_id=request_id,
                action=action,
                row_json=generation._json(row),
                origin=source,
                owner_json=owner._json,
                operation_id=request_id if native else None,
            )
            body["fingerprint"] = claim_content.hashed(body)
            encoded = generation._json(body)
            validate_record(dict(request_id=request_id, body_json=encoded))
            with sync_capture.suppress_capture(conn):
                conn.execute(SCHEMA)
            count, size = conn.execute(
                "SELECT count(*),COALESCE(sum(length(CAST(body_json AS BLOB))),0) FROM " + TABLE
            ).fetchone()
            if count >= MAX_ACTIONS or size + len(encoded.encode()) > MAX_HISTORY:
                raise ValueError("Lineage lifecycle history capacity reached")
            if native:
                client = conn._capture_client
                if action == "retire":
                    operation = client.new_graph_operation_in(
                        conn,
                        "research_content",
                        template["entity_id"],
                        {},
                        action="delete",
                        operation_id=request_id,
                    )
                else:
                    state = client._optimistic_graph(conn)[0].get(
                        ("research_content", template["entity_id"])
                    )
                    if state is None or state["active"]:
                        raise ValueError(
                            "Restore requires the explicitly retired scientific entity"
                        )
                    operation = client._new_graph_operation(
                        conn,
                        "research_content",
                        template["entity_id"],
                        template["payload"],
                        operation_id=request_id,
                        restore=True,
                        lineage_template=template,
                    )

                def write(c, op):
                    client._guard_content_parent(c, op)
                    client.writer(c, op)

                client.journal.apply_in(conn, operation, write)
            else:
                with sync_capture.suppress_capture(conn):
                    if action == "retire":
                        conn.execute(
                            "DELETE FROM paper_lineage_sets WHERE paper_id=? AND corpus_key=?",
                            (owner.paper_id, row["corpus_key"]),
                        )
                    else:
                        if not lineage_capacity.local_room_in(
                            conn, owner.paper_id, row["corpus_key"]
                        ):
                            raise ValueError("Lineage restore capacity reached")
                        conn.execute(
                            "INSERT INTO paper_lineage_sets VALUES(?,?,?,?,?,?)",
                            tuple(row[key] for key in lineage_sets.COLUMNS.split()),
                        )
            with sync_capture.suppress_capture(conn):
                conn.execute("INSERT INTO " + TABLE + " VALUES(?,?)", (request_id, encoded))
            owner.check(conn)
            if action == "restore":
                _origin_in(conn, owner, row, source, sources=True)
            applied = True
        if cancelled():
            raise ValueError("Lineage lifecycle cancelled")
        conn.execute("RELEASE " + savepoint)
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK TO " + savepoint)
            conn.execute("RELEASE " + savepoint)
        if hasattr(conn, "_capture_graph_cache"):
            conn._capture_graph_cache = None
        raise
    return dict(
        state="queued_sync" if body["operation_id"] else "saved_local",
        request_id=request_id,
        operation_id=body["operation_id"],
        action=action,
        applied=applied,
    )


def change(owner, row, *, request_id, action, origin=None, cancelled=lambda: False):
    """Worker convenience boundary; no model, file hashing, download or identity minting."""
    _worker()
    if not isinstance(owner, HighlightOwner):
        raise ValueError("Lineage lifecycle requires its loaded owner")
    with closing(generation._connect(owner.database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = apply_in(
                conn,
                owner,
                row,
                request_id=request_id,
                action=action,
                origin=origin,
                cancelled=cancelled,
            )
            conn.commit()
            return result
        except BaseException:
            conn.rollback()
            raise


def history(owner, *, limit=100):
    """Read local lifecycle evidence only; returned origins are not restore grants."""
    _worker()
    if not isinstance(owner, HighlightOwner):
        raise ValueError("Lineage history requires its loaded owner")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid Lineage history page size")
    with closing(_readonly_connection(owner.database)) as conn:
        conn.execute("BEGIN")
        owner.check(conn)
        if not _exists(conn):
            return dict(items=[], more=False)
        count, size, largest = conn.execute(
            "SELECT count(*),COALESCE(sum(length(CAST(body_json AS BLOB))),0),"
            "COALESCE(max(length(CAST(body_json AS BLOB))),0) FROM " + TABLE
        ).fetchone()
        if count > MAX_ACTIONS or size > MAX_HISTORY or largest > MAX_RECORD:
            raise ValueError("Lineage lifecycle history exceeds its bound")
        rows = conn.execute(
            "SELECT request_id,CASE WHEN length(CAST(body_json AS BLOB))<=? THEN body_json END "
            "FROM " + TABLE + " ORDER BY rowid DESC LIMIT ?",
            (MAX_RECORD, MAX_ACTIONS + 1),
        ).fetchall()
        if len(rows) > MAX_ACTIONS:
            raise ValueError("Lineage lifecycle history exceeds its bound")
        items = []
        for identity, encoded in rows:
            body = validate_record(dict(request_id=identity, body_json=encoded))
            row = json.loads(body["row_json"])
            if row["paper_id"] != owner.paper_id:
                continue
            current = lineage_projection._current(conn, owner.paper_id, row["corpus_key"])
            items.append(
                dict(
                    request_id=identity,
                    action=body["action"],
                    row=row,
                    origin=body["origin"],
                    current=current == row,
                )
            )
        return dict(items=items[:limit], more=len(items) > limit)
