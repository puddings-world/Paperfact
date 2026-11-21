"""Reconcile ordinary list reading markers against their last accepted Drive operations."""

import hashlib
import sqlite3
from contextlib import closing

from paper_daily.drive_list_history import DriveListReading
from paper_daily.drive_list_records import ListReviewRequired
from paper_daily.drive_sync_files import encode
from paper_daily.native_primary_publication import _WORKSPACE_MARKERS
from paper_daily.sync_journal import canonical_operation
from paper_daily.workspace_service import _tables

FIELDS = ("state", "delivered_at", "read_at")
DEFAULT = ("pending", None, None)


def _values(op):
    return tuple(op["payload"][field] for field in FIELDS)


def _operation(history, identity, values, previous):
    refs = history.parents[identity]
    payload = dict(
        list_id=history.list_id,
        paper_id=refs["paper"]["id"],
        **dict(zip(FIELDS, values, strict=True)),
    )
    op = dict(
        version=2,
        workspace_id=history.store.library_id,
        device_id=history.store.context,
        entity_type="reading_state",
        entity_id=identity,
        incarnation=refs["membership"]["incarnation"],
        parents=list(refs.values()),
        action="put",
        structure_revision=0,
        base_revision=previous["base_revision"] + 1 if previous else 0,
        depends_on=previous["operation_id"] if previous else None,
        payload=payload,
    )
    op["operation_id"] = hashlib.sha256(encode(op)).hexdigest()
    canonical_operation(op)
    return op


def exchange_reading(directory, store, list_id, revision, ticket):
    history = DriveListReading(directory, store, list_id, revision=revision)
    head, records = history.changes(None, revision=revision)
    latest, versions = {}, {}
    for op in records:
        identity = op["entity_id"]
        prev = latest.get(identity)
        if (
            op["depends_on"] != (prev["operation_id"] if prev else None)
            or op["base_revision"] != (prev["base_revision"] + 1 if prev else 0)
            or op["structure_revision"]
            or op["operation_id"] in versions
        ):
            raise ListReviewRequired("Reading progress history needs review")
        latest[identity] = versions[op["operation_id"]] = op
    if not history.parents:
        return []
    pending, conflicts = [], []
    with closing(sqlite3.connect(store.path, timeout=0.5)) as settings, settings:
        settings.execute("BEGIN IMMEDIATE")
        history._check(revision)
        local_ids = dict(settings.execute("SELECT remote_id,local_id FROM published_paper_ids"))
        uri = store.workspace.path.as_uri() + "?mode=rw"
        with closing(sqlite3.connect(uri, uri=True, timeout=0.5)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if _tables(conn) & _WORKSPACE_MARKERS:
                raise ListReviewRequired("Use enrolled workspace sync for reading progress")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS drive_reading_bases(context TEXT,list_id TEXT,"
                "member TEXT,op TEXT NOT NULL,PRIMARY KEY(context,list_id,member))"
            )
            bases = dict(
                conn.execute(
                    "SELECT member,op FROM drive_reading_bases WHERE context=? AND list_id=?",
                    (store.context, list_id),
                )
            )
            rows = {
                r[0]: r[1:]
                for r in conn.execute(
                    "SELECT paper_id,state,delivered_at,read_at FROM list_papers WHERE list_id=?",
                    (list_id,),
                )
            }
            for identity, refs in history.parents.items():
                ticket.check()
                local = local_ids.get(refs["paper"]["id"])
                if local not in rows:
                    raise ListReviewRequired("Refresh the bibliography before reading progress")
                values, current, base = (
                    rows[local],
                    latest.get(identity),
                    versions.get(bases.get(identity)),
                )
                if identity in bases and (not base or base["entity_id"] != identity):
                    raise ListReviewRequired("A previously accepted reading revision is missing")
                if current is None or current is base:
                    if values != (_values(current) if current else DEFAULT):
                        pending.append((local, _operation(history, identity, values, current)))
                    continue
                if values != _values(current):
                    lost_receipt = base is None and current["device_id"] == store.context
                    if lost_receipt or values != (_values(base) if base else DEFAULT):
                        conflicts.append(local)
                        continue
                    conn.execute(
                        "UPDATE list_papers SET state=?,delivered_at=?,read_at=? "
                        "WHERE list_id=? AND paper_id=?",
                        (*_values(current), list_id, local),
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO drive_reading_bases VALUES(?,?,?,?)",
                    (store.context, list_id, identity, current["operation_id"]),
                )
            store._check()
            ticket.checkpoint(conn.commit)
    if not pending:
        return conflicts
    batches = (len(pending) + 99) // 100
    size = sum(len(encode(op)) + 1 for op in records) + sum(
        len(encode(op)) + 1 for _, op in pending
    )
    if (head.generation if head else 0) + batches > 100 or size + (
        (head.generation if head else 0) + batches
    ) * 2048 > 8 * 1024**2:
        raise ListReviewRequired("Reading progress exceeds the supported history budget")
    with closing(sqlite3.connect(uri, uri=True, timeout=0.5)) as conn:
        generation = conn.execute("PRAGMA data_version").fetchone()

        def check_source():
            ticket.check()
            if conn.execute("PRAGMA data_version").fetchone() != generation:
                raise ListReviewRequired("Reading progress changed during upload; retry")

        if _tables(conn) & _WORKSPACE_MARKERS:
            raise ListReviewRequired("Workspace changed during reading sync")
        history.check_source = check_source
        for start in range(0, len(pending), 100):
            batch = pending[start : start + 100]
            for local, op in batch:
                row = conn.execute(
                    "SELECT state,delivered_at,read_at FROM list_papers "
                    "WHERE list_id=? AND paper_id=?",
                    (list_id, local),
                ).fetchone()
                if row != _values(op):
                    raise ListReviewRequired("Reading progress changed before upload; retry")
            head = history.append(head, [op for _, op in batch], revision=revision)
        check_source()
    # Record our publication before another local edit can be mistaken for a remote conflict.
    with closing(sqlite3.connect(store.path, timeout=0.5)) as settings, settings:
        settings.execute("BEGIN IMMEDIATE")
        history.check_source = None
        history._check(revision)
        with closing(sqlite3.connect(uri, uri=True, timeout=0.5)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if _tables(conn) & _WORKSPACE_MARKERS:
                raise ListReviewRequired("Workspace changed before acknowledging reading progress")
            for _, op in pending:
                key = (store.context, list_id, op["entity_id"])
                existing = conn.execute(
                    "SELECT op FROM drive_reading_bases WHERE context=? AND list_id=? AND member=?",
                    key,
                ).fetchone()
                if existing == ((op["depends_on"],) if op["depends_on"] else None):
                    conn.execute(
                        "INSERT OR REPLACE INTO drive_reading_bases VALUES(?,?,?,?)",
                        (*key, op["operation_id"]),
                    )
            store._check()
            ticket.checkpoint(conn.commit)
    return conflicts
