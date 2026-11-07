"""Explicit editable copies of detached recovery: exact source, fresh authority."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import threading
import zipfile
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import file_change, recovery_provenance, sync_recovery
from paper_daily.sync_files import canonical_json
from paper_daily.workspace_service import (
    SnapshotChanged,
    Ticket,
    WorkspaceChanged,
    _read,
    _safe_path,
)

_SEAL = object()


@dataclass(frozen=True, init=False)
class RecoveryInspection:
    _owner: object = field(repr=False)
    _snapshot: bytes = field(repr=False)
    _files: tuple = field(repr=False)
    _report: bytes = field(repr=False)
    _seal: object = field(repr=False)

    @property
    def report(self):
        return json.loads(self._report)


def _report(value, *, private_files=0):
    manifest, tables = value["manifest"], value["tables"]
    papers = {row["id"] for row in tables.get("papers", [])}
    members = {row["paper_id"] for row in tables.get("list_papers", [])}
    records = _records(value)
    blockers = []
    from paper_daily.sync_content import _stamp

    membership_pairs = {(row["list_id"], row["paper_id"]) for row in tables.get("list_papers", [])}
    for pin in tables.get("pins", []):
        try:
            _stamp(pin["pinned_at"])
        except (ValueError, TypeError):
            blockers.append("pin timestamp requires migration")
        if pin["paper_id"] not in papers:
            blockers.append("pin requires an existing paper")
        if pin["scope"] != "queue" and (pin["scope"], pin["paper_id"]) not in membership_pairs:
            blockers.append("list pin requires an existing list membership")
    return dict(
        supported=not blockers,
        blockers=blockers,
        backup_id=manifest["backup_id"],
        research_counts={
            item["name"]: item["count"]
            for item in manifest["tables"]
            if item["section"] == "research"
        },
        history_counts={
            item["name"]: item["count"]
            for item in manifest["tables"]
            if item["section"] == "protocol"
        },
        orphan_papers=len(papers - members),
        excluded_private_kv=value.get("excluded_private_kv", 0),
        excluded_private_files=private_files,
        retained_blobs=len(manifest["blobs"]),
        current_pdf_count=len(records.pdf_aliases()),
        current_deck_count=sum(
            operation["entity_id"] not in records.hidden_files
            and operation["payload"]["feature"] == "deck"
            for operation in records.applied_files.values()
        )
        + len(records.legacy_decks)
        + len(records.observed_currents),
        retained_bytes=sum(item["size"] for item in manifest["blobs"]),
        requires_explicit_editable_copy=True,
        uploaded=False,
        adopted=False,
    )


class RecoveryAdoptionService:
    def __init__(self, database, *, current_path=None):
        self.database = _safe_path(database)
        self.root = self.database.parent
        self.current_path = current_path or (lambda: self.database)
        info = self.database.stat()
        self.identity = (info.st_dev, info.st_ino)
        self._running = threading.Lock()

    def _check(self):
        info = self.database.stat()
        if (info.st_dev, info.st_ino) != self.identity or _safe_path(
            self.current_path()
        ) != self.database:
            raise WorkspaceChanged("The recovered workspace changed")

    def _capture(self, ticket):
        """Reconstruct the exact inspected archive, never treating paths as authority."""
        from paper_daily.workspace_enrollment import PRIVATE_FILES, PRIVATE_KV_PREFIXES, _schema

        self._check()
        manifest_path = _safe_path(self.root / "recovery.json")
        if not 0 < manifest_path.stat().st_size <= 4 * 1024**2:
            raise ValueError("Recovered manifest exceeds its declared bound")
        manifest_version = file_change.version(manifest_path)
        manifest = sync_recovery._load(manifest_path.read_bytes())
        sync_recovery._manifest(recovery_provenance._Manifest(manifest))
        if file_change.version(manifest_path) != manifest_version:
            raise SnapshotChanged("Recovered manifest changed")
        registry = sync_recovery._registry()
        trusted, trusted_objects = _schema()
        trusted.update(
            {
                "research_chat_links": [
                    "local_id",
                    "message_id",
                    "exchange_id",
                    "reply_to",
                    "source_hash",
                ],
                "recovery_records": ["table_name", "row_number", "data"],
                "recovery_identity": [
                    "id",
                    "backup_id",
                    "origin_workspace",
                    "origin_device",
                    "recovery_device",
                ],
            }
        )
        tables = {}
        excluded_private_kv = 0
        database_versions = self._database_versions()
        with _read(self.database, budget=30) as conn:
            names = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                if not row[0].startswith("sqlite_")
            }
            if not {"recovery_records", "recovery_identity"} <= names or names - set(trusted):
                raise ValueError("Unknown recovered database schema requires a typed adapter")
            unknown_objects = conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('trigger','view')"
            ).fetchall()
            if any(row[0] not in trusted_objects for row in unknown_objects):
                raise ValueError("Unknown recovered schema writer/view requires a typed adapter")
            for name in names:
                if [row[1] for row in conn.execute('PRAGMA table_info("' + name + '")')] != trusted[
                    name
                ]:
                    raise ValueError("Unknown recovered table columns: " + name)
            identity = conn.execute("SELECT * FROM recovery_identity").fetchall()
            if (
                len(identity) != 1
                or identity[0][0] != 1
                or tuple(identity[0][1:4])
                != (manifest["backup_id"], manifest["workspace_id"], manifest["origin_device_id"])
            ):
                raise ValueError("Recovered identity differs from its exact manifest")
            recovered = {}
            size = 0
            for count, (name, index, raw) in enumerate(
                conn.execute(
                    "SELECT table_name,row_number,CASE WHEN length(CAST(data AS BLOB))<=? "
                    "THEN data END FROM recovery_records ORDER BY table_name,row_number",
                    (sync_recovery.MAX_ROW,),
                ),
                1,
            ):
                ticket.check()
                if not isinstance(raw, str):
                    raise ValueError("Invalid recovered record")
                size += len(raw.encode())
                if count > sync_recovery.MAX_RECORDS or size > sync_recovery.MAX_METADATA:
                    raise ValueError("Recovered metadata exceeds its explicit budget")
                if (
                    name not in registry
                    or type(index) is not int
                    or index < 0
                    or index in recovered.setdefault(name, {})
                ):
                    raise ValueError("Unknown or duplicate recovered history record")
                value = sync_recovery._load(raw)
                sync_recovery._check_row(value, registry[name][1])
                recovered[name][index] = value
            expected_protocol = {
                item["name"]
                for item in manifest["tables"]
                if item["section"] == "protocol"
                and item["name"] not in {"research_chat_links", "paper_annotation_known"}
            }
            from paper_daily import inbox_content
            from paper_daily.inbox_recovery import (
                DETACHED_ORIGINALS,
                verify_detached_projection,
            )

            inbox_originals = {
                table["name"] for table in manifest["tables"] if table["name"] in DETACHED_ORIGINALS
            }
            if set(recovered) - expected_protocol - inbox_originals:
                raise ValueError("Undeclared recovered protocol")
            declared_live = set()
            for table in manifest["tables"]:
                ticket.check()
                name = table["name"]
                if name in expected_protocol or name in inbox_originals:
                    if name in inbox_originals:
                        declared_live.add(name)
                        if name not in names:
                            raise ValueError("Recovered Inbox canonical table is missing")
                    rows = recovered.get(name, {})
                    if set(rows) != set(range(table["count"])):
                        if name in inbox_originals:
                            raise ValueError(
                                "Detached Inbox originals are incomplete; "
                                "restore the original backup again"
                            )
                        raise ValueError("Recovered history is incomplete")
                    selected = [rows[index] for index in range(table["count"])]
                else:
                    declared_live.add(name)
                    if name not in names:
                        raise ValueError("Recovered canonical table is missing")
                    columns = table["columns"]
                    source_query = '"' + name + '"'
                    source_params = ()
                    if name == "kv":
                        papers = {row[0] for row in conn.execute("SELECT id FROM papers")}
                        for (key,) in conn.execute(
                            "SELECT CASE WHEN length(CAST(key AS BLOB))<=8192 THEN key END FROM kv"
                        ):
                            if not isinstance(key, str):
                                raise ValueError("Recovered KV key exceeds its supported bound")
                            if key.startswith(PRIVATE_KV_PREFIXES):
                                excluded_private_kv += 1
                            elif not sync_recovery._kv_allowed(key, papers):
                                raise ValueError(
                                    "Unknown recovered KV scope requires a typed adapter"
                                )
                        # Filter known private namespaces inside SQLite, before fetching values.
                        predicates = ["substr(key,1,?)<>?" for _ in PRIVATE_KV_PREFIXES]
                        source_params = tuple(
                            part for prefix in PRIVATE_KV_PREFIXES for part in (len(prefix), prefix)
                        )
                        source_query = '(SELECT * FROM "kv" WHERE ' + " AND ".join(predicates) + ")"
                    if (
                        conn.execute(
                            "SELECT COUNT(*) FROM " + source_query, source_params
                        ).fetchone()[0]
                        != table["count"]
                    ):
                        raise SnapshotChanged("Recovered canonical row count changed: " + name)
                    for column in columns:
                        oversized = (
                            "SELECT 1 FROM "
                            + source_query
                            + ' WHERE typeof("'
                            + column
                            + "\") IN ('text','blob') AND length(CAST(\""
                            + column
                            + '" AS BLOB))>? LIMIT 1'
                        )
                        if conn.execute(
                            oversized, (*source_params, sync_recovery.MAX_ROW)
                        ).fetchone():
                            raise ValueError("Recovered SQL scalar exceeds its row bound")
                    primary = [
                        row[1]
                        for row in sorted(
                            conn.execute('PRAGMA table_info("' + name + '")'),
                            key=lambda row: row[5],
                        )
                        if row[5]
                    ]
                    order = ",".join('"' + col + '"' for col in primary)
                    selected = [
                        dict(zip(columns, row, strict=True))
                        for row in conn.execute(
                            "SELECT "
                            + ",".join('"' + col + '"' for col in columns)
                            + " FROM "
                            + source_query
                            + (" ORDER BY " + order if order else ""),
                            source_params,
                        )
                    ]
                encoded = b"".join((sync_recovery._json(row) + "\n").encode() for row in selected)
                if (
                    len(selected) != table["count"]
                    or len(encoded) != table["size"]
                    or hashlib.sha256(encoded).hexdigest() != table["sha256"]
                ):
                    raise SnapshotChanged(
                        "Recovered table differs from its original snapshot: " + name
                    )
                tables[name] = selected
            if inbox_originals:
                verify_detached_projection(
                    conn, {name: tables[name] for name in inbox_originals}, identity[0][4]
                )
                declared_live.add(inbox_content.OWNER)
            for name in (
                names
                - declared_live
                - {"recovery_records", "recovery_identity", "workspace_revision"}
            ):
                if conn.execute('SELECT 1 FROM "' + name + '" LIMIT 1').fetchone():
                    raise ValueError(
                        "Unrepresented recovered research must not be omitted: " + name
                    )
        snapshot = canonical_json(
            dict(manifest=manifest, tables=tables, excluded_private_kv=excluded_private_kv)
        )
        files = [(str(manifest_path.relative_to(self.root)), manifest_version), *database_versions]
        with tempfile.TemporaryDirectory(prefix="paperfact-recovered-inspection-") as temporary:
            stage = Path(temporary)
            package = stage / "source.zip"
            with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("manifest.json", canonical_json(manifest))
                for table in manifest["tables"]:
                    archive.writestr(
                        "tables/" + table["name"] + ".jsonl",
                        b"".join(
                            (sync_recovery._json(row) + "\n").encode()
                            for row in tables[table["name"]]
                        ),
                    )
                for item in manifest["blobs"]:
                    ticket.check()
                    path = _safe_path(self.root / "objects" / item["sha256"])
                    version = file_change.version(path)
                    if version[2] != item["size"]:
                        raise SnapshotChanged("Recovered object exceeds its declared size")
                    archive.write(path, "objects/" + item["sha256"])
                    if file_change.version(path) != version:
                        raise SnapshotChanged("Recovered original object changed")
                    files.append((str(path.relative_to(self.root)), version))
            sync_recovery.inspect(package)
            expected = stage / "expected"
            expected.mkdir()
            records = sync_recovery._Records(manifest["workspace_id"], manifest["cursor"])
            for table in manifest["tables"]:
                for row in tables[table["name"]]:
                    records.row(table["name"], row)
            records.finish()
            # Adoption requires the stricter maintained input/source archive validators,
            # even when an older recovery archive was readable as observations only.
            stricter = recovery_provenance.validate_groups(
                recovery_provenance.encode(manifest, tables)
            )
            from paper_daily.sync_legacy_sources import validate_pdf

            digests = set()

            def collect_sources(group):
                digests.update(group.research_sources)
                for child in getattr(group, "_recovered_groups", ()):
                    collect_sources(child)

            for group in stricter:
                collect_sources(group)
            with zipfile.ZipFile(package) as archive:
                for digest in digests:
                    ticket.check()
                    validate_pdf(archive.read("objects/" + digest))
            # Materialize only from already-verified original object closure.
            (expected / "objects").mkdir()
            with zipfile.ZipFile(package) as archive:
                for item in manifest["blobs"]:
                    with (expected / "objects" / item["sha256"]).open("xb") as output:
                        sync_recovery._stream(archive, "objects/" + item["sha256"], item, output)
            sync_recovery._detached_files(expected, records)
            allowed = {relative for relative, _ in files}
            for path in expected.rglob("*"):
                if not path.is_file():
                    continue
                ticket.check()
                relative = path.relative_to(expected)
                actual = _safe_path(self.root / relative)
                version = file_change.version(actual)
                if (
                    actual.read_bytes() != path.read_bytes()
                    or file_change.version(actual) != version
                ):
                    raise SnapshotChanged("Recovered file differs from its typed projection")
                files.append((str(relative), version))
                allowed.add(str(relative))
            allowed.update(
                {self.database.name + suffix for suffix in ("", "-wal", "-shm", "-journal")}
            )
            for entries, path in enumerate(self.root.rglob("*"), 1):
                ticket.check()
                _safe_path(path)
                if entries > sync_recovery.MAX_BLOBS * 4 + 1000:
                    raise ValueError("Recovered filesystem exceeds its bounded inventory")
                relative = path.relative_to(self.root)
                if path.is_file() and len(relative.parts) == 1 and path.name in PRIVATE_FILES:
                    if str(relative) not in allowed:
                        files.append((str(relative), file_change.version(path)))
                        allowed.add(str(relative))
                    continue  # Metadata only: never open or copy credential file contents.
                if path.is_file() and str(relative) not in allowed:
                    raise ValueError("Undeclared recovered file: " + path.name)
        self._check()
        if self._database_versions() != database_versions:
            raise SnapshotChanged("Recovered database changed during inspection")
        if any(
            file_change.version(_safe_path(self.root / relative)) != version
            for relative, version in files
        ):
            raise SnapshotChanged("Recovered bytes changed before inspection completed")
        return snapshot, tuple(sorted(files))

    def _database_versions(self):
        return [
            (
                self.database.name + suffix,
                file_change.version(self.database.with_name(self.database.name + suffix)),
            )
            for suffix in ("", "-wal", "-journal")
            if self.database.with_name(self.database.name + suffix).exists()
        ]

    def _metadata_current(self, inspection, ticket):
        ticket.check()
        self._check()
        if (
            not isinstance(inspection, RecoveryInspection)
            or inspection._owner is not self
            or inspection._seal is not _SEAL
        ):
            raise ValueError("A native recovered inspection is required")
        captured_database = [
            (relative, version)
            for relative, version in inspection._files
            if relative in {self.database.name + suffix for suffix in ("", "-wal", "-journal")}
        ]
        if sorted(self._database_versions()) != sorted(captured_database):
            raise SnapshotChanged("Recovered database changed before publication")
        if any(
            file_change.version(_safe_path(self.root / relative)) != version
            for relative, version in inspection._files
        ):
            raise SnapshotChanged("Recovered files changed before publication")
        observed = set()
        ignored = {self.database.name + "-shm"}
        for count, path in enumerate(self.root.rglob("*"), 1):
            ticket.check()
            _safe_path(path)
            if count > sync_recovery.MAX_BLOBS * 4 + 1000:
                raise SnapshotChanged("Recovered filesystem inventory changed")
            if path.is_file() and str(path.relative_to(self.root)) not in ignored:
                observed.add(str(path.relative_to(self.root)))
        if observed != {relative for relative, _version in inspection._files}:
            raise SnapshotChanged("Recovered file inventory changed before publication")

    def inspect(self, *, ticket=None, progress=lambda _message: None):
        ticket = ticket or Ticket()
        progress("Inspecting recovered research, history and exact source closure")
        snapshot, files = self._capture(ticket)
        ticket.check()
        from paper_daily.workspace_enrollment import PRIVATE_FILES

        private_files = sum(
            len(Path(relative).parts) == 1 and relative in PRIVATE_FILES
            for relative, _version in files
        )
        result = object.__new__(RecoveryInspection)
        for key, value in dict(
            _owner=self,
            _snapshot=snapshot,
            _files=files,
            _report=canonical_json(_report(json.loads(snapshot), private_files=private_files)),
            _seal=_SEAL,
        ).items():
            object.__setattr__(result, key, value)
        return result

    def _validate(self, inspection, ticket):
        if (
            not isinstance(inspection, RecoveryInspection)
            or getattr(inspection, "_seal", None) is not _SEAL
            or inspection._owner is not self
        ):
            raise ValueError("Editable recovery requires this service's inspected snapshot")
        snapshot, files = self._capture(ticket)
        if snapshot != inspection._snapshot or files != inspection._files:
            raise SnapshotChanged("Recovered snapshot changed; inspect it again")
        return json.loads(snapshot)

    def prepare(
        self,
        inspection,
        output,
        *,
        backup_output,
        request_id,
        ticket=None,
        progress=lambda _message: None,
    ):
        """Prepare an editable independent copy; never activate or upload research."""
        from paper_daily import annotation_content, claim_content, store
        from paper_daily.workspace_enrollment import EnrollmentService

        ticket = ticket or Ticket()
        if not self._running.acquire(blocking=False):
            raise ValueError("Editable recovery preparation is already active")
        try:
            value = self._validate(inspection, ticket)
            if not inspection.report["supported"]:
                from paper_daily.workspace_enrollment import EnrollmentBlocked

                raise EnrollmentBlocked(inspection.report)
            output, backup = _safe_path(output), _safe_path(backup_output)
            if any(
                path == self.root
                or path.is_relative_to(self.root)
                or self.root.is_relative_to(path)
                for path in (output, backup)
            ):
                raise ValueError("Editable copy and backup must be outside recovered research")
            with tempfile.TemporaryDirectory(prefix="paperfact-recovery-baseline-") as temporary:
                root = Path(temporary)
                database = root / "papers.db"
                with closing(sqlite3.connect(database)) as conn:
                    conn.executescript(store.SCHEMA)
                    store._migrate(conn)
                    for table in value["manifest"]["tables"]:
                        if (
                            table["section"] != "research"
                            and table["name"] != "paper_annotation_known"
                        ):
                            continue
                        name, columns = table["name"], table["columns"]
                        for row in value["tables"][name]:
                            conn.execute(
                                'INSERT INTO "'
                                + name
                                + '" ('
                                + ",".join('"' + col + '"' for col in columns)
                                + ") VALUES("
                                + ",".join("?" for _ in columns)
                                + ")",
                                tuple(row[col] for col in columns),
                            )
                    _stage_live_chat(conn, value, self.root, root, ticket)
                    _stage_legacy_workflow(conn, value, self.root, root, ticket)
                    from paper_daily.recovery_position_sources import stage as stage_positions

                    stage_positions(self, inspection, conn, value, ticket)
                    from paper_daily.later_outcome_recovery import stage as stage_later_outcomes

                    stage_later_outcomes(self, inspection, conn, value, ticket)
                    conn.commit()
                records = _records(value)
                pdfs = {}
                for portable, target in records.applied_pdf.items():
                    if portable in records.hidden_pdf:
                        continue
                    local = records.paper_map[portable]
                    path = root / "pdf" / (str(len(pdfs)) + ".pdf")
                    path.parent.mkdir(exist_ok=True)
                    shutil.copyfile(self.root / "objects" / target["sha256"], path)
                    pdfs[local] = path
                for local, target in records.common_primaries.items():
                    if local in pdfs:
                        raise ValueError("Recovered primary scope is declared twice")
                    path = root / "pdf" / (str(len(pdfs)) + ".pdf")
                    path.parent.mkdir(exist_ok=True)
                    shutil.copyfile(self.root / "objects" / target["sha256"], path)
                    pdfs[local] = path
                for row in value["tables"].get(annotation_content.FEATURES["claims"], []):
                    digest = row["document_hash"]
                    folder = (
                        root
                        / "pdf"
                        / ".claim-evidence"
                        / claim_content.hashed(["claim-source-owner", row["paper_id"]])[:24]
                    )
                    folder.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(self.root / "objects" / digest, folder / (digest + ".pdf"))
                baseline = _Baseline(self, inspection, database, value, ticket, _SEAL)
                result = EnrollmentService(database).prepare(
                    output,
                    backup_output=backup,
                    request_id=request_id,
                    pdfs=pdfs,
                    ticket=ticket,
                    progress=progress,
                    _recovered=baseline,
                )
                return {
                    **result,
                    "recovered_from": value["manifest"]["backup_id"],
                    "history_preserved": True,
                    "editable_copy": True,
                }
        finally:
            self._running.release()


def _stage_live_chat(conn, value, original_root, staged_root, ticket):
    """Reuse maintained link validation; copy only explicitly consumed source digests."""
    from paper_daily import enrollment_chat_history, store, sync_content

    links = value["tables"].get("research_chat_links", [])
    if links:
        # Derive trusted DDL from the maintained initializer, never imported SQL.
        with closing(sqlite3.connect(":memory:")) as prototype:
            prototype.executescript(store.SCHEMA)
            store._migrate(prototype)
            if not prototype.in_transaction:
                prototype.execute("BEGIN")
            sync_content.initialize_content(prototype)
            ddl = prototype.execute(
                "SELECT sql FROM sqlite_master WHERE name='research_chat_links'"
            ).fetchone()[0]
        conn.execute(ddl)
        for link in links:
            ticket.check()
            enrollment_chat_history.validate_record("research_chat_links", link)
            conn.execute(
                "INSERT INTO research_chat_links VALUES(?,?,?,?,?)",
                tuple(
                    link[key]
                    for key in enrollment_chat_history.FORMATS["research_chat_links"].split()
                ),
            )
    live = enrollment_chat_history.live_inventory(conn, ticket)
    for digest in {item["sha256"] for item in live["sources"]}:
        ticket.check()
        path = Path(staged_root) / "pdf" / ".history" / (digest + ".pdf")
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_safe_path(Path(original_root) / "objects" / digest), path)


def _stage_legacy_workflow(conn, value, original_root, staged_root, ticket):
    from paper_daily import legacy_brief_recovery, legacy_briefs

    records = _records(value)
    for row in records.legacy_briefs.values():
        ticket.check()
        data = _safe_path(Path(original_root) / "objects" / row["sha256"]).read_bytes()
        if len(data) != row["size"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise SnapshotChanged("Recovered reading brief bytes changed")
        legacy_briefs.validate_markdown(data)
        path = Path(staged_root) / legacy_brief_recovery.relative(row)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if conn.execute(
            "SELECT paper_id FROM reading_log WHERE id=?", (row["local_id"],)
        ).fetchone() != (row["paper_id"],):
            raise ValueError("Recovered reading event owner changed")
        conn.execute("UPDATE reading_log SET brief_path=? WHERE id=?", (str(path), row["local_id"]))


def _records(value):
    with recovery_provenance.schema_definition_scope():
        manifest = value["manifest"]
        records = sync_recovery._Records(manifest["workspace_id"], manifest["cursor"])
        for table in manifest["tables"]:
            for row in value["tables"][table["name"]]:
                records.row(table["name"], row)
        records.finish()
        return records


class _Baseline:
    """Private publication hook; only a source-bound sealed inspection can create it."""

    def __init__(self, service, inspection, database, value, ticket, seal):
        if seal is not _SEAL:
            raise ValueError("Recovered baseline requires its native inspection")
        self.service, self.inspection, self.database = service, inspection, database
        if canonical_json(value) != inspection._snapshot or inspection._owner is not service:
            raise ValueError("Recovered baseline differs from its inspected source")
        self.value, self.ticket, self.seal = value, ticket, seal
        self.normalized_version = file_change.version(database)

    def check(self, database):
        if self.seal is not _SEAL or Path(database) != self.database:
            raise ValueError("Recovered baseline belongs to another staged workspace")
        if file_change.version(self.database) != self.normalized_version:
            raise SnapshotChanged("Private recovered baseline changed before publication")
        self.service._metadata_current(self.inspection, self.ticket)

    def publish(self, client, blobs, version_root):
        from uuid import NAMESPACE_URL, uuid5

        from paper_daily import recovery_decks, sync_artifacts, sync_deck_files
        from paper_daily.sync_document_actions import stage_file
        from paper_daily.sync_files import file_id
        from paper_daily.sync_source_files import input_versions, publish

        self.check(self.database)
        records = _records(self.value)
        # The complete original snapshot is archive-only, including pending work.
        blobs.quota_bytes = sync_recovery.MAX_TOTAL
        for item in self.value["manifest"]["blobs"]:
            self.ticket.check()
            actual = stage_file(blobs, self.service.root / "objects" / item["sha256"])
            if (actual.sha256, actual.size) != (item["sha256"], item["size"]):
                raise SnapshotChanged("Recovered original changed during staging")
        with client.journal.transaction() as conn:
            recovery_provenance.retain_in(
                conn, recovery_provenance.encode(self.value["manifest"], self.value["tables"])
            )
        slot_sources = {}
        requested_sources = set()
        from paper_daily.annotation_content import FEATURES

        for name in FEATURES.values():
            for row in self.value["tables"].get(name, []):
                if row["document_hash"] is not None:
                    requested_sources.add((row["paper_id"], row["document_hash"]))
        for operation in records.applied_files.values():
            if operation["entity_id"] in records.hidden_files:
                continue
            payload = operation["payload"]
            local = records.paper_map[payload["paper_id"]]
            if payload["feature"] == "original_source":
                requested_sources.add((local, payload["source_document_hash"]))
                continue
            if payload["feature"] == "legacy_brief":
                continue  # Fresh event/brief group is already staged by typed enrollment.
            slot_sources[(local, payload["slot"])] = payload["source_document_hash"]
        for row in records.legacy_decks.values():
            slot_sources[(row["paper_id"], row["slot"])] = None
        for row in records.observed_currents.values():
            slot_sources[(row["paper_id"], row["slot"])] = None
        for (local, mode), document_hash in slot_sources.items():
            self.ticket.check()
            detached, deck = recovery_decks.load(self.service.database, local, mode)
            if not detached or deck is None:
                raise ValueError("Current recovered deck has no exact saved closure")
            # Missing saved evidence remains explicitly absent; do not collect fresh AI inputs.
            evidence = deck._recovery_deck["evidence"]
            with client.journal.transaction() as conn:
                portable, parent = conn.execute(
                    "SELECT m.sync_id,p.incarnation FROM research_paper_identity m "
                    "JOIN research_paper_projection p ON p.sync_id=m.sync_id WHERE m.local_id=?",
                    (local,),
                ).fetchone()
            payload, encoded = sync_deck_files.encode_deck(
                deck,
                portable,
                input_versions=input_versions(),
                source_document_hash=document_hash,
                evidence=evidence,
            )
            sync_artifacts.stage_bytes(blobs, encoded)
            with client.journal.transaction() as conn:
                sync_artifacts.register_paths(
                    conn, client.journal.workspace_id, blobs, version_root
                )
                operation = client.new_graph_operation_in(
                    conn,
                    "research_file",
                    file_id(portable, "deck", mode),
                    payload,
                    operation_id=str(
                        uuid5(
                            NAMESPACE_URL,
                            client.journal.workspace_id + ":recovered-deck:" + local + ":" + mode,
                        )
                    ),
                )
                client.journal.apply_in(conn, operation, client.writer)
            materialized = sync_artifacts.materialize(blobs, version_root, operation)
            with client.journal.transaction() as conn:
                if not sync_artifacts.activate(conn, operation, materialized):
                    raise SnapshotChanged("Fresh recovered deck changed before activation")
            hashes = {item.get("document_hash") for item in deck.sources + deck.figures}
            hashes.add(document_hash)
            requested_sources.update((local, digest) for digest in hashes - {None})
        from paper_daily.proposal_recovery_review import all_carriers

        carriers = all_carriers(records)
        for carrier in carriers:
            from paper_daily import proposal_recovery

            self.ticket.check()
            for item in proposal_recovery.references(carrier):
                data = _safe_path(self.service.root / "objects" / item["sha256"]).read_bytes()
                if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                    raise SnapshotChanged("Recovered common proposal bytes changed")
                sync_artifacts.stage_bytes(blobs, {item["sha256"]: data})
            for item in json.loads(carrier["manifest_json"])["originals"]:
                requested_sources.add((carrier["paper_id"], item["sha256"]))
        for local, digest in sorted(requested_sources):
            self.ticket.check()
            if digest not in records.refs:
                raise ValueError("Current recovered original source is undeclared")
            with client.journal.transaction() as conn:
                portable, parent = conn.execute(
                    "SELECT m.sync_id,p.incarnation FROM research_paper_identity m "
                    "JOIN research_paper_projection p ON p.sync_id=m.sync_id WHERE m.local_id=?",
                    (local,),
                ).fetchone()
            publish(
                client,
                portable,
                self.service.root / "objects" / digest,
                document_hash=digest,
                parent_incarnation=parent,
                store=blobs,
                version_root=version_root,
                request_id="adopt-source:" + portable + ":" + digest[:32],
            )
        self.check(self.database)
