"""Local proof of attempted note and explanation uploads, without research text."""

import hashlib
import sqlite3
from contextlib import closing

from paper_daily.drive_list_records import ListReviewRequired
from paper_daily.drive_sync_files import MAX_INLINE, encode
from paper_daily.native_primary_publication import _WORKSPACE_MARKERS
from paper_daily.workspace_service import _tables


def matches_upload(op, expected):
    body = {key: value for key, value in op.items() if key != "operation_id"}
    return hashlib.sha256(encode(body, MAX_INLINE)).hexdigest() == expected


def remember_batch(history, batch, revision, ticket):
    store = history.store
    with closing(sqlite3.connect(store.workspace.path.as_uri() + "?mode=rw", uri=True,
                                 timeout=0.5)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        history._check(revision)
        if _tables(conn) & _WORKSPACE_MARKERS:
            raise ListReviewRequired("Workspace changed before recording upload intent")
        conn.execute("CREATE TABLE IF NOT EXISTS drive_content_sends(context TEXT,list_id TEXT,"
                     "stream TEXT,entity TEXT,op TEXT,parent TEXT,"
                     "PRIMARY KEY(context,list_id,stream,entity,op))")
        conn.executemany("INSERT OR IGNORE INTO drive_content_sends VALUES(?,?,?,?,?,?)", (
            (store.context, history.list_id, history.format, op["entity_id"], op["operation_id"],
             op["depends_on"]) for op in batch))
        store._check()
        ticket.checkpoint(conn.commit)


def confirmed_sends(conn, history, records):
    """Consume exact matches in the caller's transaction with its common-version receipt."""
    if "drive_content_sends" not in _tables(conn):
        return {}
    scope = history.store.context, history.list_id, history.format
    intents = conn.execute("SELECT entity,op,parent FROM drive_content_sends "
                           "WHERE context=? AND list_id=? AND stream=?", scope).fetchall()
    if not intents:
        return {}
    versions = {op["operation_id"]: op for op in records}
    latest = {op["entity_id"]: op["operation_id"] for op in records}
    matched = {}
    for entity, sent, parent in intents:
        op = versions.get(sent)
        if op is None:
            if entity not in latest or latest[entity] == parent:
                continue
            if parent and parent not in versions:
                raise ListReviewRequired("Content upload predecessor is missing")
        else:
            if (op["entity_id"] != entity or op["depends_on"] != parent
                    or op["device_id"] != history.store.context or not matches_upload(op, sent)):
                raise ListReviewRequired("Content upload receipt differs from verified history")
            matched[entity, parent] = op
        conn.execute("DELETE FROM drive_content_sends WHERE context=? AND list_id=? AND stream=? "
                     "AND entity=? AND op=?", (*scope, entity, sent))
    return matched
