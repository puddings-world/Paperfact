"""Bounded exact-original package closure for recorded empty-query outcomes.

No source is inferred from a cache filename. Native import proofs grant ownership
only beside the actual receiver outcome or a retained typed import conflict.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import closing, suppress
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import file_change, source_snapshots, sync_capture
from paper_daily import later_outcomes as outcomes
from paper_daily import local_source_owners as owners
from paper_daily import research_generation as generation
from paper_daily.research_lifecycle import ensure_lifecycle, parent_lifecycle
from paper_daily.sync_files import canonical_json, closed, digest
from paper_daily.sync_legacy_sources import path as owned_path
from paper_daily.sync_legacy_sources import validate_pdf

MAX_ROWS = 500
MAX_PDF_BYTES = 32 * 1024**2
MAX_TOTAL = 512 * 1024**2
MAX_METADATA = 8 * 1024**2
_SEAL = object()
IMPORT_FIELDS = "package_sha256 source_owner receiver_owner incoming_json receiver_json"


def relative(paper_id, sha):
    from paper_daily.claim_content import hashed
    from paper_daily.sync_content import _text

    _text(paper_id, 4096, nullable=False, nonempty=True)
    digest(sha)
    return (
        Path("pdf")
        / ".later-outcomes"
        / hashed(["later-outcome-owner", paper_id])[:24]
        / (sha + ".pdf")
    )


def rows(tables):
    selected = tables.get(outcomes.TABLE, [])
    if not isinstance(selected, list) or len(selected) > MAX_ROWS:
        raise ValueError("Later outcomes exceed their package row budget")
    parents = {row["id"] for row in tables["papers"]}
    seen = set()
    for row in selected:
        outcomes.validate_row(row)
        if row["paper_id"] not in parents or row["paper_id"] in seen:
            raise ValueError("Later outcome owner is missing or repeated")
        seen.add(row["paper_id"])
    return selected


def records(manifest, tables):
    selected = rows(tables)
    value = manifest.get("later_sources", [])
    expected = sorted((r["paper_id"], r["document_hash"]) for r in selected if r["document_hash"])
    if not isinstance(value, list) or len(value) != len(expected):
        raise ValueError("Later outcomes require their exact original closure")
    actual = []
    total = 0
    for item in value:
        closed(item, {"paper_id", "sha256", "size", "path"})
        if type(item["size"]) is not int or not 0 < item["size"] <= MAX_PDF_BYTES:
            raise ValueError("Later original exceeds its bounded PDF size")
        if item["path"] != relative(item["paper_id"], item["sha256"]).as_posix():
            raise ValueError("Later original differs from exact owner/hash")
        actual.append((item["paper_id"], item["sha256"]))
        total += item["size"]
        if total > MAX_TOTAL:
            raise ValueError("Later originals exceed aggregate budget")
    if actual != expected or (not expected and "later_sources" in manifest):
        raise ValueError("Later originals require ordered unique exact source owners")
    return value


def _archive_pdf(archive, item):
    info = archive.getinfo("files/" + item["path"])
    if info.file_size != item["size"]:
        raise ValueError("Later source size differs")
    with archive.open(info) as stream:
        data = stream.read(item["size"] + 1)
    if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ValueError("Later source bytes differ")
    validate_pdf(data)
    return data


def _metadata_doc(archive, name):
    matches = [item for item in archive.infolist() if item.filename == name]
    if len(matches) != 1 or not 0 < matches[0].file_size <= MAX_METADATA:
        raise ValueError("Later package requires one bounded metadata document")
    with archive.open(matches[0]) as stream:
        data = stream.read(matches[0].file_size + 1)
    if len(data) != matches[0].file_size:
        raise ValueError("Later package metadata changed during read")

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate later package metadata field")
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError("Nonfinite later package metadata value")

    try:
        return json.loads(data.decode("utf8"), object_pairs_hook=pairs, parse_constant=invalid)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid bounded later package metadata") from exc


def _validated_inputs(archive, manifest, tables):
    selected = rows(tables)
    if not selected:
        records(manifest, tables)  # No unused source declaration can bypass its row closure.
        return manifest, tables, []
    actual_manifest = _metadata_doc(archive, "manifest.json")
    actual_tables = _metadata_doc(archive, "tables.json")
    if canonical_json(actual_manifest) != canonical_json(manifest) or canonical_json(
        actual_tables
    ) != canonical_json(tables):
        raise ValueError("Later package metadata differs from its admitted objects")
    # Private parsed snapshots are independent of caller-mutable row/descriptor maps.
    selected = rows(actual_tables)
    sources = records(actual_manifest, actual_tables)
    if sources and actual_manifest.get("pdfs_included") is not True:
        raise ValueError("Include exact PDFs to share source-bound later outcomes")
    for item in sources:
        if actual_manifest.get("file_hashes", {}).get(item["path"]) != item["sha256"]:
            raise ValueError("Later source lacks its exact manifest hash")
        _archive_pdf(archive, item)
    return actual_manifest, actual_tables, selected


def validate_package(archive, manifest, tables):
    return _validated_inputs(archive, manifest, tables)[2]


def read(conn, paper_id):
    columns = ("paper_id", *outcomes.FIELDS.split())
    raw = conn.execute(
        "SELECT " + ",".join(columns) + " FROM paper_later_outcomes WHERE paper_id=?",
        (paper_id,),
    ).fetchone()
    return outcomes.validate_row(dict(zip(columns, raw, strict=True))) if raw else None


def _source_binding(conn):
    """Observe existing binding only; absent instrumentation is not unbound authority."""
    from paper_daily.reading_position_packages import _export_binding
    from paper_daily.workspace_service import _binding, _tables

    scope = _binding(conn, _tables(conn))
    captured, graph = _export_binding(conn)
    if not scope:
        if captured is not None or graph is not None:
            raise ValueError("Later source binding is incomplete")
        return None
    if graph is None:
        raise ValueError("Later source requires the persisted workspace/device identity")
    for table, value in scope:
        if table in {"paperfact_sync_identity", "research_capture_binding"} and value != graph:
            raise ValueError("Later source workspace/device bindings disagree")
    actual = {"workspace_id": graph[0], "device_id": graph[1]}
    if captured is not None and captured != actual:
        raise ValueError("Later source capture binding differs from persisted identity")
    return actual


def _owned(conn, database, row):
    identity = generation._identity(database)
    binding = _source_binding(conn)
    epoch = parent_lifecycle(conn, "paper", row["paper_id"])
    mapping = (
        conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (row["paper_id"],)
        ).fetchone()
        if binding
        else None
    )
    expected = mapping[0] if mapping else row["paper_id"]
    for receipt in owners.records(
        conn, document_hash=row["document_hash"]
    ) + source_snapshots.list_owned(database):
        owner = json.loads(receipt["owner_json"])
        if owner["format"] == source_snapshots.LINEAGE_FORMAT:
            continue  # Archived corpus observations cannot authorize another feature.
        if (
            receipt["sha256"] == row["document_hash"]
            and owner["paper_id"] == row["paper_id"]
            and owner["database_identity"] == identity
            and owner["binding"] == binding
            and owner["parent_lifecycle"] == epoch
            and owner["source_owner_id"] in {expected, row["paper_id"]}
        ):
            return source_snapshots.source_path(database, receipt, max_pdf_bytes=MAX_PDF_BYTES)
    if mapping:
        from paper_daily.sync_source_files import inspectable

        return inspectable(conn, mapping[0], row["document_hash"])
    return None


@dataclass(frozen=True)
class Export:
    database: Path
    identity: tuple
    binding: object
    selected: str
    parents: tuple
    records: tuple
    sources: tuple


def check_export(proof):
    if proof is None:
        return
    with closing(owners._connection(proof.database)) as conn:
        conn.execute("BEGIN")
        expected = json.loads(proof.selected)
        if (
            tuple(generation._identity(proof.database)) != proof.identity
            or generation._binding(conn) != proof.binding
        ):
            raise ValueError("Later outcome export workspace changed")
        if canonical_json([read(conn, r["paper_id"]) for r in expected]) != canonical_json(
            expected
        ):
            raise ValueError("Later outcome changed during export")
        if any(parent_lifecycle(conn, "paper", p) != epoch for p, epoch in proof.parents):
            raise ValueError("Later outcome paper lifetime changed during export")
        for row, (source, version) in zip(
            (r for r in expected if r["document_hash"]), proof.sources, strict=True
        ):
            if (
                _owned(conn, proof.database, row) != source
                or file_change.version(source) != version
            ):
                raise ValueError("Later original ownership or bytes changed during export")


def export_sources(database, tables, files, *, with_pdfs):
    selected = sorted(json.loads(canonical_json(rows(tables))), key=lambda r: r["paper_id"])
    if not selected:
        return None
    if any(r["document_hash"] for r in selected) and not with_pdfs:
        raise ValueError("Include exact PDFs to share source-bound later outcomes")
    database = Path(database).resolve(strict=True)
    identity = tuple(generation._identity(database))
    result = []
    sources = []
    parents = []
    total = 0
    with closing(owners._connection(database)) as conn:
        conn.execute("BEGIN")
        binding = generation._binding(conn)
        for row in selected:
            if read(conn, row["paper_id"]) != row:
                raise ValueError("Selected later outcome changed")
            parents.append((row["paper_id"], parent_lifecycle(conn, "paper", row["paper_id"])))
            if row["document_hash"] is None:
                continue
            source = _owned(conn, database, row)
            if source is None:
                raise ValueError("Exact owned later-outcome original is unavailable")
            size = source.stat().st_size
            if not 0 < size <= MAX_PDF_BYTES:
                raise ValueError("Later original exceeds bounded size")
            data, version = owners._read_pdf(source, row["document_hash"], size)
            validate_pdf(data)
            total += size
            if total > MAX_TOTAL:
                raise ValueError("Later originals exceed aggregate budget")
            target = relative(row["paper_id"], row["document_hash"])
            files[target] = source
            result.append(
                dict(
                    paper_id=row["paper_id"],
                    sha256=row["document_hash"],
                    size=size,
                    path=target.as_posix(),
                )
            )
            sources.append((source, version))
    return Export(
        database,
        identity,
        binding,
        canonical_json(selected).decode(),
        tuple(parents),
        tuple(result),
        tuple(sources),
    )


@dataclass(frozen=True, init=False)
class Prepared:
    database: Path
    identity: tuple
    binding: object
    scope: object
    row_json: str
    before_json: str
    parent: object
    present: bool
    path: object
    version: object
    target: object
    target_version: object
    size: int
    lease: object = field(repr=False)
    seal: object = field(repr=False)


class ImportLease:
    def __enter__(self):
        self.prepared = ()
        return self

    def prepare(self, *args, **kwargs):
        self.prepared = prepare_import(*args, **kwargs)
        return self.prepared

    def __exit__(self, *_exc):
        for item in self.prepared or ():
            if item.lease:
                item.lease.cleanup()


def _owner(database, identity, binding, paper, parent):
    return dict(
        format="paperfact.source-owner.v1",
        database_identity=list(identity),
        binding=binding,
        paper_id=paper,
        parent_lifecycle=parent,
        source_owner_id=paper,
    )


def _receipt(item, parent):
    owner = _owner(
        item.database, item.identity, item.binding, json.loads(item.row_json)["paper_id"], parent
    )
    row = json.loads(item.row_json)
    return owners.validate(
        dict(
            request_id="import:" + hashlib.sha256(canonical_json([owner, row])).hexdigest(),
            owner_json=canonical_json(owner).decode(),
            sha256=row["document_hash"],
            size=item.size,
            media_type="application/pdf",
        )
    )


def prepare_import(database, archive, manifest, tables, *, cancelled=lambda: False):
    from paper_daily.workspace_service import _binding, _tables

    manifest, tables, selected = _validated_inputs(archive, manifest, tables)
    if not selected:
        return ()
    database = owned_path(Path(database).resolve(strict=True))
    identity = tuple(generation._identity(database))
    with closing(generation._connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            binding = generation._binding(conn)
            scope = _binding(conn, _tables(conn))
            if binding is not None or scope:
                raise ValueError(
                    "Synchronized later outcomes require the observed package importer"
                )
            ensure_lifecycle(conn)
            observed = {
                r["paper_id"]: (
                    read(conn, r["paper_id"]),
                    parent_lifecycle(conn, "paper", r["paper_id"]),
                    bool(
                        conn.execute("SELECT 1 FROM papers WHERE id=?", (r["paper_id"],)).fetchone()
                    ),
                )
                for r in selected
            }
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    sources = {r["paper_id"]: r for r in records(manifest, tables)}
    result = []
    accepted = False
    lease = None
    try:
        for row in selected:
            if cancelled():
                return None
            before, parent, present = observed[row["paper_id"]]
            path = version = target = target_version = lease = None
            size = 0
            if row["document_hash"]:
                data = _archive_pdf(archive, sources[row["paper_id"]])
                size = len(data)
                lease = tempfile.TemporaryDirectory(prefix="paperfact-later-import-")
                path = owned_path(Path(lease.name) / "original.pdf")
                with path.open("wb") as out:
                    out.write(data)
                    out.flush()
                    os.fsync(out.fileno())
                version = file_change.version(path)
                # Destination naming is not ownership; the real receipt follows adopted SQL.
                from paper_daily.claim_content import hashed

                alias = hashed(["claim-source-owner", row["paper_id"]])[:24]
                target = owned_path(
                    database.parent
                    / "pdf"
                    / ".claim-evidence"
                    / alias
                    / (row["document_hash"] + ".pdf")
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    with suppress(FileExistsError):
                        os.link(path, target)
                    # Verify the winner's exact bytes below, off-lock.
                _data, target_version = owners._read_pdf(target, row["document_hash"], size)
                # Link creation changes native USN; exact bytes were rechecked off-lock.
                version = file_change.version(path)
            item = object.__new__(Prepared)
            for key, value in dict(
                database=database,
                identity=identity,
                binding=binding,
                scope=scope,
                row_json=canonical_json(row).decode(),
                before_json=canonical_json(before).decode(),
                parent=parent,
                present=present,
                path=path,
                version=version,
                target=target,
                target_version=target_version,
                size=size,
                lease=lease,
                seal=_SEAL,
            ).items():
                object.__setattr__(item, key, value)
            result.append(item)
        if cancelled():
            return None
        if tuple(generation._identity(database)) != identity:
            raise ValueError("Later import database changed")
        accepted = True
        return tuple(result)
    finally:
        if not accepted:
            if lease is not None and all(item.lease is not lease for item in result):
                lease.cleanup()
            for item in result:
                if item.lease:
                    item.lease.cleanup()


def _prepared(conn, item):
    if not isinstance(item, Prepared) or getattr(item, "seal", None) is not _SEAL:
        raise ValueError("Later import requires its native staged proof")
    owners._check_database(conn, item.database, item.identity, item.binding, item.scope)
    if item.path is not None and file_change.version(owned_path(item.path)) != item.version:
        raise ValueError("Later staged original changed")
    return outcomes.validate_row(json.loads(item.row_json))


def ensure_import_in(conn, prepared):
    if prepared is None or not conn.in_transaction:
        raise ValueError("Later import requires uncancelled transaction")
    for item in prepared:
        row = _prepared(conn, item)
        present = bool(
            conn.execute("SELECT 1 FROM papers WHERE id=?", (row["paper_id"],)).fetchone()
        )
        if (
            present != item.present
            or parent_lifecycle(conn, "paper", row["paper_id"]) != item.parent
            or canonical_json(read(conn, row["paper_id"])).decode() != item.before_json
        ):
            raise ValueError("Later outcome or receiver paper changed during import")


def validate_import_record(record):
    from paper_daily.enrollment_history import _value
    from paper_daily.sync_content import _text

    closed(record, IMPORT_FIELDS.split())
    digest(record["package_sha256"])
    for key in ("source_owner", "receiver_owner"):
        _text(record[key], 4096, nullable=False, nonempty=True)
    incoming = _value(record["incoming_json"])
    receiver = _value(record["receiver_json"])
    outcomes.validate_row(incoming)
    outcomes.validate_row(receiver)
    if (
        incoming["paper_id"] != record["source_owner"]
        or receiver["paper_id"] != record["receiver_owner"]
    ):
        raise ValueError("Retained later outcome differs from declared owners")
    if canonical_json(incoming) == canonical_json(receiver):
        raise ValueError("Identical outcomes need no retained conflict")
    return {r["document_hash"] for r in (incoming, receiver) if r["document_hash"]}


def retain_imports_in(conn, records):
    from paper_daily.enrollment_history import MAX_RECORDS, MAX_TOTAL, archived, retain_in, wrap

    if not isinstance(records, list) or len(records) > MAX_ROWS:
        raise ValueError("Too many later import candidates")
    if not records:
        return
    incoming = [wrap("later_outcome_import_v1", r) for r in records]
    combined = {r["record_id"]: r for r in archived(conn)}
    combined.update({r["record_id"]: r for r in incoming})
    if (
        len(combined) > MAX_RECORDS
        or sum(len(r["body_json"].encode()) for r in combined.values()) > MAX_TOTAL
    ):
        raise ValueError("Later import history exceeds aggregate budget")
    retain_in(conn, incoming)


def write_import_in(conn, prepared, *, replace, package_sha256):
    if prepared is None or not conn.in_transaction:
        raise ValueError("Later import requires uncancelled transaction")
    written = kept = 0
    retained = []
    for item in prepared:
        row = _prepared(conn, item)
        parent = parent_lifecycle(conn, "paper", row["paper_id"])
        if not parent or (item.parent is not None and parent != item.parent):
            raise ValueError("Later import paper lifetime changed")
        before = read(conn, row["paper_id"])
        if canonical_json(before).decode() != item.before_json:
            raise ValueError("Later import target changed")
        if before is not None and not replace:
            if before != row:
                kept += 1
                retained.append(
                    dict(
                        package_sha256=package_sha256,
                        source_owner=row["paper_id"],
                        receiver_owner=before["paper_id"],
                        incoming_json=item.row_json,
                        receiver_json=canonical_json(before).decode(),
                    )
                )
                retain_imports_in(conn, [retained[-1]])
        elif before != row:
            conn.execute(
                "INSERT INTO paper_later_outcomes VALUES(?,?,?,?) "
                "ON CONFLICT(paper_id) DO UPDATE SET "
                "body_json=excluded.body_json,document_hash=excluded.document_hash,"
                "written_at=excluded.written_at",
                tuple(row[k] for k in ("paper_id", "body_json", "document_hash", "written_at")),
            )
            written += 1
        expected = before if before is not None and not replace else row
        if read(conn, row["paper_id"]) != expected:
            raise ValueError("Later import target changed before source ownership")
        if item.path is None:
            continue
        receipt = _receipt(item, parent)
        target = source_snapshots.source_path(item.database, receipt, max_pdf_bytes=MAX_PDF_BYTES)
        if target != item.target:
            raise ValueError("Later import canonical source path changed")
        target.parent.mkdir(parents=True, exist_ok=True)
        if file_change.version(item.path) != item.version:
            raise ValueError("Later staged original changed before publication")
        if file_change.version(target) != item.target_version:
            raise ValueError("Later original changed before publication")
        with sync_capture.suppress_capture(conn):
            if not owners._schema(conn):
                conn.execute(owners.SCHEMA)
            prior = conn.execute(
                "SELECT owner_json,sha256,size,media_type FROM research_local_source_owners "
                "WHERE request_id=?",
                (receipt["request_id"],),
            ).fetchone()
            values = tuple(receipt[k] for k in ("owner_json", "sha256", "size", "media_type"))
            if prior is not None and tuple(prior) != values:
                raise ValueError("Later source import request changed")
            if (
                prior is None
                and conn.execute("SELECT COUNT(*) FROM research_local_source_owners").fetchone()[0]
                >= source_snapshots.MAX_RECEIPTS
            ):
                raise ValueError("Later source receipts exceed budget")
            conn.execute(
                "INSERT OR IGNORE INTO research_local_source_owners VALUES(?,?,?,?,?)",
                tuple(receipt[k] for k in owners.COLUMNS.split()),
            )
    return dict(later_outcomes=written, later_outcomes_kept=kept)


def add_enrollment_sources(conn, selected, sources, *, ticket):
    """Select exact owned paper/source pairs, never a hash-only cache lookup."""
    if not isinstance(selected, list) or len(selected) > MAX_ROWS:
        raise ValueError("Too many source-bound later outcomes to enroll")
    database = Path(generation._path(conn)).resolve(strict=True)
    for row in selected:
        ticket.check()
        outcomes.validate_row(row)
        if row["document_hash"] is None:
            continue
        if read(conn, row["paper_id"]) != row:
            raise ValueError("Later outcome changed during enrollment")
        original = _owned(conn, database, row)
        if original is None:
            raise ValueError("Later outcome requires its exact owned original before enrollment")
        size = original.stat().st_size
        if not 0 < size <= MAX_PDF_BYTES:
            raise ValueError("Later source exceeds its enrollment budget")
        verified = owners._read_pdf(original, row["document_hash"], size, lambda: ticket.cancelled)
        ticket.check()
        if verified is None:
            raise ValueError("Later source verification did not complete")
        data, _version = verified
        ticket.check()
        validate_pdf(data)
        sources[(row["paper_id"], row["document_hash"])] = dict(
            path=str(original), sha256=row["document_hash"], size=size
        )
