"""Offline peer suggestions from an observed, authorized personal Drive directory."""

import json
import sqlite3
from contextlib import closing

from paper_daily.drive_sync_files import DriveChanged
from paper_daily.sync_journal import canonical_operation

_TABLE = "drive_peer_positions"


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
        old = conn.execute(f"SELECT grant_id,generation,digest,tips FROM {_TABLE} "
                           "WHERE context=? AND folder=? AND head=? AND list_id=?",
                           scope).fetchone()
        current = (history.grant, snapshot.directory.generation, snapshot.directory.digest, encoded)
        if old and old[0] == history.grant and (
            old[1] > current[1] or (old[1] == current[1] and old != current)
        ):
            raise DriveChanged("Cached PDF suggestions have a different directory history")
        if old != current:
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
