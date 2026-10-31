"""Exact-original list packages for reading positions; file work belongs on workers.

Import ownership is granted only beside the receiver's actual position and parent
lifetime. Package timestamps/methods remain historical data, never native input
evidence or authority to select a current PDF.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import file_change, position_source_snapshots, source_snapshots, sync_capture
from paper_daily import local_source_owners as owners
from paper_daily import reading_positions as positions
from paper_daily import research_generation as generation
from paper_daily.research_lifecycle import ensure_lifecycle, parent_lifecycle
from paper_daily.sync_documents import MAX_PDF_BYTES
from paper_daily.sync_files import canonical_json, closed, read_json
from paper_daily.sync_legacy_sources import path as owned_path
from paper_daily.workspace_service import _binding, _tables

MAX_POSITIONS = 500
MAX_ORIGINAL_BYTES = 512 * 1024**2
MAX_METADATA = 16 * 1024**2
_SEAL = object()
IMPORT_FIELDS = (
    "package_sha256 source_owner receiver_owner document_hash incoming_json receiver_json"
)


def validate_import_record(record):
    from paper_daily.enrollment_history import _value
    from paper_daily.sync_content import _hash, _text

    closed(record, IMPORT_FIELDS.split())
    for key in ("package_sha256", "document_hash"):
        _hash(record[key])
    for key in ("source_owner", "receiver_owner"):
        _text(record[key], 4096, nullable=False, nonempty=True)
    for key in ("incoming_json", "receiver_json"):
        _text(record[key], 4096, nullable=False, nonempty=True)
        positions.validate_data(_value(record[key]))
    if canonical_json(_value(record["incoming_json"])) == canonical_json(
        _value(record["receiver_json"])
    ):
        raise ValueError("Identical positions need no retained import candidate")
    return {record["document_hash"]}


def retain_imports_in(conn, records):
    from paper_daily.enrollment_history import MAX_RECORDS, MAX_TOTAL, archived, retain_in, wrap

    if not isinstance(records, list) or len(records) > MAX_POSITIONS:
        raise ValueError("Position import candidates exceed their bounded count")
    if not records:
        return
    incoming = [wrap("reading_position_import_v1", record) for record in records]
    combined = {item["record_id"]: item for item in archived(conn)}
    combined.update({item["record_id"]: item for item in incoming})
    if (
        len(combined) > MAX_RECORDS
        or sum(len(item["body_json"].encode()) for item in combined.values()) > MAX_TOTAL
    ):
        raise ValueError("Position import candidates exceed their aggregate history budget")
    retain_in(conn, incoming)


def relative(paper_id, document_hash):
    from paper_daily.claim_content import hashed
    from paper_daily.sync_content import _hash, _text

    _text(paper_id, 4096, nullable=False, nonempty=True)
    _hash(document_hash)
    alias = hashed(["reading-position-owner", paper_id])[:24]
    return Path("pdf") / ".reading-positions" / alias / (document_hash + ".pdf")


def rows(tables):
    result = tables.get(positions.TABLE, [])
    if not isinstance(result, list) or len(result) > MAX_POSITIONS:
        raise ValueError("Reading positions exceed their package row limit")
    known, seen = {row["id"] for row in tables["papers"]}, set()
    for row in result:
        positions.validate_row(row)
        identity = row["paper_id"], row["document_hash"]
        if row["paper_id"] not in known or identity in seen:
            raise ValueError("Position package owner is absent or repeated")
        seen.add(identity)
    return result


def records(manifest, tables):
    selected = rows(tables)
    value = manifest.get("position_sources", [])
    if not isinstance(value, list) or len(value) != len(selected):
        raise ValueError("Position package requires its exact original-source closure")
    expected = sorted((row["paper_id"], row["document_hash"]) for row in selected)
    declared, total = [], 0
    for item in value:
        closed(item, {"paper_id", "sha256", "size", "path"})
        if type(item["size"]) is not int or not 0 < item["size"] <= MAX_PDF_BYTES:
            raise ValueError("Position original exceeds its bounded PDF size")
        if item["path"] != relative(item["paper_id"], item["sha256"]).as_posix():
            raise ValueError("Position original path differs from its exact owner/hash")
        declared.append((item["paper_id"], item["sha256"]))
        total += item["size"]
        if total > MAX_ORIGINAL_BYTES:
            raise ValueError("Position originals exceed their package byte limit")
    if declared != expected:
        raise ValueError("Position originals require the exact ordered unique owner/hash closure")
    if not selected and "position_sources" in manifest:
        raise ValueError("Position source declarations require actual position records")
    return value


def _archive_source(archive, item, row):
    info = archive.getinfo("files/" + item["path"])
    if info.file_size != item["size"]:
        raise ValueError("Position original differs from its declared size")
    with archive.open(info) as stream:
        data = stream.read(item["size"] + 1)
    if len(data) != item["size"]:
        raise ValueError("Position original changed during its bounded read")
    positions.verify_page(row, data)
    return data


def validate_package(archive, manifest, tables):
    selected = rows(tables)
    sources = records(manifest, tables)
    if not selected:
        return
    if manifest.get("pdfs_included") is not True:
        raise ValueError("Include PDFs to share saved reading positions with their exact originals")
    # The maintained legacy parser also supports older packages. The new position
    # contract additionally requires bounded duplicate-free metadata documents.
    for name in ("manifest.json", "tables.json"):
        info = archive.getinfo(name)
        if not 0 < info.file_size <= MAX_METADATA:
            raise ValueError("Position package metadata exceeds its bounded size")

        def pairs(values):
            result = {}
            for key, value in values:
                if key in result:
                    raise ValueError("Duplicate position-package metadata field")
                result[key] = value
            return result

        def invalid(_value):
            raise ValueError("Nonfinite position-package metadata value")

        json.loads(
            archive.read(info).decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid
        )
    by_identity = {(row["paper_id"], row["document_hash"]): row for row in selected}
    for item in sources:
        if manifest.get("file_hashes", {}).get(item["path"]) != item["sha256"]:
            raise ValueError("Position package original is missing its declared hash")
        _archive_source(archive, item, by_identity[(item["paper_id"], item["sha256"])])


def _export_binding(conn):
    """Capture instrumentation is optional; an existing sync binding is not."""
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    graph = None
    if "research_sync_binding" in tables:
        bound = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
        if bound is not None:
            identity = (
                conn.execute(
                    "SELECT workspace,device FROM paperfact_sync_identity WHERE id=1"
                ).fetchone()
                if "paperfact_sync_identity" in tables
                else None
            )
            if identity is None or identity[0] != bound[0]:
                raise ValueError("Position export workspace binding is inconsistent")
            graph = tuple(identity)
    return generation._binding(conn), graph


def _owned_original(conn, database, row):
    binding = generation._binding(conn)
    identity = generation._identity(database)
    epoch = parent_lifecycle(conn, "paper", row["paper_id"])
    for receipt in owners.records(conn, document_hash=row["document_hash"]):
        owner = json.loads(receipt["owner_json"])
        if (
            owner["paper_id"] == row["paper_id"]
            and owner["database_identity"] == identity
            and owner["binding"] == binding
            and owner["parent_lifecycle"] == epoch
        ):
            return source_snapshots.source_path(database, receipt, max_pdf_bytes=MAX_PDF_BYTES)
    if binding is None and _export_binding(conn)[1] is not None:
        from paper_daily.reading_position_received_sources import current_source
        from paper_daily.workspace_service import Ticket

        return Path(current_source(conn, row, ticket=Ticket())["path"])
    mapping = (
        conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (row["paper_id"],)
        ).fetchone()
        if binding
        else None
    )
    if mapping:
        from paper_daily.sync_source_files import inspectable

        original = inspectable(conn, mapping[0], row["document_hash"])
        if original is not None:
            return original
        from paper_daily.document_reader import from_workspace

        resolver = from_workspace(database)
        try:
            current = resolver.resolve(row["paper_id"])
            if current.managed and current.available and current.sha256 == row["document_hash"]:
                return current.path
        finally:
            resolver.close()
    return None


@dataclass(frozen=True)
class PositionExport:
    database: Path
    identity: tuple
    binding: object
    rows_json: str
    parents: tuple
    records: tuple
    sources: tuple


def check_export(proof):
    if proof is None:
        return
    with closing(owners._connection(proof.database)) as conn:
        conn.execute("BEGIN")
        if (
            tuple(generation._identity(proof.database)) != proof.identity
            or _export_binding(conn) != proof.binding
        ):
            raise ValueError("Position workspace changed during package export")
        expected = read_json(proof.rows_json.encode())
        current = [positions.read(conn, row["paper_id"], row["document_hash"]) for row in expected]
        if canonical_json(current) != canonical_json(expected) or any(
            parent_lifecycle(conn, "paper", paper) != epoch for paper, epoch in proof.parents
        ):
            raise ValueError("Reading position or paper lifetime changed during export; retry")
        for row, (source, observed) in zip(expected, proof.sources, strict=True):
            if (
                _owned_original(conn, proof.database, row) != source
                or file_change.version(source) != observed
            ):
                raise ValueError(
                    "The exact position original or its ownership changed during export"
                )


def export_sources(database, tables, files, *, with_pdfs):
    selected = rows(tables)
    if not selected:
        return None
    if selected and not with_pdfs:
        raise ValueError("Include PDFs to share saved reading positions with their exact originals")
    database = Path(database).resolve(strict=True)
    result, total, parents, sources = [], 0, [], []
    identity = tuple(generation._identity(database))
    with closing(owners._connection(database)) as conn:
        conn.execute("BEGIN")
        binding = _export_binding(conn)
        for row in sorted(selected, key=lambda item: (item["paper_id"], item["document_hash"])):
            original = _owned_original(conn, database, row)
            if original is None:
                raise ValueError(
                    "The exact original PDF for a saved reading position is unavailable"
                )
            size = original.stat().st_size
            data, _version = owners._read_pdf(original, row["document_hash"], size)
            sources.append((original, _version))
            positions.verify_page(row, data)
            total += size
            if total > MAX_ORIGINAL_BYTES:
                raise ValueError("Position originals exceed their package byte limit")
            target = relative(row["paper_id"], row["document_hash"])
            files[target] = original
            result.append(
                dict(
                    paper_id=row["paper_id"],
                    sha256=row["document_hash"],
                    size=size,
                    path=target.as_posix(),
                )
            )
            parents.append((row["paper_id"], parent_lifecycle(conn, "paper", row["paper_id"])))
    return PositionExport(
        database,
        identity,
        binding,
        canonical_json(
            sorted(selected, key=lambda row: (row["paper_id"], row["document_hash"]))
        ).decode(),
        tuple(parents),
        tuple(result),
        tuple(sources),
    )


@dataclass(frozen=True, init=False)
class PreparedPositionImport:
    database: Path
    identity: tuple
    binding: object
    scope: tuple
    row_json: str
    before_json: str
    parent: object
    paper_present: bool
    path: Path
    file_version: tuple
    size: int
    lease: object = field(repr=False)
    seal: object = field(repr=False)


class ImportLease:
    """Explicitly release only this call's disposable source preparations."""

    def __enter__(self):
        self.prepared = ()
        return self

    def prepare(self, *args, **kwargs):
        self.prepared = prepare_import(*args, **kwargs)
        return self.prepared

    def __exit__(self, *_exc):
        for item in self.prepared or ():
            position_source_snapshots.cleanup_stage(item.lease, item.database)


def _stage(database, identity, binding, row, data):
    lease = position_source_snapshots.create_stage(database, identity, binding)
    target = owned_path(Path(lease.name) / "original.pdf")
    try:
        with target.open("wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        _bytes, version = owners._read_pdf(target, row["document_hash"], len(data))
        return target, version, lease
    except BaseException:
        position_source_snapshots.cleanup_stage(lease, database)
        raise


def prepare_import(database, archive, manifest, tables, *, cancelled=lambda: False):
    selected = rows(tables)
    if not selected:
        return ()
    database = owned_path(Path(database).resolve(strict=True))
    identity = tuple(generation._identity(database))
    with closing(generation._connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            binding = generation._binding(conn)
            scope = _binding(conn, _tables(conn))
            if (
                binding is not None
                or conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='research_sync_binding'"
                ).fetchone()
            ):
                raise ValueError("Synchronized positions require the observed package importer")
            ensure_lifecycle(conn)
            observed = {
                (row["paper_id"], row["document_hash"]): (
                    positions.read(conn, row["paper_id"], row["document_hash"]),
                    parent_lifecycle(conn, "paper", row["paper_id"]),
                    bool(
                        conn.execute(
                            "SELECT 1 FROM papers WHERE id=?", (row["paper_id"],)
                        ).fetchone()
                    ),
                )
                for row in selected
            }
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    sources = {(item["paper_id"], item["sha256"]): item for item in records(manifest, tables)}
    result = []
    accepted = False
    try:
        for row in selected:
            if cancelled():
                return None
            source = sources[(row["paper_id"], row["document_hash"])]
            data = _archive_source(archive, source, row)
            target, version, lease = _stage(database, identity, binding, row, data)
            before, parent, present = observed[(row["paper_id"], row["document_hash"])]
            item = object.__new__(PreparedPositionImport)
            for key, value in dict(
                database=database,
                identity=identity,
                binding=binding,
                scope=scope,
                row_json=canonical_json(row).decode(),
                before_json=canonical_json(before).decode(),
                parent=parent,
                paper_present=present,
                path=target,
                file_version=version,
                size=len(data),
                lease=lease,
                seal=_SEAL,
            ).items():
                object.__setattr__(item, key, value)
            result.append(item)
        if cancelled():
            return None
        accepted = True
        return tuple(result)
    finally:
        if not accepted:
            for item in result:
                position_source_snapshots.cleanup_stage(item.lease, database)


def _prepared(conn, item):
    if not isinstance(item, PreparedPositionImport) or getattr(item, "seal", None) is not _SEAL:
        raise ValueError("Position import requires its staged exact-source proof")
    owners._check_database(conn, item.database, item.identity, item.binding, item.scope)
    if file_change.version(owned_path(item.path)) != item.file_version:
        raise ValueError("Position original changed before import publication")
    return positions.validate_row(read_json(item.row_json.encode()))


def ensure_import_in(conn, prepared):
    if prepared is None or not conn.in_transaction:
        raise ValueError("Position import requires its uncancelled caller transaction")
    for item in prepared:
        row = _prepared(conn, item)
        present = bool(
            conn.execute("SELECT 1 FROM papers WHERE id=?", (row["paper_id"],)).fetchone()
        )
        if (
            present != item.paper_present
            or parent_lifecycle(conn, "paper", row["paper_id"]) != item.parent
            or canonical_json(positions.read(conn, row["paper_id"], row["document_hash"])).decode()
            != item.before_json
        ):
            raise ValueError("Position or paper lifetime changed during import; prepare again")


def write_import_in(conn, prepared, *, replace, package_sha256):
    from paper_daily.reading_position_ops import _admitting

    if prepared is None or not conn.in_transaction:
        raise ValueError("Position import requires its uncancelled caller transaction")
    written, kept, retained = 0, 0, []
    for item in prepared:
        row = _prepared(conn, item)
        parent = parent_lifecycle(conn, "paper", row["paper_id"])
        if not parent or (item.parent is not None and parent != item.parent):
            raise ValueError("Imported position has no matching receiver paper lifetime")
        current = positions.read(conn, row["paper_id"], row["document_hash"])
        if canonical_json(current).decode() != item.before_json:
            raise ValueError("Position changed during import; prepare again")
        if current is not None and not replace:
            kept += current != row
            if current != row:
                retained.append(
                    dict(
                        package_sha256=package_sha256,
                        source_owner=row["paper_id"],
                        receiver_owner=row["paper_id"],
                        document_hash=row["document_hash"],
                        incoming_json=canonical_json(
                            {key: row[key] for key in ("page", "recorded_at", "method")}
                        ).decode(),
                        receiver_json=canonical_json(
                            {key: current[key] for key in ("page", "recorded_at", "method")}
                        ).decode(),
                    )
                )
        elif current != row:
            with _admitting(conn, row):
                conn.execute(
                    "INSERT INTO reading_positions VALUES(?,?,?,?,?) "
                    "ON CONFLICT(paper_id,document_hash) "
                    "DO UPDATE SET page=excluded.page,recorded_at=excluded.recorded_at,"
                    "method=excluded.method",
                    tuple(row[key] for key in positions.FIELDS.split()),
                )
            written += 1
        expected = current if current is not None and not replace else row
        if canonical_json(
            positions.read(conn, row["paper_id"], row["document_hash"])
        ) != canonical_json(expected):
            raise ValueError("Position changed while installing its exact original")
        owner = dict(
            format=position_source_snapshots.FORMAT,
            database_identity=list(item.identity),
            binding=item.binding,
            paper_id=row["paper_id"],
            parent_lifecycle=parent,
            source_owner_id=row["paper_id"],
            position_key=row["document_hash"],
        )
        receipt = owners.validate(
            dict(
                request_id="position:" + hashlib.sha256(canonical_json(owner)).hexdigest(),
                owner_json=canonical_json(owner).decode(),
                sha256=row["document_hash"],
                size=item.size,
                media_type="application/pdf",
            )
        )
        position_source_snapshots.publish(
            item.database, receipt, stage=item.path.parent, version=item.file_version
        )
        with sync_capture.suppress_capture(conn):
            conn.execute(owners.SCHEMA)
            prior = conn.execute(
                "SELECT owner_json,sha256,size,media_type FROM research_local_source_owners "
                "WHERE request_id=?",
                (receipt["request_id"],),
            ).fetchone()
            if prior and tuple(prior) != tuple(
                receipt[key] for key in ("owner_json", "sha256", "size", "media_type")
            ):
                raise ValueError("Position import source ownership changed")
            if (
                not prior
                and conn.execute("SELECT COUNT(*) FROM research_local_source_owners").fetchone()[0]
                >= source_snapshots.MAX_RECEIPTS
            ):
                raise ValueError("Position source ownership exceeds its receipt budget")
            conn.execute(
                "INSERT OR IGNORE INTO research_local_source_owners VALUES(?,?,?,?,?)",
                tuple(receipt[key] for key in owners.COLUMNS.split()),
            )
    with sync_capture.suppress_capture(conn):
        retain_imports_in(conn, retained)
    return dict(reading_positions=written, reading_positions_kept=kept)
