"""Native unbound Lineage import publication; bound admission remains gated.

Verified byte caches are not ownership. A caller transaction installs scientific
rows, exact receiver-original associations and a distinct native import receipt.
No sender identity or fake AI generation/candidate is adopted.
Unbound bundle imports use this publisher; synchronized enrollment remains
a separate required boundary.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import tempfile
from contextlib import closing, suppress
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import (
    claim_content,
    file_change,
    lineage_packages,
    lineage_sets,
    source_snapshots,
    sync_capture,
)
from paper_daily import (
    lineage_package_targets as targets,
)
from paper_daily import (
    local_source_owners as owners,
)
from paper_daily import research_generation as generation
from paper_daily.lineage_jobs import _worker
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_legacy_sources import path as owned_path
from paper_daily.workspace_service import _binding, _tables

TABLE = "research_lineage_imports"
COLUMNS = "request_id body_json"
FORMAT = "paperfact.lineage-import.v1"
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS research_lineage_imports("
    "request_id TEXT PRIMARY KEY,body_json TEXT NOT NULL)"
)
MAX_ACTIONS = 1000
MAX_HISTORY = 32 * 1024**2
_KEY = secrets.token_bytes(32)


def _schema(conn, name, columns):
    kind = conn.execute("SELECT type FROM sqlite_master WHERE name=?", (name,)).fetchone()
    if kind is None:
        return False
    info = list(conn.execute("PRAGMA table_info(" + name + ")"))
    if (
        tuple(kind) != ("table",)
        or [r[1] for r in info] != columns.split()
        or [r[5] for r in info] != [1] + [0] * (len(info) - 1)
        or [r[2].upper() for r in info]
        != ["INTEGER" if key == "size" else "TEXT" for key in columns.split()]
    ):
        raise ValueError("Lineage import requires its exact native table")
    return True


def _path(database, paper, sha):
    alias = claim_content.hashed(["claim-source-owner", paper])[:24]
    return owned_path(Path(database).parent / "pdf" / ".claim-evidence" / alias / (sha + ".pdf"))


def _stage_file(database, paper, item, data, cancelled):
    destination = _path(database, paper, item["sha256"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        descriptor, name = tempfile.mkstemp(prefix=".lineage-stage-", dir=destination.parent)
        temporary = owned_path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if cancelled():
                raise ValueError("Lineage source staging cancelled")
            with suppress(FileExistsError):
                os.link(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    verified = owners._read_pdf(destination, item["sha256"], item["size"], cancelled)
    if verified is None:
        raise ValueError("Lineage source staging cancelled")
    _data, version = verified
    return (paper, item["sha256"], str(destination), version, item["size"])


def _seal(database, native, request_id, mapping, content, files):
    encoded = lineage_packages._json(
        [
            str(database),
            native,
            request_id,
            mapping,
            hashlib.sha256(content.encode()).hexdigest(),
            files,
            os.getpid(),
        ]
    )
    return hmac.new(_KEY, encoded.encode(), "sha256").hexdigest()


@dataclass(frozen=True, slots=True)
class StagedImport:
    _database: Path = field(repr=False)
    _native: tuple = field(repr=False)
    _request: str = field(repr=False)
    _mapping: str = field(repr=False)
    _content: str = field(repr=False)
    _files: tuple = field(repr=False)
    _seal: str = field(repr=False)


def stage(database, package, paper_map, *, request_id, expected_native, cancelled=lambda: False):
    """Publish unowned exact-byte cache files off-lock, including for new paper IDs."""
    _worker()
    if cancelled():
        raise ValueError("Lineage source staging cancelled")
    content = targets._validated(package)
    lineage_sets.uuid(request_id)
    if not isinstance(paper_map, dict):
        raise ValueError("Lineage import requires an explicit receiver mapping")
    paper_map = dict(paper_map)
    targets._mapping(content["rows"], paper_map)
    database = owned_path(Path(database).resolve(strict=True))
    native = tuple(expected_native) if isinstance(expected_native, (tuple, list)) else ()
    if (
        len(native) != 2
        or any(type(n) is not int or n < 0 for n in native)
        or tuple(generation._identity(database)) != native
    ):
        raise ValueError("Lineage import database changed")
    with closing(_readonly_connection(database)) as conn:
        conn.execute("BEGIN")
        if generation._binding(conn) is not None or _binding(conn, _tables(conn)):
            raise ValueError("Lineage synchronized imports require compound source admission")
    data = dict(package.files)
    files = {}
    for item in content["sources"]:
        if cancelled():
            raise ValueError("Lineage source staging cancelled")
        paper = paper_map[item["paper_id"]]
        key = paper, item["sha256"]
        if key not in files:
            files[key] = _stage_file(database, paper, item, data[item["path"]], cancelled)
    if cancelled():
        raise ValueError("Lineage source staging cancelled")
    if tuple(generation._identity(database)) != native:
        raise ValueError("Lineage import database changed during source staging")
    mapping = lineage_packages._json(paper_map)
    encoded = lineage_packages._json(content)
    selected = tuple(files.values())
    return StagedImport(
        database,
        native,
        request_id,
        mapping,
        encoded,
        selected,
        _seal(database, native, request_id, mapping, encoded, selected),
    )


def _checked(staged):
    if not isinstance(staged, StagedImport) or not hmac.compare_digest(
        staged._seal,
        _seal(
            staged._database,
            staged._native,
            staged._request,
            staged._mapping,
            staged._content,
            staged._files,
        ),
    ):
        raise ValueError("Lineage publication requires its native staged originals")
    content = json.loads(staged._content)
    if tuple(generation._identity(staged._database)) != staged._native:
        raise ValueError("Lineage import database changed")
    for _paper, _sha, path, version, _size in staged._files:
        if file_change.version(owned_path(path)) != version:
            raise ValueError("Lineage staged original changed")
    return content


def _source(request_id, native, parents, row, binding, source, size):
    owner = dict(
        format="paperfact.source-owner.v1",
        database_identity=list(native),
        binding=None,
        paper_id=binding["paper_id"],
        parent_lifecycle=parents[binding["paper_id"]],
        source_owner_id=binding["paper_id"],
    )
    identity = claim_content.hashed(
        [
            FORMAT,
            request_id,
            row["paper_id"],
            row["corpus_key"],
            source["id"],
            owner,
            source["document_hash"],
        ]
    )
    return owners.validate(
        dict(
            request_id="import:" + identity,
            owner_json=lineage_packages._json(owner),
            sha256=source["document_hash"],
            size=size,
            media_type="application/pdf",
        )
    )


def _fingerprint(body):
    return claim_content.hashed(
        {
            k: (
                [{name: value for name, value in r.items() if name != "before_json"} for r in v]
                if k == "records"
                else v
            )
            for k, v in body.items()
            if k != "fingerprint"
        }
    )


def _load(encoded):
    try:
        return json.loads(encoded)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Invalid Lineage import receipt JSON") from exc


def validate_record(record):
    """Validate archived content/provenance only; never a receiver or replay grant."""
    claim_content.closed(record, COLUMNS.split())
    lineage_sets.uuid(record["request_id"])
    encoded = record["body_json"]
    if not isinstance(encoded, str) or len(encoded.encode()) > lineage_packages.MAX_METADATA:
        raise ValueError("Lineage import receipt exceeds its metadata budget")
    body = _load(encoded)
    claim_content.closed(
        body,
        {
            "format",
            "request_id",
            "database_identity",
            "paper_map",
            "parents",
            "records",
            "fingerprint",
        },
    )
    if body["format"] != FORMAT or body["request_id"] != record["request_id"]:
        raise ValueError("Lineage import receipt identity changed")
    native = body["database_identity"]
    if (
        not isinstance(native, list)
        or len(native) != 2
        or any(type(n) is not int or n < 0 for n in native)
    ):
        raise ValueError("Invalid Lineage receiver database identity")
    rows = body["records"]
    if not isinstance(rows, list) or not 0 < len(rows) <= lineage_packages.MAX_REPORTS:
        raise ValueError("Invalid Lineage import report count")
    mapping = body["paper_map"]
    if not isinstance(mapping, dict) or not 0 < len(mapping) <= lineage_packages.MAX_PAPERS:
        raise ValueError("Invalid Lineage import receiver mapping")
    for name, value in mapping.items():
        claim_content.text(name, 4096)
        claim_content.text(value, 4096)
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("Lineage import receiver owners are not distinct")
    parent_rows = body["parents"]
    if not isinstance(parent_rows, list) or len(parent_rows) != len(mapping):
        raise ValueError("Lineage import lacks its complete receiver lifetimes")
    parents = {}
    for item in parent_rows:
        claim_content.closed(item, {"paper_id", "parent_lifecycle"})
        claim_content.text(item["paper_id"], 4096)
        token = item["parent_lifecycle"]
        if (
            not isinstance(token, str)
            or len(token) != 32
            or any(c not in "0123456789abcdef" for c in token)
        ):
            raise ValueError("Invalid Lineage import parent lifetime")
        if item["paper_id"] in parents:
            raise ValueError("Duplicate Lineage receiver lifetime")
        parents[item["paper_id"]] = token
    if list(parents) != sorted(mapping.values()):
        raise ValueError("Lineage import parent order differs from receiver mapping")
    selected, seen = set(), set()
    for item in rows:
        claim_content.closed(item, {"row_json", "before_json", "sources"})
        row = lineage_sets.validate_row(_load(item["row_json"]))
        if lineage_packages._json(row) != item["row_json"]:
            raise ValueError("Lineage import scientific row is not canonical")
        key = row["paper_id"], row["corpus_key"]
        if key in seen:
            raise ValueError("Duplicate Lineage import composite target")
        seen.add(key)
        before = _load(item["before_json"])
        if lineage_packages._json(before) != item["before_json"]:
            raise ValueError("Lineage displaced row is not canonical")
        if before is not None:
            lineage_sets.validate_row(before)
            if (before["paper_id"], before["corpus_key"]) != key or before == row:
                raise ValueError("Lineage displaced research belongs to another target")
        saved = lineage_sets.decode(row["body_json"])
        selected.update(b["paper_id"] for b in saved["bindings"])
        expected = [
            (b, s)
            for b, s in zip(saved["bindings"], saved["report"]["sources"], strict=True)
            if s["availability"] == "available"
        ]
        originals = item["sources"]
        if not isinstance(originals, list) or len(originals) != len(expected):
            raise ValueError("Lineage import lacks its exact original associations")
        for (binding, source), original in zip(expected, originals, strict=True):
            owners.validate(original)
            claim_content.number(original["size"], lineage_packages.MAX_PDF_BYTES, 1)
            if original != _source(
                body["request_id"], native, parents, row, binding, source, original["size"]
            ):
                raise ValueError("Lineage imported original differs from its receiver owner")
    if selected != set(mapping.values()):
        raise ValueError("Lineage import receiver context is incomplete")
    if body["fingerprint"] != _fingerprint(body) or lineage_packages._json(body) != encoded:
        raise ValueError("Lineage import receipt fingerprint changed")
    return body


def _read(conn, request_id):
    if not _schema(conn, TABLE, COLUMNS):
        return None
    raw = conn.execute(
        "SELECT request_id,CASE WHEN length(CAST(body_json AS BLOB))<=? THEN body_json END "
        "FROM research_lineage_imports WHERE request_id=?",
        (lineage_packages.MAX_METADATA, request_id),
    ).fetchone()
    if raw is None:
        return None
    record = dict(zip(COLUMNS.split(), raw, strict=True))
    return validate_record(record)


def _association(conn, original):
    raw = conn.execute(
        "SELECT "
        + ",".join(owners.COLUMNS.split())
        + " FROM "
        + owners.TABLE
        + " WHERE request_id=?",
        (original["request_id"],),
    ).fetchone()
    return None if raw is None else dict(zip(owners.COLUMNS.split(), raw, strict=True))


def publish_in(conn, staged, observed, *, replace=False, cancelled=lambda: False):
    """Publish reports, all original associations and action receipt in caller SQL.

    Bytes were published/hashed off-lock. This bounded savepoint writes no files,
    parses/hashes no PDFs, commits no caller work and activates no sync operation.
    A crash/rollback can leave unowned cached files; those confer no source grant.
    """
    _worker()
    if not conn.in_transaction or type(replace) is not bool:
        raise ValueError("Lineage import requires a caller transaction and explicit replace policy")
    if cancelled():
        raise ValueError("Lineage import cancelled")
    content = _checked(staged)
    mapping = json.loads(staged._mapping)
    rows = targets._mapping(content["rows"], mapping)
    if not rows:
        if observed is not None or generation._path(conn) != str(staged._database):
            raise ValueError("Lineage empty import differs from its receiver")
        return dict(state="empty", reports=0)
    target = targets.checked(observed)
    if (
        generation._path(conn) != str(staged._database)
        or target["database"] != str(staged._database)
        or target["native"] != list(staged._native)
        or target["paper_map"] != mapping
        or target["rows"] != rows
        or target["sources"] != content["sources"]
    ):
        raise ValueError("Lineage staged package differs from its observed receiver")
    actual = targets._read_in(conn, rows, mapping)
    expected = target["observed"]
    if any(
        lineage_packages._json(actual[k]) != lineage_packages._json(expected[k])
        for k in ("papers", "parents")
    ):
        raise ValueError("Lineage receiver paper changed before import")
    _schema(conn, owners.TABLE, owners.COLUMNS)
    prior = _read(conn, staged._request)
    parents = dict(actual["parents"])
    files = {(p, sha): (path, version, size) for p, sha, path, version, size in staged._files}
    records = []
    for row, before in zip(rows, expected["targets"], strict=True):
        saved = lineage_sets.decode(row["body_json"])
        originals = []
        for binding, source in zip(saved["bindings"], saved["report"]["sources"], strict=True):
            if source["availability"] == "unavailable":
                continue
            path, _version, size = files[binding["paper_id"], source["document_hash"]]
            original = _source(staged._request, staged._native, parents, row, binding, source, size)
            if source_snapshots.source_path(staged._database, original) != Path(path):
                raise ValueError("Lineage canonical original path changed")
            originals.append(original)
        records.append(
            dict(
                row_json=lineage_packages._json(row),
                before_json=lineage_packages._json(before if before != row else None),
                sources=originals,
            )
        )
    body = dict(
        format=FORMAT,
        request_id=staged._request,
        database_identity=list(staged._native),
        paper_map=mapping,
        parents=[dict(paper_id=p, parent_lifecycle=t) for p, t in sorted(parents.items())],
        records=records,
    )
    body["fingerprint"] = _fingerprint(body)
    record = dict(request_id=staged._request, body_json=lineage_packages._json(body))
    validate_record(record)
    if prior is not None:
        if prior["fingerprint"] != body["fingerprint"] or actual["targets"] != rows:
            raise ValueError("Lineage import request was reused or its published target changed")
        for item in prior["records"]:
            for original in item["sources"]:
                if _association(conn, original) != original:
                    raise ValueError("Lineage imported original association changed")
        return dict(state="already_imported", reports=len(rows), request_id=staged._request)
    if lineage_packages._json(actual) != lineage_packages._json(expected):
        raise ValueError("Lineage receiver changed before import")
    if not replace and any(
        before is not None and before != row
        for row, before in zip(rows, actual["targets"], strict=True)
    ):
        raise ValueError("Lineage import conflicts with saved research; review replacement first")
    point = "lineage_import_" + secrets.token_hex(8)
    conn.execute("SAVEPOINT " + point)
    try:
        with sync_capture.suppress_capture(conn):
            conn.execute(SCHEMA)
            conn.execute(owners.SCHEMA)
            conn.execute(lineage_sets.SCHEMA)
            count, size = conn.execute(
                "SELECT COUNT(*),COALESCE(SUM(length(CAST(body_json AS BLOB))),0) FROM " + TABLE
            ).fetchone()
            if count >= MAX_ACTIONS or size + len(record["body_json"].encode()) > MAX_HISTORY:
                raise ValueError("Lineage import history exceeds its budget")
            pending_sources = {r["request_id"]: r for item in records for r in item["sources"]}
            source_count = conn.execute("SELECT COUNT(*) FROM " + owners.TABLE).fetchone()[0]
            new_sources = sum(_association(conn, r) is None for r in pending_sources.values())
            if source_count + new_sources > source_snapshots.MAX_RECEIPTS:
                raise ValueError("Lineage import source history exceeds its budget")
            for row, before, item in zip(rows, actual["targets"], records, strict=True):
                if cancelled():
                    raise ValueError("Lineage import cancelled")
                count = conn.execute(
                    "SELECT COUNT(*) FROM paper_lineage_sets WHERE paper_id=?", (row["paper_id"],)
                ).fetchone()[0]
                if before is None and count >= lineage_sets.MAX_SETS:
                    raise ValueError("Lineage import corpus count exceeds its budget")
                conn.execute(
                    "INSERT INTO paper_lineage_sets VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(paper_id,corpus_key) DO UPDATE SET body_json=excluded.body_json,"
                    "source_hash=excluded.source_hash,document_hash=excluded.document_hash,"
                    "written_at=excluded.written_at",
                    [row[k] for k in lineage_sets.COLUMNS.split()],
                )
                for original in item["sources"]:
                    old = _association(conn, original)
                    if old is not None and old != original:
                        raise ValueError("Lineage original association identity changed")
                    if old is None:
                        conn.execute(
                            "INSERT INTO " + owners.TABLE + " VALUES(?,?,?,?,?)",
                            [original[k] for k in owners.COLUMNS.split()],
                        )
            conn.execute(
                "INSERT INTO " + TABLE + " VALUES(?,?)", (record["request_id"], record["body_json"])
            )
            _checked(staged)
            if cancelled():
                raise ValueError("Lineage import cancelled")
        conn.execute("RELEASE " + point)
    except BaseException:
        conn.execute("ROLLBACK TO " + point)
        conn.execute("RELEASE " + point)
        if hasattr(conn, "_capture_graph_cache"):
            conn._capture_graph_cache = None
        raise
    return dict(state="imported", reports=len(rows), request_id=staged._request)


def current_in(conn, row):
    """Find exact stored import provenance as data; this grants no source access."""
    lineage_sets.validate_row(row)
    if not _schema(conn, TABLE, COLUMNS):
        return None
    count, size, largest, valid = conn.execute(
        "SELECT COUNT(*),COALESCE(SUM(length(CAST(body_json AS BLOB))),0),"
        "COALESCE(MAX(length(CAST(body_json AS BLOB))),0),"
        "MIN(CASE WHEN length(CAST(body_json AS BLOB))<=? THEN json_valid(body_json) ELSE 0 END) "
        "FROM (SELECT body_json FROM research_lineage_imports LIMIT ?)",
        (lineage_packages.MAX_METADATA, MAX_ACTIONS + 1),
    ).fetchone()
    if (
        count > MAX_ACTIONS
        or size > MAX_HISTORY
        or largest > lineage_packages.MAX_METADATA
        or (count and valid != 1)
    ):
        raise ValueError("Lineage import history is invalid or exceeds its read budget")
    try:
        request = conn.execute(
            "SELECT request_id FROM research_lineage_imports AS action WHERE EXISTS ("
            "SELECT 1 FROM json_each(action.body_json,'$.records') AS report "
            "WHERE json_extract(report.value,'$.row_json')=?) ORDER BY action.rowid DESC LIMIT 1",
            (lineage_packages._json(row),),
        ).fetchone()
    except sqlite3.Error as exc:
        raise ValueError("Lineage import history contains invalid report records") from exc

    return None if request is None else _read(conn, request[0])


def observe_in(conn, staged, *, cancelled=lambda: False):
    """Observe actual receiver owners from a consumed, file-verified native stage.

    This supports bounded recovery batches without keeping their PDF byte inputs
    alive. It grants no source/report write, and never hashes a PDF under SQL.
    """
    _worker()
    if not conn.in_transaction:
        raise ValueError("Lineage staged observation requires a caller transaction")
    if cancelled():
        raise ValueError("Lineage staged observation cancelled")
    content = _checked(staged)
    if generation._path(conn) != str(staged._database):
        raise ValueError("Lineage staged observation belongs to another database")
    mapping = json.loads(staged._mapping)
    rows = targets._mapping(content["rows"], mapping)
    if not rows:
        return None
    observed = targets._read_in(conn, rows, mapping)
    if tuple(generation._identity(staged._database)) != staged._native:
        raise ValueError("Lineage staged observation database changed")
    if cancelled():
        raise ValueError("Lineage staged observation cancelled")
    encoded = lineage_packages._json(
        dict(
            database=str(staged._database),
            native=list(staged._native),
            observed=observed,
            paper_map=mapping,
            rows=rows,
            sources=content["sources"],
        )
    )
    return targets.Targets(encoded, targets._seal(encoded))
