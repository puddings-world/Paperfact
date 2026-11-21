"""Publish ordinary reader notes using their verified paper and device-local identity."""

import hashlib
import json
import sqlite3
from contextlib import closing
from uuid import NAMESPACE_URL, uuid5

from paper_daily.drive_content_receipts import confirmed_sends, remember_batch
from paper_daily.drive_list_history import DriveListNotes
from paper_daily.drive_list_records import ListReviewRequired
from paper_daily.drive_sync_files import MAX_INLINE, encode
from paper_daily.sync_content import validate_rich_note
from paper_daily.workspace_service import _read, _tables


class NoteEditConflict(ListReviewRequired):
    """A mapped card diverged from a verified base on this device and Drive."""


def _identity(store, key, paper, created, *, origin=None):
    author = origin or store.context
    namespace = uuid5(NAMESPACE_URL, f"paperfact:{store.library_id}:{author}:notes")
    return str(uuid5(namespace, f"{key}:{paper}:{created}"))


def _payload(paper, row):
    body, kind, created, page, anchor = row
    payload = dict(body=body, kind=kind, created_at=created, page=page,
                   anchor=json.loads(anchor) if anchor is not None else None, paper_id=paper)
    validate_rich_note(payload)
    return payload


def reader_notes(history, ticket):
    ticket.check()
    history._check(history.revision)
    store = history.store
    notes = {}
    used = 0
    with _read(store.path) as settings, _read(store.workspace.path) as conn:
        tables = _tables(conn)
        if "research_capture_binding" in tables:
            raise ListReviewRequired("Use the enrolled workspace to synchronize its notes")
        # Sizes are checked before fetching a potentially malformed large body into Python.
        for row in conn.execute(
            "SELECT n.id,n.paper_id,length(CAST(n.body AS BLOB)),length(CAST(n.anchor AS BLOB)) "
            "FROM list_papers m JOIN notes n ON n.paper_id=m.paper_id "
            "WHERE m.list_id=? ORDER BY n.id", (history.list_id,)
        ):
            ticket.check()
            key, local_paper, body_size, anchor_size = row
            if body_size is None or body_size > 200 * 1024 or (anchor_size or 0) > 200 * 1024:
                raise ListReviewRequired("A note exceeds the supported size")
            paper = settings.execute(
                "SELECT remote_id FROM published_paper_ids WHERE local_id=?", (local_paper,)
            ).fetchone()
            if paper is None:
                raise ListReviewRequired("Exchange the bibliography before its notes")
            parent = history.paper_parent(paper[0])
            fields = conn.execute(
                "SELECT body,kind,created_at,page,anchor FROM notes WHERE id=?", (key,)
            ).fetchone()
            payload = _payload(paper[0], fields)
            mapped = None
            if "drive_library_note_ids" in tables:
                mapped = conn.execute(
                    "SELECT remote_id,incarnation,paper FROM drive_library_note_ids "
                    "WHERE context=? AND local_id=?", (store.context, key)
                ).fetchone()
            identity = mapped[0] if mapped else _identity(store, key, local_paper, fields[2])
            if mapped and mapped[2] != paper[0]:
                raise ListReviewRequired("Mapped note now belongs to a different paper")
            op = dict(version=2, workspace_id=store.library_id, device_id=store.context,
                      entity_type="note", entity_id=identity,
                      incarnation=mapped[1] if mapped else identity, action="put",
                      base_revision=0, structure_revision=0, depends_on=None, parents=[parent],
                      payload=payload)
            raw = encode(op, MAX_INLINE)
            used += len(raw) + 128
            if used > 8 * 1024**2 or len(notes) >= 10000:
                raise ListReviewRequired("Selected notes exceed the current history budget")
            op["operation_id"] = hashlib.sha256(raw).hexdigest()
            notes[identity] = op
    history._check(history.revision)
    return notes


def publish_reader_notes(directory, store, list_id, revision, ticket):
    """Add new cards; require review before publishing a divergent existing card."""
    ticket.check()
    history = DriveListNotes(directory, store, list_id, revision=revision)
    head, records = history.changes(None, revision=revision)
    return _publish(history, head, records, ticket)


def _publish(history, head, records, ticket, bases=None, conflicts=None):
    local = reader_notes(history, ticket)
    remote = {op["entity_id"]: op for op in records}
    batches, batch, batch_size = [], [], 0
    size = 0
    for identity, op in local.items():
        if conflicts and identity in conflicts:
            continue
        existing = remote.get(identity)
        if existing is not None:
            fields = ("action", "parents", "incarnation")
            if any(existing[key] != op[key] for key in fields):
                raise ListReviewRequired("Existing note identity changed; review both copies")
            if existing["payload"] == op["payload"]:
                continue
            if not bases or bases.get(identity) != existing["operation_id"]:
                raise ListReviewRequired("Existing note changed; retain both copies for review")
            op.pop("operation_id")
            op.update(base_revision=existing["base_revision"] + 1,
                      depends_on=existing["operation_id"])
            op["operation_id"] = hashlib.sha256(encode(op, MAX_INLINE)).hexdigest()
        length = len(encode(op, MAX_INLINE)) + 1
        size += length
        if len(batch) == 100 or batch_size + length > MAX_INLINE - 2048:
            batches.append(batch)
            batch, batch_size = [], 0
        batch.append(op)
        batch_size += length
    if batch:
        batches.append(batch)
    generations = (head.generation if head else 0) + len(batches)
    size += sum(len(encode(op, MAX_INLINE)) + 1 for op in records)
    if batches and (generations > 100 or size + generations * 2048 > 8 * 1024**2):
        raise ListReviewRequired("Adding these notes would exceed the readable history budget")
    for batch in batches:
        ticket.check()
        if bases is not None:
            remember_batch(history, batch, history.revision, ticket)
        head = history.append(head, batch, revision=history.revision)
        if bases is not None:
            records = [*records, *batch]
            receive_reader_notes(history, records, ticket,
                                 published={op["operation_id"] for op in batch},
                                 conflicts=conflicts)
    return head


def note_chains(history, records):
    chains = {}
    edits = history.grant.startswith("edits-v1:")
    for op in records:
        chain = chains.setdefault(op["entity_id"], [])
        if op["action"] != "put":
            raise ListReviewRequired("Note removal requires review")
        previous = chain[-1] if chain else None
        if (op["structure_revision"] != 0 or op["base_revision"] != len(chain)
                or op["depends_on"] != (previous["operation_id"] if previous else None)
                or previous and (not edits or previous["parents"] != op["parents"]
                                 or previous["incarnation"] != op["incarnation"])):
            raise ListReviewRequired("Revised note history needs reconciliation")
        chain.append(op)
    return chains


def receive_reader_notes(history, records, ticket, *, published=(), conflicts=None):
    """Install a checked batch atomically, keeping a paper-wide mapping across lists."""
    bases = {}
    if not records:
        return bases
    store = history.store
    edits = history.grant.startswith("edits-v1:")
    chains = note_chains(history, records)
    with closing(sqlite3.connect(store.path, timeout=0.5)) as settings, settings:
        settings.execute("BEGIN IMMEDIATE")
        history._check(history.revision)
        with closing(sqlite3.connect(store.workspace.path.as_uri() + "?mode=rw",
                                     uri=True, timeout=0.5)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if "research_capture_binding" in _tables(conn):
                raise ListReviewRequired("Use the enrolled workspace to synchronize its notes")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS drive_library_note_ids(context TEXT,remote_id TEXT,"
                "incarnation TEXT NOT NULL,paper TEXT NOT NULL,local_id INTEGER NOT NULL,"
                "PRIMARY KEY(context,remote_id),UNIQUE(context,local_id))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS drive_library_note_bases(context TEXT,list_id TEXT,"
                "remote_id TEXT,operation_id TEXT NOT NULL,PRIMARY KEY(context,list_id,remote_id))"
            )
            confirmed = confirmed_sends(conn, history, records)
            for identity, chain in chains.items():
                ticket.check()
                key = (store.context, history.list_id, identity)
                receipt = conn.execute(
                    "SELECT operation_id FROM drive_library_note_bases "
                    "WHERE context=? AND list_id=? AND remote_id=?", key
                ).fetchone()
                base = next((item for item in chain if receipt and
                             item["operation_id"] == receipt[0]), None)
                if receipt and base is None:
                    raise ListReviewRequired("Note history lost its previously accepted revision")
                acknowledged = confirmed.get((identity, receipt[0] if receipt else None))
                if acknowledged and edits:
                    _receive_one(history, settings, conn, acknowledged, base, published=True)
                    base = acknowledged
                    conn.execute("INSERT OR REPLACE INTO drive_library_note_bases VALUES(?,?,?,?)",
                                 (*key, base["operation_id"]))
                latest = chain[-1]
                try:
                    _receive_one(history, settings, conn, latest, base if edits else None,
                                 latest["operation_id"] in published)
                except NoteEditConflict:
                    if conflicts is None:
                        raise
                    conflicts.add(identity)
                    continue
                if edits:
                    bases[identity] = latest["operation_id"]
                    if not receipt or receipt[0] != latest["operation_id"]:
                        conn.execute("INSERT OR REPLACE INTO drive_library_note_bases "
                                     "VALUES(?,?,?,?)", (*key, latest["operation_id"]))
            store._check()
            ticket.checkpoint(conn.commit)
    return bases


def _receive_one(history, settings, conn, op, base, published):
    store, payload = history.store, op["payload"]
    if op["action"] != "put":
        raise ListReviewRequired("Note removal requires review")
    validate_rich_note(payload)
    paper, identity = payload["paper_id"], op["entity_id"]
    local = settings.execute(
        "SELECT local_id FROM published_paper_ids WHERE remote_id=?", (paper,)
    ).fetchone()
    if local is None or not conn.execute(
        "SELECT 1 FROM list_papers WHERE list_id=? AND paper_id=?", (history.list_id, local[0])
    ).fetchone():
        raise ListReviewRequired("Receive the note's paper in this list first")
    local_paper = local[0]
    mapped = conn.execute(
        "SELECT local_id,paper,incarnation FROM drive_library_note_ids "
        "WHERE context=? AND remote_id=?", (store.context, identity)
    ).fetchone()
    if mapped:
        row = conn.execute("SELECT body,kind,created_at,page,anchor FROM notes "
                           "WHERE id=? AND paper_id=?", (mapped[0], local_paper)).fetchone()
        if mapped[1:] != (paper, op["incarnation"]) or row is None:
            raise ListReviewRequired("Existing note changed; retain both copies for review")
        if published:
            # Drive confirmed the snapshot; the user may already be editing it again.
            return
        local_payload = _payload(paper, row)
        if local_payload == payload or base and base["operation_id"] == op["operation_id"]:
            return
        if not base:
            raise ListReviewRequired("Existing note changed; retain both copies for review")
        if local_payload != base["payload"]:
            raise NoteEditConflict("Existing note changed; retain both copies for review")
        conn.execute("UPDATE notes SET body=?,kind=?,created_at=?,page=?,anchor=? WHERE id=?",
                     (payload["body"], payload["kind"], payload["created_at"], payload["page"],
                      json.dumps(payload["anchor"]) if payload["anchor"] is not None else None,
                      mapped[0]))
        return
    key = None
    for candidate, body, kind, page, anchor in conn.execute(
        "SELECT id,body,kind,page,anchor FROM notes WHERE paper_id=? AND created_at=?",
        (local_paper, payload["created_at"]),
    ):
        same = _payload(paper, (body, kind, payload["created_at"], page, anchor)) == payload
        if _identity(store, candidate, local_paper, payload["created_at"]) == identity:
            if not same and not published:
                raise ListReviewRequired("Published note was edited; retain both versions")
            key = candidate
            break
        if same and not conn.execute(
            "SELECT 1 FROM drive_library_note_ids WHERE context=? AND local_id=?",
            (store.context, candidate)
        ).fetchone():
            if _identity(store, candidate, local_paper, payload["created_at"],
                         origin=op["device_id"]) == identity:
                key = candidate
                break
            raise ListReviewRequired("Possible existing local note; review before joining")
    if key is None:
        if op["device_id"] == store.context:
            raise ListReviewRequired("Published note is missing locally; review before restoring")
        cursor = conn.execute(
            "INSERT INTO notes(paper_id,body,kind,created_at,page,anchor) VALUES(?,?,?,?,?,?)",
            (local_paper, payload["body"], payload["kind"], payload["created_at"], payload["page"],
             json.dumps(payload["anchor"]) if payload["anchor"] is not None else None),
        )
        key = cursor.lastrowid
    conn.execute("INSERT INTO drive_library_note_ids VALUES(?,?,?,?,?)",
                 (store.context, identity, op["incarnation"], paper, key))


def exchange_reader_notes(directory, store, list_id, revision, ticket):
    history = DriveListNotes(directory, store, list_id, revision=revision)
    head, records = history.changes(None, revision=revision)
    conflicts = set()
    bases = receive_reader_notes(history, records, ticket, conflicts=conflicts)
    head = _publish(history, head, records, ticket, bases, conflicts)
    if conflicts:
        raise NoteEditConflict(f"{len(conflicts)} note(s) changed on both devices; "
                               "retain both copies for review. Other notes can sync.")
    return head
