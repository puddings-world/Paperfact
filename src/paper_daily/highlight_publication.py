"""Closed companion writes for one generated analysis and its exact PDF marks.

The analysis receipt carries the located output; old mark rows keep user-owned
hidden preferences. Canonical readers display only the current analysis layer.
"""

import hashlib
import json
from dataclasses import replace

from paper_daily import annotation_content, sync_capture, sync_content
from paper_daily import research_generation as generation

TABLE = "paper_highlight_analysis"
MARK_FIELDS = [
    "paper_id",
    "document_hash",
    "source_key",
    "analysis_hash",
    "anchor",
    "quote",
    "reason",
    "hidden",
]


def inputs(conn, owner):
    rows = [
        dict(row)
        for row in conn.execute(
            "SELECT " + ",".join(MARK_FIELDS) + " FROM pdf_ai_highlights WHERE paper_id=? "
            "ORDER BY document_hash,source_key LIMIT ?",
            (owner, generation.MAX_ROWS + 1),
        )
    ]
    if len(rows) > generation.MAX_ROWS:
        raise ValueError("Highlight history exceeds the observed-record budget")
    known = bool(
        conn.execute(
            "SELECT 1 FROM paper_annotation_known "
            "WHERE feature='highlight_analysis' AND paper_id=?",
            (owner,),
        ).fetchone()
    )
    tokens = {}
    if sync_capture.enabled(conn):
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?",
            (owner,),
        ).fetchone()[0]
        keys = {row["document_hash"] + ":" + row["source_key"] for row in rows}
        # Projection identity survives deletion: capture tombstones as well as rows.
        keys.update(
            row[0]
            for row in conn.execute(
                "SELECT item_key FROM research_content_projection WHERE feature='ai_highlight' "
                "AND scope_kind='paper' AND scope_id=? LIMIT ?",
                (portable, generation.MAX_ROWS + 1),
            )
        )
        if len(keys) > generation.MAX_ROWS:
            raise ValueError("Highlight history exceeds the observed-graph budget")
        tokens = {
            key: sync_capture.observe_target(conn, "paper", owner, "ai_highlight", key)
            for key in sorted(keys)
        }
    return {"marks": rows, "known": known, "tokens": tokens}


def token(context, key):
    data = context.data
    if data["binding"] is None:
        return None
    if key in data["inputs"]["tokens"]:
        return data["inputs"]["tokens"][key]
    observed = data["observation"]
    parent = observed["parents"]
    return {
        "workspace_id": data["binding"]["workspace_id"],
        "kind": "research_content",
        "entity_id": sync_content.content_id(
            {"kind": "paper", "id": parent[0]["id"]},
            "ai_highlight",
            key,
        ),
        "revision": 0,
        "predecessor": None,
        "incarnation": None,
        "active": False,
        "parents": parent,
    }


def seal(context, row, located, unmatched):
    """Attach already located output without observing any new write authority."""
    old = {(item["document_hash"], item["source_key"]): item for item in context.inputs["marks"]}
    marks = []
    for key, anchor, item in located:
        marks.append(
            {
                "paper_id": context.owner_id,
                "document_hash": row["document_hash"],
                "source_key": key,
                "analysis_hash": row["source_hash"],
                "anchor": json.dumps(anchor, sort_keys=True, separators=(",", ":")),
                "quote": item["text"],
                "reason": item["reason"],
                "hidden": old.get((row["document_hash"], key), {}).get("hidden", 0),
            }
        )
    body = annotation_content.decode("highlight_analysis", row["body_json"])
    indexes = [body["items"].index(item) for item in unmatched]
    data = context.data
    data["highlight_plan"] = {"marks": marks, "unmatched": indexes}
    result = replace(context, _json=generation._context_json(data))
    validate(result, row)
    return result


def validate(context, row):
    data = context.data
    captured = data["inputs"]
    if (
        data["table"] != TABLE
        or data["input_reader"] != "highlights"
        or not data["document"]
        or row["document_hash"] != data["document"]["sha256"]
    ):
        raise ValueError("Highlight publication requires its exact observed PDF")
    if (
        not isinstance(captured, dict)
        or set(captured) != {"marks", "known", "tokens"}
        or type(captured["known"]) is not bool
        or not isinstance(captured["marks"], list)
        or len(captured["marks"]) > generation.MAX_ROWS
        or not isinstance(captured["tokens"], dict)
        or len(captured["tokens"]) > generation.MAX_ROWS
    ):
        raise ValueError("Invalid highlight observation")
    originals = {}
    for original in captured["marks"]:
        _validate_mark(original, context.owner_id)
        identity = (original["document_hash"], original["source_key"])
        if identity in originals:
            raise ValueError("Duplicate captured highlight")
        originals[identity] = original
    if data["binding"] is None and captured["tokens"]:
        raise ValueError("Unbound highlights cannot carry synchronized authority")
    for key, observed in captured["tokens"].items():
        if (
            not isinstance(key, str)
            or len(key) != 129
            or key[64] != ":"
            or not annotation_content.HASH.fullmatch(key[:64])
            or not annotation_content.HASH.fullmatch(key[65:])
        ):
            raise ValueError("Invalid observed highlight identity")
        parent = data["observation"]["parents"]
        if (
            not isinstance(observed, dict)
            or set(observed)
            != {
                "workspace_id",
                "kind",
                "entity_id",
                "revision",
                "predecessor",
                "incarnation",
                "active",
                "parents",
            }
            or observed["workspace_id"] != data["binding"]["workspace_id"]
            or observed["kind"] != "research_content"
            or observed["parents"] != parent
            or observed["entity_id"]
            != sync_content.content_id(
                {"kind": "paper", "id": parent[0]["id"]}, "ai_highlight", key
            )
            or type(observed["revision"]) is not int
            or observed["revision"] < 0
            or type(observed["active"]) is not bool
            or any(
                observed[name] is not None and not isinstance(observed[name], str)
                for name in ("incarnation", "predecessor")
            )
        ):
            raise ValueError("Invalid captured highlight authority")
    plan = data.get("highlight_plan")
    if (
        not isinstance(plan, dict)
        or set(plan) != {"marks", "unmatched"}
        or not isinstance(plan["marks"], list)
        or not isinstance(plan["unmatched"], list)
        or len(plan["marks"]) + len(plan["unmatched"]) > annotation_content.MAX_ITEMS
    ):
        raise ValueError("Invalid located highlight plan")
    body = annotation_content.decode("highlight_analysis", row["body_json"])
    items = body["items"]
    expected = {
        hashlib.sha256(f"{item['page']}:{item['text']}".encode()).hexdigest(): (i, item)
        for i, item in enumerate(items)
    }
    used = []
    for mark in plan["marks"]:
        _validate_mark(mark, context.owner_id)
        match = expected.get(mark["source_key"])
        if match is None:
            raise ValueError("Located mark is not part of the analysis")
        index, item = match
        anchor = json.loads(mark["anchor"])
        old = originals.get((mark["document_hash"], mark["source_key"]))
        if (
            mark["document_hash"] != row["document_hash"]
            or mark["analysis_hash"] != row["source_hash"]
            or mark["quote"] != item["text"]
            or mark["reason"] != item["reason"]
            or item["page"] is None
            or anchor["p0"] != item["page"] - 1
            or anchor["p1"] != anchor["p0"]
            or mark["hidden"] != (old["hidden"] if old else 0)
        ):
            raise ValueError("Located highlight differs from its verified analysis or user choice")
        used.append(index)
    if any(type(index) is not int for index in plan["unmatched"]):
        raise ValueError("Invalid unlocated highlight index")
    used.extend(plan["unmatched"])
    if sorted(used) != list(range(len(items))):
        raise ValueError("Every highlight must be located or explicitly unmatched exactly once")


def _validate_mark(mark, owner):
    if (
        not isinstance(mark, dict)
        or set(mark) != set(MARK_FIELDS)
        or mark["paper_id"] != owner
        or not isinstance(mark["source_key"], str)
        or not annotation_content.HASH.fullmatch(mark["source_key"])
    ):
        raise ValueError("Invalid highlight row")
    values = {name: mark[name] for name in sync_content.FEATURES["ai_highlight"][2].split()}
    values["anchor"] = json.loads(values["anchor"])
    sync_content.validate_payload(
        {
            "scope": {"kind": "paper", "id": "11111111-1111-4111-8111-111111111111"},
            "feature": "ai_highlight",
            "key": mark["document_hash"] + ":" + mark["source_key"],
            "data": values,
            "source_document_hash": mark["document_hash"],
        }
    )


def expectations(context):
    return [
        token(context, mark["document_hash"] + ":" + mark["source_key"])
        for mark in context.data["highlight_plan"]["marks"]
    ]


def stale(conn, context):
    for mark, observed in zip(
        context.data["highlight_plan"]["marks"], expectations(context), strict=True
    ):
        if observed and not observed["active"] and observed["incarnation"] is not None:
            return "A deleted highlight requires explicit restoration"
        current = sync_capture.observe_target(
            conn,
            "paper",
            context.owner_id,
            "ai_highlight",
            mark["document_hash"] + ":" + mark["source_key"],
        )
        if current != observed:
            return "Highlight content or its parent changed"
    return None


def apply(conn, context):
    """Called only inside the analysis publication transaction and captured scope."""
    for mark in context.data["highlight_plan"]["marks"]:
        conn.execute(
            "INSERT INTO pdf_ai_highlights(" + ",".join(MARK_FIELDS) + ") VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(paper_id,document_hash,source_key) DO UPDATE SET "
            "analysis_hash=excluded.analysis_hash,anchor=excluded.anchor,quote=excluded.quote,"
            "reason=excluded.reason,hidden=excluded.hidden",
            tuple(mark[name] for name in MARK_FIELDS),
        )
