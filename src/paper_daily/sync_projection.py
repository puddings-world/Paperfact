"""Bounded read-only research projection, not a canonical sync bootstrap.

Only database-backed allowlisted research is included. No filesystem attachments,
provider settings, credentials, telemetry, or network operations are read.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

from paper_daily.sync_journal import _identifier

_HASH = re.compile(r"[0-9a-fA-F]{64}")
_SOURCE_FIELDS = {
    "lists": ("id", "name", "note"),
    "list_papers": ("list_id", "paper_id", "position", "state"),
    "papers": ("id", "title", "authors_json", "year", "doi", "page_url"),
    "notes": ("id", "paper_id", "body", "created_at", "kind", "page", "anchor"),
    "dives": ("paper_id", "body", "written_at"),
    "close_readings": ("paper_id", "body", "written_at"),
    "paper_context": ("paper_id", "summary", "written_at"),
    "list_surveys": ("list_id", "body", "written_at"),
    "cites": (
        "paper_id",
        "ref_key",
        "title",
        "doi",
        "year",
        "purpose",
        "gist",
        "verdict",
        "why",
        "basis",
    ),
    "pdf_highlights": ("paper_id", "document_hash", "anchor", "quote"),
    "pdf_ai_highlights": (
        "paper_id",
        "document_hash",
        "source_key",
        "anchor",
        "quote",
        "reason",
        "hidden",
    ),
}


def _encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _text(value, *, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ValueError("Invalid research text field")
    return value


def _integer(value, *, nullable=False, minimum=0):
    if value is None and nullable:
        return None
    if type(value) is not int or value < minimum:
        raise ValueError("Invalid research numeric field")
    return value


def _public_url(value):
    """Metadata hyperlink only; never an authorized attachment fetch instruction."""
    if not isinstance(value, str) or len(value) > 4096 or "\\" in value:
        return None
    if any(ord(ch) <= 32 or ord(ch) == 127 for ch in value):
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or host.lower() == "localhost"
            or "." not in host
            or parsed.port not in (None, 443)
        ):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if host.lower().endswith((".localhost", ".local", ".internal")):
                return None
        return value
    except ValueError:
        return None


def _authors(raw):
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, RecursionError):
        raise ValueError("Invalid paper author metadata") from None
    if not isinstance(value, list):
        raise ValueError("Invalid paper author metadata")
    result = []
    for author in value:
        name = author.get("name") if isinstance(author, dict) else author
        result.append(_text(name))
    return result


def _anchor(raw):
    if raw is None:
        return None, None, "absent"
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, RecursionError):
        return None, None, "unsupported"
    if not isinstance(value, dict):
        return None, None, "unsupported"
    fingerprint = value.get("document_hash")
    fingerprint = (
        fingerprint.lower()
        if isinstance(fingerprint, str) and _HASH.fullmatch(fingerprint)
        else None
    )
    fields = ("p0", "o0", "p1", "o1")
    if any(type(value.get(key)) is not int or value[key] < 0 for key in fields) or (
        value["p1"],
        value["o1"],
    ) < (value["p0"], value["o0"]):
        return None, fingerprint, "unsupported"
    return (
        {"schema_version": 1, "kind": "word_range", **{key: value[key] for key in fields}},
        fingerprint,
        "available",
    )


def _preflight(conn, max_records, max_bytes):
    records, size = 0, 0
    for table, fields in _SOURCE_FIELDS.items():
        lengths = "+".join(f"COALESCE(length(CAST({field} AS BLOB)),0)" for field in fields)
        row = conn.execute(f"SELECT COUNT(*),COALESCE(SUM({lengths}),0) FROM {table}").fetchone()
        records += row[0]
        size += row[1]
        if records > max_records:
            raise ValueError("Research projection exceeds the record limit")
        if size > max_bytes:
            raise ValueError("Research projection exceeds the byte limit")


def _sync_state(conn, tables, kind, identity, cursor):
    pending = awaiting = 0
    if "paperfact_sync_operations" in tables:
        pending = conn.execute(
            "SELECT COUNT(*) FROM paperfact_sync_operations WHERE entity_type=? "
            "AND entity_id=? AND server_revision IS NULL",
            (kind, identity),
        ).fetchone()[0]
        awaiting = conn.execute(
            "SELECT COUNT(*) FROM paperfact_sync_operations WHERE entity_type=? "
            "AND entity_id=? AND server_revision>?",
            (kind, identity, cursor),
        ).fetchone()[0]
    head = None
    if "paperfact_sync_heads" in tables:
        head = conn.execute(
            "SELECT revision,applied_revision FROM paperfact_sync_heads "
            "WHERE entity_type=? AND entity_id=?",
            (kind, identity),
        ).fetchone()
    revision = head[1] if head is not None and head[1] >= 0 else None
    if pending:
        state = "pending"
    elif awaiting:
        state = "awaiting"
    elif head is not None and head[1] < head[0]:
        state = "deferred"
    elif head is not None and head[1] == head[0] and head[0] > 0:
        state = "synced"
    else:
        state = "local"
    return {"revision": revision, "sync_state": state}


def _require_link(collection, identity):
    if identity not in collection:
        raise ValueError("Research projection contains an unresolved record reference")
    return collection[identity]


def _project(conn, workspace_id, max_records, max_bytes):
    binding = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
    if binding is None or binding[0] != workspace_id:
        raise ValueError("Research projection workspace does not match")
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    _preflight(conn, max_records, max_bytes)
    cursor = 0
    if "paperfact_sync_cursor" in tables:
        row = conn.execute("SELECT sequence FROM paperfact_sync_cursor WHERE id=1").fetchone()
        if row is None:
            raise ValueError("Invalid research sync cursor")
        cursor = _integer(row[0])
    lists, papers = {}, {}
    for row in conn.execute("SELECT id,name,note FROM lists ORDER BY created_at,id"):
        identity = _text(row["id"])
        lists[identity] = {
            "id": identity,
            "name": _text(row["name"]),
            "note": _text(row["note"], nullable=True),
            **_sync_state(conn, tables, "list", identity, cursor),
            "members": [],
            "analysis_sections": [],
        }
    for row in conn.execute(
        "SELECT id,title,authors_json,year,doi,page_url FROM papers ORDER BY id"
    ):
        identity = _text(row["id"])
        papers[identity] = {
            "id": identity,
            "title": _text(row["title"]),
            "authors": _authors(row["authors_json"]),
            "year": _integer(row["year"]),
            "doi": _text(row["doi"], nullable=True),
            "url": _public_url(row["page_url"]),
            "pdf_asset_id": None,
            "analysis_sections": [],
            "citations": [],
        }
    for row in conn.execute(
        "SELECT list_id,paper_id,position,state FROM list_papers ORDER BY list_id,position,paper_id"
    ):
        target = _require_link(lists, row["list_id"])
        _require_link(papers, row["paper_id"])
        target["members"].append(
            {
                "paper_id": row["paper_id"],
                "position": _integer(row["position"]),
                "state": _text(row["state"]),
            }
        )
    for table, key, body, kind, collection in (
        ("dives", "paper_id", "body", "deep_reading", papers),
        ("close_readings", "paper_id", "body", "close_reading", papers),
        ("paper_context", "paper_id", "summary", "context", papers),
        ("list_surveys", "list_id", "body", "survey", lists),
    ):
        for row in conn.execute(f"SELECT {key},{body},written_at FROM {table} ORDER BY {key}"):
            target = _require_link(collection, row[0])
            target["analysis_sections"].append(
                {"kind": kind, "body": _text(row[1], nullable=True), "written_at": _text(row[2])}
            )
    for row in conn.execute(
        "SELECT paper_id,ref_key,title,doi,year,purpose,gist,verdict,why,basis "
        "FROM cites ORDER BY paper_id,ref_key"
    ):
        target = _require_link(papers, row["paper_id"])
        item = {
            field: _text(row[field], nullable=True)
            for field in ("ref_key", "title", "doi", "purpose", "gist", "verdict", "why", "basis")
        }
        item["year"] = _integer(row["year"], nullable=True)
        target["citations"].append(item)
    notes = []
    for row in conn.execute(
        "SELECT n.id,n.paper_id,n.body,n.created_at,n.kind,n.page,n.anchor,"
        "m.sync_id,m.paper_id AS mapped_paper,m.created_at AS mapped_created "
        "FROM notes AS n LEFT JOIN research_note_identity AS m ON m.local_id=n.id ORDER BY n.id"
    ):
        if row["sync_id"] is None:
            raise ValueError("Research projection contains an unenrolled note")
        if row["paper_id"] != row["mapped_paper"] or row["created_at"] != row["mapped_created"]:
            raise ValueError("Research note identity requires reconciliation")
        _require_link(papers, row["paper_id"])
        anchor, fingerprint, anchor_status = _anchor(row["anchor"])
        notes.append(
            {
                "id": _text(row["sync_id"]),
                "paper_id": row["paper_id"],
                "body": _text(row["body"]),
                "kind": _text(row["kind"]),
                "page": _integer(row["page"], nullable=True),
                "editable": row["kind"] == "note" and row["page"] is None and row["anchor"] is None,
                **_sync_state(conn, tables, "note", row["sync_id"], cursor),
                "anchor": anchor,
                "anchor_status": anchor_status,
                "pdf_hash": fingerprint,
            }
        )
    highlights = []
    for table, origin in (("pdf_highlights", "manual"), ("pdf_ai_highlights", "ai")):
        columns = "paper_id,document_hash,anchor,quote"
        if origin == "ai":
            columns += ",source_key,reason,hidden"
        for row in conn.execute(f"SELECT {columns} FROM {table} ORDER BY paper_id,id"):
            _require_link(papers, row["paper_id"])
            anchor, _, anchor_status = _anchor(row["anchor"])
            fingerprint = row["document_hash"]
            fingerprint = (
                fingerprint.lower()
                if isinstance(fingerprint, str) and _HASH.fullmatch(fingerprint)
                else None
            )
            source = row["source_key"] if origin == "ai" else row["anchor"]
            identity = hashlib.sha256(
                _encode([workspace_id, origin, row["paper_id"], row["document_hash"], source])
            ).hexdigest()
            if origin == "ai" and row["hidden"] not in (0, 1):
                raise ValueError("Invalid highlight visibility")
            highlights.append(
                {
                    "id": identity,
                    "paper_id": row["paper_id"],
                    "origin": origin,
                    "quote": _text(row["quote"]),
                    "reason": _text(row["reason"]) if origin == "ai" else "",
                    "hidden": bool(row["hidden"]) if origin == "ai" else False,
                    "pdf_hash": fingerprint,
                    "anchor": anchor,
                    "anchor_status": anchor_status,
                }
            )
    pending = (
        conn.execute(
            "SELECT COUNT(*) FROM paperfact_sync_operations WHERE server_revision IS NULL"
        ).fetchone()[0]
        if "paperfact_sync_operations" in tables
        else 0
    )
    awaiting = (
        conn.execute(
            "SELECT COUNT(*) FROM paperfact_sync_operations WHERE server_revision>?", (cursor,)
        ).fetchone()[0]
        if "paperfact_sync_operations" in tables
        else 0
    )
    deferred = (
        conn.execute(
            "SELECT COUNT(*) FROM paperfact_sync_heads WHERE applied_revision<revision"
        ).fetchone()[0]
        if "paperfact_sync_heads" in tables
        else 0
    )
    return {
        "schema_version": 1,
        "workspace_id": workspace_id,
        "cursor": cursor,
        "capabilities": {
            "database_read_projection": True,
            "sync_bootstrap": False,
            "assets": False,
            "decks": False,
        },
        "local_state": {
            "pending_operations": pending,
            "awaiting_receipts": awaiting,
            "deferred_entities": deferred,
        },
        "lists": list(lists.values()),
        "papers": list(papers.values()),
        "notes": notes,
        "highlights": highlights,
        "decks": [],
        "assets": [],
    }


def read_manifest(path: Path, *, workspace_id: str, max_records=10000, max_bytes=8 * 1024 * 1024):
    """Read one consistent bounded snapshot without creating or modifying a database.

    Text remains untrusted text, not HTML. This is a local research read projection;
    its cursor is not authority to skip pending/deferred data during sync bootstrap.
    """
    _identifier(workspace_id)
    if type(max_records) is not int or not 1 <= max_records <= 100000:
        raise ValueError("Invalid projection record limit")
    if type(max_bytes) is not int or not 1 <= max_bytes <= 64 * 1024 * 1024:
        raise ValueError("Invalid projection byte limit")
    conn = None
    try:
        conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        result = _project(conn, workspace_id, max_records, max_bytes)
        if len(_encode(result)) > max_bytes:
            raise ValueError("Research projection exceeds the byte limit")
        return result
    except sqlite3.DatabaseError:
        raise ValueError("Research database is unavailable or incompatible") from None
    finally:
        if conn is not None:
            conn.close()
