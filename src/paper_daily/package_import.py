"""Observed, staged imports into an already enrolled research workspace.

One typed graph/projector transaction owns research, outbox, attachment activation
and its action receipt. Private staged blobs are cache, never applied authority.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import shutil
import tempfile
import zipfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from paper_daily import (
    annotation_content,
    bundle,
    research_generation,
    research_job_lock,
    sync_capture,
    sync_content,
)
from paper_daily.file_change import version
from paper_daily.sync_artifacts import (
    activate,
    materialize,
    paths,
    register_paths,
    stage_bytes,
)
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_deck_files import encode_deck
from paper_daily.sync_deck_publication import runtime
from paper_daily.sync_documents import bind_verified_document, desired_document, verify_document
from paper_daily.sync_files import canonical_json, file_id
from paper_daily.sync_journal import canonical_operation
from paper_daily.workspace_service import Ticket, WorkspaceChanged, _binding, _safe_path, _tables

MAX_PACKAGE = 512 * 1024**2
MAX_FILES = 4096
MAX_ROWS = 4000
MAX_PAPERS = 500
_RECEIPTS = "package_import_receipts"
_SEAL = object()
_DERIVED_PAPER_FIELDS = {"crawled_at", "enriched_at", "scored_at"}
_LEGACY_PAPER_FIELDS = {
    "author_strength",
    "award",
    "citation_count",
    "influential_count",
    "is_canon",
    "paper_type",
    "reference_count",
    "score",
    "score_parts_json",
    "topic",
    "type_confidence",
}
_EMPTY_INPUTS = {
    "schema_version": 1,
    "complete": False,
    "entities": [],
    "documents": [],
    "inputs_sha256": None,
}


class UnsupportedPackage(ValueError):
    def __init__(self, reason, details=()):
        self.details = list(details)
        super().__init__(
            reason
            + (": " + ", ".join(str(item) for item in self.details[:8]) if self.details else "")
        )


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _uid(*parts):
    return str(
        uuid5(NAMESPACE_URL, "paperfact:package:" + json.dumps(parts, separators=(",", ":")))
    )


def _snapshot(conn, client, kind, identity):
    graph = client._optimistic_graph(conn)[0].get((kind, identity))
    operation = sync_capture._current(conn, client, kind, identity)
    return {"graph": copy.deepcopy(graph), "operation": operation}


def _target(operation):
    return {
        **operation["payload"],
        "workspace_id": operation["workspace_id"],
        "operation_id": operation["operation_id"],
        "incarnation": operation["incarnation"],
        "parent_incarnation": operation["parents"][0]["incarnation"],
    }


def _receipt(conn, identity):
    if _RECEIPTS not in _tables(conn):
        return None
    row = conn.execute(
        f"SELECT fingerprint,result_json FROM {_RECEIPTS} WHERE request_id=?", (identity,)
    ).fetchone()
    return (row[0], json.loads(row[1])) if row else None


@dataclass(frozen=True)
class PreparedImport:
    seal: object
    context: str
    operations: str
    observations: str
    report: str
    documents: tuple
    artifacts: tuple
    originals: tuple
    blob_store: object
    version_root: Path
    work: Path
    proposals: tuple = ()

    def preview(self):
        value = json.loads(self.report)
        return {**value, "state": "prepared", "applied": False}


class PackageImporter:
    def __init__(self, database, data_root, *, current_path=None):
        self.database = _safe_path(database)
        self.root = _safe_path(data_root)
        self.current_path = current_path or (lambda: self.database)
        self.client = runtime(database=self.database)
        if self.client is None:
            raise ValueError("An explicitly enrolled workspace is required")
        self.identity = tuple(research_generation._identity(self.database))
        with self.client.journal.transaction() as conn:
            self.binding = _binding(conn, _tables(conn))
            if "research_capture_binding" not in _tables(conn):
                raise ValueError("Commit-time capture must be installed before enrolled import")
            capture = conn.execute(
                "SELECT workspace,device FROM research_capture_binding"
            ).fetchall()
            if len(capture) != 1 or tuple(capture[0]) != (
                self.client.journal.workspace_id,
                self.client.journal.device_id,
            ):
                raise ValueError("The import capture binding is invalid")
            configured = paths(conn)
            reader = (
                conn.execute(
                    "SELECT workspace,blob_root,projection_root,legacy_root "
                    "FROM document_reader_paths WHERE id=1"
                ).fetchone()
                if "document_reader_paths" in _tables(conn)
                else None
            )
            self.reader_paths = tuple(reader) if reader else None
        blob_root = (
            configured[0].root
            if configured
            else (Path(self.reader_paths[1]) if self.reader_paths else self.root / ".package-blobs")
        )
        self.store = configured[0] if configured else BlobStore(blob_root)
        self.version_root = configured[1] if configured else self.root / ".package-versions"

    def _check(self, conn=None):
        if (
            Path(self.current_path()).resolve() != self.database
            or tuple(research_generation._identity(self.database)) != self.identity
        ):
            raise WorkspaceChanged("The import workspace changed or was replaced")
        if conn is not None and _binding(conn, _tables(conn)) != self.binding:
            raise WorkspaceChanged("The import workspace binding changed")

    def _current_ticket(self, ticket):
        ticket.check()
        self._check()
        return True

    def _inventory(self, archive, ticket):
        selected = _safe_path(archive)
        before = version(selected)
        if selected.stat().st_size > MAX_PACKAGE:
            raise UnsupportedPackage("The package exceeds the import byte budget")
        with selected.open("rb") as stream:
            digest = hashlib.sha256()
            while chunk := stream.read(1024**2):
                ticket.check()
                digest.update(chunk)
        with zipfile.ZipFile(selected) as z:
            infos = z.infolist()
            if len(infos) > MAX_FILES or sum(item.file_size for item in infos) > MAX_PACKAGE:
                raise UnsupportedPackage("The expanded package exceeds the import budget")
            if any(
                item.file_size > 8 * 1024**2
                for item in infos
                if item.filename in {"manifest.json", "tables.json"}
            ):
                raise UnsupportedPackage("The package metadata exceeds its byte budget")
            manifest, tables, owners = bundle._validated(z)
            if not isinstance(tables, dict) or any(
                not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
                for rows in tables.values()
            ):
                raise ValueError("Package tables must contain bounded research row collections")
            if len(tables["papers"]) + len(tables.get("cited_papers", [])) > MAX_PAPERS:
                raise UnsupportedPackage("The package exceeds the paper count budget")
            if sum(len(rows) for rows in tables.values()) > MAX_ROWS:
                raise UnsupportedPackage("The package exceeds the research row budget")
            known = {
                "papers",
                "cited_papers",
                "refs",
                "list_surveys",
                "list_reading_goals",
                "pins",
                "queue_pins",
                "deck_proposals",
                *bundle.PER_PAPER,
                "pdf_ai_highlights",
                "pdf_highlights",
                "notes",
                "chat",
                "kv",
            }
            unsupported = [name for name, rows in tables.items() if name not in known and rows]
            for marker in tables.get("paper_annotation_known", []):
                table = annotation_content.FEATURES[marker["feature"]]
                if not any(row["paper_id"] == marker["paper_id"] for row in tables.get(table, [])):
                    unsupported.append("annotation deletion without portable history")
            if tables.get("kv"):
                unsupported.append("legacy research KV caches")
            if unsupported:
                raise UnsupportedPackage(
                    "This package contains unsupported research scopes", unsupported
                )
            for table, rows in tables.items():
                if table in ("papers", "cited_papers"):
                    allowed = (
                        sync_capture.PAPER_COLUMNS
                        | {"title_key"}
                        | _DERIVED_PAPER_FIELDS
                        | _LEGACY_PAPER_FIELDS
                    )
                    nonempty = {
                        name
                        for row in rows
                        for name in _LEGACY_PAPER_FIELDS
                        if row.get(name) not in (None, 0, "", "{}", "[]")
                    }
                    if nonempty:
                        raise UnsupportedPackage(
                            "Legacy paper module metadata requires a reviewed portable adapter",
                            sorted(nonempty),
                        )
                elif table == "notes":
                    allowed = sync_content.RICH_NOTE_FIELDS | {"id"}
                elif table == "paper_annotation_known":
                    allowed = {"feature", "paper_id"}
                elif table in sync_content.TABLE_FEATURES:
                    feature = sync_content.TABLE_FEATURES[table]
                    _table, natural, field_names = sync_content.FEATURES[feature]
                    allowed = set(field_names.split()) | {"paper_id", "list_id", "id"}
                    if natural:
                        allowed.add(natural)
                    if feature in {"ai_highlight", "manual_highlight"}:
                        allowed.add("document_hash")
                    if feature == "chat":
                        allowed |= {"message_id", "exchange_id", "reply_to", "source_hash"}
                else:
                    continue
                if any(set(row) - allowed for row in rows):
                    raise UnsupportedPackage("Unsupported package row fields", [table])
            annotation_caches = {
                "paper-highlights": "paper_highlight_analysis",
                "reading-links": "paper_reading_links",
                "research-questions": "paper_research_questions",
            }
            for relative, owner in owners.items():
                folder = Path(relative).parts[0]
                if folder == "material-positions":
                    raise UnsupportedPackage(
                        "Edited material positions require a reviewed portable adapter", [relative]
                    )
                table = annotation_caches.get(folder)
                if table and not any(row["paper_id"] == owner for row in tables.get(table, [])):
                    raise UnsupportedPackage(
                        "Legacy annotation caches require typed research before enrolled import",
                        [relative],
                    )
            files = {name: z.read("files/" + name) for name in owners}
        if version(selected) != before:
            raise ValueError("The selected package changed while it was inspected")
        return selected, before, digest.hexdigest(), manifest, tables, owners, files

    def prepare(
        self,
        archive,
        *,
        replace=False,
        request_id=None,
        ticket=None,
        allow_new_namespace=False,
        target_list_id=None,
        paper_mapping=None,
        confirmed_mapping=False,
    ):
        if any(
            type(value) is not bool for value in (replace, allow_new_namespace, confirmed_mapping)
        ):
            raise ValueError("Import choices must be explicit booleans")
        ticket = ticket or Ticket()
        self._check()
        selected, stamp, fingerprint, manifest, tables, owners, files = self._inventory(
            archive, ticket
        )
        proposal_store_index = None
        if tables.get("deck_proposals"):
            from paper_daily.local_blob_binding import bind
            from paper_daily.research_lifecycle import ensure_lifecycle

            self._check()
            # Explicit local setup, before observing a parent or staging content;
            # this neither enrolls a device nor publishes a research operation.
            with self.client.journal.transaction() as metadata:
                self._check(metadata)
                ensure_lifecycle(metadata)
            proposal_store_index = bind(self.client, self.store)
            self._check()
        mapping_option = dict(paper_mapping or {})
        if (target_list_id or mapping_option) and not confirmed_mapping:
            raise UnsupportedPackage("Existing targets require an explicitly confirmed mapping")
        action_fingerprint = _hash(
            canonical_json(
                {
                    "package": fingerprint,
                    "replace": bool(replace),
                    "list": target_list_id,
                    "papers": mapping_option,
                    "new_namespace": bool(allow_new_namespace),
                }
            )
        )
        request = request_id or _uid(self.client.journal.workspace_id, action_fingerprint)
        from paper_daily.sync_journal import _identifier

        _identifier(request)
        # A read-only snapshot can simulate prospective graph state. It grants no
        # SQL authority: apply rebuilds every envelope against the actual transaction.
        with closing(research_generation._connect(self.database)) as conn:
            conn.execute("BEGIN")
            self._check(conn)
            prior = _receipt(conn, request)
            if prior:
                if prior[0] != action_fingerprint:
                    raise ValueError("Import request identity was reused for another package")
                return self._replay(prior[1], request, action_fingerprint)
            if tables.get("queue_pins") and not sync_content.pin_cleanup_ready(conn):
                raise UnsupportedPackage("Queue pin cleanup requires explicit installation")
            conn._capture_graph_cache = copy.deepcopy(self.client._optimistic_graph(conn))
            graph = conn._capture_graph_cache[0]
            list_id = target_list_id or _uid(fingerprint, "list", manifest["list"]["id"])
            existing_lists = [
                key for key, value in graph.items() if key[0] == "list" and value["active"]
            ]
            namespace_roster = (
                sorted(
                    (identity, value["incarnation"])
                    for (kind, identity), value in graph.items()
                    if kind == "list" and value["active"]
                )
                if ("list", list_id) not in graph and not (allow_new_namespace or confirmed_mapping)
                else None
            )
            if (
                existing_lists
                and ("list", list_id) not in graph
                and not (allow_new_namespace or confirmed_mapping)
            ):
                raise UnsupportedPackage(
                    "An unknown package needs a reviewed destination or explicit new namespace"
                )
            papers, identities = {}, {}
            all_papers = tables["papers"] + tables.get("cited_papers", [])
            for row in all_papers:
                old = row["id"]
                if old in papers:
                    raise ValueError("Duplicate paper identity in package")
                if old in mapping_option:
                    found = conn.execute(
                        "SELECT sync_id FROM research_paper_identity WHERE local_id=?",
                        (mapping_option[old],),
                    ).fetchone()
                    if found is None:
                        raise ValueError("A confirmed target paper is unavailable")
                    portable, local = found[0], mapping_option[old]
                else:
                    portable = _uid(fingerprint, "paper", old)
                    found = conn.execute(
                        "SELECT local_id FROM research_paper_identity WHERE sync_id=?", (portable,)
                    ).fetchone()
                    local = found[0] if found else "sync:" + portable
                    collision = conn.execute("SELECT 1 FROM papers WHERE id=?", (old,)).fetchone()
                    if collision and not found:
                        raise UnsupportedPackage(
                            "A legacy paper ID collides; confirm its mapping", [old]
                        )
                papers[old] = {"local_id": local, "portable_id": portable}
                identities[old] = portable
            if set(mapping_option) - set(papers):
                raise ValueError("The confirmed mapping contains a paper outside this package")
            if target_list_id and not graph.get(("list", list_id), {}).get("active"):
                raise ValueError("The confirmed list is missing or deleted")
            # Capture before any staging or ending this target read snapshot.
            proposal_parents = []
            if tables.get("deck_proposals"):
                from paper_daily.research_lifecycle import parent_lifecycle

                for local in sorted({item["local_id"] for item in papers.values()}):
                    exists = conn.execute(
                        "SELECT 1 FROM papers WHERE id=?", (local,)).fetchone()
                    token = parent_lifecycle(conn, "paper", local)
                    if exists and token is None:
                        raise ValueError("Proposal receiver requires a known local lifecycle")
                    proposal_parents.append([local, bool(exists), token])
            operations, observations = [], {}
            report = {
                "enrolled": True,
                "list": list_id,
                "name": manifest["list"]["name"],
                "identity_mapping": papers,
                "source_list_id": manifest["list"]["id"],
                "package_fingerprint": fingerprint,
                "replayed": False,
                "pdf_conflicts": [],
                "state": "applied_locally",
                "remote_sync": "not_requested",
                "pdf_ok": [],
                "pdf_needed": [],
                "omitted_derivatives": [],
                "files": 0,
                "joined_list": 0,
            }

            def remember(kind, identity):
                key = (kind, identity)
                if key not in observations:
                    observations[key] = _snapshot(conn, self.client, kind, identity)

            def add(kind, identity, payload, category, *, overwrite=replace):
                remember(kind, identity)
                current = graph.get((kind, identity))
                prior_op = sync_capture._current(conn, self.client, kind, identity)
                if current:
                    if not current["active"]:
                        raise UnsupportedPackage(
                            "Deleted targets require explicit restoration", [identity]
                        )
                    if prior_op and prior_op["payload"] == payload:
                        return prior_op
                    if not overwrite:
                        return prior_op
                operation = self.client.new_graph_operation_in(
                    conn,
                    kind,
                    identity,
                    payload,
                    operation_id=_uid(request, kind, identity),
                )
                operations.append(operation)
                self.client._overlay_optimistic(conn._capture_graph_cache, operation)
                report[category] = report.get(category, 0) + 1
                return operation

            for row in all_papers:
                portable = identities[row["id"]]
                remember("paper", portable)
                payload = sync_capture._payload(conn, "papers", row)
                category = "papers" if row in tables["papers"] else "cited_papers"
                add(
                    "paper", portable, payload, category, overwrite=replace and category == "papers"
                )
            add(
                "list",
                list_id,
                {"name": manifest["list"]["name"], "note": manifest["list"].get("note") or ""},
                "lists",
            )
            from paper_daily.sync_schema_v2 import membership_id

            for member in manifest["members"]:
                portable = identities[member["paper_id"]]
                add(
                    "membership",
                    membership_id(list_id, portable),
                    {
                        "list_id": list_id,
                        "paper_id": portable,
                        "citation": member.get("citation"),
                        "added_at": member["added_at"],
                    },
                    "joined_list",
                    overwrite=False,
                )
            prior_members = [
                membership_id(list_id, row[0])
                for row in conn.execute(
                    "SELECT m.sync_id FROM list_papers p JOIN research_paper_identity m "
                    "ON m.local_id=p.paper_id WHERE p.list_id=? ORDER BY p.position,p.paper_id",
                    (list_id,),
                )
            ]
            ordered = list(prior_members)
            for member in manifest["members"]:
                identity = membership_id(list_id, identities[member["paper_id"]])
                if identity not in ordered:
                    ordered.append(identity)
            order = self.client.new_order_operation_in(
                conn,
                "list_order",
                list_id,
                ordered,
                operation_id=_uid(request, "list_order", list_id),
            )
            add("list_order", list_id, order["payload"], "orders", overwrite=True)
            documents, originals, artifacts = [], [], []
            work = Path(tempfile.mkdtemp(prefix=".package-import-", dir=self.root))
            try:
                for old, record in manifest.get("pdfs", {}).items():
                    if record is None:
                        report["pdf_needed"].append(old)
                        continue
                    portable = identities[old]
                    remember("paper_document", portable)
                    current = desired_document(conn, portable)
                    if current and current["sha256"] != record["sha256"]:
                        report["pdf_conflicts"].append(old)
                        continue
                    relative = "pdf/" + bundle._safe_name(old) + ".pdf"
                    data = files.get(relative)
                    if data is None:
                        raise UnsupportedPackage(
                            "Enrolled import requires included primary PDF bytes", [old]
                        )
                    stage_bytes(self.store, {record["sha256"]: data})
                    op = add(
                        "paper_document",
                        portable,
                        {
                            "paper_id": portable,
                            "sha256": record["sha256"],
                            "size": len(data),
                            "media_type": "application/pdf",
                        },
                        "documents",
                        overwrite=False,
                    )
                    target = _target(op)
                    documents.append((target, verify_document(self.store, target)))
                    report["pdf_ok"].append(old)
                    report["files"] += 1
                self._prepare_originals(
                    conn,
                    manifest,
                    tables,
                    files,
                    identities,
                    graph,
                    request,
                    work,
                    originals,
                    artifacts,
                    observations,
                    add,
                    ticket,
                    report,
                )
                from paper_daily import deck_proposal_packages

                proposals = deck_proposal_packages.prepare_imports(
                    tables.get("deck_proposals", []), files, papers, request, self.store,
                    client=self.client, expected_native=self.identity,
                    current=lambda: self._current_ticket(ticket))
                if proposals:
                    report["deck_proposals"] = len(proposals)
                self._content(conn, manifest, tables, identities, list_id, fingerprint, add, report)
                self._prepare_decks(
                    conn,
                    files,
                    owners,
                    identities,
                    fingerprint,
                    request,
                    add,
                    artifacts,
                    report,
                    ticket,
                )
                for table in known_categories():
                    report.setdefault(table, 0)
                # End our own read snapshot before the source seam's bounded
                # binding check; DELETE-journal workspaces must not self-deadlock.
                conn.rollback()
                from paper_daily.sync_source_files import prepare_source

                sealed_originals = []
                for portable, parent, selected_source, digest, operation in originals:
                    staged = prepare_source(
                        self.client,
                        portable,
                        selected_source,
                        document_hash=digest,
                        parent_incarnation=parent,
                        store=self.store,
                        version_root=self.version_root,
                        request_id=operation["operation_id"],
                    )
                    sealed_originals.append((staged, operation))
                self._check()
                data = {
                    "database": str(self.database),
                    "identity": self.identity,
                    "binding": self.binding,
                    "archive": str(selected),
                    "archive_version": stamp,
                    "request": request,
                    "fingerprint": action_fingerprint,
                    "namespace_roster": namespace_roster,
                    "queue_pin_intent": bool(tables.get("queue_pins")),
                    "proposal_store_index": proposal_store_index,
                    "proposal_parents": proposal_parents,
                    "proposal_replace": replace,
                }
                return PreparedImport(
                    _SEAL,
                    canonical_json(data).decode(),
                    canonical_json(operations).decode(),
                    canonical_json([[*key, value] for key, value in observations.items()]).decode(),
                    canonical_json(report).decode(),
                    tuple(documents),
                    tuple(artifacts),
                    tuple(sealed_originals),
                    self.store,
                    self.version_root,
                    work,
                    proposals,
                )
            except BaseException:
                self._cleanup(work)
                raise

    def _replay(self, report, request, fingerprint):
        return PreparedImport(
            _SEAL,
            canonical_json(
                {
                    "database": str(self.database),
                    "identity": self.identity,
                    "binding": self.binding,
                    "request": request,
                    "fingerprint": fingerprint,
                }
            ).decode(),
            "[]",
            "[]",
            canonical_json(
                {
                    **report,
                    "replayed": True,
                    "state": "previously_applied",
                    "availability_rechecked": False,
                }
            ).decode(),
            (),
            (),
            (),
            self.store,
            self.version_root,
            self.root,
        )

    def _prepare_originals(
        self,
        conn,
        manifest,
        tables,
        files,
        identities,
        graph,
        request,
        work,
        originals,
        artifacts,
        observations,
        add,
        ticket,
        report,
    ):
        from paper_daily.sync_source_files import encode

        records = [
            (item["paper_id"], item, True) for item in manifest.get("position_sources", [])
        ]
        records += [
            (item["paper_id"], item, True) for item in manifest.get("later_sources", [])
        ]
        records += [
            (old, {"sha256": row["sha256"],
                   "path": "pdf/" + bundle._safe_name(old) + ".pdf"}, False)
            for old, row in manifest.get("pdfs", {}).items()
            if row
        ]
        records += [
            (old, record, False) for old, record in manifest.get("claim_sources", {}).items()
        ]
        from paper_daily.deck_proposal_packages import relative

        records += [
            (row["paper_id"], {"sha256": original["sha256"],
             "path": relative(row["paper_id"], original["sha256"]).as_posix()}, True)
            for row in tables.get("deck_proposals", [])
            for original in row["manifest"]["originals"]
        ]
        seen = set()
        for old, record, position in records:
            if (old, record["sha256"]) in seen:
                continue
            ticket.check()
            if old in report["pdf_conflicts"] and not position:
                continue
            seen.add((old, record["sha256"]))
            relative = record["path"]
            if relative is None or relative not in files:
                raise UnsupportedPackage(
                    "Claim originals must be included before enrolled import", [old]
                )
            portable = identities[old]
            parent = graph[("paper", portable)]["incarnation"]
            selected = work / (record["sha256"] + ".pdf")
            selected.write_bytes(files[relative])
            identity = file_id(portable, "original_source", record["sha256"])
            payload, blobs = encode(portable, files[relative])
            stage_bytes(self.store, blobs)
            operation = add("research_file", identity, payload, "original_sources", overwrite=False)
            originals.append((portable, parent, selected, record["sha256"], operation))
            artifacts.append((operation, materialize(self.store, self.version_root, operation)))
            report["files"] += 1

    def _content(self, conn, manifest, tables, identities, list_id, fingerprint, add, report):
        for table, rows in tables.items():
            if table not in sync_content.TABLE_FEATURES or table == "notes":
                continue
            feature = sync_content.TABLE_FEATURES[table]
            _table, natural, field_names = sync_content.FEATURES[feature]
            for index, row in enumerate(rows):
                old = row.get("paper_id")
                if (old in report["pdf_conflicts"]
                        and feature not in {"reading_position", "later_outcome"}):
                    continue
                if feature in {"list_survey", "reading_goal", "list_pin"}:
                    scope = {"kind": "list", "id": list_id}
                else:
                    scope = {"kind": "paper", "id": identities[old]}
                if feature == "list_pin":
                    key = identities[row["paper_id"]]
                elif feature == "reference_edge":
                    key = identities[row["ref_paper_id"]]
                elif natural == "id":
                    key = row.get("message_id") or _uid(fingerprint, table, index)
                else:
                    key = row[natural] if natural else "main"
                if feature == "ai_highlight":
                    key = row["document_hash"] + ":" + key
                data = {field: row[field] for field in field_names.split()}
                for field in ("anchor", "contexts_json", "reading_json", "body_json"):
                    if field in data and data[field] is not None:
                        data[field] = json.loads(data[field])
                if feature == "chat" and row.get("message_id"):
                    data.update(exchange_id=row["exchange_id"], reply_to=row["reply_to"])
                source_hash = (
                    row.get("document_hash") or row.get("source_hash")
                    if feature == "chat"
                    else row.get("document_hash")
                )
                if source_hash is None and isinstance(data.get("anchor"), dict):
                    source_hash = data["anchor"].get("document_hash")
                payload = {
                    "scope": scope,
                    "feature": feature,
                    "key": key,
                    "data": data,
                    "source_document_hash": source_hash,
                }
                sync_content.validate_payload(payload)
                installed = add(
                    "research_content", sync_content.content_id(scope, feature, key), payload, table
                )
                if feature == "reading_position" and installed and installed["payload"] != payload:
                    report.setdefault("position_import_candidates", []).append({
                        "package_sha256": fingerprint, "source_owner": old,
                        "receiver_owner": identities[old], "document_hash": key,
                        "incoming_json": canonical_json(data).decode(),
                        "receiver_json": canonical_json(installed["payload"]["data"]).decode(),
                    })
                if feature == "later_outcome" and installed and installed["payload"] != payload:
                    current_data = installed["payload"]["data"]
                    incoming = {"paper_id": old, **row}
                    receiver = {"paper_id": scope["id"], **current_data,
                                "body_json": canonical_json(current_data["body_json"]).decode()}
                    report.setdefault("later_outcome_import_candidates", []).append({
                        "package_sha256": fingerprint, "source_owner": old,
                        "receiver_owner": scope["id"],
                        "incoming_json": canonical_json(incoming).decode(),
                        "receiver_json": canonical_json(receiver).decode(),
                    })
        for row in tables.get("queue_pins", []):
            scope = {"kind": "paper", "id": identities[row["paper_id"]]}
            payload = {"scope": scope, "feature": "queue_pin", "key": "main",
                       "data": {"pinned_at": row["pinned_at"]}, "source_document_hash": None}
            sync_content.validate_payload(payload)
            operation = add("research_content", sync_content.content_id(scope, "queue_pin", "main"),
                            payload, "queue_pins", overwrite=False)
            if operation and operation["payload"] != payload:
                report.setdefault("queue_pin_preserved", []).append({
                    "package_sha256": fingerprint, "source_owner": row["paper_id"],
                    "receiver_owner": scope["id"], "incoming_pinned_at": row["pinned_at"],
                    "receiver_pinned_at": operation["payload"]["data"]["pinned_at"],
                })
        for index, row in enumerate(tables.get("notes", [])):
            if row["paper_id"] in report["pdf_conflicts"]:
                continue
            payload = {key: row.get(key) for key in sync_content.RICH_NOTE_FIELDS}
            payload["paper_id"] = identities[row["paper_id"]]
            payload["anchor"] = json.loads(row["anchor"]) if row.get("anchor") is not None else None
            sync_content.validate_rich_note(payload)
            add("note", _uid(fingerprint, "note", index), payload, "notes")

    def _prepare_decks(
        self, conn, files, owners, identities, fingerprint, request, add, artifacts, report, ticket
    ):
        from paper_daily.presentations import deck_from_dict
        from paper_daily.slide_layout import used_figures

        consumed = set()
        for relative, data in files.items():
            parts = Path(relative).parts
            if (
                len(parts) != 3
                or parts[0] != "presentations"
                or parts[2] not in ("guide.json", "notes.json")
            ):
                continue
            ticket.check()
            old = owners[relative]
            if old in report["pdf_conflicts"]:
                continue
            deck = deck_from_dict(json.loads(data))
            if deck.paper_id != old or deck.mode + ".json" != parts[2]:
                raise ValueError("Package deck differs from its declared owner/mode")
            image_bytes = {}
            for figure in deck.figures:
                if figure["id"] not in used_figures(deck):
                    continue
                filename = figure.get("asset") or figure.get("file")
                if not isinstance(filename, str) or Path(filename).name != filename:
                    raise ValueError("Package deck figure filename is unsafe")
                image = (
                    (Path(relative).parent / "assets" / filename).as_posix()
                    if figure.get("asset")
                    else (Path("figures") / bundle._safe_name(old) / filename).as_posix()
                )
                if image not in files:
                    raise UnsupportedPackage("Package deck is missing a required figure", [image])
                image_bytes[figure["id"]] = files[image]
                consumed.add(image)
            deck._revision_figures = image_bytes
            evidence = None
            if deck.source_hash:
                evidence_path = (
                    Path(relative).parent / "evidence" / (deck.source_hash + ".json")
                ).as_posix()
                if evidence_path in files:
                    evidence = json.loads(files[evidence_path])
                    consumed.add(evidence_path)
            hashes = {
                row.get("document_hash")
                for row in deck.sources
                if row.get("kind") in {"original", "figure"} and row.get("document_hash")
            }
            if len(hashes) > 1:
                raise UnsupportedPackage("Multiple deck originals need an explicit source mapping")
            source_hash = next(iter(hashes), None)
            if source_hash and not any(
                owner == old and relative.startswith("pdf/") and _hash(blob) == source_hash
                for relative, blob in files.items()
                for owner in [owners[relative]]
            ):
                raise UnsupportedPackage("A deck original is not present in this package", [old])
            payload, blobs = encode_deck(
                deck,
                identities[old],
                input_versions=copy.deepcopy(_EMPTY_INPUTS),
                source_document_hash=source_hash,
                evidence=evidence,
            )
            stage_bytes(self.store, blobs)
            identity = file_id(identities[old], "deck", deck.mode)
            operation = add("research_file", identity, payload, "decks")
            if operation and operation["payload"] == payload:
                artifacts.append((operation, materialize(self.store, self.version_root, operation)))
                report["files"] += 1
            consumed.add(relative)
        for relative in files:
            if (relative.startswith(("pdf/", "deck-proposals/"))
                    or relative in consumed):
                continue
            if Path(relative).parts[0] not in {
                "presentations",
                "figures",
                "text",
                "paper-highlights",
                "reading-links",
                "material-positions",
                "research-questions",
            }:
                raise UnsupportedPackage("Unsupported package artifact", [relative])
            report["omitted_derivatives"].append(relative)

    def apply(self, prepared, *, ticket=None):
        try:
            return self._apply(prepared, ticket=ticket)
        finally:
            if (
                isinstance(prepared, PreparedImport)
                and getattr(prepared, "seal", None) is _SEAL
                and prepared.work != self.root
                and prepared.work.parent == self.root
            ):
                try:
                    self._cleanup(prepared.work)
                except OSError:
                    logging.getLogger(__name__).warning(
                        "Private package staging cleanup is pending"
                    )

    def _apply(self, prepared, *, ticket=None):
        if not isinstance(prepared, PreparedImport) or getattr(prepared, "seal", None) is not _SEAL:
            raise ValueError("Import requires a trusted prepared package")
        ticket = ticket or Ticket()
        data = json.loads(prepared.context)
        if (
            data["database"] != str(self.database)
            or tuple(data["identity"]) != self.identity
            or canonical_json(data["binding"]) != canonical_json(self.binding)
        ):
            raise WorkspaceChanged("The prepared import belongs to another database/binding")
        self._check()
        ticket.check()
        if "archive" in data and canonical_json(version(Path(data["archive"]))) != canonical_json(
            data["archive_version"]
        ):
            raise ValueError("The selected archive changed after preparation")
        context = self.client.journal.transaction()
        conn = context.__enter__()
        ended = False
        try:
            self._check(conn)
            prior = _receipt(conn, data["request"])
            if prior:
                if prior[0] != data["fingerprint"]:
                    raise ValueError("Import request identity was reused")
                report = {
                    **prior[1],
                    "replayed": True,
                    "state": "previously_applied",
                    "availability_rechecked": False,
                }
            else:
                if data.get("proposal_store_index") is not None:
                    index = self.store.root / "index.sqlite"
                    info = index.stat()
                    if [info.st_dev, info.st_ino] != data["proposal_store_index"]:
                        raise WorkspaceChanged("Proposal artifact index was replaced")
                    from paper_daily.research_lifecycle import parent_lifecycle

                    for local, existed, token in data["proposal_parents"]:
                        exists = conn.execute(
                            "SELECT 1 FROM papers WHERE id=?", (local,)).fetchone()
                        if (bool(exists) != existed
                                or parent_lifecycle(conn, "paper", local) != token):
                            raise WorkspaceChanged(
                                "Proposal receiver lifecycle changed after preview")
                if data.get("queue_pin_intent") and not sync_content.pin_cleanup_ready(conn):
                    raise UnsupportedPackage("Queue pin cleanup requires explicit installation")
                if data.get("namespace_roster") is not None:
                    roster = sorted(
                        [identity, value["incarnation"]]
                        for (kind, identity), value in self.client._optimistic_graph(conn)[
                            0
                        ].items()
                        if kind == "list" and value["active"]
                    )
                    if roster != data["namespace_roster"]:
                        raise ValueError("The import namespace changed; prepare its preview again")
                for kind, identity, expected in json.loads(prepared.observations):
                    if _snapshot(conn, self.client, kind, identity) != expected:
                        raise ValueError("Import targets changed after preview; prepare again")
                from paper_daily import deck_proposal_packages

                with deck_proposal_packages.import_targets_in(
                    conn, self.client, prepared.proposals,
                    current=lambda: self._current_ticket(ticket),
                    allow_updates=data.get("proposal_replace", False),
                ) as proposal_grant:
                    register_paths(
                        conn,
                        self.client.journal.workspace_id,
                        prepared.blob_store,
                        prepared.version_root,
                    )
                    from paper_daily.document_reader import register_document_paths

                    if self.reader_paths:
                        current_reader = conn.execute(
                            "SELECT workspace,blob_root,projection_root,legacy_root "
                            "FROM document_reader_paths WHERE id=1"
                        ).fetchone()
                        if tuple(current_reader or ()) != self.reader_paths:
                            raise WorkspaceChanged("The document storage registration changed")
                    else:
                        register_document_paths(
                            conn,
                            workspace_id=self.client.journal.workspace_id,
                            blob_root=prepared.blob_store.root,
                            projection_root=self.root / ".package-reader",
                            legacy_root=self.root / "pdf",
                        )
                    originals = {op["operation_id"]: staged for staged, op in prepared.originals}
                    from paper_daily.sync_source_files import publish_source_in

                    for operation in json.loads(prepared.operations):
                        ticket.check()
                        actual = self.client.new_graph_operation_in(
                            conn,
                            operation["entity_type"],
                            operation["entity_id"],
                            operation["payload"],
                            operation_id=operation["operation_id"],
                        )
                        if canonical_operation(actual) != canonical_operation(operation):
                            raise ValueError("Import graph changed before its observed write")
                        if operation["operation_id"] in originals:
                            published = publish_source_in(
                                conn, self.client, originals[operation["operation_id"]]
                            )
                            if published != operation:
                                raise ValueError(
                                    "Original source differs from its prepared operation"
                                )
                        else:
                            self.client.journal.apply_in(conn, operation, self.client.writer)
                    for target, proof in prepared.documents:
                        if not bind_verified_document(conn, target, proof):
                            raise ValueError("Imported PDF target changed before activation")
                    for operation, directory in prepared.artifacts:
                        if not activate(conn, operation, directory):
                            raise ValueError("Imported artifact target changed before activation")
                    from paper_daily import deck_proposal_packages

                    adopted = proposal_grant.adopt()
                    report = json.loads(prepared.report)
                    if adopted:
                        report["proposal_ids"] = adopted
                    from paper_daily.reading_position_packages import retain_imports_in

                    retain_imports_in(conn, report.get("position_import_candidates", []))
                    from paper_daily.later_outcome_packages import (
                        retain_imports_in as retain_later_imports,
                    )
                    from paper_daily.queue_pins import retain_imports_in

                    retain_later_imports(conn, report.get("later_outcome_import_candidates", []))

                    retain_imports_in(conn, report.get("queue_pin_preserved", []))
                    conn.execute(
                        f"CREATE TABLE IF NOT EXISTS {_RECEIPTS}(request_id TEXT PRIMARY KEY, "
                        "fingerprint TEXT NOT NULL, result_json TEXT NOT NULL)"
                    )
                    conn.execute(
                        f"INSERT INTO {_RECEIPTS} VALUES(?,?,?)",
                        (
                            data["request"],
                            data["fingerprint"],
                            canonical_json(report).decode(),
                        ),
                    )
            ticket.check()
            self._check(conn)
            if data.get("proposal_store_index") is not None:
                info = (self.store.root / "index.sqlite").stat()
                if [info.st_dev, info.st_ino] != data["proposal_store_index"]:
                    raise WorkspaceChanged("Proposal artifact index changed before commit")

            def commit():
                nonlocal ended
                ended = True
                context.__exit__(None, None, None)

            ticket.publish(commit)
            return report
        except BaseException as exc:
            if not ended:
                context.__exit__(type(exc), exc, exc.__traceback__)
            raise

    def _cleanup(self, work):
        selected = _safe_path(work)
        if selected.parent != self.root or not selected.name.startswith(".package-import-"):
            raise ValueError("Unexpected import staging directory")
        if selected.exists():
            shutil.rmtree(selected)


def known_categories():
    return (
        "papers",
        "cited_papers",
        "notes",
        "chat",
        "pins",
        "queue_pins",
        "refs",
        "list_surveys",
        "list_reading_goals",
        *bundle.PER_PAPER,
        "pdf_ai_highlights",
        "pdf_highlights",
        "kv",
    )


def import_package(database, data_root, archive, **options):
    """Shared UI/CLI service entry; never starts a provider or remote transfer."""
    owner = _hash(str(Path(archive).resolve()).encode())
    with research_job_lock.claim(database, "package-import", owner) as acquired:
        if not acquired:
            raise ValueError("This package import is already in progress")
        importer = PackageImporter(
            database, data_root, current_path=options.pop("current_path", None)
        )
        ticket = options.pop("ticket", None) or Ticket()
        prepared = importer.prepare(archive, ticket=ticket, **options)
        return importer.apply(prepared, ticket=ticket)
