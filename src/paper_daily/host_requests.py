"""Work the reader left for an agent host to answer with its own account.

Paperfact cannot wake a host. A request waits here until the host lists it, answers
it through the feature's task and save tools, and the save marks it done. The queue
is local to this device: it is not a research record and is never synced.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime

from paper_daily import store

# feature -> (tool that returns the task, tool that stores the answer)
FEATURES = {
    "dive": ("research.dive.task", "research.dive.save"),
    "citations": ("research.citations.task", "research.citations.save"),
}
MAX_PENDING = 200

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS research_host_requests("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,feature TEXT NOT NULL,paper_id TEXT NOT NULL,"
    "state TEXT NOT NULL DEFAULT 'pending',requested_at TEXT NOT NULL,finished_at TEXT)",
    # One open request per feature and paper: asking twice must not queue it twice.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_host_requests_open "
    "ON research_host_requests(feature,paper_id) WHERE state='pending'",
)


def _now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def _open(database=None):
    conn = sqlite3.connect(database or store.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    for statement in _SCHEMA:
        conn.execute(statement)
    return conn


def request(feature: str, paper_id: str, *, database=None) -> int:
    """Queue one feature for one paper; return the request already open, if any."""
    if feature not in FEATURES:
        raise ValueError(f"No agent host can answer {feature}")
    with closing(_open(database)) as conn, conn:
        if conn.execute("SELECT 1 FROM papers WHERE id=?", (paper_id,)).fetchone() is None:
            raise ValueError("The selected paper no longer exists")
        found = conn.execute(
            "SELECT id FROM research_host_requests "
            "WHERE feature=? AND paper_id=? AND state='pending'",
            (feature, paper_id),
        ).fetchone()
        if found:
            return found["id"]
        count = conn.execute(
            "SELECT COUNT(*) FROM research_host_requests WHERE state='pending'"
        ).fetchone()[0]
        if count >= MAX_PENDING:
            raise ValueError(f"{MAX_PENDING} requests are already waiting for an agent host")
        return conn.execute(
            "INSERT INTO research_host_requests(feature,paper_id,requested_at) VALUES(?,?,?)",
            (feature, paper_id, _now()),
        ).lastrowid


def pending(limit: int = 20, *, database=None) -> list[dict]:
    """Open requests, oldest first, with the tools that answer each."""
    with closing(_open(database)) as conn, conn:
        rows = conn.execute(
            "SELECT r.id,r.feature,r.paper_id,r.requested_at,p.title "
            "FROM research_host_requests r JOIN papers p ON p.id=r.paper_id "
            "WHERE r.state='pending' ORDER BY r.id LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "request_id": row["id"],
            "feature": row["feature"],
            "paper_id": row["paper_id"],
            "title": row["title"],
            "requested_at": row["requested_at"],
            "task_tool": FEATURES[row["feature"]][0],
            "save_tool": FEATURES[row["feature"]][1],
        }
        for row in rows
        if row["feature"] in FEATURES
    ]


def _close(state, where, values, database):
    with closing(_open(database)) as conn, conn:
        return conn.execute(
            f"UPDATE research_host_requests SET state=?,finished_at=? "
            f"WHERE state='pending' AND {where}",
            (state, _now(), *values),
        ).rowcount


def finish(feature: str, paper_id: str, *, database=None) -> bool:
    """A saved answer closes the open request for that feature and paper."""
    return bool(_close("done", "feature=? AND paper_id=?", (feature, paper_id), database))


def cancel(request_id: int, *, database=None) -> bool:
    return bool(_close("cancelled", "id=?", (request_id,), database))


def waiting(feature: str, paper_id: str, *, database=None) -> bool:
    with closing(_open(database)) as conn:
        return (
            conn.execute(
                "SELECT 1 FROM research_host_requests "
                "WHERE feature=? AND paper_id=? AND state='pending'",
                (feature, paper_id),
            ).fetchone()
            is not None
        )
