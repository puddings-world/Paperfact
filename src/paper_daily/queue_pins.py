"""Explicit paper-scoped queue-pin intent; caller owns transaction and commit."""

from paper_daily import store
from paper_daily.sync_capture import observe_target, suppress_capture
from paper_daily.sync_content import content_id, pin_cleanup_ready


def set_enrolled(conn, local_paper_id, on, *, expected=None, pinned_at=None):
    if not pin_cleanup_ready(conn):
        raise ValueError("Queue pin cleanup requires explicit installation")
    current = observe_target(conn, "paper", local_paper_id, "queue_pin")
    if expected is not None and current != expected:
        raise ValueError("Pin target changed; choose the current paper again")
    if not conn.execute("SELECT 1 FROM papers WHERE id=?", (local_paper_id,)).fetchone():
        raise ValueError("Pin paper no longer exists")
    if len(current["parents"]) != 1 or not current["parents"][0]["active"]:
        raise ValueError("Pin requires its current active paper")
    portable = current["parents"][0]["id"]
    payload = {
        "scope": {"kind": "paper", "id": portable},
        "feature": "queue_pin",
        "key": "main",
        "data": {"pinned_at": pinned_at or store.now()},
        "source_document_hash": None,
    }
    client = conn._capture_client
    graph = client._optimistic_graph(conn)[0]
    identity = content_id(payload["scope"], "queue_pin", "main")
    old = graph.get(("research_content", identity))
    wanted = [{key: current["parents"][0][key] for key in ("kind", "id", "incarnation")}]
    live = bool(
        old and old["active"] and client._parent_keys(old["parents"]) == client._parent_keys(wanted)
    )
    existing = conn.execute(
        "SELECT pinned_at FROM pins WHERE scope='queue' AND paper_id=?", (local_paper_id,)
    ).fetchone()
    if on and live and existing is not None:
        return {"changed": False, "pinned": True, "operation_id": None}
    if not on and not live:
        with suppress_capture(conn):
            conn.execute("DELETE FROM pins WHERE scope='queue' AND paper_id=?", (local_paper_id,))
        return {"changed": existing is not None, "pinned": False, "operation_id": None}
    operation = client.new_graph_operation_in(
        conn,
        "research_content",
        identity,
        payload if on else {},
        action="put" if on else "delete",
        restore=bool(on and old is not None and not live),
    )
    client.journal.apply_in(conn, operation, client.writer)
    return {"changed": True, "pinned": on, "operation_id": operation["operation_id"]}


IMPORT_FIELDS = {
    "package_sha256",
    "source_owner",
    "receiver_owner",
    "incoming_pinned_at",
    "receiver_pinned_at",
}


def validate_import_record(record):
    from paper_daily.sync_content import _hash, _stamp, _text

    if not isinstance(record, dict) or set(record) != IMPORT_FIELDS:
        raise ValueError("Unknown queue-pin import provenance")
    _hash(record["package_sha256"])
    for field in ("source_owner", "receiver_owner"):
        _text(record[field], 4096, nullable=False, nonempty=True)
    for field in ("incoming_pinned_at", "receiver_pinned_at"):
        _stamp(record[field])
    if record["incoming_pinned_at"] == record["receiver_pinned_at"]:
        raise ValueError("Identical pins require no conflict provenance")


def retain_imports_in(conn, records):
    from paper_daily.enrollment_history import MAX_RECORDS, MAX_TOTAL, archived, retain_in, wrap

    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ValueError("Queue-pin import history exceeds its record bound")
    if not records:
        return
    incoming = [wrap("queue_pin_import_v1", row) for row in records]
    combined = {row["record_id"]: row for row in archived(conn)}
    for row in incoming:
        prior = combined.get(row["record_id"])
        if prior is not None and prior != row:
            raise ValueError("Queue-pin import history identity was reused")
        combined[row["record_id"]] = row
    if (
        len(combined) > MAX_RECORDS
        or sum(len(row["body_json"].encode()) for row in combined.values()) > MAX_TOTAL
    ):
        raise ValueError("Queue-pin import history exceeds its aggregate bound")
    retain_in(conn, incoming)
