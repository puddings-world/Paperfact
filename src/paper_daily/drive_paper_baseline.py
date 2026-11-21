"""Capture the selected list's native paper and membership baseline from an ordinary reader."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from uuid import NAMESPACE_URL, uuid5

from paper_daily.drive_list_history import DriveListPapers
from paper_daily.drive_list_records import ListReviewRequired
from paper_daily.drive_sync_files import MAX_INLINE, encode
from paper_daily.sync_capture import PAPER_COLUMNS, _payload
from paper_daily.sync_journal import canonical_operation
from paper_daily.sync_schema_v2 import membership_id
from paper_daily.workspace_service import _read


def _put(store, kind, identity, incarnation, payload, parents):
    op = dict(
        version=2,
        workspace_id=store.library_id,
        device_id=store.context,
        entity_type=kind,
        entity_id=identity,
        incarnation=incarnation,
        action="put",
        base_revision=0,
        structure_revision=0,
        depends_on=None,
        parents=parents,
        payload=payload,
    )
    op["operation_id"] = hashlib.sha256(encode(op)).hexdigest()
    canonical_operation(op)
    return op


def initial_batches(store, list_id, revision, ticket, *, bindings=None):
    """Validate the whole snapshot before the first upload. Never enroll or edit the source."""
    selection = store.load()
    if selection.revision != revision or list_id not in selection.selected:
        raise ValueError("This device changed its list selection")
    namespace = uuid5(NAMESPACE_URL, f"paperfact:{store.library_id}:{store.context}:papers")
    list_parent = dict(
        kind="list", id=list_id, incarnation=str(uuid5(namespace, "list:" + list_id))
    )
    batches, batch = [], []
    used = batch_bytes = 0
    with _read(store.workspace.path) as conn:
        conn.row_factory = sqlite3.Row
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_capture_binding'"
        ).fetchone():
            raise ListReviewRequired("Use the existing enrolled workspace for this library")
        if not conn.execute("SELECT 1 FROM lists WHERE id=?", (list_id,)).fetchone():
            raise ListReviewRequired("The selected source list is missing")
        columns = ",".join("p." + key for key in sorted(PAPER_COLUMNS))
        has_received = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='drive_library_papers'"
        ).fetchone()
        remote_id, mapping, params = "NULL", "", (list_id,)
        if has_received:
            remote_id = "d.remote_id"
            mapping = "LEFT JOIN drive_library_papers d ON d.context=? AND d.local_id=p.id "
            params = (store.context, list_id)
        rows = conn.execute(
            f"SELECT {columns},m.citation,m.added_at,{remote_id} AS portable FROM list_papers m "
            f"LEFT JOIN papers p ON p.id=m.paper_id {mapping}WHERE m.list_id=? "
            "ORDER BY m.position,m.paper_id",
            params,
        )
        for row in rows:
            ticket.check()
            if row["id"] is None:
                raise ListReviewRequired("Restore the missing paper before publishing its list")
            identity = row["portable"] or str(uuid5(namespace, row["id"]))
            if bindings is not None:
                bindings.append((identity, row["id"]))
            member = membership_id(list_id, identity)
            paper = _put(store, "paper", identity, identity, _payload(conn, "papers", row), [])
            link = _put(
                store,
                "membership",
                member,
                member,
                dict(
                    list_id=list_id,
                    paper_id=identity,
                    citation=row["citation"],
                    added_at=row["added_at"],
                ),
                [list_parent, dict(kind="paper", id=identity, incarnation=identity)],
            )
            size = len(encode([paper, link]))
            # Leave room for the envelope and prior head in each Drive record.
            if len(batch) == 100 or batch_bytes + size > MAX_INLINE - 2048:
                batches.append(batch)
                batch, batch_bytes = [], 0
            batch.extend((paper, link))
            batch_bytes += size
            used += size
            if len(batches) >= 100 or used + (len(batches) + 1) * 2048 > 8 * 1024**2:
                raise ListReviewRequired("Selected bibliography exceeds the current history budget")
    if batch:
        batches.append(batch)
    ticket.check()
    return batches


def publish_initial(directory, store, list_id, revision, ticket, *, append_new=False):
    """Publish a first bibliography or resume its exact acknowledged prefix after interruption."""
    history = DriveListPapers(directory, store, list_id)
    bindings = []
    batches = initial_batches(store, list_id, revision, ticket, bindings=bindings)
    head, received = history.changes(None, revision=revision)
    if append_new and received:
        remote_ids = {op["entity_id"] for op in received[::2]}
        if not remote_ids <= {identity for identity, _ in bindings}:
            raise ListReviewRequired("Selected bibliography changed or has removed papers; review")
        list_parent = next(p for p in received[1]["parents"] if p["kind"] == "list")
        pending = []
        for batch in batches:
            additions = []
            for paper, member in zip(batch[::2], batch[1::2], strict=True):
                if paper["entity_id"] in remote_ids:
                    continue
                parents = [list_parent if p["kind"] == "list" else p for p in member["parents"]]
                member = _put(
                    store,
                    "membership",
                    member["entity_id"],
                    member["incarnation"],
                    member["payload"],
                    parents,
                )
                additions.extend((paper, member))
            if additions:
                pending.append(additions)
    else:
        expected = [op for batch in batches for op in batch]
        if received != expected[: len(received)]:
            raise ListReviewRequired(
                "Existing bibliography has other edits; reconcile before publishing"
            )
        pending = []
        offset = 0
        for batch in batches:
            remaining = batch[max(0, len(received) - offset) :]
            if remaining:
                pending.append(remaining)
            offset += len(batch)
    if head and pending:
        generations = head.generation + len(pending)
        payload_bytes = sum(len(encode(op)) + 1 for op in received)
        payload_bytes += sum(len(encode(batch, MAX_INLINE)) for batch in pending)
        if generations > 100 or payload_bytes + generations * 2048 > 8 * 1024**2:
            raise ListReviewRequired("New papers exceed the readable history budget")
    # Bind local IDs before the first remote write so a lost acknowledgement
    # cannot turn the source paper into an unknown duplicate on a return trip.
    with closing(sqlite3.connect(store.path, timeout=0.5)) as settings, settings:
        settings.execute("BEGIN IMMEDIATE")
        store._check()
        current = store._load(settings)
        if current.revision != revision or list_id not in current.selected:
            raise ValueError("This device changed its list selection")
        settings.execute(
            "CREATE TABLE IF NOT EXISTS published_paper_ids("
            "remote_id TEXT PRIMARY KEY,local_id TEXT NOT NULL UNIQUE)"
        )
        for start in range(0, len(bindings), 400):
            ticket.check()
            group = bindings[start : start + 400]
            slots = ",".join("?" for _ in group)
            known = dict(
                settings.execute(
                    "SELECT remote_id,local_id FROM published_paper_ids "
                    f"WHERE remote_id IN ({slots})",
                    [identity for identity, _ in group],
                )
            )
            if any(identity in known and known[identity] != local for identity, local in group):
                raise ListReviewRequired("Published paper identity has a different local binding")
            try:
                settings.executemany(
                    "INSERT INTO published_paper_ids VALUES(?,?)",
                    ((identity, local) for identity, local in group if identity not in known),
                )
            except sqlite3.IntegrityError as exc:
                raise ListReviewRequired(
                    "Local paper already has a different published ID"
                ) from exc
        ticket.checkpoint(settings.commit)
    for batch in pending:
        ticket.check()
        head = history.append(head, batch, revision=revision)
    return head
