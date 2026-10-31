"Closed workspace-owned capture metadata. No fetching, AI, paper or list authority."

from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

MAX_CHARS = 2048
MAX_BYTES = 8192
PAGE_SIZE = 256
KINDS = frozenset({"doi", "url", "idea"})
STATES = frozenset({"new", "kept", "dismissed"})
FIELDS = frozenset({"kind", "text", "state", "created_at", "updated_at"})
SPACE = (
    "[\\u0009-\\u000d\\u0020\\u0085\\u00a0\\u1680\\u2000-"
    "\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]"
)


def trim(value):
    return re.sub(r"^" + SPACE + r"+|" + SPACE + r"+$", "", value)


ITEMS = "research_inbox_items"
HISTORY = "research_inbox_history"
OWNER = "research_inbox_owner"
REQUESTS = "research_inbox_requests"
CANDIDATES = "research_inbox_candidates"
SCHEMAS = {
    ITEMS: (
        "id TEXT PRIMARY KEY,body_json TEXT,incarnation TEXT NOT NULL,"
        + "version TEXT NOT NULL,active INTEGER NOT NULL CHECK(active IN (0,1))"
    ),
    HISTORY: (
        "version TEXT PRIMARY KEY,item_id TEXT NOT NULL,body_json TEXT,"
        + "incarnation TEXT NOT NULL,active INTEGER NOT NULL CHECK(active IN (0,1))"
    ),
    OWNER: "id INTEGER PRIMARY KEY CHECK(id=1),token TEXT NOT NULL",
    REQUESTS: (
        "request_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,"
        "owner_token TEXT NOT NULL,result_json TEXT NOT NULL"
    ),
    CANDIDATES: (
        "id TEXT PRIMARY KEY,item_id TEXT NOT NULL,body_json TEXT,"
        + "observed_json TEXT NOT NULL,action TEXT NOT NULL,resolved_by TEXT"
    ),
}

COLUMNS = {
    ITEMS: "id body_json incarnation version active",
    HISTORY: "version item_id body_json incarnation active",
    OWNER: "id token",
    REQUESTS: "request_id fingerprint owner_token result_json",
    CANDIDATES: "id item_id body_json observed_json action resolved_by",
}


def uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Inbox identities require canonical UUIDs")
    return value


def encode(value):
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )


def decode(raw):
    def fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate Inbox JSON field")
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError("Nonfinite Inbox JSON number")

    return json.loads(raw, object_pairs_hook=fields, parse_constant=invalid)


def timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Inbox timestamp is invalid")
    if (
        re.fullmatch(
            (
                "[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:"
                "[0-9]{2}(?:\\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0"
                "-9]{2})"
            ),
            value,
        )
        is None
    ):
        raise ValueError("Inbox timestamps need bounded ISO date/time with timezone")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Inbox timestamps need a timezone")


def display_value(kind, text):
    value = trim(text)
    if kind == "doi":
        value = re.sub(r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)", "", value, flags=re.I)
        return value.lower()
    return value


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != FIELDS:
        raise ValueError("Unexpected Inbox fields")
    if (
        not isinstance(payload["kind"], str)
        or payload["kind"] not in KINDS
        or not isinstance(payload["state"], str)
        or payload["state"] not in STATES
    ):
        raise ValueError("Unsupported Inbox kind or triage state")
    text = payload["text"]
    if (
        not isinstance(text, str)
        or not trim(text)
        or len(text) > MAX_CHARS
        or len(text.encode("utf-8")) > MAX_BYTES
        or any(ord(c) < 32 and c not in "\t\r\n" for c in text)
    ):
        raise ValueError("Inbox text must contain 1 to 2048 characters / at most 8192 UTF-8 bytes")
    value = display_value(payload["kind"], text)
    if payload["kind"] == "doi" and (
        re.fullmatch(r"10\.[0-9]{4,9}/.+", value) is None or re.search(SPACE, value)
    ):
        raise ValueError("Use a DOI, doi: prefix or doi.org URL")
    if payload["kind"] == "url":
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or "%" in parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "\\" in value
            or re.search(SPACE, value)
            or any(ord(c) <= 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("Inbox URLs require HTTP(S) without embedded credentials")
        _port = parsed.port  # Reject malformed ports; this never opens the address.
    timestamp(payload["created_at"])
    timestamp(payload["updated_at"])
    return payload


def initialize(conn):
    if not conn.in_transaction:
        raise ValueError("Inbox initialization requires a caller transaction")
    for table, columns in SCHEMAS.items():
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table}({columns})")
        if [row[1] for row in conn.execute(f"PRAGMA table_info({table})")] != COLUMNS[
            table
        ].split():
            raise ValueError("Inbox schema requires explicit repair")


def validate_row(table, row):
    if table not in COLUMNS or not isinstance(row, dict) or set(row) != set(COLUMNS[table].split()):
        raise ValueError("Unexpected Inbox stored fields")
    if table in {ITEMS, HISTORY}:
        uuid(row["id"] if table == ITEMS else row["item_id"])
        from paper_daily.sync_journal import _identifier

        _identifier(row["incarnation"])
        _identifier(row["version"])
        if type(row["active"]) is not int or row["active"] not in (0, 1):
            raise ValueError("Invalid Inbox lifecycle")
        if row["body_json"] is not None:
            validate(decode(row["body_json"]))
        elif row["active"]:
            raise ValueError("Active Inbox item has no capture text")
    elif table == OWNER:
        if type(row["id"]) is not int or row["id"] != 1:
            raise ValueError("Invalid Inbox owner")
        uuid(row["token"])
    elif table == REQUESTS:
        uuid(row["request_id"])
        uuid(row["owner_token"])
        if (
            not isinstance(row["fingerprint"], str)
            or re.fullmatch(r"[0-9a-f]{64}", row["fingerprint"]) is None
        ):
            raise ValueError("Invalid Inbox request fingerprint")
        value = decode(row["result_json"])
        if not isinstance(value, dict) or set(value) != {
            "status",
            "item_id",
            "version",
            "candidate_id",
        }:
            raise ValueError("Invalid Inbox request result")
        uuid(value["item_id"])
        if value["status"] not in {"saved", "conflict", "resolved"}:
            raise ValueError("Invalid Inbox request outcome")
        from paper_daily.sync_journal import _identifier

        _identifier(value["version"])
        if value["candidate_id"] is not None:
            uuid(value["candidate_id"])
    else:
        uuid(row["id"])
        uuid(row["item_id"])
        if row["action"] not in {"put", "delete"}:
            raise ValueError("Invalid Inbox candidate action")
        if row["body_json"] is not None:
            validate(decode(row["body_json"]))
        validate_observation(decode(row["observed_json"]))
        if row["resolved_by"] is not None:
            from paper_daily.sync_journal import _identifier

            _identifier(row["resolved_by"])
    return row


def validate_observation(value):
    if not isinstance(value, dict) or set(value) != {"version", "incarnation", "active"}:
        raise ValueError("Invalid Inbox observed base")
    if all(item is None for item in value.values()):
        return
    from paper_daily.sync_journal import _identifier

    _identifier(value["version"])
    _identifier(value["incarnation"])
    if type(value["active"]) is not int or value["active"] not in (0, 1):
        raise ValueError("Invalid Inbox observed lifecycle")


def write(conn, operation):
    "Apply only an already validated workspace-root operation in its caller transaction."
    from paper_daily.sync_journal import canonical_operation

    canonical_operation(operation)
    if operation["version"] != 2 or operation["entity_type"] != "inbox_item":
        raise ValueError("Inbox writer needs its typed root operation")
    if not conn.in_transaction:
        raise ValueError("Inbox writes require a caller transaction")
    uuid(operation["entity_id"])
    payload = operation["payload"] if operation["action"] == "put" else None
    if payload is not None:
        validate(payload)
    prior = conn.execute(
        f"SELECT body_json FROM {ITEMS} WHERE id=?", (operation["entity_id"],)
    ).fetchone()
    body = encode(payload) if payload is not None else prior[0] if prior else None
    active = int(operation["action"] == "put")
    retained = conn.execute(
        f"SELECT * FROM {HISTORY} WHERE version=?", (operation["operation_id"],)
    ).fetchone()
    if retained is not None:
        if (
            retained[1] != operation["entity_id"]
            or retained[3] != operation["incarnation"]
            or retained[4] != active
            or (active and retained[2] != body)
        ):
            raise ValueError("Inbox operation identity was reused with different content")
        body = retained[2]
    row = (
        operation["entity_id"],
        body,
        operation["incarnation"],
        operation["operation_id"],
        active,
    )
    conn.execute(
        (
            f"INSERT INTO {ITEMS} VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            + "body_json=excluded.body_json,incarnation=excl"
            "uded.incarnation,version=excluded.version,act"
            "ive=excluded.active"
        ),
        row,
    )
    conn.execute(
        f"INSERT OR IGNORE INTO {HISTORY} VALUES(?,?,?,?,?)",
        (row[3], row[0], row[1], row[2], row[4]),
    )
