"""Receiver-local imported originals; private receipts are never replay authority.

Import stages immutable bytes off-lock, then grants ownership only beside the
actual canonical claim in its SQL transaction. Read-only viewers create nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing, suppress
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path

from paper_daily import (
    annotation_content,
    claim_content,
    file_change,
    source_snapshots,
    sync_capture,
)
from paper_daily import research_generation as generation
from paper_daily.research_lifecycle import ensure_lifecycle, parent_lifecycle
from paper_daily.sync_documents import MAX_PDF_BYTES
from paper_daily.sync_files import canonical_json
from paper_daily.sync_legacy_sources import path as owned_path
from paper_daily.sync_legacy_sources import validate_pdf
from paper_daily.workspace_service import _binding, _tables

TABLE = "research_local_source_owners"
COLUMNS = source_snapshots.COLUMNS
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS research_local_source_owners("
    "request_id TEXT PRIMARY KEY,owner_json TEXT NOT NULL,sha256 TEXT NOT NULL,"
    "size INTEGER NOT NULL,media_type TEXT NOT NULL)"
)
MAX_IMPORTS = 500
MAX_IMPORT_BYTES = 512 * 1024**2
MAX_METADATA = 16 * 1024**2
_SEAL = object()


def validate(row):
    source_snapshots.validate(row, max_pdf_bytes=MAX_PDF_BYTES)
    owner = json.loads(row["owner_json"])
    if owner["format"] in {source_snapshots.NOTE_FORMAT, source_snapshots.LINEAGE_FORMAT}:
        return row
    if owner["format"] in source_snapshots.POSITION_FORMATS:
        if row["request_id"] != "position:" + hashlib.sha256(canonical_json(owner)).hexdigest():
            raise ValueError("Position source receipt requires its exact typed owner")
        return row
    if not row["request_id"].startswith("import:") or owner["source_owner_id"] != owner["paper_id"]:
        raise ValueError("Imported source receipt requires its receiver-local owner")
    return row


def _connection(database):
    conn = sqlite3.connect(
        Path(database).as_uri() + "?mode=ro",
        uri=True,
        factory=sync_capture.CaptureConnection,
        timeout=0.05,
    )
    conn.row_factory = sqlite3.Row
    return conn


def _schema(conn):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone():
        return False
    if [row[1] for row in conn.execute("PRAGMA table_info(" + TABLE + ")")] != COLUMNS.split():
        raise ValueError("Local original ownership schema requires review")
    return True


def records(conn, *, document_hash=None):
    """Bounded original observations for archival; not a grant to a new DB owner."""
    if not _schema(conn):
        return []
    rows, size = [], 0
    for raw in conn.execute(
        "SELECT request_id,CASE WHEN length(CAST(owner_json AS BLOB))<=? THEN owner_json END,"
        "sha256,size,media_type FROM "
        + TABLE
        + (" WHERE sha256=?" if document_hash is not None else "")
        + " ORDER BY request_id LIMIT ?",
        (
            (source_snapshots.MAX_RECEIPT, document_hash, source_snapshots.MAX_RECEIPTS + 1)
            if document_hash is not None
            else (source_snapshots.MAX_RECEIPT, source_snapshots.MAX_RECEIPTS + 1)
        ),
    ):
        row = dict(zip(COLUMNS.split(), raw, strict=True))
        validate(row)
        size += len(canonical_json(row))
        if len(rows) >= source_snapshots.MAX_RECEIPTS or size > MAX_METADATA:
            raise ValueError("Local source provenance exceeds its metadata budget")
        rows.append(row)
    return rows


def list_owned(database):
    """Archive private observations with their original owners; never rebind them."""
    with closing(_connection(Path(database).resolve(strict=True))) as conn:
        return records(conn)


def _claim(conn, paper_id):
    row = conn.execute(
        "SELECT paper_id,CASE WHEN length(CAST(body_json AS BLOB))<=? THEN body_json END,"
        "source_hash,document_hash,written_at FROM paper_claim_sets WHERE paper_id=?",
        (annotation_content.MAX_BYTES, paper_id),
    ).fetchone()
    if row is None:
        return None
    value = dict(
        zip(
            ("paper_id", "body_json", "source_hash", "document_hash", "written_at"),
            row,
            strict=True,
        )
    )
    annotation_content.validate_row("claims", value)
    return value


def _check_database(conn, database, identity, binding, scope):
    if (
        generation._path(conn) != str(database)
        or tuple(generation._identity(database)) != identity
        or generation._binding(conn) != binding
        or _binding(conn, _tables(conn)) != scope
    ):
        raise ValueError("Imported original database or workspace changed")


def _read_pdf(path, digest, size, cancelled=lambda: False):
    selected = owned_path(path)
    if type(size) is not int or not 0 < size <= MAX_PDF_BYTES:
        raise ValueError("Original source exceeds its byte budget")
    if selected.stat().st_size != size:
        raise ValueError("Original source size changed")
    result, actual = bytearray(), hashlib.sha256()
    with selected.open("rb") as stream:
        before = file_change.version(selected, stream=stream)
        while block := stream.read(min(256 * 1024, size + 1 - len(result))):
            if cancelled():
                return None
            result.extend(block)
            actual.update(block)
            if len(result) > size:
                raise ValueError("Original source grew during verification")
        if len(result) != size or file_change.version(selected, stream=stream) != before:
            raise ValueError("Original source changed during verification")
    if actual.hexdigest() != digest or file_change.version(selected) != before:
        raise ValueError("Original source bytes differ from their owned hash")
    return bytes(result), before


@dataclass(frozen=True, init=False)
class PreparedImportSource:
    database: Path
    identity: tuple
    binding: object
    scope: tuple
    paper_id: str
    claim: bytes
    sha256: str
    size: int
    path: Path
    file_version: tuple
    seal: object = field(repr=False)


def prepare_import(database, archive, manifest, tables, *, excluded=(), cancelled=lambda: False):
    """Publish only included claim originals as unowned immutable cache bytes.

    The archive is already validated by bundle. This seam validates its typed claim
    rows again, owns its own file/read handles, and performs no research writes.
    """
    from paper_daily.bundle import _claim_source_relative

    database = owned_path(Path(database).resolve(strict=True))
    identity = tuple(generation._identity(database))
    with closing(_connection(database)) as conn:
        binding = generation._binding(conn)
        scope = _binding(conn, _tables(conn))
    if binding is not None:
        raise ValueError("An enrolled workspace must use the observed package importer")
    selected = []
    total = 0
    for row in tables.get("paper_claim_sets", []):
        annotation_content.validate_row("claims", row)
        paper_id, digest = row["paper_id"], row["document_hash"]
        if paper_id in excluded:
            continue
        record = manifest.get("claim_sources", {}).get(paper_id)
        if record is None or record.get("path") is None:
            continue  # No included bytes means no new ownership, never a B fallback.
        relative = _claim_source_relative(paper_id, digest)
        if record != {"sha256": digest, "path": relative.as_posix()}:
            raise ValueError("Imported original manifest differs from its claim")
        info = archive.getinfo("files/" + relative.as_posix())
        total += info.file_size
        if (
            not 0 < info.file_size <= MAX_PDF_BYTES
            or total > MAX_IMPORT_BYTES
            or len(selected) >= MAX_IMPORTS
        ):
            raise ValueError("Imported originals exceed their bounded byte/count budget")
        target = owned_path(database.parent / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        owned_path(target)
        handle, temporary = tempfile.mkstemp(prefix=".original-", suffix=".part", dir=target.parent)
        temporary = Path(temporary)
        try:
            actual, amount = hashlib.sha256(), 0
            with (
                os.fdopen(handle, "wb") as out,
                archive.open("files/" + relative.as_posix()) as source,
            ):
                while block := source.read(256 * 1024):
                    if cancelled():
                        return None
                    amount += len(block)
                    if amount > info.file_size:
                        raise ValueError("Imported original exceeds its declared byte budget")
                    actual.update(block)
                    out.write(block)
                out.flush()
                os.fsync(out.fileno())
            if amount != info.file_size or actual.hexdigest() != digest:
                raise ValueError("Imported original bytes differ from their manifest")
            if not target.exists():
                # Atomic create without replacing even a concurrent owner's file.
                with suppress(FileExistsError):
                    os.link(temporary, target)
            temporary.unlink(missing_ok=True)
            verified = _read_pdf(target, digest, amount, cancelled)
            if verified is None:
                return None
            verified_bytes, file_version = verified
            validate_pdf(verified_bytes)
        finally:
            temporary.unlink(missing_ok=True)
        proof = object.__new__(PreparedImportSource)
        for key, value in dict(
            database=database,
            identity=identity,
            binding=binding,
            scope=scope,
            paper_id=paper_id,
            claim=canonical_json(row),
            sha256=digest,
            size=amount,
            path=target,
            file_version=file_version,
            seal=_SEAL,
        ).items():
            object.__setattr__(proof, key, value)
        selected.append(proof)
    if cancelled():
        return None
    if tuple(generation._identity(database)) != identity:
        raise ValueError("Imported original database changed during staging")
    return tuple(selected)


def ensure_import_in(conn, prepared):
    """Install receiver epochs in the importer's transaction before paper SQL."""
    if prepared is None:
        raise ValueError("Original import was cancelled")
    if not conn.in_transaction:
        raise ValueError("Original ownership requires the import transaction")
    for item in prepared:
        _prepared(conn, item)
    if prepared:
        ensure_lifecycle(conn)


def _prepared(conn, item):
    if not isinstance(item, PreparedImportSource) or getattr(item, "seal", None) is not _SEAL:
        raise ValueError("Original import requires its native staged proof")
    _check_database(conn, item.database, item.identity, item.binding, item.scope)
    if file_change.version(owned_path(item.path)) != item.file_version:
        raise ValueError("Imported original changed before ownership publication")


def register_import_in(conn, prepared):
    """No commit or hashing: canonical claim, fresh receiver epoch and native proof."""
    if not conn.in_transaction:
        raise ValueError("Original ownership requires the import transaction")
    written = 0
    for item in prepared:
        _prepared(conn, item)
        current = _claim(conn, item.paper_id)
        if current is None or canonical_json(current) != item.claim:
            continue  # Existing newer canonical research was kept by ordinary import.
        parent = parent_lifecycle(conn, "paper", item.paper_id)
        if not parent:
            raise ValueError("Imported original has no fresh receiver paper lifecycle")
        owner = dict(
            format="paperfact.source-owner.v1",
            database_identity=list(item.identity),
            binding=item.binding,
            paper_id=item.paper_id,
            parent_lifecycle=parent,
            source_owner_id=item.paper_id,
        )
        row = validate(
            dict(
                request_id="import:" + claim_content.hashed([owner, json.loads(item.claim)]),
                owner_json=canonical_json(owner).decode(),
                sha256=item.sha256,
                size=item.size,
                media_type="application/pdf",
            )
        )
        if (
            source_snapshots.source_path(item.database, row, max_pdf_bytes=MAX_PDF_BYTES)
            != item.path
        ):
            raise ValueError("Imported original is outside its fixed owned cache")
        if not _schema(conn):
            conn.execute(SCHEMA)
        old = conn.execute(
            "SELECT " + COLUMNS.replace(" ", ",") + " FROM " + TABLE + " WHERE request_id=?",
            (row["request_id"],),
        ).fetchone()
        if old is not None:
            if dict(zip(COLUMNS.split(), old, strict=True)) != row:
                raise ValueError("Original import request was reused for another owner")
            continue
        if (
            conn.execute("SELECT COUNT(*) FROM " + TABLE).fetchone()[0]
            >= source_snapshots.MAX_RECEIPTS
        ):
            raise ValueError("Local original ownership exceeds its receipt budget")
        conn.execute(
            "INSERT INTO " + TABLE + " VALUES(?,?,?,?,?)",
            tuple(row[key] for key in COLUMNS.split()),
        )
        written += 1
    return written


def _owner_matches(conn, owner, row, *, generated=False):
    expected = json.loads(row["owner_json"])
    if expected["format"] == source_snapshots.LINEAGE_FORMAT:
        return False  # An archived corpus observation cannot authorize claim originals.
    loaded = json.loads(owner._json)
    source_owner = (
        ((loaded.get("graph") or {}).get("entity_id") or owner.paper_id)
        if generated
        else owner.paper_id
    )
    return (
        expected["source_owner_id"] == source_owner
        and expected["database_identity"] == generation._identity(owner.database)
        and expected["binding"] == generation._binding(conn)
        and expected["paper_id"] == owner.paper_id
        and expected["parent_lifecycle"] == parent_lifecycle(conn, "paper", owner.paper_id)
    )


def _generated(owner, digest, cancelled):
    context = json.loads(owner._json)
    namespace = source_snapshots._namespace(
        {
            "database_identity": context["database_identity"],
            "binding": context["binding"],
        }
    )
    root = owned_path(owner.database.parent / ".paperfact-source-snapshots" / namespace)
    if not root.is_dir():
        return
    with os.scandir(root) as iterator:
        entries = [Path(item.path) for item in islice(iterator, source_snapshots.MAX_RECEIPTS + 1)]
    if len(entries) > source_snapshots.MAX_RECEIPTS:
        raise ValueError("Generated original directory exceeds its entry budget")
    count, size = 0, 0
    for path in sorted(entries):
        if cancelled():
            return
        owned_path(path)
        if path.suffix != ".json":
            continue  # A concurrent private stage is not a published receipt.
        count += 1
        if (
            count > source_snapshots.MAX_RECEIPTS
            or path.stat().st_size > source_snapshots.MAX_RECEIPT
        ):
            raise ValueError("Generated original receipt scan exceeds its metadata budget")
        with path.open("rb") as stream:
            receipt_version = file_change.version(path, stream=stream)
            encoded = stream.read(source_snapshots.MAX_RECEIPT + 1)
            if (
                len(encoded) > source_snapshots.MAX_RECEIPT
                or len(encoded) != receipt_version[2]
                or file_change.version(path, stream=stream) != receipt_version
            ):
                raise ValueError("Generated original receipt changed during its bounded read")
        if file_change.version(path) != receipt_version:
            raise ValueError("Generated original receipt changed during verification")
        size += len(encoded)
        if size > MAX_METADATA:
            raise ValueError("Generated original receipt scan exceeds its byte budget")
        row = source_snapshots.validate(source_snapshots._decode(encoded))
        if source_snapshots.receipt_path(owner.database, row) != path:
            raise ValueError("Generated original receipt differs from its fixed location")
        if row["sha256"] == digest:
            yield row, path, receipt_version


@dataclass(frozen=True, init=False)
class LocalOriginal:
    owner: object = field(repr=False)
    data: bytes = field(repr=False)
    source: Path = field(repr=False)
    file_version: tuple = field(repr=False)
    document_hash: str
    claim: bytes = field(repr=False)
    receipt: bytes = field(repr=False)
    receipt_path: object = field(repr=False)
    receipt_version: object = field(repr=False)
    seal: object = field(repr=False)


def metadata_current(snapshot):
    """Short read-only guard: no byte hashing, PDF parsing or identity creation."""
    if not isinstance(snapshot, LocalOriginal) or getattr(snapshot, "seal", None) is not _SEAL:
        return False
    try:
        with closing(_connection(snapshot.owner.database)) as conn:
            conn.execute("BEGIN")
            snapshot.owner.check(conn)
            row = _claim(conn, snapshot.owner.paper_id)
            receipt = (
                source_snapshots.validate(json.loads(snapshot.receipt))
                if snapshot.receipt_path is not None
                else validate(json.loads(snapshot.receipt))
            )
            if (
                row is None
                or canonical_json(row) != snapshot.claim
                or not _owner_matches(
                    conn, snapshot.owner, receipt, generated=snapshot.receipt_path is not None
                )
            ):
                return False
            if snapshot.receipt_path is None:
                if not _schema(conn):
                    return False
                raw = conn.execute(
                    "SELECT "
                    + COLUMNS.replace(" ", ",")
                    + " FROM "
                    + TABLE
                    + " WHERE request_id=?",
                    (receipt["request_id"],),
                ).fetchone()
                if (
                    raw is None
                    or canonical_json(dict(zip(COLUMNS.split(), raw, strict=True)))
                    != snapshot.receipt
                ):
                    return False
            elif file_change.version(snapshot.receipt_path) != snapshot.receipt_version:
                return False
            return file_change.version(owned_path(snapshot.source)) == snapshot.file_version
    except (ValueError, OSError, sqlite3.Error):
        return False


def prepare(owner, expected, *, cancelled=lambda: False):
    """Verify one current private imported/generated original in a worker.

    The supplied loaded owner must already exist. This function never installs an
    epoch, registers a receipt, falls back to the current PDF, or starts AI/network.
    """
    from paper_daily.manual_highlight_ops import HighlightOwner

    if not isinstance(owner, HighlightOwner):
        raise ValueError("Original source requires the actual loaded paper owner")
    if cancelled():
        return None
    with closing(_connection(owner.database)) as conn:
        conn.execute("BEGIN")
        owner.check(conn)
        row = _claim(conn, owner.paper_id)
        if row is None:
            raise ValueError("The displayed canonical claim set is unavailable")
        saved = dict(
            annotation_content.decode("claims", row["body_json"]),
            paper_id=owner.paper_id,
            source_hash=row["source_hash"],
            document_hash=row["document_hash"],
            known=True,
        )
        if saved != expected:
            raise ValueError("Displayed research changed")
        digest = row["document_hash"]
        candidates = [
            (item, None, None)
            for item in records(conn, document_hash=digest)
            if item["sha256"] == digest and _owner_matches(conn, owner, item)
        ]
        if not candidates:
            candidates = [
                item
                for item in _generated(owner, digest, cancelled)
                if _owner_matches(conn, owner, item[0], generated=True)
            ]
        claim = canonical_json(row)
    if cancelled():
        return None
    for receipt, location, receipt_version in candidates:
        source = source_snapshots.source_path(owner.database, receipt, max_pdf_bytes=MAX_PDF_BYTES)
        verified = _read_pdf(source, digest, receipt["size"], cancelled)
        if verified is None:
            return None
        data, file_version = verified
        result = object.__new__(LocalOriginal)
        for key, value in dict(
            owner=owner,
            data=data,
            source=source,
            file_version=file_version,
            document_hash=digest,
            claim=claim,
            receipt=canonical_json(receipt),
            receipt_path=location,
            receipt_version=receipt_version,
            seal=_SEAL,
        ).items():
            object.__setattr__(result, key, value)
        if cancelled():
            return None
        if metadata_current(result):
            return None if cancelled() else result
        raise ValueError("Original ownership changed during verification")
    raise ValueError("Original version has no current receiver-owned source receipt")
