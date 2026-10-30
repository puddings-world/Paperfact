"""Closed, bounded business data for portable reading annotations.

No file, provider, workspace or credential access. Legacy cache adoption and
generation observation belong to the explicit research operation layer.
"""

import json
import re

FEATURES = {
    "claims": "paper_claim_sets",
    "highlight_analysis": "paper_highlight_analysis",
    "reading_links": "paper_reading_links",
    "research_questions": "paper_research_questions",
}
FIELDS = "body_json source_hash document_hash written_at"
MAX_BYTES = 220 * 1024
MAX_ITEMS = 32
MAX_PAGE = 1000000
HASH = re.compile(r"[0-9a-f]{64}")
KINDS = {"problem", "contribution", "method", "evidence", "limitation", "definition"}
STATEMENTS = [
    f"CREATE TABLE IF NOT EXISTS {table}(paper_id TEXT PRIMARY KEY,"
    "body_json TEXT NOT NULL,source_hash TEXT NOT NULL,document_hash TEXT,"
    "written_at TEXT NOT NULL)"
    for table in FEATURES.values()
]
STATEMENTS.append(
    "CREATE TABLE IF NOT EXISTS paper_annotation_known("
    "feature TEXT NOT NULL,paper_id TEXT NOT NULL,PRIMARY KEY(feature,paper_id))"
)
TRIGGERS = {}
for feature, table in FEATURES.items():
    for action in ("insert", "update", "delete"):
        rows = (
            ("OLD", "NEW") if action == "update" else (("OLD",) if action == "delete" else ("NEW",))
        )
        writes = " ".join(
            "INSERT INTO paper_annotation_known(feature,paper_id) "
            f"SELECT '{feature}',{row}.paper_id WHERE NOT EXISTS ("
            "SELECT 1 FROM paper_annotation_known "
            f"WHERE feature='{feature}' AND paper_id={row}.paper_id);"
            for row in rows
        )
        name = f"paperfact_annotation_{feature}_{action}"
        statement = (f"CREATE TRIGGER IF NOT EXISTS {name} "
                     f"AFTER {action.upper()} ON {table} BEGIN {writes} END")
        TRIGGERS[name] = statement
        STATEMENTS.append(statement)
    STATEMENTS.append(
        "INSERT OR IGNORE INTO paper_annotation_known(feature,paper_id) "
        f"SELECT '{feature}',paper_id FROM {table}"
    )
SCHEMA = ";\n".join(STATEMENTS) + ";"


def _closed(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("Unexpected reading annotation fields")


def _text(value, maximum, *, minimum=1):
    if (
        not isinstance(value, str)
        or not minimum <= len(value) <= maximum
        or (minimum and not value.strip())
    ):
        raise ValueError("Invalid reading annotation text")


def _number(value, maximum, *, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Invalid reading annotation number")


def _page(value):
    if value is not None:
        _number(value, MAX_PAGE, minimum=1)


def _items(value, maximum, *, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError("Invalid reading annotation collection")


def validate(feature, body):
    """Validate already decoded bounded data; reject diagnostics and unknown keys."""
    if feature == "claims":
        from paper_daily.claim_content import validate as validate_claims

        validate_claims(body)
    elif feature == "research_questions":
        _closed(body, {"items"})
        _items(body["items"], 6, minimum=1)
        questions = set()
        for item in body["items"]:
            _closed(item, {"question", "why", "evidence", "page"})
            _text(item["question"], 280)
            _text(item["why"], 800)
            _text(item["evidence"], 8192, minimum=15)
            _page(item["page"])
            normalized = item["question"].strip()
            if normalized in questions:
                raise ValueError("Duplicate research question")
            questions.add(normalized)
    elif feature == "highlight_analysis":
        _closed(body, {"items", "coverage"})
        _items(body["items"], MAX_ITEMS)
        quotes = set()
        for item in body["items"]:
            _closed(item, {"text", "page", "kind", "reason", "source"})
            _text(item["text"], 4000, minimum=20)
            _text(item["reason"], 1600)
            _page(item["page"])
            if not isinstance(item["kind"], str) or item["kind"] not in KINDS:
                raise ValueError("Invalid highlight role")
            expected = f"page:{item['page']}" if item["page"] is not None else "original"
            if item["source"] != expected:
                raise ValueError("Highlight source differs from its page")
            identity = (item["page"], item["text"])
            if identity in quotes:
                raise ValueError("Duplicate highlight")
            quotes.add(identity)
        coverage = body["coverage"]
        _closed(coverage, {"pages", "empty_pages", "chunks", "has_page_numbers"})
        _number(coverage["pages"], 20000, minimum=1)
        _number(coverage["chunks"], 20000, minimum=1)
        if type(coverage["has_page_numbers"]) is not bool:
            raise ValueError("Invalid page coverage flag")
        _items(coverage["empty_pages"], coverage["pages"])
        pages = set()
        for page in coverage["empty_pages"]:
            _page(page)
            if page in pages or (page is None and coverage["has_page_numbers"]):
                raise ValueError("Invalid empty-page coverage")
            pages.add(page)
        if coverage["has_page_numbers"] and any(item["page"] is None for item in body["items"]):
            raise ValueError("Missing numbered highlight page")
    elif feature == "reading_links":
        _closed(body, {"links", "analysis_hash"})
        if not isinstance(body["analysis_hash"], str) or not HASH.fullmatch(body["analysis_hash"]):
            raise ValueError("Invalid linked highlight digest")
        _items(body["links"], MAX_ITEMS)
        used = set()
        for link in body["links"]:
            _closed(link, {"quote", "section", "explanation"})
            _number(link["quote"], MAX_ITEMS - 1)
            _text(link["explanation"], 1200)
            if not isinstance(link["section"], str) or not re.fullmatch(
                r"(?:dive|close):(?:0|[1-9][0-9]{0,5})", link["section"]
            ):
                raise ValueError("Invalid explanation section")
            if link["quote"] in used:
                raise ValueError("Repeated highlight explanation link")
            used.add(link["quote"])
    else:
        raise ValueError("Unsupported reading annotation feature")
    # All nested containers have been checked before serializing.
    if (
        len(
            json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        > MAX_BYTES
    ):
        raise ValueError("Reading annotations exceed their inline budget")
    return body


def decode(feature, encoded):
    """Bound bytes before JSON parsing; duplicate object keys cannot hide content."""
    if (
        not isinstance(encoded, (str, bytes))
        or len(encoded.encode("utf-8") if isinstance(encoded, str) else encoded) > MAX_BYTES
    ):
        raise ValueError("Reading annotations exceed their inline budget")

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate reading annotation key")
            result[key] = value
        return result

    try:
        return validate(feature, json.loads(encoded, object_pairs_hook=pairs))
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid reading annotation JSON") from exc


def initialize(conn):
    """Create the fixed tables in an existing caller transaction; never commit."""
    if not conn.in_transaction:
        raise ValueError("Reading annotation initialization requires a caller transaction")
    def normalized(sql):
        # SQLite may omit the creation guard in sqlite_master. Preserve string
        # literal case; only normalize whitespace and that optional header clause.
        sql = re.sub(r"\bIF\s+NOT\s+EXISTS\b", "", sql, count=1, flags=re.I)
        return " ".join(sql.rstrip(";").split())

    for name, expected in TRIGGERS.items():
        actual = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,)
        ).fetchone()
        if actual is not None and normalized(actual[0]) != normalized(expected):
            # Upgrade obsolete INSERT OR IGNORE triggers once in the caller's
            # transaction. Unchanged initialization must not mutate schema order.
            conn.execute(f'DROP TRIGGER "{name}"')
    for statement in STATEMENTS:
        if statement.strip():
            conn.execute(statement)
    for table in FEATURES.values():
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if columns != {"paper_id", *FIELDS.split()}:
            raise ValueError("Unsupported reading annotation schema")


def validate_row(feature, row):
    """Validate a sharing/recovery SQL row without reading any workspace."""
    from paper_daily.sync_content import _stamp

    _closed(row, {"paper_id", *FIELDS.split()})
    _text(row["paper_id"], 4096)
    if not isinstance(row["source_hash"], str) or not HASH.fullmatch(row["source_hash"]):
        raise ValueError("Invalid annotation input digest")
    if row["document_hash"] is not None and (
        not isinstance(row["document_hash"], str) or not HASH.fullmatch(row["document_hash"])
    ):
        raise ValueError("Invalid annotation source PDF digest")
    _stamp(row["written_at"])
    body = decode(feature, row["body_json"])
    if feature == "claims" and (
            row["document_hash"] is None
            or row["document_hash"] != body["report"]["source"]["document_hash"]):
        raise ValueError("Claim set belongs to a different original source")
    return row
