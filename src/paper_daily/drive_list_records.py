"""Apply list records with a device-local base and an independent receipt for each list."""

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime

from paper_daily.drive_list_history import DriveListHistory
from paper_daily.drive_sync_files import decode, encode
from paper_daily.library_directory import ScopeHead
from paper_daily.workspace_service import _read


class ListReviewRequired(ValueError):
    """An individual list needs review before its exchange can continue."""


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
    conn.execute(
        "CREATE TABLE IF NOT EXISTS list_record_sends("
        "list_id TEXT,op TEXT,parent BLOB,generation INTEGER,name_hash TEXT,note_hash TEXT,"
        "PRIMARY KEY(list_id,op))"
    )
    row = conn.execute(
        "SELECT head,digest FROM list_record_receipts WHERE list_id=?", (list_id,)
    ).fetchone()
    if row is None:
        return None, None
    return ScopeHead(**decode(row[0])), row[1]


def _acknowledged(conn, changes, store, list_id, local):
    for op in reversed(changes):
        sent = conn.execute(
            "SELECT parent,generation,name_hash,note_hash FROM list_record_sends "
            "WHERE list_id=? AND op=?", (list_id, op["operation_id"])
        ).fetchone()
        if sent is None:
            continue
        parent = decode(sent[0])
        accepted = op["payload"]
        token = _digest([store.context, list_id, parent, _digest(accepted)])
        if (op["operation_id"] != token or op["device_id"] != store.context
                or op["base_revision"] != sent[1]):
            raise ListReviewRequired("The list upload does not match its local receipt")
        if local is None:
            raise ListReviewRequired("Published list removed locally; review before restoring")
        # A remote field merged into our upload may never have reached the local database.
        effective = {key: accepted[key] if _digest(local[key]) == old_hash else local[key]
                     for key, old_hash in zip(("name", "note"), sent[2:], strict=True)}
        return accepted, effective
    return None, local


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
        raise ListReviewRequired("List retirement requires review")
    remote = changes[-1]["payload"] if changes else None
    original, effective = None, local
    if changes:
        with closing(sqlite3.connect(store.path, timeout=0.5)) as private:
            original, effective = _acknowledged(private, changes, store, list_id, local)
    merge_base = _digest(original) if original is not None else base
    if local is None and base is not None:
        raise ListReviewRequired("A retained list was removed locally; review before restoring")
    target = remote if remote is not None else local
    if (remote is not None and effective is not None
            and remote != effective and _digest(effective) != merge_base):
        if original is None and anchor:
            original = history.applied_payload(anchor, revision=revision)
        if original is None or _digest(original) != merge_base:
            raise ListReviewRequired("No verified common list details; both versions were retained")
        target = dict(remote)
        for field in ("name", "note"):
            if effective[field] == original[field]:
                continue
            if remote[field] != original[field] and remote[field] != effective[field]:
                raise ListReviewRequired(f"Conflicting list {field}; both versions were retained")
            target[field] = effective[field]
    if target is None:
        return "waiting_source"
    digest = _digest(target)
    if (remote is None and digest != base) or (remote is not None and target != remote):
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
        with closing(sqlite3.connect(store.path, timeout=0.5)) as private, private:
            private.execute("BEGIN IMMEDIATE")
            ticket.check()
            store._check()
            if store._load(private).revision != revision or _receipt(private, list_id) != (
                anchor, base
            ):
                raise ValueError("List sync context changed before upload; retry")
            parent = encode(head.record() if head else None)
            row = (parent, op["base_revision"], _digest(local["name"]), _digest(local["note"]))
            private.execute("INSERT OR IGNORE INTO list_record_sends VALUES(?,?,?,?,?,?)",
                            (list_id, token, *row))
            if private.execute(
                "SELECT parent,generation,name_hash,note_hash FROM list_record_sends "
                "WHERE list_id=? AND op=?", (list_id, token)
            ).fetchone() != row:
                raise ListReviewRequired("Concurrent list edits require review")
        head = history.append(head, [op], revision=revision)
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
        private.execute("DELETE FROM list_record_sends WHERE list_id=? AND generation<?",
                        (list_id, head.generation))
    return "updated"
