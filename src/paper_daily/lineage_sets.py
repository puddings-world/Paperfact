"""Typed corpus bindings stay separate from portable lineage evidence identities."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID

from paper_daily import lineage_content as evidence
from paper_daily.claim_content import closed, digest, hashed, text

TABLE = "paper_lineage_sets"
FIELDS = "body_json source_hash document_hash written_at"
COLUMNS = "paper_id corpus_key " + FIELDS
FORMAT = "paperfact.lineage-set.v1"
MAX_BYTES = 230 * 1024
MAX_SETS = 64
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS paper_lineage_sets("
    "paper_id TEXT NOT NULL,corpus_key TEXT NOT NULL,body_json TEXT NOT NULL,"
    "source_hash TEXT NOT NULL,document_hash TEXT NOT NULL,written_at TEXT NOT NULL,"
    "PRIMARY KEY(paper_id,corpus_key))"
)


def uuid(value):
    if not isinstance(value, str):
        raise ValueError("Lineage corpus identity requires a canonical UUID")
    try:
        if str(UUID(value)) != value:
            raise ValueError("Invalid lineage corpus identity")
    except (ValueError, AttributeError):
        raise ValueError("Lineage corpus identity requires a canonical UUID") from None


def canonical(value):
    result = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    if len(result.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Lineage set exceeds its bounded inline budget")
    return result


def validate(body, *, portable=False):
    closed(body, {"format", "corpus_id", "inputs", "generation", "report", "bindings"})
    if body["format"] != FORMAT:
        raise ValueError("Unsupported lineage set format")
    uuid(body["corpus_id"])
    closed(body["inputs"], {"dive", "close_reading"})
    for value in body["inputs"].values():
        if value is not None:
            digest(value)
    metadata = body["generation"]
    closed(metadata, {"task", "backend", "requested_model", "returned_model"})
    if metadata["task"] != "lineage":
        raise ValueError("Invalid lineage generation task")
    text(metadata["backend"], 64)
    text(metadata["requested_model"], 512, nullable=True)
    text(metadata["returned_model"], 512, nullable=True)
    evidence.validate(body["report"])
    if body["report"]["verification_scope"] != "original_snapshots":
        raise ValueError("Saved lineage must identify its original snapshot scope")
    bindings = body["bindings"]
    sources = body["report"]["sources"]
    if not isinstance(bindings, list) or len(bindings) != len(sources):
        raise ValueError("Lineage requires each captured source owner")
    seen = set()
    for binding, source in zip(bindings, sources, strict=True):
        closed(binding, {"source_id", "paper_id"})
        if binding["source_id"] != source["id"]:
            raise ValueError("Lineage source binding changed its evidence identity")
        text(binding["paper_id"], 4096)
        if portable:
            uuid(binding["paper_id"])
        if binding["paper_id"] in seen:
            raise ValueError("Lineage corpus has duplicate selected paper owners")
        seen.add(binding["paper_id"])
    if bindings[0]["source_id"] != body["report"]["focal"]:
        raise ValueError("Lineage corpus must begin with its focal paper")
    canonical(body)
    return body


def decode(encoded, *, portable=False):
    if not isinstance(encoded, str) or len(encoded.encode()) > MAX_BYTES:
        raise ValueError("Lineage set exceeds its bounded inline budget")

    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value:
                raise ValueError("Duplicate lineage set field")
            value[key] = item
        return value

    def invalid(_value):
        raise ValueError("Nonfinite lineage set value")

    try:
        return validate(
            json.loads(encoded, object_pairs_hook=pairs, parse_constant=invalid), portable=portable
        )
    except (TypeError, UnicodeError, RecursionError):
        raise ValueError("Invalid bounded lineage set") from None


def source_hash(body):
    validate(body)
    return hashed(
        [
            FORMAT,
            body["corpus_id"],
            body["inputs"],
            [
                {"id": s["id"], "document_hash": s["document_hash"]}
                for s in body["report"]["sources"]
            ],
        ]
    )


def validate_row(row):
    from paper_daily.sync_content import _stamp

    closed(row, COLUMNS.split())
    text(row["paper_id"], 4096)
    uuid(row["corpus_key"])
    digest(row["document_hash"])
    digest(row["source_hash"])
    _stamp(row["written_at"])
    body = decode(row["body_json"])
    focal = body["report"]["sources"][0]
    if (
        row["corpus_key"] != body["corpus_id"]
        or row["paper_id"] != body["bindings"][0]["paper_id"]
        or row["document_hash"] != focal["document_hash"]
        or row["source_hash"] != source_hash(body)
    ):
        raise ValueError("Lineage row differs from its captured corpus")
    return row


def convert(conn, body, *, portable):
    """Map only registered paper identities; never mint identities from a report."""
    validate(body, portable=not portable)
    result = json.loads(canonical(body))
    for binding in result["bindings"]:
        row = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?"
            if portable
            else "SELECT local_id FROM research_paper_identity WHERE sync_id=?",
            (binding["paper_id"],),
        ).fetchone()
        if row is None:
            raise ValueError("Lineage requires its registered selected paper owner")
        if not conn.execute(
            "SELECT 1 FROM papers WHERE id=?", (binding["paper_id"] if portable else row[0],)
        ).fetchone():
            raise ValueError("Lineage selected paper owner is missing")
        binding["paper_id"] = row[0]
    validate(result, portable=portable)
    if result["report"] != body["report"]:
        raise ValueError("Lineage identity conversion altered source evidence")
    return result


def saved(database, paper_id, *, corpus_id=None):
    """Bounded saved-only read; no account, search, source activation or AI."""
    if corpus_id is not None:
        uuid(corpus_id)
    database = Path(database).resolve(strict=True)
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.05)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone():
            return []
        clauses = "paper_id=?" + (" AND corpus_key=?" if corpus_id else "")
        rows = conn.execute(
            "SELECT paper_id,corpus_key,CASE WHEN length(CAST(body_json AS BLOB))<=? "
            "THEN body_json END,source_hash,document_hash,written_at FROM paper_lineage_sets "
            "WHERE " + clauses + " ORDER BY written_at DESC,corpus_key LIMIT ?",
            (MAX_BYTES, paper_id, corpus_id, MAX_SETS + 1)
            if corpus_id
            else (MAX_BYTES, paper_id, MAX_SETS + 1),
        ).fetchall()
        if len(rows) > MAX_SETS:
            raise ValueError("Lineage history requires bounded explicit selection")
        result = [dict(zip(COLUMNS.split(), row, strict=True)) for row in rows]
        for row in result:
            validate_row(row)
        return result
