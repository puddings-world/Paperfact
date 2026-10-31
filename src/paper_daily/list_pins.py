"""Explicit per-list pin intent, separate from device-local offline retention.

The caller owns transaction/commit. A current UI toggle may explicitly restore
its current membership's pin; arbitrary SQL cannot revive an old tombstone.
"""

from __future__ import annotations

from paper_daily import store
from paper_daily.sync_capture import enabled, install, observe_target, suppress_capture
from paper_daily.sync_content import _stamp, content_id, parent_identities, pin_cleanup_ready
from paper_daily.sync_schema_v2 import membership_id


def set_pinned(conn, scope, local_paper_id, on, *, expected=None, pinned_at=None):
    if type(on) is not bool:
        raise ValueError("Pin state must be a boolean")
    if not isinstance(scope, str) or not scope or not isinstance(local_paper_id, str):
        raise ValueError("Select a list and paper")
    if on and pinned_at is not None:
        _stamp(pinned_at)
    if (
        not enabled(conn)
        and conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name IN "
            "('research_capture_binding','research_sync_binding','paperfact_sync_identity') LIMIT 1"
        ).fetchone()
    ):
        raise ValueError("An enrolled pin action requires its CaptureConnection")
    if scope == "queue" and not pin_cleanup_ready(conn):
        raise ValueError(
            "Queue pin cleanup requires explicit installation or a fresh editable copy"
        )
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    existing = conn.execute(
        "SELECT pinned_at FROM pins WHERE scope=? AND paper_id=?", (scope, local_paper_id)
    ).fetchone()
    member = conn.execute(
        "SELECT 1 FROM list_papers lp JOIN lists l ON l.id=lp.list_id "
        "JOIN papers p ON p.id=lp.paper_id WHERE lp.list_id=? AND lp.paper_id=?",
        (scope, local_paper_id),
    ).fetchone()
    if not enabled(conn):
        if on and scope != "queue" and member is None:
            raise ValueError("Pin requires a paper in the selected list")
        if on:
            stamp = pinned_at or store.now()
            _stamp(stamp)
            cursor = conn.execute(
                "INSERT OR IGNORE INTO pins VALUES(?,?,?)", (scope, local_paper_id, stamp)
            )
        else:
            cursor = conn.execute(
                "DELETE FROM pins WHERE scope=? AND paper_id=?", (scope, local_paper_id)
            )
        return {"changed": bool(cursor.rowcount), "pinned": on, "operation_id": None}
    if scope == "queue":
        from paper_daily.queue_pins import set_enrolled

        return set_enrolled(conn, local_paper_id, on, expected=expected, pinned_at=pinned_at)
    if member is None:
        raise ValueError("Pin requires a current list membership")
    portable = conn.execute(
        "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (local_paper_id,)
    ).fetchone()
    if portable is None:
        raise ValueError("Pin paper is not enrolled")
    portable = portable[0]
    current = observe_target(conn, "list", scope, "list_pin", portable)
    if expected is not None and current != expected:
        raise ValueError("Pin target or membership changed; choose the current paper again")
    client = conn._capture_client
    graph = client._optimistic_graph(conn)[0]
    member_id = membership_id(scope, portable)
    # Validates membership's complete exact root closure, not just its UUID.
    client._reading_parents(graph, member_id)
    if not pin_cleanup_ready(conn):
        journal = conn._capture_client.journal
        install(conn, workspace_id=journal.workspace_id, device_id=journal.device_id)
        if not pin_cleanup_ready(conn):
            raise ValueError("List pin cleanup schema requires explicit repair")
    payload = {
        "scope": {"kind": "list", "id": scope},
        "feature": "list_pin",
        "key": portable,
        "data": {"pinned_at": pinned_at or store.now()},
        "source_document_hash": None,
    }
    wanted = [
        {"kind": kind, "id": identity, "incarnation": graph[(kind, identity)]["incarnation"]}
        for kind, identity in parent_identities(payload)
    ]
    identity = content_id(payload["scope"], "list_pin", portable)
    old = graph.get(("research_content", identity))
    live = bool(
        old and old["active"] and client._parent_keys(old["parents"]) == client._parent_keys(wanted)
    )
    if on and live and existing is not None:
        return {"changed": False, "pinned": True, "operation_id": None}
    if not on and not live:
        # Explicit clear may remove a stale local row; an obsolete membership
        # cannot be restored merely to manufacture a portable pin deletion.
        with suppress_capture(conn):
            conn.execute("DELETE FROM pins WHERE scope=? AND paper_id=?", (scope, local_paper_id))
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
