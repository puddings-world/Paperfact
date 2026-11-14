"""Unbound Lineage publication with all-original transactional associations.

The application coordinator chooses this only for unbound workspaces. Bound
workspaces use the explicit native compound journal publisher, never an outbox
bypass through this seam.
"""

from __future__ import annotations

import hmac
import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import (
    file_change,
    lineage_candidates,
    lineage_observation,
    lineage_sets,
    local_source_owners,
    research_lineage,
    source_snapshots,
    sync_capture,
)
from paper_daily import position_source_snapshots as atomic_sources
from paper_daily import research_generation as generation
from paper_daily.lineage_jobs import _worker
from paper_daily.sync_files import canonical_json

TABLE = "research_lineage_publications"
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS research_lineage_publications("
    "request_id TEXT PRIMARY KEY,candidate_id TEXT NOT NULL,row_json TEXT NOT NULL,"
    "sources_json TEXT NOT NULL)"
)
PAPER_SQL = "CASE WHEN json_valid(row_json) THEN json_extract(row_json,'$.paper_id') END"
CORPUS_SQL = "CASE WHEN json_valid(row_json) THEN json_extract(row_json,'$.corpus_key') END"
INDEX = (
    "CREATE INDEX IF NOT EXISTS research_lineage_publications_target ON "
    + TABLE
    + "("
    + PAPER_SQL
    + ","
    + CORPUS_SQL
    + ")"
)
_KEY = secrets.token_bytes(32)


def _fail(code):
    raise research_lineage.LineageError(code)


def _seal(candidate, files):
    value = [id(candidate), candidate._seal, [[str(p), v] for p, v in files]]
    return hmac.new(_KEY, research_lineage._json(value).encode(), "sha256").hexdigest()


@dataclass(frozen=True, slots=True)
class PreparedPublication:
    _candidate: lineage_candidates.PreparedCandidate = field(repr=False)
    _files: tuple = field(repr=False)
    _seal: str = field(repr=False)


def prepare(candidate, *, cancelled=lambda: False):
    """Verify retained originals off-lock; stage no SQL grants or schema changes."""
    _worker()
    record = lineage_candidates.checked(candidate)
    if candidate._target is None or record["reason"] != "pending_lineage_publication":
        _fail("lineage_observed_publication_required")
    data = lineage_observation.lease_data(candidate._target)
    if data["binding"] is not None:
        _fail("lineage_compound_sync_publication_required")
    lineage_observation.check_target(candidate._target)
    context = json.loads(record["context_json"])
    files = []
    for row in context["inputs"]["originals"]:
        if cancelled():
            _fail("cancelled")
        # Atomic pairs bind bytes and their original metadata, not just a hash.
        receipt = source_snapshots.receipt_path(data["database"], row)
        receipt_version = file_change.version(receipt)
        source, source_version = atomic_sources.verify(Path(data["database"]), row)
        if file_change.version(receipt) != receipt_version:
            _fail("lineage_staged_original_changed")
        files.extend(((receipt, receipt_version), (source, source_version)))
    if cancelled():
        _fail("cancelled")
    lineage_observation.check_target(candidate._target)
    files = tuple(files)
    return PreparedPublication(candidate, files, _seal(candidate, files))


def _retry_check(conn, observed, row):
    """Recheck original metadata allowing only this exact already-installed row."""
    expected = lineage_observation.checked(observed)
    actual, versions = lineage_observation._read_in(
        conn,
        observed._corpus,
        expected["corpus_id"],
        expected["request_id"],
        captured=json.loads(observed._corpus._json),
        sizes={s["source_id"]: s["size"] for s in expected["sources"]},
    )
    if actual["target"] != row:
        _fail("lineage_publication_changed")
    actual["target"] = expected["target"]
    if canonical_json(actual) != canonical_json(expected) or versions != observed._versions:
        _fail("lineage_observation_changed")


def _source_record(conn, request_id):
    return conn.execute(
        "SELECT request_id,CASE WHEN length(CAST(owner_json AS BLOB))<=? "
        "THEN owner_json END,sha256,size,media_type FROM "
        + local_source_owners.TABLE
        + " WHERE request_id=?",
        (source_snapshots.MAX_RECEIPT, request_id),
    ).fetchone()


def _receipt(conn, request_id):
    return conn.execute(
        "SELECT request_id,candidate_id,CASE WHEN length(CAST(row_json AS BLOB))<=? "
        "THEN row_json END,CASE WHEN length(CAST(sources_json AS BLOB))<=? "
        "THEN sources_json END FROM " + TABLE + " WHERE request_id=?",
        (generation.MAX_CONTEXT_BYTES, generation.MAX_CONTEXT_BYTES, request_id),
    ).fetchone()


def publish_in(conn, prepared):
    """Install row, all original associations and receipt in a caller transaction.

    No commit, model call, byte hashing or filesystem publication occurs here.
    The caller must rollback/commit its transaction; retries verify the exact
    published row and every association before acknowledging the old request.
    """
    _worker()
    if not isinstance(prepared, PreparedPublication) or not hmac.compare_digest(
        prepared._seal, _seal(prepared._candidate, prepared._files)
    ):
        _fail("invalid_lineage_publication")
    record = lineage_candidates.checked(prepared._candidate)
    lease = prepared._candidate._target
    data = lineage_observation.lease_data(lease)
    if data["binding"] is not None:
        _fail("lineage_compound_sync_publication_required")
    if not conn.in_transaction:
        _fail("lineage_transaction_required")
    for path, version in prepared._files:
        if file_change.version(path) != version:
            _fail("lineage_staged_original_changed")
    context = json.loads(record["context_json"])
    row = json.loads(record["row_json"])
    originals = context["inputs"]["originals"]
    receipt = (
        record["request_id"],
        record["candidate_id"],
        record["row_json"],
        generation._json(originals),
    )
    savepoint = "lineage_publication_" + secrets.token_hex(8)
    conn.execute("SAVEPOINT " + savepoint)
    try:
        with sync_capture.suppress_capture(conn):
            conn.execute(SCHEMA)
            conn.execute(INDEX)
            conn.execute(local_source_owners.SCHEMA)
            prior = _receipt(conn, record["request_id"])
            if prior is not None:
                if tuple(prior) != receipt:
                    _fail("lineage_publication_request_reused")
                _retry_check(conn, lease._observation, row)
                for original in originals:
                    saved = _source_record(conn, original["request_id"])
                    if saved is None or tuple(saved) != tuple(
                        original[k] for k in local_source_owners.COLUMNS.split()
                    ):
                        _fail("lineage_original_association_changed")
            else:
                lineage_observation.check_in(conn, lease._observation)
                count = conn.execute(
                    "SELECT COUNT(*) FROM paper_lineage_sets WHERE paper_id=?",
                    (row["paper_id"],),
                ).fetchone()[0]
                if data["target"] is None and count >= lineage_sets.MAX_SETS:
                    _fail("lineage_set_limit")
                conn.execute(
                    "INSERT INTO paper_lineage_sets VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(paper_id,corpus_key) DO UPDATE SET "
                    "body_json=excluded.body_json,source_hash=excluded.source_hash,"
                    "document_hash=excluded.document_hash,written_at=excluded.written_at",
                    tuple(row[k] for k in lineage_sets.COLUMNS.split()),
                )
                for original in originals:
                    prior_source = _source_record(conn, original["request_id"])
                    values = tuple(original[k] for k in local_source_owners.COLUMNS.split())
                    if prior_source is not None and tuple(prior_source) != values:
                        _fail("lineage_original_association_changed")
                    if prior_source is None:
                        conn.execute(
                            "INSERT INTO " + local_source_owners.TABLE + " VALUES(?,?,?,?,?)",
                            values,
                        )
                conn.execute("INSERT INTO " + TABLE + " VALUES(?,?,?,?)", receipt)
        conn.execute("RELEASE " + savepoint)
    except BaseException:
        conn.execute("ROLLBACK TO " + savepoint)
        conn.execute("RELEASE " + savepoint)
        if hasattr(conn, "_capture_graph_cache"):
            conn._capture_graph_cache = None
        raise
    return {
        "state": "published",
        "request_id": record["request_id"],
        "candidate_id": record["candidate_id"],
    }
