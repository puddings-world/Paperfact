"""Closed source-bound reading positions; page numbers never choose an original."""

from __future__ import annotations

TABLE = "reading_positions"
FIELDS = "paper_id document_hash page recorded_at method"
MAX_PAGE = 1_000_001
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS reading_positions("
    "paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,"
    "document_hash TEXT NOT NULL,page INTEGER NOT NULL,recorded_at TEXT NOT NULL,"
    "method TEXT NOT NULL,PRIMARY KEY(paper_id,document_hash))"
)
RECEIPTS = "research_reading_position_receipts"
RECEIPT_FIELDS = "request_id request_json result_json"
RECEIPT_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS research_reading_position_receipts("
    "request_id TEXT PRIMARY KEY,request_json TEXT NOT NULL,result_json TEXT NOT NULL)"
)
CLEANUP = (
    "CREATE TRIGGER IF NOT EXISTS paperfact_reading_position_paper_delete "
    "AFTER DELETE ON papers BEGIN DELETE FROM reading_positions WHERE paper_id=OLD.id; END"
)


def validate_data(data):
    from paper_daily.sync_content import _stamp

    if not isinstance(data, dict) or set(data) != {"page", "recorded_at", "method"}:
        raise ValueError("Unexpected reading-position fields")
    if type(data["page"]) is not int or not 1 <= data["page"] <= MAX_PAGE:
        raise ValueError("Reading position requires a bounded one-based page")
    _stamp(data["recorded_at"])
    if data["method"] not in ("observed", "entered"):
        raise ValueError("Reading position requires an observed or entered method")
    return data


def validate_wire(payload):
    from paper_daily.sync_content import FIELDS as WIRE_FIELDS
    from paper_daily.sync_content import _hash, _uuid

    if not isinstance(payload, dict) or set(payload) != WIRE_FIELDS:
        raise ValueError("Unexpected reading-position envelope")
    scope = payload["scope"]
    if not isinstance(scope, dict) or set(scope) != {"kind", "id"} or scope["kind"] != "paper":
        raise ValueError("Reading position requires its exact paper")
    _uuid(scope["id"])
    _hash(payload["key"])
    if (
        payload["feature"] != "reading_position"
        or payload["source_document_hash"] != payload["key"]
    ):
        raise ValueError("Reading position source must equal its exact hash key")
    validate_data(payload["data"])
    return payload


def validate_row(row):
    from paper_daily.sync_content import _hash, _text

    if not isinstance(row, dict) or set(row) != set(FIELDS.split()):
        raise ValueError("Unexpected stored reading-position fields")
    _text(row["paper_id"], 4096, nullable=False, nonempty=True)
    _hash(row["document_hash"])
    validate_data({key: row[key] for key in ("page", "recorded_at", "method")})
    return row


def verify_page(row, data):
    """A worker checks the exact original's real count, never sender metadata."""
    import hashlib

    import pymupdf

    validate_row(row)
    if hashlib.sha256(data).hexdigest() != row["document_hash"]:
        raise ValueError("Reading position original differs from its exact hash")
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        if pdf.needs_pass or not 1 <= row["page"] <= pdf.page_count <= MAX_PAGE:
            raise ValueError("Reading position exceeds its exact PDF page count")
        return pdf.page_count


def initialize(conn):
    if not conn.in_transaction:
        raise ValueError("Reading-position initialization requires a caller transaction")
    conn.execute(SCHEMA)
    conn.execute(RECEIPT_SCHEMA)
    conn.execute(CLEANUP)
    if not ready(conn):
        raise ValueError("Reading-position schema requires explicit migration")


def ready(conn):
    import re

    if [row[1] for row in conn.execute("PRAGMA table_info(reading_positions)")] != FIELDS.split():
        return False
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' "
        "AND name='paperfact_reading_position_paper_delete'"
    ).fetchone()

    def canonical(sql):
        return re.sub(r"\s+", "", sql).lower().replace("ifnotexists", "").rstrip(";")

    return bool(row and row[0] and canonical(row[0]) == canonical(CLEANUP))


def read(conn, paper_id, document_hash):
    from paper_daily.sync_content import _hash

    _hash(document_hash)
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone():
        return None
    result = conn.execute(
        "SELECT "
        + FIELDS.replace(" ", ",")
        + " FROM reading_positions WHERE paper_id=? AND document_hash=?",
        (paper_id, document_hash),
    ).fetchone()
    return validate_row(dict(zip(FIELDS.split(), result, strict=True))) if result else None
