"""Reconcile ordinary list reading markers against their last accepted Drive operations."""

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import dataclass

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
    refs = history.parents_for(identity)
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


def _versions(records):
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
    return latest, versions


@dataclass(frozen=True)
class _ObservedReading:
    latest: dict
    versions: dict
    size: int


def _observe(history, revision):
    history._check(revision)
    head = history._current_head()
    files = history.directory.files
    key = (history.store.context, history.directory.folder, history.directory.head,
           history.list_id, history.paper_head, history.grant, revision, head)
    with files.membership_lock:
        snapshot = files.reading_cache.get(key)
    if snapshot is None:
        records = history._since(head, None, revision)
        latest, versions = _versions(records)
        size = sum(len(encode(op)) + 1 for op in records)
        snapshot = _ObservedReading(latest, versions, size)
        if records and size <= 2 * 1024**2:
            with files.membership_lock:
                cache = files.reading_cache
                for stale in list(cache):
                    if stale[:4] == key[:4]:
                        del cache[stale]
                while len(cache) >= 16 or sum(v.size for v in cache.values()) + size > 2 * 1024**2:
                    del cache[next(iter(cache))]
                cache[key] = snapshot
    history._check(revision)
    return head, snapshot


def _divergent(values, current, base, context):
    if current is None or current is base or values == _values(current):
        return False
    lost_receipt = base is None and current["device_id"] == context
    return lost_receipt or values != (_values(base) if base else DEFAULT)


def exchange_reading(directory, store, list_id, revision, ticket):
    history = DriveListReading(directory, store, list_id, revision=revision)
    head, snapshot = _observe(history, revision)
    latest, versions = snapshot.latest, snapshot.versions
    if not history.memberships:
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
            for identity, membership in history.memberships.items():
                ticket.check()
                local = local_ids.get(membership[0])
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
                    if _divergent(values, current, base, store.context):
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
    size = snapshot.size + sum(
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


def review_reading(directory, store, list_id, revision, ticket, decision=None):
    if decision is not None and decision[1] not in ("local", "remote"):
        raise ValueError("Choose an observed reading progress version")
    history = DriveListReading(directory, store, list_id, revision=revision)
    _, snapshot = _observe(history, revision)
    latest, versions = snapshot.latest, snapshot.versions
    cards = []
    uri = store.workspace.path.as_uri() + ("?mode=rw" if decision else "?mode=ro")
    with closing(sqlite3.connect(store.path, timeout=0.5)) as settings, settings:
        settings.execute("BEGIN IMMEDIATE")
        history._check(revision)
        with closing(sqlite3.connect(uri, uri=True, timeout=0.5)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE" if decision else "BEGIN")
            tables = _tables(conn)
            if tables & _WORKSPACE_MARKERS:
                raise ListReviewRequired("Workspace binding changed")
            if "drive_reading_bases" in tables:
                for identity, op in latest.items():
                    ticket.check()
                    if decision and decision[0]["identity"] != identity:
                        continue
                    mapped = settings.execute(
                        "SELECT local_id FROM published_paper_ids WHERE remote_id=?",
                        (op["payload"]["paper_id"],),
                    ).fetchone()
                    if not mapped:
                        continue
                    row = conn.execute(
                        "SELECT p.title,m.state,m.delivered_at,m.read_at,b.op FROM list_papers m "
                        "JOIN papers p ON p.id=m.paper_id LEFT JOIN drive_reading_bases b "
                        "ON b.context=? AND b.list_id=m.list_id AND b.member=? "
                        "WHERE m.list_id=? AND m.paper_id=?",
                        (store.context, identity, list_id, mapped[0]),
                    ).fetchone()
                    if not row:
                        continue
                    base = versions.get(row[4])
                    if row[4] and (not base or base["entity_id"] != identity):
                        raise ListReviewRequired("Common reading revision is missing")
                    if not _divergent(row[1:4], op, base, store.context):
                        continue
                    cards.append(
                        dict(
                            feature="reading",
                            title=row[0],
                            identity=identity,
                            key=mapped[0],
                            list_id=list_id,
                            context=store.context,
                            grant=history.grant,
                            remote_id=op["operation_id"],
                            base_id=row[4],
                            base=dict(zip(FIELDS, _values(base), strict=True)) if base else None,
                            local=dict(zip(FIELDS, row[1:4], strict=True)),
                            remote=dict(zip(FIELDS, _values(op), strict=True)),
                        )
                    )
            store._check()
            ticket.check()
            if decision is None:
                return cards
            if cards != [decision[0]]:
                raise ValueError("Reading progress changed after review; compare again")
            card = cards[0]
            if decision[1] == "remote":
                data = card["remote"]
                conn.execute(
                    "UPDATE list_papers SET state=?,delivered_at=?,read_at=? "
                    "WHERE list_id=? AND paper_id=?",
                    (data["state"], data["delivered_at"], data["read_at"], list_id, card["key"]),
                )
            conn.execute(
                "INSERT OR REPLACE INTO drive_reading_bases VALUES(?,?,?,?)",
                (store.context, list_id, card["identity"], card["remote_id"]),
            )
            ticket.checkpoint(conn.commit)
