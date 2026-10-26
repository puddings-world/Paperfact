"""Opt-in list/text-note persistence for the experimental sync contract.

No runtime configuration, provider, or network imports. Existing app writers do
not call this adapter yet. Callers own conflict checks and the transaction.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from paper_daily.sync_journal import _identifier, canonical_operation

_REQUIRED = {
    "papers": {"id"},
    "lists": {"id", "name", "note", "created_at"},
    "list_papers": {"list_id", "paper_id"},
    "notes": {"id", "paper_id", "body", "created_at", "kind", "page", "anchor"},
}


def initialize(conn: sqlite3.Connection, *, workspace_id: str, device_id: str) -> None:
    """Add portable note identities inside an already-open caller transaction.

    The device distinguishes independent legacy integer IDs within one workspace.
    Existing mappings travel with a bootstrap snapshot; never remap them on join.
    This does not create the research schema or alter a legacy note.
    """
    _identifier(workspace_id)
    _identifier(device_id)
    if not conn.in_transaction:
        raise ValueError("Research initialization requires a caller transaction")
    for table, required in _REQUIRED.items():
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not required <= columns:
            raise ValueError("An initialized, compatible research database is required")
    conn.execute("SAVEPOINT research_adapter_init")
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_sync_binding ("
            "id INTEGER PRIMARY KEY CHECK(id=1),workspace TEXT NOT NULL,origin TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO research_sync_binding VALUES(1,?,?)",
            (workspace_id, device_id),
        )
        binding = conn.execute("SELECT workspace,origin FROM research_sync_binding WHERE id=1")
        if tuple(binding.fetchone()) != (workspace_id, device_id):
            raise ValueError(
                "Research workspace/device binding differs; explicit enrollment required"
            )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_note_identity ("
            "sync_id TEXT PRIMARY KEY,local_id INTEGER UNIQUE,paper_id TEXT NOT NULL,"
            "created_at TEXT NOT NULL)"
        )
        namespace = uuid5(NAMESPACE_URL, f"paperfact:{workspace_id}:{device_id}:notes")
        rows = conn.execute(
            "SELECT id,paper_id,created_at FROM notes "
            "WHERE id NOT IN (SELECT local_id FROM research_note_identity "
            "WHERE local_id IS NOT NULL)"
        ).fetchall()
        for local_id, paper_id, created_at in rows:
            # A deleted mapping never rebinds an integer ID reused by another writer.
            sync_id = str(uuid5(namespace, f"{local_id}:{paper_id}:{created_at}"))
            conn.execute(
                "INSERT INTO research_note_identity VALUES(?,?,?,?)",
                (sync_id, local_id, paper_id, created_at),
            )
        conn.execute("RELEASE SAVEPOINT research_adapter_init")
    except BaseException:
        conn.execute("ROLLBACK TO SAVEPOINT research_adapter_init")
        conn.execute("RELEASE SAVEPOINT research_adapter_init")
        raise


def prepare(path: Path, *, workspace_id: str, device_id: str) -> None:
    """Prepare an existing database explicitly; never create an empty database by typo."""
    uri = Path(path).resolve().as_uri() + "?mode=rw"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        conn.execute("BEGIN IMMEDIATE")
        initialize(conn, workspace_id=workspace_id, device_id=device_id)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def note_identity(conn: sqlite3.Connection, local_id: int) -> str:
    """Look up an enrolled local note; callers must not use its integer ID on the wire."""
    if type(local_id) is not int or local_id <= 0:
        raise ValueError("Invalid local note ID")
    row = conn.execute(
        "SELECT sync_id FROM research_note_identity WHERE local_id=?", (local_id,)
    ).fetchone()
    if row is None:
        raise ValueError("Note is not enrolled in this research adapter")
    return row[0]


def _plain_note(conn, mapping):
    row = conn.execute(
        "SELECT paper_id,created_at,kind,page,anchor FROM notes WHERE id=?", (mapping[0],)
    ).fetchone()
    if row is None or tuple(row[:2]) != tuple(mapping[1:]):
        raise ValueError("Mapped note changed outside the adapter; reconciliation required")
    if row[2] != "note" or row[3] is not None or row[4] is not None:
        raise ValueError("Anchored and non-text notes are not supported by this contract")


def _write_note(conn, value):
    sync_id, payload = value["entity_id"], value["payload"]
    mapping = conn.execute(
        "SELECT local_id,paper_id,created_at FROM research_note_identity WHERE sync_id=?",
        (sync_id,),
    ).fetchone()
    if mapping is not None and mapping[0] is not None:
        _plain_note(conn, mapping)
    if value["action"] == "delete":
        if mapping is not None and mapping[0] is not None:
            conn.execute("DELETE FROM notes WHERE id=?", (mapping[0],))
            conn.execute(
                "UPDATE research_note_identity SET local_id=NULL WHERE sync_id=?", (sync_id,)
            )
        return
    paper_id = payload["paper_id"]
    if mapping is not None and mapping[1] != paper_id:
        raise ValueError("An existing note cannot be reassigned to another paper")
    if conn.execute("SELECT 1 FROM papers WHERE id=?", (paper_id,)).fetchone() is None:
        raise ValueError("Paper metadata must be synchronized before its notes")
    if mapping is not None and mapping[0] is not None:
        conn.execute("UPDATE notes SET body=? WHERE id=?", (payload["body"], mapping[0]))
        return
    created_at = (
        mapping[2] if mapping is not None else datetime.now(UTC).isoformat(timespec="seconds")
    )
    inserted = conn.execute(
        "INSERT INTO notes(paper_id,body,created_at,kind) VALUES(?,?,?,'note')",
        (paper_id, payload["body"], created_at),
    )
    conn.execute(
        "INSERT INTO research_note_identity VALUES(?,?,?,?) "
        "ON CONFLICT(sync_id) DO UPDATE SET local_id=excluded.local_id",
        (sync_id, inserted.lastrowid, paper_id, created_at),
    )


def research_writer(conn: sqlite3.Connection, operation: dict) -> None:
    """Apply one validated list/note mutation without committing or invoking AI.

    Use as Journal.apply's callback or in a remote-apply transaction after conflict
    resolution. Device ID may differ on remote apply, but workspace must match.
    This function does not suppress retries or decide whether stale writes win.
    """
    canonical_operation(operation)
    if not conn.in_transaction:
        raise ValueError("Research writes require a caller transaction")
    binding = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
    if binding is None or binding[0] != operation["workspace_id"]:
        raise ValueError("Research operation belongs to another workspace")
    if operation["entity_type"] == "note":
        _write_note(conn, operation)
        return
    identity, payload = operation["entity_id"], operation["payload"]
    if operation["action"] == "delete":
        # List removal never deletes papers, notes, analyses or other memberships.
        conn.execute("DELETE FROM list_papers WHERE list_id=?", (identity,))
        conn.execute("DELETE FROM lists WHERE id=?", (identity,))
        return
    conn.execute(
        "INSERT INTO lists(id,name,note,created_at) VALUES(?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name,note=excluded.note",
        (
            identity,
            payload["name"],
            payload["note"],
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )
