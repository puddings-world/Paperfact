"""Capture the selected list's native paper and membership baseline from an ordinary reader."""

from __future__ import annotations

import hashlib
import sqlite3
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


def initial_batches(store, list_id, revision, ticket):
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
        rows = conn.execute(
            f"SELECT {columns},m.citation,m.added_at FROM list_papers m "
            "LEFT JOIN papers p ON p.id=m.paper_id WHERE m.list_id=? "
            "ORDER BY m.position,m.paper_id",
            (list_id,),
        )
        for row in rows:
            ticket.check()
            if row["id"] is None:
                raise ListReviewRequired("Restore the missing paper before publishing its list")
            identity = str(uuid5(namespace, row["id"]))
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


def publish_initial(directory, store, list_id, revision, ticket):
    """Publish a first bibliography or resume its exact acknowledged prefix after interruption."""
    history = DriveListPapers(directory, store, list_id)
    batches = initial_batches(store, list_id, revision, ticket)
    head, received = history.changes(None, revision=revision)
    expected = [op for batch in batches for op in batch]
    if received != expected[: len(received)]:
        raise ListReviewRequired(
            "Existing bibliography has other edits; reconcile before publishing"
        )
    offset = 0
    for batch in batches:
        ticket.check()
        end = offset + len(batch)
        if end > len(received):
            head = history.append(head, batch[max(0, len(received) - offset) :], revision=revision)
        offset = end
    return head
