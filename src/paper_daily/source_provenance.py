"""Private archive-only original-source receipts, with no active owner authority."""

from __future__ import annotations

import hashlib

from paper_daily.sync_files import canonical_json, closed, digest, read_json

TABLE = "research_source_archive"
COLUMNS = "record_id body_json"
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS research_source_archive ("
    "record_id TEXT PRIMARY KEY,body_json TEXT NOT NULL);"
)


def validate(row):
    from paper_daily import source_snapshots

    closed(row, {"record_id", "body_json"})
    digest(row["record_id"])
    value = row["body_json"]
    if not isinstance(value, str) or len(value.encode("utf-8")) > source_snapshots.MAX_RECEIPT:
        raise ValueError("Archived source provenance exceeds its bound")
    body = read_json(value.encode("utf-8"))
    source_snapshots.validate(body)
    if hashlib.sha256(value.encode("utf-8")).hexdigest() != row["record_id"]:
        raise ValueError("Archived source provenance identity differs from its content")
    return body


def wrap(receipt):
    from paper_daily import source_snapshots

    source_snapshots.validate(receipt)
    body = canonical_json(receipt)
    return {"record_id": hashlib.sha256(body).hexdigest(), "body_json": body.decode("utf-8")}


def archived(conn):
    from paper_daily import source_snapshots

    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone():
        return []
    output = []
    for raw in conn.execute(
        "SELECT record_id,CASE WHEN length(CAST(body_json AS BLOB))<=? THEN body_json "
        "ELSE NULL END FROM research_source_archive ORDER BY record_id LIMIT ?",
        (source_snapshots.MAX_RECEIPT, source_snapshots.MAX_RECEIPTS + 1),
    ):
        row = dict(zip(COLUMNS.split(), raw, strict=True))
        validate(row)
        output.append(row)
        if len(output) > source_snapshots.MAX_RECEIPTS:
            raise ValueError("Archived source provenance exceeds its record bound")
    return output


def retain_in(conn, records):
    """Caller transaction; records remain original observations, never new identities."""
    from paper_daily import source_snapshots

    if not conn.in_transaction:
        raise ValueError("Source provenance archive requires a caller transaction")
    if not isinstance(records, list) or len(records) > source_snapshots.MAX_RECEIPTS:
        raise ValueError("Source provenance archive exceeds its record bound")
    for row in records:
        validate(row)
    if records:
        conn.execute(SCHEMA)
    for row in records:
        old = conn.execute(
            "SELECT body_json FROM research_source_archive WHERE record_id=?", (row["record_id"],)
        ).fetchone()
        if old is not None and old[0] != row["body_json"]:
            raise ValueError("Archived source provenance identity was reused")
        conn.execute(
            "INSERT OR IGNORE INTO research_source_archive VALUES(?,?)",
            (row["record_id"], row["body_json"]),
        )
