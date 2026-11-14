"""Bounded read-only signatures of the saved text actually shown by a reader.

Signatures announce stale views; they grant no source, write or model authority.
"""

from __future__ import annotations

import hashlib

from paper_daily import reader_saved_inputs as saved
from paper_daily import research_chat

NOTE_FIELDS = ("id", "body", "kind", "created_at", "page", "anchor")


def digest(value):
    encoded = saved._json(value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def notes(rows):
    return digest(
        sorted([{key: row[key] for key in NOTE_FIELDS} for row in rows], key=lambda row: row["id"])
    )


def snapshot(value, targets):
    data = value.data
    result = {}
    if "chat" in targets:
        result["chat"] = digest(
            {
                "rows": [item["row"] for item in data["chat"]["rows"]],
                "pending": data["pending"],
            }
        )
    if "dive" in targets:
        result["dive"] = digest([data["dives"], data["close_readings"]])
    return result


def read(conn, owner):
    """Use the caller's read transaction and exact loaded-paper owner."""
    owner.check(conn)
    tables = saved._tables(conn)
    note_rows = saved._rows(conn, tables, "notes", owner.paper_id, NOTE_FIELDS)
    # Bound chat before its maintained grouping/link reader materializes records.
    saved._rows(conn, tables, "chat", owner.paper_id, ("id", "body"))
    history = research_chat.history(conn, owner.paper_id) if "chat" in tables else []
    pending = research_chat.pending_requests(conn, owner.paper_id)
    dives = saved._rows(conn, tables, "dives", owner.paper_id, ("body",))
    close = saved._rows(conn, tables, "close_readings", owner.paper_id, ("body",))
    result = {
        "notes": notes(note_rows),
        "chat": digest({"rows": history, "pending": pending}),
        "dive": digest([dives, close]),
    }
    owner.check(conn)
    return result
