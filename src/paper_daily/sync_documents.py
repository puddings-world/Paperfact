"""Explicit document intents and verified-byte bindings, without reader activation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from paper_daily.sync_blobs import BlobError, BlobManifest, BlobStore, _no_link
from paper_daily.sync_journal import _identifier

MAX_PDF_BYTES = 150 * 1024 * 1024
_TARGET_FIELDS = {
    "workspace_id",
    "paper_id",
    "operation_id",
    "incarnation",
    "parent_incarnation",
    "sha256",
    "size",
    "media_type",
}
_SEAL = object()


def validate_manifest(value, *, paper_id=None):
    if not isinstance(value, dict) or set(value) != {"paper_id", "sha256", "size", "media_type"}:
        raise ValueError("Unexpected or missing document manifest fields")
    identity = value["paper_id"]
    try:
        if not isinstance(identity, str) or str(UUID(identity)) != identity:
            raise ValueError("Invalid portable document paper")
    except (ValueError, AttributeError):
        raise ValueError("Invalid portable document paper") from None
    if paper_id is not None and identity != paper_id:
        raise ValueError("Document identity must match its paper parent")
    if (
        not isinstance(value["sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None
    ):
        raise ValueError("Document requires a lowercase SHA256 digest")
    if type(value["size"]) is not int or not 0 < value["size"] <= MAX_PDF_BYTES:
        raise ValueError("Document size must be positive and at most 150 MiB")
    if value["media_type"] != "application/pdf":
        raise ValueError("Only primary PDF documents are supported")


def _validate_target(target):
    if not isinstance(target, dict) or set(target) != _TARGET_FIELDS:
        raise ValueError("Invalid document target")
    for key in ("workspace_id", "operation_id", "incarnation", "parent_incarnation"):
        _identifier(target[key])
    validate_manifest({key: target[key] for key in ("paper_id", "sha256", "size", "media_type")})


def _encode(target):
    _validate_target(target)
    return json.dumps(target, sort_keys=True, separators=(",", ":"))


def initialize(conn):
    if not conn.in_transaction:
        raise ValueError("Document initialization requires a caller transaction")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS research_paper_projection ("
        "sync_id TEXT PRIMARY KEY,incarnation TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS research_document_desired ("
        "paper_id TEXT PRIMARY KEY,target TEXT NOT NULL,active INTEGER NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS research_document_applied ("
        "paper_id TEXT PRIMARY KEY,target TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS research_document_intents ("
        "operation_id TEXT PRIMARY KEY,paper_id TEXT NOT NULL,target TEXT NOT NULL,"
        "state TEXT NOT NULL DEFAULT 'pending')"
    )


def _stored_target(conn, table, paper_id, *, active=False):
    # Table names are internal constants, never caller-supplied paths or SQL.
    row = conn.execute(
        f"SELECT CASE WHEN length(target)<=4096 THEN target ELSE NULL END FROM {table} "
        "WHERE paper_id=?" + (" AND active=1" if active else ""),
        (paper_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        target = json.loads(row[0])
        _validate_target(target)
    except (TypeError, ValueError, RecursionError):
        raise ValueError("Invalid stored document target") from None
    if target["paper_id"] != paper_id:
        raise ValueError("Stored document identity does not match")
    binding = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
    if binding is None or target["workspace_id"] != binding[0]:
        raise ValueError("Stored document workspace does not match")
    return target


def desired_document(conn, paper_id):
    """Read the active desired manifest; no bytes or paths are accessed."""
    return _stored_target(conn, "research_document_desired", paper_id, active=True)


def applied_document(conn, paper_id):
    """Return the last bound target, which can differ from the desired document."""
    return _stored_target(conn, "research_document_applied", paper_id)


def list_desired_documents(conn, *, after="", limit=100):
    """Page current transfer targets by portable paper ID, without exposing bookkeeping."""
    if type(limit) is not int or not 1 <= limit <= 1000 or not isinstance(after, str):
        raise ValueError("Invalid document target page")
    if after:
        _identifier(after)
    rows = conn.execute(
        "SELECT paper_id FROM research_document_desired WHERE active=1 AND paper_id>? "
        "ORDER BY paper_id LIMIT ?",
        (after, limit),
    ).fetchall()
    return [desired_document(conn, row[0]) for row in rows]


def _paper_current(conn, target):
    row = conn.execute(
        "SELECT p.id,g.incarnation FROM research_paper_identity m "
        "LEFT JOIN papers p ON p.id=m.local_id "
        "LEFT JOIN research_paper_projection g ON g.sync_id=m.sync_id WHERE m.sync_id=?",
        (target["paper_id"],),
    ).fetchone()
    return row is not None and row[0] is not None and row[1] == target["parent_incarnation"]


def write_document(conn, operation):
    """Store metadata and its durable transfer intent in the research transaction."""
    from paper_daily.sync_journal import canonical_operation

    canonical_operation(operation)
    if not conn.in_transaction or operation["entity_type"] != "paper_document":
        raise ValueError("Document writes require a transaction and document operation")
    binding = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
    if binding is None or binding[0] != operation["workspace_id"]:
        raise ValueError("Document operation belongs to another workspace")
    identity = operation["entity_id"]
    if operation["action"] == "delete":
        current = desired_document(conn, identity)
        if current is not None and (current["incarnation"], current["parent_incarnation"]) == (
            operation["incarnation"],
            operation["parents"][0]["incarnation"],
        ):
            conn.execute(
                "UPDATE research_document_desired SET active=0 WHERE paper_id=?", (identity,)
            )
            conn.execute(
                "UPDATE research_document_intents SET state='superseded' WHERE paper_id=? "
                "AND state='pending'",
                (identity,),
            )
        return
    target = {
        **operation["payload"],
        "workspace_id": operation["workspace_id"],
        "operation_id": operation["operation_id"],
        "incarnation": operation["incarnation"],
        "parent_incarnation": operation["parents"][0]["incarnation"],
    }
    if not _paper_current(conn, target):
        raise ValueError("Document requires its current projected paper incarnation")
    encoded = _encode(target)
    prior = conn.execute(
        "SELECT target FROM research_document_intents WHERE operation_id=?",
        (target["operation_id"],),
    ).fetchone()
    if prior is not None and prior[0] != encoded:
        raise ValueError("Document operation identity was reused with different content")
    conn.execute(
        "UPDATE research_document_intents SET state='superseded' WHERE paper_id=? "
        "AND operation_id!=? AND state='pending'",
        (identity, target["operation_id"]),
    )
    conn.execute(
        "INSERT INTO research_document_desired VALUES(?,?,1) ON CONFLICT(paper_id) "
        "DO UPDATE SET target=excluded.target,active=1 WHERE target!=excluded.target OR active!=1",
        (identity, encoded),
    )
    conn.execute(
        "INSERT INTO research_document_intents(operation_id,paper_id,target) VALUES(?,?,?) "
        "ON CONFLICT(operation_id) DO NOTHING",
        (target["operation_id"], identity, encoded),
    )


def _identity(path):
    for entry in (path, *path.parents):
        _no_link(entry)
    info = path.stat()
    if not path.is_file():
        raise BlobError("Document object must be a regular file")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@dataclass(frozen=True, init=False)
class VerifiedDocument:
    """Process-local validation snapshot; never deserialize one from a remote claim."""

    _target: str
    _path: Path
    _identity: tuple
    _seal: object

    def matches(self, target):
        if getattr(self, "_seal", None) is not _SEAL or self._target != _encode(target):
            return False
        try:
            return _identity(self._path) == self._identity
        except (OSError, BlobError):
            return False


def verify_document(store: BlobStore, target: dict) -> VerifiedDocument:
    """Verify bytes and PDF readability off the UI thread; do not activate a reader."""
    import pymupdf

    encoded = _encode(target)
    if not isinstance(store, BlobStore):
        raise ValueError("An explicitly bound BlobStore is required")
    manifest = BlobManifest(target["sha256"], target["size"])
    path = store._path(manifest)
    before = _identity(path)
    store.verified_path(manifest)
    try:
        with path.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise ValueError("Invalid PDF header")
            stream.seek(max(0, target["size"] - 4096))
            if b"%%EOF" not in stream.read(4096):
                raise ValueError("Incomplete PDF")
        with pymupdf.open(path) as document:
            if document.needs_pass or document.page_count < 1:
                raise ValueError("Unreadable PDF")
            for index in range(document.page_count):
                document.load_page(index)
    except Exception:
        raise ValueError("Document is not a complete readable PDF") from None
    if _identity(path) != before:
        raise ValueError("Document changed during verification")
    verified = object.__new__(VerifiedDocument)
    for key, value in {
        "_target": encoded,
        "_path": path,
        "_identity": before,
        "_seal": _SEAL,
    }.items():
        object.__setattr__(verified, key, value)
    return verified


def bind_verified_document(conn, target: dict, verified: VerifiedDocument) -> bool:
    """Bind only a still-current verified target; caller owns session checks and commit."""
    if not conn.in_transaction:
        raise ValueError("Document binding requires a caller transaction")
    encoded = _encode(target)
    if not isinstance(verified, VerifiedDocument):
        raise ValueError("Document binding requires an explicit verification snapshot")
    if not verified.matches(target) or desired_document(conn, target["paper_id"]) != target:
        return False
    if not _paper_current(conn, target):
        return False
    conn.execute(
        "INSERT INTO research_document_applied VALUES(?,?) ON CONFLICT(paper_id) "
        "DO UPDATE SET target=excluded.target WHERE target!=excluded.target",
        (target["paper_id"], encoded),
    )
    conn.execute(
        "UPDATE research_document_intents SET state='bound' "
        "WHERE operation_id=? AND state!='bound'",
        (target["operation_id"],),
    )
    return True
