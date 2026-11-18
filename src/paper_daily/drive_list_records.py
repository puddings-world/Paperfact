"""Apply list records with a device-local base and an independent receipt for each list."""

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime

from paper_daily.drive_list_history import DriveListHistory
from paper_daily.drive_sync_files import decode, encode
from paper_daily.library_directory import ScopeHead
from paper_daily.workspace_service import _read


def _digest(payload):
    return hashlib.sha256(encode(payload)).hexdigest()


def _payload(conn, identity):
    row = conn.execute("SELECT name,note FROM lists WHERE id=?", (identity,)).fetchone()
    return {"name": row[0], "note": row[1] or ""} if row else None


def _receipt(conn, list_id):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS list_record_receipts("
        "list_id TEXT PRIMARY KEY,head BLOB NOT NULL,digest TEXT NOT NULL)"
    )
    row = conn.execute(
        "SELECT head,digest FROM list_record_receipts WHERE list_id=?", (list_id,)
    ).fetchone()
    if row is None:
        return None, None
    return ScopeHead(**decode(row[0])), row[1]


def exchange_list(directory, store, list_id, revision, ticket):
    """Transfer only a list's name/description, retaining both sides on conflict."""
    history = DriveListHistory(directory, store, list_id)
    history._check(revision)
    with closing(sqlite3.connect(store.path, timeout=0.5)) as private:
        anchor, base = _receipt(private, list_id)
    with _read(store.workspace.path) as research:
        if research.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_capture_binding'"
        ).fetchone():
            raise ValueError("Review the existing sync workspace before adopting it")
        local = _payload(research, list_id)
    head, changes = history.changes(anchor, revision=revision)
    if any(op["action"] != "put" for op in changes):
        raise ValueError("List retirement requires review")
    remote = changes[-1]["payload"] if changes else None
    if local is None and base is not None:
        raise ValueError("A retained list was removed locally; review before restoring")
    if remote is not None and local is not None and remote != local and _digest(local) != base:
        raise ValueError("Both copies have different list details; both versions were retained")
    target = remote if remote is not None else local
    if target is None:
        return "waiting_source"
    digest = _digest(target)
    if remote is None and digest != base:
        token = _digest([store.context, list_id, head.record() if head else None, digest])
        op = dict(
            version=1,
            operation_id=token,
            workspace_id=directory.library_id,
            device_id=store.context,
            entity_type="list",
            entity_id=list_id,
            action="put",
            base_revision=head.generation if head else 0,
            depends_on=None,
            payload=target,
        )
        head = history.append(anchor, [op], revision=revision)
    if head == anchor and digest == base:
        return "current"
    # A receipt is committed last. After a crash the exact local payload can be
    # recognized on retry. A genuinely divergent edit is retained for review.
    with closing(sqlite3.connect(store.path, timeout=0.5)) as private, private:
        private.execute("BEGIN IMMEDIATE")
        ticket.check()
        store._check()
        if store._load(private).revision != revision or _receipt(private, list_id) != (
            anchor,
            base,
        ):
            raise ValueError("Device settings or the applied history changed; retry")
        with (
            closing(
                sqlite3.connect(store.workspace.path.as_uri() + "?mode=rw", uri=True, timeout=0.5)
            ) as research,
            research,
        ):
            research.execute("BEGIN IMMEDIATE")
            if _payload(research, list_id) != local:
                raise ValueError("List changed on this device while syncing; retry")
            if target != local:
                if local is None:
                    research.execute(
                        "INSERT INTO lists(id,name,note,created_at) VALUES(?,?,?,?)",
                        (
                            list_id,
                            target["name"],
                            target["note"],
                            datetime.now(UTC).isoformat(timespec="seconds"),
                        ),
                    )
                else:
                    research.execute(
                        "UPDATE lists SET name=?,note=? WHERE id=?",
                        (target["name"], target["note"], list_id),
                    )
            store._check()
            ticket.checkpoint(research.commit)
        private.execute(
            "INSERT INTO list_record_receipts VALUES(?,?,?) ON CONFLICT(list_id) "
            "DO UPDATE SET head=excluded.head,digest=excluded.digest",
            (list_id, encode(head.record()), digest),
        )
    return "updated"
