"""Prepare an isolated, reviewed first-enrollment candidate; never adopt or upload it.

This bounded slice rejects unsupported source scopes. It is not a substitute for
workspace-wide writer draining/maintenance locking at eventual runtime adoption.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
from contextlib import closing
from pathlib import Path
from uuid import UUID, uuid5

from paper_daily import store, sync_recovery
from paper_daily.document_reader import register_document_paths
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_capture import CORE, CaptureConnection, capture_existing, install
from paper_daily.sync_client import SyncClient
from paper_daily.sync_content import CONTENT_TABLES
from paper_daily.sync_document_actions import stage_file
from paper_daily.sync_documents import bind_verified_document, desired_document, verify_document
from paper_daily.sync_journal import Journal
from paper_daily.sync_operations import ResearchOperations
from paper_daily.sync_recovery_fs import publish_directory
from paper_daily.sync_research import prepare as prepare_adapter
from paper_daily.sync_research import research_order_writer, research_writer
from paper_daily.workspace_service import SnapshotChanged, Ticket, _read, _safe_path

MAX_ROWS = 100_000
MAX_METADATA = 64 * 1024**2
MAX_FILES = 256
MAX_BYTES = 512 * 1024**2
PRIVATE_FILES = {".env", "credentials.json", "tokens.json", "settings.json", "config.json"}
SUPPORTED = CORE | set(CONTENT_TABLES)
LOCAL_DERIVED = {"authors", "paper_authors", "workspace_revision", "research_source_archive"}


class EnrollmentBlocked(ValueError):
    """A complete supported baseline cannot be represented without omissions."""

    def __init__(self, plan):
        self.plan = plan
        super().__init__("Enrollment blocked: " + "; ".join(plan["blockers"]))


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _identity(path):
    path = _safe_path(path)
    info = path.stat()
    return (str(path), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _schema():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        from paper_daily.source_provenance import SCHEMA as archive_schema

        conn.execute(archive_schema)  # Trusted optional catalogue, not runtime initialization.
        objects = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('trigger','view')"
            )
        }
        return {
            row[0]: [column[1] for column in conn.execute(f'PRAGMA table_info("{row[0]}")')]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not row[0].startswith("sqlite_")
        }, objects


def _research_tables():
    return {
        name
        for name, (section, _columns) in sync_recovery._registry().items()
        if section == "research"
    }


def _database(conn, ticket):
    """Closed schema, bounded rows; secrets contribute to invalidation, never output."""
    trusted, trusted_objects = _schema()
    research_tables = _research_tables()
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    blockers, rows, counts, digest, size, count, excluded = [], {}, {}, hashlib.sha256(), 0, 0, 0
    objects = list(
        conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")
    )
    digest.update(_json(objects).encode())
    for kind, name, _table, _sql in objects:
        if kind in {"trigger", "view"} and name not in trusted_objects:
            blockers.append("unsupported schema writer/view: " + name)
    if any(
        kind == "trigger" and name == "paperfact_pin_membership_delete"
        for kind, name, _table, _sql in objects
    ):
        from paper_daily.sync_content import pin_cleanup_ready

        if not pin_cleanup_ready(conn):
            blockers.append("pin cleanup trigger requires review")
    optional = set(getattr(sync_recovery, "OPTIONAL_RESEARCH_TABLES", set()))
    optional.add("research_source_archive")
    if not (set(trusted) - set(optional)) <= names:
        blockers.append("schema: initialized current research schema required")
    for table in sorted(names - {"sqlite_sequence"}):
        ticket.check()
        if table not in trusted:
            blockers.append("unsupported table: " + table)
            continue
        columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
        if columns != trusted[table]:
            blockers.append("unsupported columns: " + table)
            continue
        selected = []
        for raw in conn.execute(
            f'SELECT * FROM "{table}" ORDER BY '
            + ",".join('"' + column + '"' for column in columns)
        ):
            ticket.check()
            encoded = _json(list(raw)).encode()
            count += 1
            size += len(encoded)
            if count > MAX_ROWS or size > MAX_METADATA:
                raise ValueError("Enrollment metadata exceeds its bounded inventory")
            digest.update(table.encode() + b"\0" + encoded + b"\n")
            value = dict(zip(columns, raw, strict=True))
            if table == "kv" and value["key"] != "lists.order":
                if sync_recovery._kv_allowed(value["key"], set()):
                    blockers.append("unsupported research KV: " + value["key"])
                elif value["key"].startswith(("citegraph.", "followups.checked.", "resources:")):
                    blockers.append("unsupported research KV scope")
                elif value["key"].startswith(
                    ("ui.", "ai.", "provider.", "account.", "usage.", "auth.")
                ):
                    excluded += 1
                else:
                    blockers.append("unsupported KV scope")
                continue
            selected.append(value)
        if table == "pins":
            from paper_daily.sync_content import _stamp

            for pin in selected:
                try:
                    _stamp(pin["pinned_at"])
                except (ValueError, TypeError):
                    blockers.append("list pin timestamp requires migration")
                if pin["scope"] == "queue":
                    blockers.append("legacy queue pins require migration")
                elif (
                    conn.execute(
                        "SELECT 1 FROM list_papers lp JOIN lists l ON l.id=lp.list_id "
                        "JOIN papers p ON p.id=lp.paper_id WHERE lp.list_id=? AND lp.paper_id=?",
                        (pin["scope"], pin["paper_id"]),
                    ).fetchone()
                    is None
                ):
                    blockers.append("list pin requires an existing list membership")
        if table == "paper_annotation_known":
            from paper_daily.annotation_content import FEATURES

            for marker in selected:
                target = FEATURES.get(marker["feature"])
                if target is None or not conn.execute(
                    f'SELECT 1 FROM "{target}" WHERE paper_id=?', (marker["paper_id"],)
                ).fetchone():
                    blockers.append(
                        "known annotation deletion requires explicit enrollment migration")
        counts[table] = len(selected)
        if selected and table not in SUPPORTED | LOCAL_DERIVED | {"paper_annotation_known"}:
            blockers.append("unsupported writer scope: " + table)
        if selected and table in SUPPORTED and table not in research_tables:
            blockers.append("missing recovery coverage: " + table)
        if table in research_tables:
            rows[table] = selected
    return rows, counts, digest.hexdigest(), excluded, blockers


def _files(root, database, pdfs, papers, ticket, *, claim_sources=(), owned_sources=(),
           receipt_paths=(), source_inventory=None):
    if not isinstance(pdfs, dict) or len(pdfs) > MAX_FILES:
        raise ValueError("Use a bounded mapping of local paper IDs to explicit PDF files")
    blockers, manifests, selected, metadata, total = [], {}, set(), [], 0
    for local_id, raw in sorted(pdfs.items()):
        ticket.check()
        if not isinstance(local_id, str) or local_id not in papers:
            raise ValueError("PDF selection must identify an existing local paper")
        path = _safe_path(raw)
        before = _identity(path)
        if (
            not path.is_file()
            or path.suffix.lower() != ".pdf"
            or not 0 < before[3] <= 150 * 1024**2
        ):
            raise ValueError("Select a nonempty PDF of at most 150 MiB")
        digest, measured = hashlib.sha256(), 0
        with path.open("rb") as stream:
            while chunk := stream.read(256 * 1024):
                ticket.check()
                measured += len(chunk)
                total += len(chunk)
                if measured > before[3] or total > MAX_BYTES:
                    raise ValueError("PDF inventory exceeds its bounded bytes")
                digest.update(chunk)
        if measured != before[3] or before != _identity(path):
            raise SnapshotChanged("Source PDF changed during inventory")
        manifests[local_id] = {"path": str(path), "sha256": digest.hexdigest(), "size": measured}
        selected.add(path)
        metadata.append(before)
    aliases = {}
    source_inventory = source_inventory if source_inventory is not None else {}
    from paper_daily import annotation_content
    from paper_daily.claim_content import hashed

    for row in owned_sources:
        selected_source = _safe_path(row["path"])
        aliases[selected_source] = row["sha256"]
    for row in claim_sources:
        annotation_content.validate_row("claims", row)
        local_id, digest = row["paper_id"], row["document_hash"]
        if local_id not in papers:
            blockers.append("claim source requires its existing paper owner")
            continue
        selected_primary = manifests.get(local_id)
        owner = hashed(["claim-source-owner", local_id])[:24]
        candidate = _safe_path(root / "pdf" / ".claim-evidence" / owner / (digest + ".pdf"))
        if selected_primary and selected_primary["sha256"] == digest:
            source_inventory[(local_id, digest)] = selected_primary
            if candidate.is_file():
                aliases[candidate] = digest
            continue
        if not candidate.is_file():
            candidates = [item for item in owned_sources if item["sha256"] == digest]
            if candidates:
                candidate = _safe_path(candidates[0]["path"])
        if not candidate.is_file():
            blockers.append("claim source requires its exact selected original PDF: " + local_id)
            continue
        aliases[candidate] = digest
        source_inventory[(local_id, digest)] = {
            "path": str(candidate), "sha256": digest, "size": candidate.stat().st_size}
    checked_aliases = set()
    private_receipts = {_safe_path(item) for item in receipt_paths}
    entries = 0
    for entry in root.rglob("*"):
        ticket.check()
        entry = _safe_path(entry)
        entries += 1
        if entries > MAX_FILES * 8:
            raise ValueError("Source directory exceeds its bounded entry inventory")
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise ValueError("Source inventory contains an unsupported filesystem entry")
        relative = entry.relative_to(root)
        metadata.append(_identity(entry))
        if entry in private_receipts:
            continue  # Validated private receipt is archived, never shared authority.
        if entry in selected or entry in {
            database,
            Path(str(database) + "-wal"),
            Path(str(database) + "-shm"),
            Path(str(database) + "-journal"),
        }:
            continue
        if len(relative.parts) == 1 and (relative.name in PRIVATE_FILES or entry.suffix == ".log"):
            continue
        if entry in aliases:
            before = _identity(entry)
            if not 0 < before[3] <= 150 * 1024**2:
                raise SnapshotChanged("Claim source alias exceeds its declared source budget")
            measured = hashlib.sha256()
            with entry.open("rb") as stream:
                while chunk := stream.read(256 * 1024):
                    ticket.check()
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ValueError("Claim source inventory exceeds its bounded bytes")
                    measured.update(chunk)
            if before != _identity(entry) or measured.hexdigest() != aliases[entry]:
                raise SnapshotChanged("Claim source alias changed during inventory")
            checked_aliases.add(entry)
            continue  # Declared original bytes are staged separately from the primary.
        blockers.append("unsupported or unmapped file: " + relative.as_posix())
    if set(aliases) - checked_aliases - selected:
        blockers.append("owned original source is outside the bounded source inventory")
    return manifests, sorted(set(metadata)), blockers


class EnrollmentService:
    """Explicit source and output paths. Source research is never enrolled in place."""

    def __init__(self, database, *, source_root=None):
        self.database = _safe_path(database)
        self.source_root = _safe_path(source_root or self.database.parent)
        if (
            not self.source_root.is_dir()
            or not self.database.is_file()
            or not self.database.is_relative_to(self.source_root)
        ):
            raise ValueError("Select an existing database inside its explicit research directory")
        self._running = threading.Lock()

    def _inventory(self, conn, pdfs, ticket):
        rows, counts, digest, excluded, blockers = _database(conn, ticket)
        from paper_daily import source_provenance, source_snapshots

        receipts = source_snapshots.list_owned(self.database)
        provenance = {row["record_id"]: row for row in source_provenance.archived(conn)}
        for receipt in receipts:
            archived = source_provenance.wrap(receipt)
            provenance[archived["record_id"]] = archived
        owned_sources = [
            {"path": str(source_snapshots.source_path(self.database, row)),
             "sha256": row["sha256"], "size": row["size"]}
            for row in receipts
        ]
        seen_owned = {(item["path"], item["sha256"]) for item in owned_sources}
        for archived in provenance.values():
            receipt = source_provenance.validate(archived)
            cached = source_snapshots.source_path(self.database, receipt)
            if (str(cached), receipt["sha256"]) in seen_owned:
                continue
            if not cached.is_file() or cached.stat().st_size != receipt["size"]:
                blockers.append("archived original source bytes require explicit migration")
                continue
            owned_sources.append({"path": str(cached), "sha256": receipt["sha256"],
                                  "size": receipt["size"]})
            seen_owned.add((str(cached), receipt["sha256"]))
        sources = {}
        papers = {row["id"] for row in rows.get("papers", [])}
        manifests, files, file_blockers = _files(
            self.source_root, self.database, pdfs, papers, ticket,
            claim_sources=rows.get("paper_claim_sets", []), owned_sources=owned_sources,
            receipt_paths=[source_snapshots.receipt_path(self.database, row) for row in receipts],
            source_inventory=sources,
        )
        return {
            "rows": rows,
            "original_sources": sources,
            "owned_sources": owned_sources,
            "source_provenance": sorted(provenance.values(), key=lambda row: row["record_id"]),
            "counts": counts,
            "digest": digest,
            "files": files,
            "pdfs": manifests,
            "excluded_private_kv": excluded,
            "blockers": sorted(set(blockers + file_blockers)),
            "claim_source_duplicates": sum(
                1 for row in rows.get("paper_claim_sets", [])
                if row["paper_id"] in manifests
                and manifests[row["paper_id"]]["sha256"] == row["document_hash"]
            ),
        }

    @staticmethod
    def _report(inventory):
        research_tables = _research_tables()
        return {
            "supported": not inventory["blockers"],
            "blockers": inventory["blockers"],
            "research_counts": {
                key: value for key, value in inventory["counts"].items() if key in research_tables
            },
            "pdf_count": len(inventory["pdfs"]),
            "original_source_count": len(inventory["original_sources"]),
            "archived_source_receipts": len(inventory["source_provenance"]),
            "claim_sources_covered_by_primary": inventory["claim_source_duplicates"],
            "pdf_bytes": sum(value["size"] for value in inventory["pdfs"].values()),
            "excluded_private_kv": inventory["excluded_private_kv"],
            "local_derived_tables": sorted(LOCAL_DERIVED),
            "runtime_enrollment_complete": False,
            "requires_review_and_adoption": True,
        }

    def plan(self, *, pdfs=None, ticket=None):
        """Read-only coverage report before creating output, backup or sync identities."""
        ticket = ticket or Ticket()
        with _read(self.database, budget=30) as conn:
            inventory = self._inventory(conn, ({} if pdfs is None else pdfs), ticket)
        ticket.check()
        return self._report(inventory)

    def prepare(
        self,
        output,
        *,
        backup_output,
        request_id,
        pdfs=None,
        ticket=None,
        progress=lambda _message: None,
    ):
        """Publish a candidate and independent verified archive; no adoption or network.

        Retries use the same caller UUID to retain workspace/device/paper identities.
        Unpublished operation IDs are not a durable resumable enrollment protocol.
        """
        ticket = ticket or Ticket()
        request = UUID(request_id)
        if str(request) != request_id:
            raise ValueError("Enrollment requires a canonical UUID request ID")
        output, backup = _safe_path(output), _safe_path(backup_output)
        if any(path.exists() for path in (output, backup)):
            raise ValueError("Enrollment output and backup must both be new paths")
        if (
            any(
                path.is_relative_to(self.source_root) or self.source_root.is_relative_to(path)
                for path in (output, backup)
            )
            or backup.is_relative_to(output)
            or output == backup
        ):
            raise ValueError("Enrollment paths must be separate from source and each other")
        if not output.parent.is_dir() or not backup.parent.is_dir():
            raise ValueError("Explicit output parent directories must already exist")
        if not self._running.acquire(blocking=False):
            raise ValueError("Enrollment preparation is already running")
        try:
            with _read(self.database, budget=30) as source:
                before = self._inventory(source, ({} if pdfs is None else pdfs), ticket)
                source.close()
                report = self._report(before)
                if not report["supported"]:
                    raise EnrollmentBlocked(report)
                progress("Coverage checked; staging an isolated research copy")
                with tempfile.TemporaryDirectory(
                    prefix=".paperfact-enrollment-", dir=output.parent
                ) as temporary:
                    stage = Path(temporary) / "workspace"
                    stage.mkdir()
                    database = stage / "papers.db"
                    with closing(sqlite3.connect(database)) as copied:
                        copied.executescript(store.SCHEMA)
                        store._migrate(copied)
                        for table, values in before["rows"].items():
                            for row in values:
                                columns = ",".join('"' + column + '"' for column in row)
                                copied.execute(
                                    f'INSERT INTO "{table}" ({columns}) VALUES('
                                    + ",".join("?" for _ in row)
                                    + ")",
                                    tuple(row.values()),
                                )
                        from paper_daily.source_provenance import retain_in

                        retain_in(copied, before["source_provenance"])
                        copied.commit()
                    workspace = str(uuid5(request, "workspace"))
                    device = str(uuid5(request, "device"))
                    prepare_adapter(database, workspace_id=workspace, device_id=device)
                    client = SyncClient(
                        Journal(database, workspace_id=workspace, device_id=device),
                        research_writer,
                        order_writer=research_order_writer,
                    )
                    with closing(sqlite3.connect(database, factory=CaptureConnection)) as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        install(conn, workspace_id=workspace, device_id=device)
                        capture_existing(conn)
                        conn.commit()
                    ticket.check()
                    blobs = BlobStore(stage / "blobs", quota_bytes=MAX_BYTES)
                    actions = ResearchOperations(client)
                    for selected in before["owned_sources"]:
                        ticket.check()
                        retained = stage_file(blobs, Path(selected["path"]))
                        if (retained.sha256, retained.size) != (
                            selected["sha256"], selected["size"]):
                            raise SnapshotChanged("Owned original source changed while staging")
                    for local_id, selected in before["pdfs"].items():
                        ticket.check()
                        progress("Verifying primary PDF: " + local_id)
                        manifest = stage_file(blobs, Path(selected["path"]))
                        if (manifest.sha256, manifest.size) != (
                            selected["sha256"],
                            selected["size"],
                        ):
                            raise SnapshotChanged("Source PDF changed while staging")
                        with client.journal.transaction() as conn:
                            portable = conn.execute(
                                "SELECT sync_id FROM research_paper_identity WHERE local_id=?",
                                (local_id,),
                            ).fetchone()[0]
                        actions.attach_document(
                            portable, manifest, store=blobs, request_id="enroll-pdf:" + portable
                        )
                        with client.journal.transaction() as conn:
                            target = desired_document(conn, portable)
                        proof = verify_document(blobs, target)
                        with client.journal.transaction() as conn:
                            if not bind_verified_document(conn, target, proof):
                                raise SnapshotChanged("Staged document target changed")
                    from paper_daily.sync_source_files import publish

                    for (local_id, digest), selected in before["original_sources"].items():
                        ticket.check()
                        with client.journal.transaction() as conn:
                            portable, parent = conn.execute(
                                "SELECT m.sync_id,g.incarnation FROM research_paper_identity m "
                                "JOIN research_paper_projection g ON g.sync_id=m.sync_id "
                                "WHERE m.local_id=?", (local_id,),
                            ).fetchone()
                        publish(client, portable, selected["path"], document_hash=digest,
                                parent_incarnation=parent, store=blobs,
                                version_root=stage / "research-versions",
                                request_id="enroll-source:" + portable + ":" + digest[:32])
                    with client.journal.transaction() as conn:
                        for table, expected in before["rows"].items():
                            current = [
                                dict(zip(row.keys(), row, strict=True))
                                for row in conn.execute(f'SELECT * FROM "{table}"')
                            ]
                            if table == "kv":
                                current = [
                                    row
                                    for row in current
                                    if row["key"] in {item["key"] for item in expected}
                                ]
                            if sorted(map(_json, current)) != sorted(map(_json, expected)):
                                raise EnrollmentBlocked(
                                    {
                                        **report,
                                        "supported": False,
                                        "blockers": ["non-lossless baseline: " + table],
                                    }
                                )
                        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise ValueError("Staged database failed integrity checking")
                    progress("Creating and inspecting independent recovery backup")
                    ticket.check()
                    archive = Path(temporary) / "backup.zip"
                    manifest = sync_recovery.create(database, archive, blob_store=blobs)
                    if sync_recovery.inspect(archive) != manifest:
                        raise ValueError("Recovery backup verification failed")
                    # Persist only final local roots, never temporary paths or credentials.
                    with client.journal.transaction() as conn:
                        conn.execute(
                            "UPDATE research_file_paths SET blob_root=?,version_root=? WHERE id=1",
                            (str(output / "blobs"), str(output / "research-versions")),
                        )
                        register_document_paths(
                            conn,
                            workspace_id=workspace,
                            blob_root=output / "blobs",
                            projection_root=output / "reader",
                            legacy_root=output / "legacy",
                        )
                    with blobs._transaction() as conn:
                        conn.execute(
                            "CREATE TABLE transfer_binding "
                            "(id INTEGER PRIMARY KEY,workspace TEXT,device TEXT,research_path TEXT)"
                        )
                        conn.execute(
                            "INSERT INTO transfer_binding VALUES(1,?,?,?)",
                            (workspace, device, str(output / "papers.db")),
                        )
                    # A fresh read transaction observes committed WAL changes made while staging.
                    with _read(self.database, budget=30) as current:
                        after = self._inventory(current, ({} if pdfs is None else pdfs), ticket)
                    if before != after:
                        raise SnapshotChanged(
                            "Source research or files changed; retry from a new snapshot"
                        )
                    ticket.check()
                    progress("Verified candidate ready for explicit review and adoption")
                    # Progress callbacks can invalidate/cancel; recheck after them as well.
                    with _read(self.database, budget=30) as current:
                        latest = self._inventory(current, ({} if pdfs is None else pdfs), ticket)
                    if before != latest:
                        raise SnapshotChanged("Source changed before publication")

                    def publish():
                        os.link(archive, backup)
                        try:
                            publish_directory(stage, output)
                        except BaseException:
                            if backup.exists() and os.path.samefile(archive, backup):
                                backup.unlink()
                            raise

                    ticket.publish(publish)
                    return {
                        **report,
                        "status": "prepared_for_review",
                        "destination": str(output),
                        "database": str(output / "papers.db"),
                        "backup": str(backup),
                        "backup_id": manifest["backup_id"],
                        "workspace_id": workspace,
                        "device_id": device,
                        "uploaded": False,
                        "adopted": False,
                    }
        finally:
            self._running.release()
