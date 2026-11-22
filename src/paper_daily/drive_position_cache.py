"""Offline peer suggestions from an observed, authorized personal Drive directory."""

import json
import sqlite3
from contextlib import closing

from paper_daily.drive_sync_files import DriveChanged
from paper_daily.sync_journal import canonical_operation

_TABLE = "drive_peer_positions"


def _watch_memberships(conn):
    # A cached suggestion belongs to the observed membership, even when a replacement
    # uses the same local IDs and timestamp. INSERT also covers SQLite REPLACE.
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' "
                        "AND name='drive_positions_member_added'").fetchone():
        conn.execute(f"DELETE FROM {_TABLE}")
    for name, event, condition, affected in (
        ("added", "INSERT", "", "NEW.list_id"),
        ("removed", "DELETE", "", "OLD.list_id"),
        ("moved", "UPDATE OF list_id,paper_id", " WHEN OLD.list_id IS NOT NEW.list_id "
         "OR OLD.paper_id IS NOT NEW.paper_id", "OLD.list_id,NEW.list_id"),
    ):
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS drive_positions_member_{name} "
                     f"AFTER {event} ON list_papers{condition} BEGIN DELETE FROM {_TABLE} "
                     f"WHERE list_id IN ({affected}); END")


def retain(history, head, tips, revision, ticket):
    store = history.store
    directory = history.directory
    peers = [op for op in tips if op["device_id"] != store.context]
    snapshot = directory.read()
    entry = history._entry(snapshot)
    if entry.positions_head != head:
        raise DriveChanged("PDF suggestions changed during sync")
    encoded = json.dumps(peers, ensure_ascii=False, separators=(",", ":"))
    scope = (store.context, directory.folder, directory.head, history.list_id)
    with closing(sqlite3.connect(store.workspace.path.as_uri() + "?mode=rw", uri=True)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        history._check(revision)
        conn.execute(f"CREATE TABLE IF NOT EXISTS {_TABLE}("
                     "context TEXT,folder TEXT,head TEXT,list_id TEXT,grant_id TEXT,"
                     "generation INTEGER,digest TEXT,tips TEXT,"
                     "PRIMARY KEY(context,folder,head,list_id))")
        _watch_memberships(conn)
        old = conn.execute(f"SELECT grant_id,generation,digest,tips FROM {_TABLE} "
                           "WHERE context=? AND folder=? AND head=? AND list_id=?",
                           scope).fetchone()
        current = (history.grant, snapshot.directory.generation, snapshot.directory.digest, encoded)
        if old and old[0] == history.grant and (
            old[1] > current[1] or (old[1] == current[1] and old != current)
        ):
            raise DriveChanged("Cached PDF suggestions have a different directory history")
        if old != current:
            if peers and (not old or old[3] != encoded):
                from paper_daily.drive_transfer_progress import report

                report("download", paper=peers[0]["payload"]["scope"]["id"], count=len(peers))
            conn.execute(f"INSERT OR REPLACE INTO {_TABLE} VALUES(?,?,?,?,?,?,?,?)",
                         (*scope, *current))
        ticket.checkpoint(conn.commit)
    return peers


def cached(store, folder, head, list_id, revision):
    """Return the last authorized snapshot without contacting Drive or opening PDFs."""
    grant = store.position_grant(list_id, revision)
    if not grant:
        return []
    with closing(sqlite3.connect(store.workspace.path.as_uri() + "?mode=ro", uri=True)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                            (_TABLE,)).fetchone():
            return []
        row = conn.execute(f"SELECT tips FROM {_TABLE} WHERE context=? AND folder=? AND head=? "
                           "AND list_id=? AND grant_id=?",
                           (store.context, folder, head, list_id, grant)).fetchone()
    tips = json.loads(row[0]) if row else []
    for op in tips:
        canonical_operation(op)
        if (op["workspace_id"] != store.library_id or op["device_id"] == store.context
                or op["entity_type"] != "research_content" or op["action"] != "put"
                or op["payload"]["feature"] != "reading_position"):
            raise ValueError("Invalid offline PDF suggestion")
    return tips if store.position_grant(list_id, revision) == grant else []

def for_original(store, folder, head, list_id, revision, local_id, digest):
    """Read peer choices for one local member and exact PDF without contacting Drive."""
    from paper_daily.workspace_service import _read, _tables

    grant = store.position_grant(list_id, revision)
    if not grant:
        return []
    with _read(store.path) as settings:
        if "published_paper_ids" not in _tables(settings):
            return []
        binding = settings.execute("SELECT remote_id FROM published_paper_ids WHERE local_id=?",
                                   (local_id,)).fetchone()
    if not binding:
        return []
    with _read(store.workspace.path) as research:
        store._check(research)
        # Older snapshots predate local membership invalidation. A sync upgrades them.
        if not research.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' "
                                "AND name='drive_positions_member_added'").fetchone():
            return []
        if not research.execute("SELECT 1 FROM list_papers WHERE list_id=? AND paper_id=?",
                                (list_id, local_id)).fetchone():
            return []
        tips = cached(store, folder, head, list_id, revision)
    if store.position_grant(list_id, revision) != grant:
        return []
    return [op for op in tips if op["payload"]["scope"]["id"] == binding[0]
            and op["payload"]["source_document_hash"] == digest]

def navigate(store, folder, head, list_id, revision, view, chosen, visit, *, cancelled):
    """Admit one explicit jump while the device grant and local paper are current."""
    from paper_daily import reading_position_ops

    owner = view.highlight.owner
    if owner.database != store.workspace.path or cancelled():
        return False
    # Follow the settings-then-research lock order used by membership reconciliation.
    with closing(sqlite3.connect(store.path.as_uri() + "?mode=rw", uri=True,
                                 timeout=0.5)) as settings, closing(
        sqlite3.connect(owner.database.as_uri() + "?mode=rw", uri=True, timeout=0.5)
    ) as research:
        settings.execute("BEGIN IMMEDIATE")
        research.execute("BEGIN IMMEDIATE")
        store._check(research)
        owner.check(research)
        choices = for_original(store, folder, head, list_id, revision,
                               owner.paper_id, view.highlight.fingerprint)
        if chosen not in choices:
            return False
        page = chosen["payload"]["data"]["page"]
        if not 1 <= page <= view.page_count:
            return False
        reading_position_ops._current_source(view)
        return False if cancelled() else bool(visit(page))
