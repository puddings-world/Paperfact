"""Exact-original reads for a loaded local Lineage result, without source fallback.

This reader grants no write, sync enrollment or detached-archive adoption.
A worker verifies bytes; GUI delivery must use the actual current loaded owner.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field

from paper_daily import (
    claim_content,
    file_change,
    lineage_publication,
    lineage_sets,
    local_source_owners,
    source_snapshots,
)
from paper_daily import position_source_snapshots as atomic_sources
from paper_daily import research_generation as generation
from paper_daily.lineage_jobs import _worker
from paper_daily.lineage_recovery import linked_publication
from paper_daily.manual_highlight_ops import HighlightOwner, _readonly_connection
from paper_daily.research_lifecycle import parent_lifecycle

_KEY = secrets.token_bytes(32)
FIELDS = "request_id context_json row_json status candidate_id reason"


def _row(conn, paper, corpus):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='paper_lineage_sets'").fetchone():
        raise ValueError("Displayed Lineage result is unavailable")
    raw = conn.execute(
        "SELECT paper_id,corpus_key,CASE WHEN length(CAST(body_json AS BLOB))<=? "
        "THEN body_json END,source_hash,document_hash,written_at FROM paper_lineage_sets "
        "WHERE paper_id=? AND corpus_key=?",
        (lineage_sets.MAX_BYTES, paper, corpus),
    ).fetchone()
    if raw is None:
        raise ValueError("Displayed Lineage result is unavailable")
    result = dict(zip(lineage_sets.COLUMNS.split(), raw, strict=True))
    return lineage_sets.validate_row(result)


def _candidate(conn, request_id):
    columns = FIELDS.split()
    limits = (128, generation.MAX_CONTEXT_BYTES, generation.MAX_CONTEXT_BYTES, 16, 64, 128)
    fields = ",".join(
        "CASE WHEN length(CAST(" + key + " AS BLOB))<=? THEN " + key + " END" for key in columns
    )
    raw = conn.execute(
        "SELECT " + fields + " FROM research_generation_requests WHERE request_id=?",
        (*limits, request_id),
    ).fetchone()
    if raw is None:
        raise ValueError("Lineage result lacks its exact retained request")
    return dict(zip(columns, raw, strict=True))


def _latest(conn, row):
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name=?", (lineage_publication.TABLE,)
    ).fetchone():
        raise ValueError("Lineage result has no current local publication receipt")
    selected = conn.execute(
        "SELECT CASE WHEN length(request_id)<=128 THEN request_id END FROM "
        + lineage_publication.TABLE
        + " WHERE "
        + lineage_publication.PAPER_SQL
        + "=? AND "
        + lineage_publication.CORPUS_SQL
        + "=? AND row_json=? ORDER BY rowid DESC LIMIT 1",
        (row["paper_id"], row["corpus_key"], generation._json(row)),
    ).fetchone()
    if selected is None or not isinstance(selected[0], str):
        raise ValueError("Lineage result has no current local publication receipt")
    raw = lineage_publication._receipt(conn, selected[0])
    return dict(zip(("request_id", "candidate_id", "row_json", "sources_json"), raw, strict=True))


def _parents(conn, owner, context):
    owner.check(conn)
    if (
        context["db_path"] != str(owner.database)
        or context["database_identity"] != generation._identity(owner.database)
        or context["binding"] is not None
        or generation._binding(conn) is not None
    ):
        raise ValueError("Lineage original workspace changed")
    for parent in context["inputs"]["parents"]:
        if (
            parent_lifecycle(conn, "paper", parent["paper_id"]) != parent["parent_lifecycle"]
            or not conn.execute("SELECT 1 FROM papers WHERE id=?", (parent["paper_id"],)).fetchone()
        ):
            raise ValueError("Lineage selected paper lifetime changed")


def _associations(conn, originals):
    for original in originals:
        raw = lineage_publication._source_record(conn, original["request_id"])
        if raw is None or tuple(raw) != tuple(
            original[key] for key in local_source_owners.COLUMNS.split()
        ):
            raise ValueError("Lineage exact original association changed")


def _seal(
    owner,
    metadata,
    source_id,
    document_hash,
    paper_id,
    path,
    version,
    receipt_path,
    receipt_version,
    data,
):
    value = [
        id(owner),
        str(owner.database),
        owner.paper_id,
        owner._json,
        metadata,
        source_id,
        document_hash,
        paper_id,
        str(path),
        version,
        str(receipt_path),
        receipt_version,
        id(data),
        os.getpid(),
    ]
    return hmac.new(_KEY, generation._json(value).encode(), "sha256").hexdigest()


@dataclass(frozen=True, slots=True)
class Original:
    _owner: HighlightOwner = field(repr=False)
    _metadata: str = field(repr=False)
    source_id: str
    document_hash: str
    paper_id: str
    _source: object = field(repr=False)
    _version: tuple = field(repr=False)
    _receipt_path: object = field(repr=False)
    _receipt_version: tuple = field(repr=False)
    _data: bytes = field(repr=False)
    _seal: str = field(repr=False)


def _checked(snapshot):
    if (
        not isinstance(snapshot, Original)
        or not isinstance(snapshot._owner, HighlightOwner)
        or not isinstance(snapshot._data, bytes)
        or not isinstance(snapshot._seal, str)
    ):
        raise ValueError("Lineage original requires its native verified snapshot")
    if not hmac.compare_digest(
        snapshot._seal,
        _seal(
            snapshot._owner,
            snapshot._metadata,
            snapshot.source_id,
            snapshot.document_hash,
            snapshot.paper_id,
            snapshot._source,
            snapshot._version,
            snapshot._receipt_path,
            snapshot._receipt_version,
            snapshot._data,
        ),
    ):
        raise ValueError("Lineage original requires its native verified snapshot")
    return json.loads(snapshot._metadata)


def metadata_current(snapshot):
    """Bounded native/SQL/file metadata guard; no PDF parsing, hashing or writes."""
    try:
        expected = _checked(snapshot)
        owner = snapshot._owner
        with closing(_readonly_connection(owner.database)) as conn:
            conn.execute("BEGIN")
            context = json.loads(expected["candidate"]["context_json"])
            _parents(conn, owner, context)
            if _row(conn, owner.paper_id, expected["row"]["corpus_key"]) != expected["row"]:
                return False
            if _latest(conn, expected["row"]) != expected["publication"]:
                return False
            if _candidate(conn, expected["publication"]["request_id"]) != expected["candidate"]:
                return False
            _associations(conn, context["inputs"]["originals"])
        return (
            file_change.version(snapshot._source) == snapshot._version
            and file_change.version(snapshot._receipt_path) == snapshot._receipt_version
        )
    except (ValueError, TypeError, OSError, sqlite3.Error):
        return False


def prepare(owner, expected, source_id, *, cancelled=lambda: False):
    """Worker-only exact saved-result read. None means unavailable or cancelled."""
    _worker()
    if not isinstance(owner, HighlightOwner):
        raise ValueError("Lineage original requires the actual loaded paper owner")
    lineage_sets.validate_row(expected)
    claim_content.digest(source_id)
    if expected["paper_id"] != owner.paper_id:
        raise ValueError("Lineage original belongs to another loaded paper")
    if cancelled():
        return None
    with closing(_readonly_connection(owner.database)) as conn:
        conn.execute("BEGIN")
        owner.check(conn)
        if _row(conn, owner.paper_id, expected["corpus_key"]) != expected:
            raise ValueError("Displayed Lineage result changed")
        receipt = _latest(conn, expected)
        candidate = _candidate(conn, receipt["request_id"])
        saved, originals, context = linked_publication(receipt, candidate)
        if saved != expected:
            raise ValueError("Lineage publication changed")
        _parents(conn, owner, context)
        _associations(conn, originals)
        body = lineage_sets.decode(expected["body_json"])
        selected = next((s for s in body["report"]["sources"] if s["id"] == source_id), None)
        if selected is None:
            raise ValueError("Lineage source is not selected in the displayed corpus")
        if selected["availability"] == "unavailable":
            return None
        original = next(
            r for r in originals if json.loads(r["owner_json"])["source_id"] == source_id
        )
        paper = json.loads(original["owner_json"])["paper_id"]
        metadata = generation._json(dict(row=expected, publication=receipt, candidate=candidate))
    if cancelled():
        return None
    location = source_snapshots.receipt_path(owner.database, original)
    receipt_version = file_change.version(location)
    path = source_snapshots.source_path(owner.database, original)
    verified = local_source_owners._read_pdf(path, original["sha256"], original["size"], cancelled)
    if verified is None:
        return None
    data, version = verified
    verified_path, verified_version = atomic_sources.verify(
        owner.database, original, known_version=version
    )
    if (
        verified_path != path
        or verified_version != version
        or file_change.version(location) != receipt_version
    ):
        raise ValueError("Lineage original changed during verification")
    snapshot = Original(
        owner,
        metadata,
        source_id,
        original["sha256"],
        paper,
        path,
        version,
        location,
        receipt_version,
        data,
        _seal(
            owner,
            metadata,
            source_id,
            original["sha256"],
            paper,
            path,
            version,
            location,
            receipt_version,
            data,
        ),
    )
    if cancelled():
        return None
    if not metadata_current(snapshot):
        raise ValueError("Lineage original ownership changed during verification")
    return snapshot


def for_delivery(snapshot, owner, expected, source_id):
    """Deliver immutable verified PDF bytes only to the actual current loaded view."""
    metadata = _checked(snapshot)
    if (
        owner is not snapshot._owner
        or source_id != snapshot.source_id
        or expected != metadata["row"]
        or not metadata_current(snapshot)
    ):
        raise ValueError("Loaded Lineage view changed before original delivery")
    return snapshot._data
