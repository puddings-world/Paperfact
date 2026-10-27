"""Closed, portable research rows; explicit caller transactions, no AI or files."""

from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

HASH = re.compile(r"[0-9a-f]{64}")
FIELDS = {"scope", "feature", "key", "data", "source_document_hash"}
# feature: (table, natural key or integer identity, field names)
FEATURES = {
    "dive": ("dives", None, "body written_at spec"),
    "close_reading": ("close_readings", None, "body spec written_at"),
    "citation": (
        "cites",
        "ref_key",
        "title s2_id year venue citations influential purpose gist "
        "verdict why contexts_json doi basis spec edited written_at",
    ),
    "followup": (
        "followups",
        "work_id",
        "title year venue doi citations abstract verdict why "
        "relation contexts_json arxiv_id edited fetched_at",
    ),
    "context": ("paper_context", None, "summary reading_json written_at edited"),
    "resource": (
        "resources",
        "url",
        "kind own source context stars license pushed_at note alive checked_at",
    ),
    "manual_highlight": ("pdf_highlights", "id", "anchor quote created_at"),
    "ai_highlight": ("pdf_ai_highlights", "source_key", "analysis_hash anchor quote reason hidden"),
    "chat": ("chat", "id", "role body created_at page anchor"),
    "list_survey": ("list_surveys", None, "body papers spec written_at edited"),
}
TABLE_FEATURES = {value[0]: feature for feature, value in FEATURES.items()}
TABLE_FEATURES["notes"] = "note"
CONTENT_TABLES = frozenset(TABLE_FEATURES)
FILE_ONLY_SCOPES = (
    "presentations",
    "figures",
    "text",
    "paper-highlights",
    "reading-links",
    "material-positions",
    "research-questions",
)
RICH_NOTE_FIELDS = {"paper_id", "body", "kind", "created_at", "page", "anchor"}


def _text(value, limit=16384, *, nullable=True, nonempty=False):
    if nullable and value is None:
        return
    if (
        not isinstance(value, str)
        or len(value.encode("utf-8")) > limit
        or (nonempty and not value.strip())
    ):
        raise ValueError("Invalid bounded research text")


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Expected canonical portable UUID")


def _hash(value, *, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ValueError("Invalid source document hash")


def _stamp(value):
    _text(value, 64, nullable=False, nonempty=True)
    if datetime.fromisoformat(value).tzinfo is None:
        raise ValueError("Research timestamp requires a timezone")


def _integer(value, *, nullable=False, maximum=2**31 - 1):
    if value is None and nullable:
        return
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("Invalid bounded research integer")


def validate_anchor(value):
    if value is None:
        return
    fields = {"p0", "o0", "p1", "o1"}
    if not isinstance(value, dict) or not fields <= set(value) <= fields | {"document_hash"}:
        raise ValueError("Invalid closed text anchor")
    for key in fields:
        _integer(value[key], maximum=1000000)
    if (value["p1"], value["o1"]) < (value["p0"], value["o0"]):
        raise ValueError("Reversed text anchor")
    if "document_hash" in value:
        _hash(value["document_hash"], nullable=True)


def validate_rich_note(payload):
    if not isinstance(payload, dict) or set(payload) != RICH_NOTE_FIELDS:
        raise ValueError("Unexpected rich note fields")
    _uuid(payload["paper_id"])
    _text(payload["body"], 200 * 1024, nullable=False)
    _text(payload["kind"], 40, nullable=False, nonempty=True)
    _stamp(payload["created_at"])
    _integer(payload["page"], nullable=True, maximum=1000001)
    if payload["page"] == 0:
        raise ValueError("Visible note page is one-based")
    validate_anchor(payload["anchor"])
    if payload["anchor"] is not None and payload["page"] not in (
        None,
        payload["anchor"]["p0"] + 1,
    ):
        raise ValueError("Note page differs from its anchor")


def content_id(scope, feature, key):
    encoded = json.dumps([scope["kind"], scope["id"], feature, key], separators=(",", ":"))
    return str(uuid5(NAMESPACE_URL, "paperfact:research-content:" + encoded))


def validate_payload(payload, *, entity_id=None, parents=None):
    from paper_daily.sync_journal import ID

    if not isinstance(payload, dict) or set(payload) != FIELDS:
        raise ValueError("Unexpected research-content fields")
    scope, feature, key = payload["scope"], payload["feature"], payload["key"]
    if feature not in FEATURES or not isinstance(scope, dict) or set(scope) != {"kind", "id"}:
        raise ValueError("Unsupported research-content feature/scope")
    expected = "list" if feature == "list_survey" else "paper"
    if (
        scope["kind"] != expected
        or not isinstance(scope["id"], str)
        or not ID.fullmatch(scope["id"])
    ):
        raise ValueError("Incorrect research-content scope")
    if expected == "paper":
        _uuid(scope["id"])
    _text(key, 4096, nullable=False, nonempty=True)
    table, natural, fields = FEATURES[feature]
    if natural is None and key != "main":
        raise ValueError("Singleton research uses the main key")
    if natural == "id":
        _uuid(key)
    if feature == "resource":
        url = urlsplit(key)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            raise ValueError("Resource URLs require HTTP(S) without credentials")
    if entity_id is not None and entity_id != content_id(scope, feature, key):
        raise ValueError("Research-content identity differs from its scope/feature/key")
    if parents is not None and (
        len(parents) != 1 or parents[0]["kind"] != expected or parents[0]["id"] != scope["id"]
    ):
        raise ValueError("Research-content parent differs from its scope")
    _hash(payload["source_document_hash"], nullable=True)
    if feature in ("manual_highlight", "ai_highlight"):
        _hash(payload["source_document_hash"])
    data = payload["data"]
    allowed = [set(fields.split())]
    if feature == "chat":
        allowed.append(allowed[0] | {"exchange_id", "reply_to"})
    if not isinstance(data, dict) or set(data) not in allowed:
        raise ValueError("Unexpected research-content data fields")
    if feature == "chat" and "exchange_id" in data:
        _uuid(data["exchange_id"])
        if data["reply_to"] is not None:
            _uuid(data["reply_to"])
        if (
            (data["role"] == "user" and data["reply_to"] is not None)
            or (
                data["role"] == "assistant"
                and (data["reply_to"] is None or data["reply_to"] == key)
            )
            or data["role"] == "system"
        ):
            raise ValueError("Invalid linked conversation role/reference")
    for name, value in data.items():
        if name in ("exchange_id", "reply_to"):
            continue
        if name in ("created_at", "written_at", "fetched_at", "checked_at"):
            _stamp(value)
        elif name in ("edited", "hidden", "influential", "own"):
            _integer(value, maximum=1)
        elif name in ("year", "citations", "stars", "papers", "page", "alive"):
            _integer(value, nullable=True, maximum=1 if name == "alive" else 2**31 - 1)
        elif name == "anchor":
            validate_anchor(value)
            if feature in ("manual_highlight", "ai_highlight") and value is None:
                raise ValueError("Highlights require an anchor")
            if value and value.get("document_hash") not in (None, payload["source_document_hash"]):
                raise ValueError("Contradictory source document hashes")
        elif name == "analysis_hash":
            _hash(value)
        elif name == "contexts_json":
            if value is not None:
                if not isinstance(value, list) or len(value) > 200:
                    raise ValueError("Invalid citation contexts")
                for text in value:
                    _text(text, 8192, nullable=False)
        elif name == "reading_json":
            if value is not None:
                if not isinstance(value, list) or len(value) > 100:
                    raise ValueError("Invalid reading recommendations")
                for item in value:
                    if not isinstance(item, dict) or set(item) != {"title", "direction", "why"}:
                        raise ValueError("Unexpected reading recommendation fields")
                    for text in item.values():
                        _text(text, 8192, nullable=False)
        else:
            _text(
                value,
                200 * 1024 if name == "body" else 32 * 1024,
                nullable=name not in ("body", "quote", "role", "kind", "source", "reason"),
            )
    if feature == "chat" and data["role"] not in ("user", "assistant", "system"):
        raise ValueError("Unsupported conversation role")
    if feature == "ai_highlight" and not key.startswith(payload["source_document_hash"] + ":"):
        raise ValueError("AI highlight key must include its document hash")
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 240 * 1024:
        raise ValueError("Research content exceeds its inline limit")


def initialize_content(conn):
    if not conn.in_transaction:
        raise ValueError("Content initialization requires a caller transaction")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS research_chat_links(local_id INTEGER "
        "PRIMARY KEY,message_id TEXT NOT NULL UNIQUE,exchange_id TEXT "
        "NOT NULL,reply_to TEXT,source_hash TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS research_content_identity (feature TEXT NOT NULL,"
        "sync_key TEXT NOT NULL,local_id INTEGER,paper_id TEXT NOT NULL,created_at TEXT NOT NULL,"
        "PRIMARY KEY(feature,sync_key),UNIQUE(feature,local_id))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS research_content_projection (entity_id TEXT PRIMARY KEY,"
        "feature TEXT NOT NULL,scope_kind TEXT NOT NULL,scope_id TEXT NOT NULL,"
        "item_key TEXT NOT NULL,"
        "incarnation TEXT NOT NULL,parent_incarnation TEXT NOT NULL,source_hash TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS research_rich_note_projection (sync_id TEXT PRIMARY KEY,"
        "incarnation TEXT NOT NULL,parent_incarnation TEXT NOT NULL)"
    )


def _portable_paper(conn, local_id):
    row = conn.execute(
        "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (local_id,)
    ).fetchone()
    if row is None:
        raise ValueError("Paper must be enrolled before its research content")
    return row[0]


def _row_key(conn, table, row):
    feature = TABLE_FEATURES[table]
    if (
        table == "chat"
        and conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_chat_links'"
        ).fetchone()
    ):
        link = conn.execute(
            "SELECT message_id FROM research_chat_links WHERE local_id=?", (row["id"],)
        ).fetchone()
        if link is not None:
            return link[0]
    if table == "notes":
        mapped = conn.execute(
            "SELECT sync_id,paper_id,created_at FROM research_note_identity WHERE local_id=?",
            (row["id"],),
        ).fetchone()
    else:
        mapped = conn.execute(
            "SELECT sync_key,paper_id,created_at FROM research_content_identity "
            "WHERE feature=? AND local_id=?",
            (feature, row["id"]),
        ).fetchone()
    if mapped is not None and tuple(mapped[1:]) == (row["paper_id"], row["created_at"]):
        return mapped[0]
    binding = conn.execute(
        "SELECT workspace,origin FROM research_sync_binding WHERE id=1"
    ).fetchone()
    if binding is None:
        raise ValueError("Research identity binding is missing")
    label = "notes" if table == "notes" else table
    namespace = uuid5(NAMESPACE_URL, f"paperfact:{binding[0]}:{binding[1]}:{label}")
    return str(uuid5(namespace, f"{row['id']}:{row['paper_id']}:{row['created_at']}"))


def content_payload(conn, table, row):
    if table not in CONTENT_TABLES:
        raise ValueError("Unsupported research content table")
    row = dict(row)
    if table == "notes":
        payload = {key: row[key] for key in RICH_NOTE_FIELDS}
        payload["paper_id"] = _portable_paper(conn, row["paper_id"])
        payload["anchor"] = json.loads(row["anchor"]) if row["anchor"] is not None else None
        validate_rich_note(payload)
        return payload
    feature = TABLE_FEATURES[table]
    _, natural, fields = FEATURES[feature]
    scope = (
        {"kind": "list", "id": row["list_id"]}
        if feature == "list_survey"
        else {"kind": "paper", "id": _portable_paper(conn, row["paper_id"])}
    )
    key = _row_key(conn, table, row) if natural == "id" else (row[natural] if natural else "main")
    if feature == "ai_highlight":
        key = row["document_hash"] + ":" + key
    data = {field: row[field] for field in fields.split()}
    if feature == "chat":
        link = conn.execute(
            "SELECT exchange_id,reply_to,source_hash FROM research_chat_links WHERE local_id=?",
            (row["id"],),
        ).fetchone()
        if link is not None:
            data.update(exchange_id=link[0], reply_to=link[1])
    for field in ("anchor", "contexts_json", "reading_json"):
        if field in data and data[field] is not None:
            data[field] = json.loads(data[field])
    source_hash = row.get("document_hash")
    if feature == "chat" and link is not None:
        source_hash = link[2]
    if source_hash is None and isinstance(data.get("anchor"), dict):
        source_hash = data["anchor"].get("document_hash")
    if source_hash is None and feature not in ("manual_highlight", "ai_highlight"):
        previous = conn.execute(
            "SELECT source_hash FROM research_content_projection WHERE entity_id=?",
            (content_id(scope, feature, key),),
        ).fetchone()
        if previous is not None:
            source_hash = previous[0]
    payload = dict(
        scope=scope, feature=feature, key=key, data=data, source_document_hash=source_hash
    )
    validate_payload(payload)
    return payload


def content_identity(conn, table, row):
    if table == "notes":
        return "note", _row_key(conn, table, dict(row))
    payload = content_payload(conn, table, row)
    return "research_content", content_id(payload["scope"], payload["feature"], payload["key"])


def enroll_content_identities(conn):
    if not conn.in_transaction:
        raise ValueError("Identity enrollment requires a caller transaction")
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ("notes", "chat", "pdf_highlights"):
        if table not in tables:
            continue
        cursor = conn.execute(f"SELECT * FROM {table}")
        names = [column[0] for column in cursor.description]
        for values in cursor.fetchall():
            row = dict(zip(names, values, strict=True))
            key = _row_key(conn, table, row)
            if table == "notes":
                conn.execute(
                    "UPDATE research_note_identity SET local_id=NULL "
                    "WHERE local_id=? AND sync_id!=?",
                    (row["id"], key),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO research_note_identity VALUES(?,?,?,?)",
                    (key, row["id"], row["paper_id"], row["created_at"]),
                )
            else:
                feature = TABLE_FEATURES[table]
                conn.execute(
                    "UPDATE research_content_identity SET local_id=NULL "
                    "WHERE feature=? AND local_id=? AND sync_key!=?",
                    (feature, row["id"], key),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO research_content_identity VALUES(?,?,?,?,?)",
                    (feature, key, row["id"], row["paper_id"], row["created_at"]),
                )


def snapshot_content(conn, *, tables=None):
    selected = CONTENT_TABLES if tables is None else frozenset(tables)
    if not selected <= CONTENT_TABLES:
        raise ValueError("Unsupported content snapshot table")
    existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    output = {}
    for table in sorted(selected & existing):
        cursor = conn.execute(f"SELECT * FROM {table}")
        names = [column[0] for column in cursor.description]
        for values in cursor:
            row = dict(zip(names, values, strict=True))
            output[content_identity(conn, table, row)] = content_payload(conn, table, row)
    return output


def _local_scope(conn, scope, *, required=True):
    if scope["kind"] == "list":
        local = scope["id"]
        found = conn.execute("SELECT 1 FROM lists WHERE id=?", (local,)).fetchone()
    else:
        found = conn.execute(
            "SELECT local_id FROM research_paper_identity WHERE sync_id=?", (scope["id"],)
        ).fetchone()
        local = found[0] if found else None
        found = conn.execute("SELECT 1 FROM papers WHERE id=?", (local,)).fetchone()
    if found is None and (required or local is None):
        raise ValueError("Research content requires its materialized parent")
    return local


def write_content(conn, operation):
    """Project one feature row; preserve all unrelated research and local integer IDs."""
    if not conn.in_transaction:
        raise ValueError("Research content requires a caller transaction")
    identity, parent = operation["entity_id"], operation["parents"][0]
    marker = conn.execute(
        "SELECT feature,scope_kind,scope_id,item_key,incarnation,parent_incarnation,source_hash "
        "FROM research_content_projection WHERE entity_id=?",
        (identity,),
    ).fetchone()
    deleting = operation["action"] == "delete"
    if deleting:
        if marker is None or tuple(marker[4:6]) != (
            operation["incarnation"],
            parent["incarnation"],
        ):
            return
        feature, scope_kind, scope_id, key = marker[:4]
        scope, data, source_hash = {"kind": scope_kind, "id": scope_id}, {}, marker[6]
    else:
        payload = operation["payload"]
        validate_payload(payload, entity_id=identity, parents=operation["parents"])
        feature, scope, key, data, source_hash = (
            payload["feature"],
            payload["scope"],
            payload["key"],
            dict(payload["data"]),
            payload["source_document_hash"],
        )
    if (scope["kind"], scope["id"]) != (parent["kind"], parent["id"]):
        raise ValueError("Content projection cannot move to another parent")
    local = _local_scope(conn, scope, required=not deleting)
    table, natural, _fields = FEATURES[feature]
    scope_column = "list_id" if scope["kind"] == "list" else "paper_id"
    where, parameters = f"{scope_column}=?", [local]
    mapping = None
    if natural == "id":
        mapping = conn.execute(
            "SELECT local_id,paper_id,created_at FROM research_content_identity "
            "WHERE feature=? AND sync_key=?",
            (feature, key),
        ).fetchone()
        if mapping is not None and mapping[1] != local:
            raise ValueError("Content integer identity cannot move between papers")
        where += " AND id=?"
        parameters.append(mapping[0] if mapping else None)
    elif natural:
        where += f" AND {natural}=?"
        parameters.append(key.split(":", 1)[1] if feature == "ai_highlight" else key)
    if feature in ("manual_highlight", "ai_highlight"):
        where += " AND document_hash=?"
        parameters.append(source_hash)
    if deleting:
        conn.execute(f"DELETE FROM {table} WHERE {where}", parameters)
        if feature == "chat" and mapping is not None:
            conn.execute("DELETE FROM research_chat_links WHERE local_id=?", (mapping[0],))
        if natural == "id":
            conn.execute(
                "UPDATE research_content_identity SET local_id=NULL WHERE feature=? AND sync_key=?",
                (feature, key),
            )
        return
    if mapping is not None and mapping[2] != data["created_at"]:
        raise ValueError("Research item creation identity cannot change")
    for field in ("anchor", "contexts_json", "reading_json"):
        if field in data and data[field] is not None:
            data[field] = json.dumps(data[field], ensure_ascii=False, sort_keys=True)
    linkage = None
    if feature == "chat" and "exchange_id" in data:
        linkage = (data.pop("exchange_id"), data.pop("reply_to"))
    stored = dict(data)
    stored[scope_column] = local
    if natural and natural != "id":
        stored[natural] = key.split(":", 1)[1] if feature == "ai_highlight" else key
    if feature in ("manual_highlight", "ai_highlight"):
        stored["document_hash"] = source_hash
    columns = list(stored)
    current = conn.execute(
        f"SELECT {','.join(columns)} FROM {table} WHERE {where}", parameters
    ).fetchone()
    if current is None:
        inserted = conn.execute(
            f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
            list(stored.values()),
        )
        if natural == "id":
            conn.execute(
                "INSERT INTO research_content_identity VALUES(?,?,?,?,?) "
                "ON CONFLICT(feature,sync_key) DO UPDATE SET local_id=excluded.local_id",
                (feature, key, inserted.lastrowid, local, data["created_at"]),
            )
    elif tuple(current) != tuple(stored.values()):
        conn.execute(
            f"UPDATE {table} SET {','.join(column + '=?' for column in columns)} WHERE {where}",
            [*stored.values(), *parameters],
        )
    if feature == "chat" and linkage is not None:
        local_row = conn.execute(
            "SELECT local_id FROM research_content_identity WHERE feature='chat' AND sync_key=?",
            (key,),
        ).fetchone()
        conn.execute(
            (
                "INSERT INTO research_chat_links VALUES(?,?,?,?,?) ON "
                "CONFLICT(local_id) DO UPDATE SET message_id=excluded.message_id,"
                "exchange_id=excluded.exchange_id,reply_to=excluded.reply_to,sour"
                "ce_hash=excluded.source_hash"
            ),
            (local_row[0], key, *linkage, source_hash),
        )
    conn.execute(
        "INSERT INTO research_content_projection VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(entity_id) DO UPDATE SET incarnation=excluded.incarnation,"
        "parent_incarnation=excluded.parent_incarnation,source_hash=excluded.source_hash",
        (
            identity,
            feature,
            scope["kind"],
            scope["id"],
            key,
            operation["incarnation"],
            parent["incarnation"],
            source_hash,
        ),
    )


def write_rich_note(conn, operation):
    """Explicit rich v2 notes share the old stable note ID; legacy plain writes stay guarded."""
    if not conn.in_transaction:
        raise ValueError("Rich notes require a caller transaction")
    identity, parent = operation["entity_id"], operation["parents"][0]
    marker = conn.execute(
        "SELECT incarnation,parent_incarnation FROM research_rich_note_projection WHERE sync_id=?",
        (identity,),
    ).fetchone()
    deleting = operation["action"] == "delete"
    if deleting and (
        marker is None or tuple(marker) != (operation["incarnation"], parent["incarnation"])
    ):
        return
    local = _local_scope(conn, {"kind": "paper", "id": parent["id"]})
    mapping = conn.execute(
        "SELECT local_id,paper_id,created_at FROM research_note_identity WHERE sync_id=?",
        (identity,),
    ).fetchone()
    if mapping is not None and mapping[1] != local:
        raise ValueError("An existing note cannot be reassigned")
    if deleting:
        if mapping is not None:
            conn.execute(
                "DELETE FROM notes WHERE id=? AND paper_id=? AND created_at=?", tuple(mapping)
            )
            conn.execute(
                "UPDATE research_note_identity SET local_id=NULL WHERE sync_id=?", (identity,)
            )
        return
    payload = operation["payload"]
    validate_rich_note(payload)
    if payload["paper_id"] != parent["id"]:
        raise ValueError("Rich note differs from its paper parent")
    if mapping is not None and mapping[2] != payload["created_at"]:
        raise ValueError("Note creation identity cannot change")
    anchor = (
        json.dumps(payload["anchor"], sort_keys=True) if payload["anchor"] is not None else None
    )
    values = (payload["body"], payload["kind"], payload["page"], anchor)
    current = conn.execute(
        "SELECT body,kind,page,anchor,paper_id,created_at FROM notes WHERE id=?",
        (mapping[0] if mapping else None,),
    ).fetchone()
    if current is not None:
        if tuple(current[4:]) != (local, payload["created_at"]):
            raise ValueError("Mapped note changed outside the adapter")
        if tuple(current[:4]) != values:
            conn.execute(
                "UPDATE notes SET body=?,kind=?,page=?,anchor=? WHERE id=?", (*values, mapping[0])
            )
    else:
        inserted = conn.execute(
            "INSERT INTO notes(body,kind,page,anchor,paper_id,created_at) VALUES(?,?,?,?,?,?)",
            (*values, local, payload["created_at"]),
        )
        conn.execute(
            "INSERT INTO research_note_identity VALUES(?,?,?,?) "
            "ON CONFLICT(sync_id) DO UPDATE SET local_id=excluded.local_id",
            (identity, inserted.lastrowid, local, payload["created_at"]),
        )
    conn.execute(
        "INSERT INTO research_rich_note_projection VALUES(?,?,?) "
        "ON CONFLICT(sync_id) DO UPDATE SET "
        "incarnation=excluded.incarnation,parent_incarnation=excluded.parent_incarnation",
        (identity, operation["incarnation"], parent["incarnation"]),
    )
