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
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from paper_daily.sync_journal import _identifier

_HASH = re.compile(r"[0-9a-fA-F]{64}")
_SOURCE_FIELDS = {
    "lists": ("id", "name", "note"),
    "list_papers": ("list_id", "paper_id", "position", "state"),
    "pins": ("scope", "paper_id", "pinned_at"),
    "reading_positions": ("paper_id", "document_hash", "page", "recorded_at", "method"),
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
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, fields in _SOURCE_FIELDS.items():
        if table == "reading_positions" and table not in tables:
            continue
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


def _project(conn, workspace_id, max_records, max_bytes, *, position_rows=None):
    binding = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
    if binding is None or binding[0] != workspace_id:
        raise ValueError("Research projection workspace does not match")
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if (
        position_rows is None
        and "reading_positions" in tables
        and conn.execute("SELECT 1 FROM reading_positions LIMIT 1").fetchone()
    ):
        raise ValueError("Source-bound reading positions are not supported by this snapshot")
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
    for pin in conn.execute("SELECT paper_id,pinned_at FROM pins WHERE scope='queue'"):
        paper = _require_link(papers, pin["paper_id"])
        paper["queue_pin"] = {"pinned_at": _reading_timestamp(_text(pin["pinned_at"]))}
    pin_rows = {
        (row["scope"], row["paper_id"]): _reading_timestamp(_text(row["pinned_at"]))
        for row in conn.execute(
            "SELECT pin.scope,pin.paper_id,pin.pinned_at FROM pins pin "
            "JOIN list_papers lp ON lp.list_id=pin.scope AND lp.paper_id=pin.paper_id "
            "WHERE pin.scope!='queue'"
        )
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
                **(
                    {"pinned": True, "pinned_at": pin_rows[(row["list_id"], row["paper_id"])]}
                    if (row["list_id"], row["paper_id"]) in pin_rows
                    else {}
                ),
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
    result = {
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
    if any("queue_pin" in paper for paper in papers.values()):
        result["required_capabilities"] = ["queue_pin"]
    return result


def _portable_uuid(value):
    if not isinstance(value, str):
        raise ValueError("Invalid portable paper identity")
    try:
        if str(UUID(value)) != value:
            raise ValueError("Invalid portable paper identity")
    except (ValueError, AttributeError):
        raise ValueError("Invalid portable paper identity") from None
    return value


def _graph_info(conn, tables, kind, identity, state, cursor, parents):
    if state["sync_state"] != "synced" or "paperfact_sync_graph" not in tables:
        return None
    row = conn.execute(
        "SELECT CASE WHEN length(metadata)<=8192 THEN metadata ELSE NULL END "
        "FROM paperfact_sync_graph WHERE entity_type=? AND entity_id=?",
        (kind, identity),
    ).fetchone()
    if row is None:
        return None
    try:
        data = json.loads(row[0])
    except (TypeError, ValueError, RecursionError):
        raise ValueError("Invalid research graph metadata") from None
    if not isinstance(data, dict) or set(data) != {
        "incarnation",
        "parents",
        "structure_revision",
        "active",
    }:
        raise ValueError("Invalid research graph metadata")
    _identifier(data["incarnation"])
    structure = _integer(data["structure_revision"])
    if (
        structure > cursor
        or type(data["active"]) is not bool
        or not isinstance(data["parents"], list)
    ):
        raise ValueError("Invalid research graph metadata")
    found = {}
    for ref in data["parents"]:
        if not isinstance(ref, dict) or set(ref) != {"kind", "id", "incarnation"}:
            raise ValueError("Invalid research graph parent")
        allowed = ("list", "paper", "membership") if kind == "reading_state" else ("list", "paper")
        if ref["kind"] not in allowed or ref["kind"] in found:
            raise ValueError("Invalid research graph parent")
        _identifier(ref["id"])
        _identifier(ref["incarnation"])
        if ref["kind"] == "paper":
            _portable_uuid(ref["id"])
        found[ref["kind"]] = ref["id"]
    if found != parents:
        raise ValueError("Research graph parents do not match projected content")
    if not data["active"]:
        return None
    return {
        "incarnation": data["incarnation"],
        "parents": data["parents"],
        "structure_revision": structure,
    }


def _reading_timestamp(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Invalid reading-state timestamp")
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Invalid reading-state timestamp")
    except ValueError:
        raise ValueError("Invalid reading-state timestamp") from None
    return value


def _reading_projection(conn, tables, member, collection, paper_graph, times, cursor):
    if member["state"] not in {"pending", "delivered", "read", "skipped", "deferred"}:
        raise ValueError("Invalid reading state")
    result = {
        "id": member["id"],
        "state": member["state"],
        "delivered_at": _reading_timestamp(times[0]),
        "read_at": _reading_timestamp(times[1]),
        **_sync_state(conn, tables, "reading_state", member["id"], cursor),
    }
    result["graph"] = _graph_info(
        conn,
        tables,
        "reading_state",
        member["id"],
        result,
        cursor,
        {"membership": member["id"], "list": collection["id"], "paper": member["paper_id"]},
    )
    reason = "graph_unavailable" if result["graph"] is None else None
    if result["graph"] is not None:
        graphs = {"membership": member["graph"], "list": collection["graph"], "paper": paper_graph}
        if any(
            graphs[ref["kind"]] is None or graphs[ref["kind"]]["incarnation"] != ref["incarnation"]
            for ref in result["graph"]["parents"]
        ):
            reason = "parent_graph_unavailable"
            result["graph"] = None
    if reason is None:
        marker = (
            conn.execute(
                "SELECT incarnation,list_incarnation,paper_incarnation "
                "FROM research_membership_projection WHERE sync_id=?",
                (member["id"],),
            ).fetchone()
            if "research_membership_projection" in tables
            else None
        )
        incarnations = {ref["kind"]: ref["incarnation"] for ref in result["graph"]["parents"]}
        expected = tuple(incarnations[kind] for kind in ("membership", "list", "paper"))
        if marker is None or tuple(marker) != expected:
            reason = "membership_projection_unavailable"
            result["graph"] = None
    result.update(editable=reason is None, read_only_reason=reason)
    return result


def _portable_projection(conn, result):
    from paper_daily.sync_schema_v2 import membership_id

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    mapping, seen = {}, set()
    for row in conn.execute(
        "SELECT p.id,m.sync_id FROM papers p LEFT JOIN research_paper_identity m ON m.local_id=p.id"
    ):
        if row[1] is None:
            raise ValueError("Research projection contains an unenrolled paper")
        portable = _portable_uuid(row[1])
        if portable in seen:
            raise ValueError("Research projection has ambiguous paper identities")
        mapping[row[0]] = portable
        seen.add(portable)
    cursor = result["cursor"]
    reading_times = {}
    for row in conn.execute(
        "SELECT list_id,paper_id,"
        "CASE WHEN length(delivered_at)<=64 THEN delivered_at "
        "WHEN delivered_at IS NULL THEN NULL ELSE '' END,"
        "CASE WHEN length(read_at)<=64 THEN read_at "
        "WHEN read_at IS NULL THEN NULL ELSE '' END FROM list_papers"
    ):
        reading_times[(row[0], mapping[row[1]])] = (row[2], row[3])
    paper_graphs = {}
    for paper in result["papers"]:
        paper["id"] = mapping[paper["id"]]
        paper.update(_sync_state(conn, tables, "paper", paper["id"], cursor))
        paper["graph"] = _graph_info(conn, tables, "paper", paper["id"], paper, cursor, {})
        paper_graphs[paper["id"]] = paper["graph"]
    for collection in result["lists"]:
        collection["graph"] = _graph_info(
            conn, tables, "list", collection["id"], collection, cursor, {}
        )
        for member in collection["members"]:
            member["paper_id"] = mapping[member["paper_id"]]
            member["id"] = membership_id(collection["id"], member["paper_id"])
            member.update(_sync_state(conn, tables, "membership", member["id"], cursor))
            member["graph"] = _graph_info(
                conn,
                tables,
                "membership",
                member["id"],
                member,
                cursor,
                {"list": collection["id"], "paper": member["paper_id"]},
            )
            if member["graph"] is not None:
                parent_graphs = {
                    "list": collection["graph"],
                    "paper": paper_graphs[member["paper_id"]],
                }
                if any(
                    parent_graphs[ref["kind"]] is None
                    or parent_graphs[ref["kind"]]["incarnation"] != ref["incarnation"]
                    for ref in member["graph"]["parents"]
                ):
                    member["graph"] = None
            member["reading_state"] = _reading_projection(
                conn,
                tables,
                member,
                collection,
                paper_graphs[member["paper_id"]],
                reading_times[(collection["id"], member["paper_id"])],
                cursor,
            )
        collection["members"].sort(key=lambda item: (item["position"], item["paper_id"]))
        collection["order"] = _order_projection(conn, tables, result, collection)
    result["list_order"] = _order_projection(conn, tables, result)
    _workspace_display_order(conn, result)
    for note in result["notes"]:
        note["paper_id"] = mapping[note["paper_id"]]
        note["graph"] = _graph_info(
            conn, tables, "note", note["id"], note, cursor, {"paper": note["paper_id"]}
        )
        reason = None
        if not note["editable"]:
            reason = "unsupported_note_contract"
        elif note["graph"] is None:
            reason = "graph_unavailable"
        elif paper_graphs[note["paper_id"]] is None or (
            note["graph"]["parents"][0]["incarnation"]
            != paper_graphs[note["paper_id"]]["incarnation"]
        ):
            reason = "paper_graph_unavailable"
        note.update(editable=reason is None, read_only_reason=reason)
    highlight_ids = {}
    for table, origin in (("pdf_highlights", "manual"), ("pdf_ai_highlights", "ai")):
        source_column = "source_key" if origin == "ai" else "anchor"
        for row in conn.execute(f"SELECT paper_id,document_hash,{source_column} FROM {table}"):
            old_key = [result["workspace_id"], origin, row[0], row[1], row[2]]
            new_key = [result["workspace_id"], origin, mapping[row[0]], row[1], row[2]]
            highlight_ids[hashlib.sha256(_encode(old_key)).hexdigest()] = hashlib.sha256(
                _encode(new_key)
            ).hexdigest()
    for highlight in result["highlights"]:
        highlight["paper_id"] = mapping[highlight["paper_id"]]
        highlight["id"] = highlight_ids[highlight["id"]]
    result["papers"].sort(key=lambda item: item["id"])
    result["notes"].sort(key=lambda item: item["id"])
    result["highlights"].sort(key=lambda item: item["id"])
    result["schema_version"] = 2
    result["capabilities"]["note_contract_version"] = 2
    result["capabilities"]["reading_state_contract_version"] = 2
    result["capabilities"]["ordering_contract_version"] = 2
    return result


def _order_projection(conn, tables, result, collection=None):
    from paper_daily.sync_research import _order_targets

    kind = "workspace_list_order" if collection is None else "list_order"
    identity = "workspace-lists" if collection is None else collection["id"]
    cursor = result["cursor"]
    projected = _sync_state(conn, tables, kind, identity, cursor)
    projected["graph"] = _graph_info(
        conn,
        tables,
        kind,
        identity,
        projected,
        cursor,
        {} if collection is None else {"list": identity},
    )
    reason = "graph_unavailable" if projected["graph"] is None else None
    if reason is None and collection is not None:
        parent = projected["graph"]["parents"][0]
        if (
            collection["graph"] is None
            or collection["graph"]["incarnation"] != parent["incarnation"]
        ):
            reason = "parent_graph_unavailable"
    if reason is None:
        items = result["lists"] if collection is None else collection["members"]
        if any(item["graph"] is None for item in items):
            reason = "item_graph_unavailable"
        elif not {"research_list_projection", "research_membership_projection"} <= tables:
            reason = "projection_unavailable"
        else:
            scope = {
                "kind": kind,
                "id": identity,
                "incarnation": None if collection is None else collection["graph"]["incarnation"],
            }
            try:
                targets = _order_targets(conn, scope)
                expected = {(item["id"], item["graph"]["incarnation"]) for item in items}
                if {(key, value[0]) for key, value in targets.items()} != expected:
                    reason = "projection_unavailable"
            except ValueError:
                reason = "projection_unavailable"
    if reason is not None:
        projected["graph"] = None
    projected.update(editable=reason is None, read_only_reason=reason)
    return projected


def _workspace_display_order(conn, result):
    """Read only the explicitly allowed display preference; never enumerate settings."""
    row = conn.execute(
        "SELECT CASE WHEN length(CAST(value AS BLOB))<=262144 THEN value ELSE NULL END "
        "FROM kv WHERE key='lists.order'"
    ).fetchone()
    if row is None:
        return
    try:
        order = json.loads(row[0])
    except (ValueError, TypeError, RecursionError):
        raise ValueError("Invalid bounded workspace list order") from None
    if not isinstance(order, list) or len(order) > 2000:
        raise ValueError("Invalid bounded workspace list order")
    for identity in order:
        _identifier(identity)
    if len(set(order)) != len(order):
        raise ValueError("Invalid duplicate workspace list order")
    ranks = {identity: index for index, identity in enumerate(order)}
    result["lists"].sort(key=lambda item: ranks.get(item["id"], len(order)))


def _document_projection(conn, result, verified_documents, max_records, max_bytes):
    from paper_daily.sync_documents import (
        VerifiedDocument,
        _paper_current,
        applied_document,
        desired_document,
    )
    from paper_daily.sync_documents import (
        _encode as encode_target,
    )

    if not isinstance(verified_documents, (tuple, list)) or len(verified_documents) > 10000:
        raise ValueError("Invalid document verification snapshots")
    if any(not isinstance(item, VerifiedDocument) for item in verified_documents):
        raise ValueError("Document availability requires explicit verification snapshots")
    verified_by_target = {}
    for snapshot in verified_documents:
        key = getattr(snapshot, "_target", None)
        if not isinstance(key, str) or len(key) > 4096:
            raise ValueError("Invalid document verification snapshot")
        verified_by_target[key] = snapshot
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    supported = {"research_document_desired", "research_document_applied"} <= tables
    if supported:
        records = size = 0
        for table, condition in (
            ("research_document_desired", " WHERE active=1"),
            ("research_document_applied", ""),
        ):
            count, byte_size = conn.execute(
                f"SELECT count(*),COALESCE(SUM(length(CAST(target AS BLOB))),0) FROM {table}"
                + condition
            ).fetchone()
            records += count
            size += byte_size
        _preflight(conn, max_records - records, max_bytes - size)
        orphan = conn.execute(
            "SELECT 1 FROM research_document_desired d "
            "LEFT JOIN research_paper_identity m ON m.sync_id=d.paper_id "
            "LEFT JOIN papers p ON p.id=m.local_id WHERE d.active=1 AND p.id IS NULL LIMIT 1"
        ).fetchone()
        if orphan is not None:
            raise ValueError("Document projection contains an unresolved paper reference")
    assets = {}
    for paper in result["papers"]:
        desired = desired_document(conn, paper["id"]) if supported else None
        applied = applied_document(conn, paper["id"]) if supported else None
        state = _sync_state(conn, tables, "paper_document", paper["id"], result["cursor"])
        document = {
            "desired": None,
            "applied_sha256": applied["sha256"] if applied is not None else None,
            "availability": "unchecked",
            **state,
        }
        if desired is not None:
            manifest = {key: desired[key] for key in ("paper_id", "sha256", "size", "media_type")}
            document["desired"] = manifest
            asset_id = "sha256:" + desired["sha256"]
            paper["pdf_asset_id"] = asset_id
            snapshot = verified_by_target.get(encode_target(desired))
            if (
                "research_paper_projection" in tables
                and _paper_current(conn, desired)
                and snapshot is not None
                and snapshot.matches(desired)
            ):
                document["availability"] = "available"
            asset = {
                "id": asset_id,
                "sha256": desired["sha256"],
                "size": desired["size"],
                "media_type": desired["media_type"],
                "availability": document["availability"],
            }
            prior = assets.get(asset_id)
            if prior is not None:
                if (prior["size"], prior["media_type"]) != (asset["size"], asset["media_type"]):
                    raise ValueError("Conflicting document content manifests")
                if prior["availability"] == "available":
                    asset["availability"] = "available"
            assets[asset_id] = asset
        paper["document"] = document
    result["assets"] = [assets[key] for key in sorted(assets)]
    result["capabilities"]["document_contract_version"] = 2
    result["capabilities"]["document_manifests"] = True
    result["capabilities"]["assets"] = True
    result["capabilities"]["reader_activation"] = False


def read_manifest(
    path: Path,
    *,
    workspace_id: str,
    schema_version=1,
    max_records=10000,
    max_bytes=8 * 1024 * 1024,
    verified_documents=(),
):
    """Read one consistent bounded snapshot without creating or modifying a database.

    Text remains untrusted text, not HTML. This is a local research read projection;
    its cursor is not authority to skip pending/deferred data during sync bootstrap.
    """
    _identifier(workspace_id)
    if type(schema_version) is not int or schema_version not in (1, 2):
        raise ValueError("Unsupported read projection version")
    if type(max_records) is not int or not 1 <= max_records <= 100000:
        raise ValueError("Invalid projection record limit")
    if type(max_bytes) is not int or not 1 <= max_bytes <= 64 * 1024 * 1024:
        raise ValueError("Invalid projection byte limit")
    conn = None
    try:
        conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        # Positions require the portable owner plus its exact original declaration.
        # Version 1 and incomplete source closures retain the existing refusal.
        position_rows = None
        if schema_version == 2:
            from paper_daily.reading_position_projection import declarations

            binding = conn.execute(
                "SELECT workspace FROM research_sync_binding WHERE id=1"
            ).fetchone()
            if binding is None or binding[0] != workspace_id:
                raise ValueError("Research projection workspace does not match")
            position_rows = declarations(conn)
        result = _project(conn, workspace_id, max_records, max_bytes, position_rows=position_rows)
        if schema_version == 2:
            result = _portable_projection(conn, result)
            _document_projection(conn, result, verified_documents, max_records, max_bytes)
            from paper_daily.reading_position_projection import attach

            attach(result, position_rows)
        from paper_daily.inbox_projection import attach as attach_inbox

        attach_inbox(conn, result, max_records=max_records)
        if (
            position_rows
            and sum(
                len(result.get(key, []))
                for key in (
                    "lists",
                    "papers",
                    "notes",
                    "highlights",
                    "decks",
                    "assets",
                    "reading_positions",
                )
            )
            + len(result.get("inbox", {}).get("items", []))
            > max_records
        ):
            raise ValueError("Research projection exceeds the record limit")
        if len(_encode(result)) > max_bytes:
            raise ValueError("Research projection exceeds the byte limit")
        return result
    except sqlite3.DatabaseError:
        raise ValueError("Research database is unavailable or incompatible") from None
    finally:
        if conn is not None:
            conn.close()
