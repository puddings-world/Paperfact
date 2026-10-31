"""Independent, credential-free research recovery packages; no active rejoin.

An archive contains typed rows, never the source database's pages or SQL schema.
Restoration builds a fresh detached database and archives original protocol records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path
from uuid import UUID, uuid4

from paper_daily import annotation_content
from paper_daily.inbox_recovery import DETACHED_ORIGINALS as INBOX_DETACHED_ORIGINALS
from paper_daily.inbox_recovery import PROTOCOL as INBOX_PROTOCOL
from paper_daily.inbox_recovery import RESEARCH as INBOX_RESEARCH
from paper_daily.store import SCHEMA, _migrate
from paper_daily.sync_blobs import BlobManifest, BlobStore, _no_link
from paper_daily.sync_client import validate_event
from paper_daily.sync_journal import _identifier, canonical_operation
from paper_daily.sync_recovery_fs import publish_directory

FORMAT = "paperfact-recovery"
VERSION = 1
MAX_ROW = 16 * 1024**2
MAX_METADATA = 256 * 1024**2
MAX_TOTAL = 8 * 1024**3
MAX_RECORDS = 500_000
MAX_BLOBS = 10_000
HASH = re.compile(r"[0-9a-f]{64}")
RESEARCH_TABLES = frozenset(
    {
        "papers",
        "authors",
        "paper_authors",
        "refs",
        "queue",
        "reading_log",
        "lists",
        "list_papers",
        "kv",
        "notes",
        "pdf_highlights",
        "pdf_ai_highlights",
        "dives",
        "cites",
        "followups",
        "close_readings",
        "list_surveys",
        "paper_context",
        "pins",
        "resources",
        "chat",
    }
)
OPTIONAL_RESEARCH_TABLES = {"list_reading_goals", "reading_positions"} | INBOX_RESEARCH

PROTOCOL = {
    "research_reading_position_receipts": "request_id request_json result_json",
    **INBOX_PROTOCOL,
    "research_legacy_brief_recovery": "local_id paper_id sha256 size media_type legacy_day",
    "research_legacy_brief_targets": "event_key paper_id descriptor_json",
    "research_recovery_provenance": "record_id body_json",
    "research_local_source_owners": "request_id owner_json sha256 size media_type",
    "research_history_archive": "record_id protocol body_json",
    "research_source_archive": "record_id body_json",
    "research_source_snapshot_recovery": "request_id owner_json sha256 size media_type",
    "paper_annotation_known": "feature paper_id",
    "paperfact_sync_identity": "id workspace device",
    "paperfact_sync_operations": (
        "sequence operation_id fingerprint entity_type entity_id envelope server_revision"
    ),
    "paperfact_sync_cursor": "id sequence",
    "paperfact_sync_inbox": "sequence event outcome",
    "paperfact_sync_heads": "entity_type entity_id revision operation applied_revision",
    "paperfact_sync_conflicts": "operation_id sequence resolved_by",
    "paperfact_sync_graph": "entity_type entity_id metadata",
    "paperfact_sync_graph_projection": "entity_type entity_id source operation active reason",
    "paperfact_sync_graph_receipts": "operation_id event",
    "paperfact_sync_order_projection": "scope revision digest",
    "research_sync_binding": "id workspace origin",
    "research_paper_identity": "sync_id local_id",
    "research_note_identity": "sync_id local_id paper_id created_at",
    "research_list_projection": "sync_id incarnation",
    "research_membership_projection": "sync_id incarnation list_incarnation paper_incarnation",
    "research_paper_projection": "sync_id incarnation",
    "research_content_identity": "feature sync_key local_id paper_id created_at",
    "research_content_projection": (
        "entity_id feature scope_kind scope_id item_key incarnation parent_incarnation source_hash"
    ),
    "research_rich_note_projection": "sync_id incarnation parent_incarnation",
    "research_document_desired": "paper_id target active",
    "research_document_applied": "paper_id target",
    "research_document_intents": "operation_id paper_id target state",
    "research_resolution_intents": "operation_id conflict_sequence request operation",
    "research_action_receipts": "request_id fingerprint result",
    "research_review_drafts": (
        "draft_id origin origin_id owner_json preview_json body request_id revision "
        "updated_at save_order fingerprint"
    ),
    "research_parent_lifecycle": "kind entity_id token active",
    "research_review_receipts": (
        "request_id fingerprint origin origin_id decision result provenance"
    ),
    "research_capture_binding": "id workspace device",
    "research_capture_candidates": "id content",
    "research_generation_requests": "request_id context_json row_json status candidate_id reason",
    "research_chat_requests": (
        "request_id context_json question_json answer_json status candidate_id reason"
    ),
    "research_chat_recovery": (
        "request_id context_json question_json answer_json status candidate_id reason"
    ),
    "research_chat_links": "local_id message_id exchange_id reply_to source_hash",
    "research_chat_review_receipts": (
        "request_id fingerprint record_json target_json answer_json result_json"
    ),
    "research_generation_recovery": "request_id context_json row_json status candidate_id reason",
    "research_compound_requests": (
        "request_id context_json mutations_json status candidate_id reason"
    ),
    "research_compound_recovery": (
        "request_id context_json mutations_json status candidate_id reason"
    ),
    "research_slide_revision_recovery": "request_id manifest",
    "research_legacy_source_recovery": "sha256 size media_type",
    "research_legacy_deck_recovery": "paper_id slot request_id parent_token deck",
    "research_file_desired": "entity_id operation active",
    "research_file_applied": "entity_id operation",
    "research_file_versions": "operation_id entity_id operation",
    "research_file_intents": "operation_id entity_id state",
    "research_file_candidates": "candidate_id entity_id payload observation",
    "research_file_drafts": "candidate_id entity_id deck observation",
    "integration_operations": "id fingerprint result created_at",
}
EXCLUDED_PROTOCOL = {
    "research_capture_dirty",
    "research_capture_bases",
    "research_document_transfers",
    "research_file_paths",
    "research_file_transfers",
}
LEGACY_FOLDERS = (
    "pdf",
    "text",
    "figures",
    "presentations",
    "paper-highlights",
    "reading-links",
    "material-positions",
    "research-questions",
    "briefs",
)


class RecoveryError(ValueError):
    """The package cannot truthfully be called a complete research backup."""


def _json(value):
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise RecoveryError("Duplicate JSON object key")
        out[key] = value
    return out


def _load(raw):
    try:
        return json.loads(
            raw,
            object_pairs_hook=_pairs,
            parse_constant=lambda _v: (_ for _ in ()).throw(RecoveryError("Nonfinite JSON value")),
        )
    except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
        raise RecoveryError("Invalid recovery JSON") from exc


def _path(path):
    value = Path(path).absolute()
    for part in reversed((value, *value.parents)):
        _no_link(part)
    return value


def _research_schema():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        return {
            name: [row[1] for row in conn.execute(f'PRAGMA table_info("{name}")')]
            for name in (
                RESEARCH_TABLES | OPTIONAL_RESEARCH_TABLES
                | frozenset(annotation_content.FEATURES.values())
            )
        }


def _registry():
    result = {name: ("research", columns) for name, columns in _research_schema().items()}
    result.update({name: ("protocol", columns.split()) for name, columns in PROTOCOL.items()})
    return result


def _kv_allowed(key, papers):
    return key in {"lists.order", "lists.legacy_queue"} or any(
        key.startswith(prefix) and key[len(prefix) :] in papers
        for prefix in ("citegraph.", "followups.checked.", "resources:")
    )


def _check_row(row, columns):
    if not isinstance(row, dict) or set(row) != set(columns):
        raise RecoveryError("Unexpected recovery row fields")
    for value in row.values():
        if value is not None and type(value) not in (str, int, float):
            raise RecoveryError("Unsupported SQLite research value")
        if isinstance(value, float) and not math.isfinite(value):
            raise RecoveryError("Nonfinite SQLite research value")


def _add_blob(refs, value):
    manifest = BlobManifest(value["sha256"], value["size"])
    if not 0 < manifest.size <= 150 * 1024**2:
        raise RecoveryError("Invalid recovery blob size")
    old = refs.get(manifest.sha256)
    if old is not None and old != manifest.size:
        raise RecoveryError("One digest has inconsistent sizes")
    refs[manifest.sha256] = manifest.size
    if len(refs) > MAX_BLOBS:
        raise RecoveryError("Recovery blob count exceeds its bound")


def _operation_refs(value, refs):
    operation = _load(canonical_operation(value))
    if operation["action"] != "put":
        return operation
    if operation["entity_type"] == "paper_document":
        _add_blob(refs, operation["payload"])
    elif operation["entity_type"] == "research_file":
        from paper_daily.sync_files import referenced_blobs

        for item in referenced_blobs(operation):
            _add_blob(refs, item)
    return operation


class _Records:
    def __init__(self, workspace, cursor):
        self.workspace, self.cursor = workspace, cursor
        self.refs, self.events, self.receipts, self.pending = {}, {}, {}, []
        self.sequence = 0
        self.paper_map, self.applied_pdf, self.applied_files, self.artifacts = {}, {}, {}, {}
        self.paper_ids = set()
        self.local_paper_ids = set()
        self.hidden_pdf, self.hidden_files = set(), set()
        self.pending_ids = set()
        self.research_sources = set()
        self.annotation_owners = set()
        self.queue_pin_owners = set()
        self.slide_revisions = {}
        self.legacy_sources = {}
        self.archived_sources = {}
        self.legacy_decks = {}
        self.parent_lifecycles = {}
        self.recovered_provenance = []
        self.legacy_briefs, self.legacy_events = {}, {}
        self.reading_positions = {}
        from paper_daily.inbox_recovery import Records as InboxRecords

        self.inbox = InboxRecords()

    def _artifact(self, payload):
        self.artifacts[_json(payload)] = payload
        if payload["source_document_hash"] is not None:
            self.research_sources.add(payload["source_document_hash"])
        self.research_sources.update(
            item["sha256"] for item in payload["input_versions"]["documents"]
        )

    def row(self, name, row):
        if name == "pins" and row["scope"] == "queue":
            from paper_daily.sync_content import _stamp, _text

            _stamp(row["pinned_at"])
            _text(row["paper_id"], 4096, nullable=False, nonempty=True)
            self.queue_pin_owners.add(row["paper_id"])
        if name == "reading_positions":
            from paper_daily.reading_positions import validate_row

            validate_row(row)
            identity = row["paper_id"], row["document_hash"]
            if identity in self.reading_positions:
                raise RecoveryError("Duplicate source-bound reading position")
            self.reading_positions[identity] = row
            self.annotation_owners.add(row["paper_id"])
            self.research_sources.add(row["document_hash"])
        if name == "research_reading_position_receipts":
            from paper_daily.reading_position_ops import validate_receipt

            self.research_sources.update(validate_receipt(row))
            owner = _load(row["request_json"])["owner"]
            if owner["binding"] is not None and owner["binding"]["workspace_id"] != self.workspace:
                raise RecoveryError("Position receipt belongs to another workspace")
        if name in INBOX_RESEARCH | set(INBOX_PROTOCOL):
            self.inbox.add(name, row)
            return
        if name == "queue":
            from paper_daily.legacy_workflow import validate_queue

            validate_queue(row)
        if name == "reading_log":
            from paper_daily.legacy_workflow import validate_event as validate_legacy_event

            validate_legacy_event(row)
            if row["id"] in self.legacy_events:
                raise RecoveryError("Duplicate reading event identity")
            self.legacy_events[row["id"]] = row
        if name == "research_legacy_brief_targets":
            from paper_daily.legacy_briefs import validate_target

            validate_target(row)
            _add_blob(self.refs, _load(row["descriptor_json"]))
        if name == "research_legacy_brief_recovery":
            from paper_daily.legacy_brief_recovery import validate

            validate(row)
            if row["local_id"] in self.legacy_briefs:
                raise RecoveryError("Duplicate reading brief identity")
            self.legacy_briefs[row["local_id"]] = row
            _add_blob(self.refs, row)
        if name == "research_recovery_provenance":
            from paper_daily.recovery_provenance import decode

            decode(row)
            self.recovered_provenance.append(row)
            return
        if name in {"research_document_desired", "research_file_desired"}:
            if row["active"] not in (0, 1):
                raise RecoveryError("Invalid desired-file activity")
            if row["active"] == 0:
                if name == "research_document_desired":
                    self.hidden_pdf.add(row["paper_id"])
                else:
                    self.hidden_files.add(row["entity_id"])
        if name in annotation_content.FEATURES.values():
            self.annotation_owners.add(row["paper_id"])
            feature = next(k for k, v in annotation_content.FEATURES.items() if v == name)
            annotation_content.validate_row(feature, row)
            if row["document_hash"] is not None:
                self.research_sources.add(row["document_hash"])
        if name == "paper_annotation_known" and (
            row["feature"] not in annotation_content.FEATURES
            or not isinstance(row["paper_id"], str)
            or not row["paper_id"]
        ):
            raise RecoveryError("Invalid annotation cache authority marker")
        if name == "paper_annotation_known":
            self.annotation_owners.add(row["paper_id"])
        if name == "papers":
            self.paper_ids.add(row["id"])
        elif name == "research_paper_identity":
            if row["sync_id"] in self.paper_map or row["local_id"] in self.local_paper_ids:
                raise RecoveryError("Ambiguous portable paper identity")
            self.paper_map[row["sync_id"]] = row["local_id"]
            self.local_paper_ids.add(row["local_id"])
        elif name in {
            "paperfact_sync_identity",
            "research_capture_binding",
            "research_sync_binding",
        }:
            if row["workspace"] != self.workspace or row["id"] != 1:
                raise RecoveryError("Research binding differs from archive workspace")
        elif name == "paperfact_sync_inbox":
            event = _load(row["event"])
            validate_event(event, self.workspace)
            if (
                row["sequence"] != self.sequence + 1
                or event["sequence"] != row["sequence"]
                or event["outcome"] != row["outcome"]
            ):
                raise RecoveryError("Recovery inbox is not a contiguous retained history")
            self.sequence += 1
            operation = _operation_refs(event["operation"], self.refs)
            if event["head"]["operation"]:
                _operation_refs(event["head"]["operation"], self.refs)
            identity = operation["operation_id"]
            if identity in self.events:
                raise RecoveryError("Duplicate operation in retained history")
            self.events[identity] = (event["sequence"], _json(event), operation["version"])
        elif name == "paperfact_sync_graph_receipts":
            event = _load(row["event"])
            validate_event(event, self.workspace)
            if row["operation_id"] != event["operation"]["operation_id"]:
                raise RecoveryError("Receipt identity differs from its operation")
            if row["operation_id"] in self.receipts:
                raise RecoveryError("Duplicate graph receipt")
            self.receipts[row["operation_id"]] = _json(event)
        elif name == "paperfact_sync_operations":
            operation = _operation_refs(_load(row["envelope"]), self.refs)
            encoded = canonical_operation(operation)
            if (
                operation["workspace_id"] != self.workspace
                or any(
                    operation[key] != row[key]
                    for key in ("operation_id", "entity_type", "entity_id")
                )
                or hashlib.sha256(encoded.encode()).hexdigest() != row["fingerprint"]
            ):
                raise RecoveryError("Invalid retained outgoing operation")
            if row["operation_id"] in self.pending_ids:
                raise RecoveryError("Duplicate outgoing operation")
            self.pending_ids.add(row["operation_id"])
            self.pending.append((row["operation_id"], row["server_revision"]))
        elif name in (
            "paperfact_sync_heads",
            "paperfact_sync_graph_projection",
            "research_resolution_intents",
            "research_file_desired",
            "research_file_applied",
            "research_file_versions",
        ) and row.get("operation"):
            operation = _operation_refs(_load(row["operation"]), self.refs)
            if operation["workspace_id"] != self.workspace:
                raise RecoveryError("Operation belongs to another workspace")
        elif name in {
            "research_document_desired",
            "research_document_applied",
            "research_document_intents",
        }:
            from paper_daily.sync_documents import _validate_target

            target = _load(row["target"])
            _validate_target(target)
            if target["workspace_id"] != self.workspace:
                raise RecoveryError("Document belongs to another workspace")
            if target["paper_id"] != row["paper_id"]:
                raise RecoveryError("Document paper identity differs from its row")
            _add_blob(self.refs, target)
            self.research_sources.add(target["sha256"])
            if name == "research_document_applied":
                self.applied_pdf[row["paper_id"]] = target
        elif name == "research_review_drafts":
            from paper_daily.research_review_drafts import validate_record

            validate_record(row)
        elif name == "research_parent_lifecycle":
            from paper_daily.research_lifecycle import validate_record

            validate_record(row)
            self.parent_lifecycles[(row["kind"], row["entity_id"])] = row
        elif name == "research_review_receipts":
            from paper_daily.research_review import validate_receipt

            validate_receipt(row)
        elif name == "research_capture_candidates":
            candidate = _load(row["content"])
            if not isinstance(candidate, dict) or set(candidate) != {"observations", "mutations"}:
                raise RecoveryError("Invalid retained capture candidate")
        elif name == "research_file_drafts":
            from paper_daily.presentations import deck_from_dict

            raw, observation = _load(row["deck"]), _load(row["observation"])
            deck_from_dict(raw)
            if (
                not isinstance(observation, dict)
                or observation.get("workspace_id") != self.workspace
            ):
                raise RecoveryError("Draft observation belongs to another workspace")
            if observation.get("entity_id") != row["entity_id"]:
                raise RecoveryError("Draft identity differs from its observation")
            original = observation.get("artifact")
            known = set()
            if original:
                original = _operation_refs(original, self.refs)
                if (
                    original["entity_type"] != "research_file"
                    or original["action"] != "put"
                    or original["workspace_id"] != self.workspace
                    or original["entity_id"] != row["entity_id"]
                ):
                    raise RecoveryError("Invalid draft base artifact")
                payload = original["payload"]
                self._artifact(payload)
                known = {
                    asset["sha256"] + ".png"
                    for asset in payload["assets"]
                    if asset["role"] == "figure"
                }
            for figure in raw["figures"]:
                if figure.get("asset") not in known:
                    raise RecoveryError(
                        "Draft contains unpinned research assets; migrate before backup"
                    )
        elif name == "research_file_candidates":
            from paper_daily.sync_files import validate_payload

            payload = _load(row["payload"])
            validate_payload(payload, entity_id=row["entity_id"])
            for item in [payload["body"], *payload["assets"]]:
                _add_blob(self.refs, item)
            _load(row["observation"])
            self._artifact(payload)
        elif name == "research_legacy_deck_recovery":
            from paper_daily.recovery_decks import validate_slot

            descriptor = validate_slot(row)
            key = (row["paper_id"], row["slot"])
            if key in self.legacy_decks:
                raise RecoveryError("Duplicate recovered current deck slot")
            self.legacy_decks[key] = row
            _add_blob(self.refs, descriptor)
        elif name == "research_legacy_source_recovery":
            from paper_daily.sync_legacy_sources import validate_manifest

            validate_manifest(row)
            if row["sha256"] in self.legacy_sources:
                raise RecoveryError("Duplicate archive-only source manifest")
            self.legacy_sources[row["sha256"]] = row
            _add_blob(self.refs, row)
        elif name == "research_slide_revision_recovery":
            from paper_daily import sync_slide_recovery

            manifest = sync_slide_recovery.validate_manifest(row)
            if manifest["workspace_id"] != self.workspace:
                raise RecoveryError("Slide receipt belongs to another workspace")
            if row["request_id"] in self.slide_revisions:
                raise RecoveryError("Duplicate retained slide revision")
            self.slide_revisions[row["request_id"]] = row
            self.research_sources.update(item["sha256"] for item in manifest["sources"])
            for descriptor in sync_slide_recovery.references(manifest):
                _add_blob(self.refs, descriptor)
        elif name in {"research_chat_requests", "research_chat_recovery"}:
            from paper_daily.research_chat import validate_request_record

            validate_request_record(row)
            context = _load(row["context_json"])
            if context["document"] is not None:
                self.research_sources.add(context["document"]["sha256"])
            binding = context["binding"]
            if binding is not None and binding["workspace_id"] != self.workspace:
                raise RecoveryError("QA receipt belongs to another workspace")
        elif name == "research_chat_review_receipts":
            from paper_daily.research_chat_review import source_hashes, validate_receipt

            validate_receipt(row)
            snapshot = _load(row["target_json"])
            binding = snapshot["binding"]
            if binding is not None and binding["workspace_id"] != self.workspace:
                raise RecoveryError("QA review target belongs to another workspace")
            self.research_sources.update(source_hashes(row))
        elif name == "research_chat_links":
            from paper_daily.research_chat import validate_link

            validate_link(row)
            if row["source_hash"] is not None:
                self.research_sources.add(row["source_hash"])
        elif name in {"research_compound_requests", "research_compound_recovery"}:
            from paper_daily.research_compound import validate_request_record

            validate_request_record(row)
            context = _load(row["context_json"])
            if context["document"] is not None:
                self.research_sources.add(context["document"]["sha256"])
            binding = context["binding"]
            if binding is not None and binding["workspace_id"] != self.workspace:
                raise RecoveryError("Compound receipt belongs to another workspace")
        elif name == "research_history_archive":
            from paper_daily.enrollment_history import validate

            _original, sources = validate(row)
            self.research_sources.update(sources)
        elif name == "research_source_archive":
            from paper_daily.source_provenance import validate

            receipt = validate(row)
            _add_blob(self.refs, receipt)
            self.research_sources.add(receipt["sha256"])
            self.archived_sources[receipt["sha256"]] = {
                key: receipt[key] for key in ("sha256", "size", "media_type")
            }
        elif name == "research_local_source_owners":
            from paper_daily.local_source_owners import validate

            validate(row)
            owner = json.loads(row["owner_json"])
            if owner["binding"] is not None and owner["binding"]["workspace_id"] != self.workspace:
                raise RecoveryError("Imported original belongs to another workspace")
            _add_blob(self.refs, row)
            self.research_sources.add(row["sha256"])
            self.archived_sources[row["sha256"]] = {
                key: row[key] for key in ("sha256", "size", "media_type")
            }
        elif name == "research_source_snapshot_recovery":
            from paper_daily.source_snapshots import validate

            validate(row)
            owner = json.loads(row["owner_json"])
            if owner["binding"] is not None and owner["binding"]["workspace_id"] != self.workspace:
                raise RecoveryError("Source snapshot belongs to another workspace")
            self.research_sources.add(row["sha256"])
        elif name in {"research_generation_requests", "research_generation_recovery"}:
            from paper_daily.research_generation import validate_request_record

            validate_request_record(row)
            context = _load(row["context_json"])
            if context["document"] is not None:
                self.research_sources.add(context["document"]["sha256"])
            binding = context["binding"]
            if binding is not None and binding["workspace_id"] != self.workspace:
                raise RecoveryError("Generation receipt belongs to another workspace")

        if name in {"paperfact_sync_inbox", "paperfact_sync_graph_receipts"}:
            event = _load(row["event"])
            operations = [event["operation"], event["head"]["operation"]]
        elif name == "paperfact_sync_operations":
            operations = [_load(row["envelope"])]
        elif row.get("operation"):
            operations = [_load(row["operation"])]
        else:
            operations = []
        for operation in operations:
            if (
                operation
                and operation["action"] == "put"
                and operation["entity_type"] == "paper_document"
            ):
                self.research_sources.add(operation["payload"]["sha256"])
            if (
                operation
                and operation["entity_type"] == "research_file"
                and operation["action"] == "put"
            ):
                payload = operation["payload"]
                self._artifact(payload)
                if name == "research_file_applied":
                    if row["entity_id"] != operation["entity_id"]:
                        raise RecoveryError("Applied artifact identity differs from its row")
                    self.applied_files[operation["entity_id"]] = operation

    def pdf_aliases(self):
        result = {}
        owners = {}
        # The reader's sanitizer produces ASCII, so Unicode normalization adds
        # nothing here. Case folding also protects Windows/default macOS disks.
        # Include papers with no applied bytes: their legacy lookup must never
        # accidentally resolve another paper's restored PDF.
        for local in self.paper_ids:
            key = (re.sub(r"[^A-Za-z0-9._-]", "_", local) + ".pdf").casefold()
            owners[key] = None if key in owners else local
        for paper, target in self.applied_pdf.items():
            if paper in self.hidden_pdf:
                continue
            local = self.paper_map.get(paper)
            if local is None or local not in self.paper_ids:
                raise RecoveryError("Applied PDF has no exact local paper mapping")
            name = re.sub(r"[^A-Za-z0-9._-]", "_", local) + ".pdf"
            key = name.casefold()
            if len(name) > 240 or owners[key] != local or name in result:
                raise RecoveryError("Ambiguous or oversized detached PDF alias")
            # A filename extension does not make Windows device names regular
            # files. Reject rather than rename and break the reader's DB lookup.
            if re.fullmatch(r"con|prn|aux|nul|com[1-9]|lpt[1-9]", key.split(".", 1)[0]):
                raise RecoveryError("Detached PDF alias is not a portable filename")
            result[name] = (target["sha256"], target["size"])
        return result

    def finish(self):
        self.inbox.finish()
        from paper_daily.legacy_brief_recovery import validate_records

        validate_records(self)
        if self.recovered_provenance:
            from paper_daily.recovery_provenance import validate_groups

            self._recovered_groups = validate_groups(
                self.recovered_provenance, depth=getattr(self, "_provenance_depth", 0)
            )
            for archived in self._recovered_groups:
                for sha256, size in archived.refs.items():
                    _add_blob(self.refs, {"sha256": sha256, "size": size})
        if self.queue_pin_owners - self.paper_ids:
            raise RecoveryError("Queue pin has no archived paper")
        if self.annotation_owners - self.paper_ids:
            raise RecoveryError("Reading annotation has no archived paper")
        for row in self.legacy_decks.values():
            parent = self.parent_lifecycles.get(("paper", row["paper_id"]))
            if (
                row["paper_id"] not in self.paper_ids
                or parent is None
                or not parent["active"]
                or parent["token"] != row["parent_token"]
            ):
                raise RecoveryError(
                    "Recovered current deck differs from its active paper lifecycle"
                )
        if self.research_sources - set(self.refs):
            raise RecoveryError("Research source PDF lacks a retained document manifest")
        self.pdf_aliases()
        if self.sequence != self.cursor:
            raise RecoveryError("Cursor is not backed by complete retained history")
        expected = {key: value[1] for key, value in self.events.items() if value[2] == 2}
        if expected != self.receipts:
            raise RecoveryError("Historical graph receipt closure is incomplete")
        for identity, revision in self.pending:
            if revision is not None:
                if type(revision) is not int or revision < 1:
                    raise RecoveryError("Invalid outgoing acknowledgment")
                if revision <= self.cursor and (
                    identity not in self.events or self.events[identity][0] != revision
                ):
                    raise RecoveryError("Acknowledgment does not match retained history")


def _verified_source_cache(database, receipt):
    """Bounded exact bytes and native identity, never authority from a cache name."""
    from paper_daily import file_change
    from paper_daily.source_snapshots import source_path

    location = source_path(database, receipt)
    expected = receipt["size"]
    digest, size = hashlib.sha256(), 0
    try:
        with location.open("rb") as stream:
            before = file_change.version(location, stream=stream)
            if before[2] != expected:
                raise RecoveryError("Owned source cache changed during backup")
            while block := stream.read(min(1024**2, expected + 1 - size)):
                size += len(block)
                if size > expected:
                    raise RecoveryError("Owned source cache changed during backup")
                digest.update(block)
            if file_change.version(location, stream=stream) != before:
                raise RecoveryError("Owned source cache changed during backup")
        if (size != expected or digest.hexdigest() != receipt["sha256"]
                or file_change.version(location) != before):
            raise RecoveryError("Owned source cache changed during backup")
    except (OSError, ValueError) as error:
        raise RecoveryError("Owned source cache changed during backup") from error
    return location, before


def _legacy_check(root, aliases, represented=None, *, verified_sources=None):
    """Do not label a partial SQL-only archive as a complete existing workspace."""
    if root is None:
        return
    root = _path(root)
    for name in LEGACY_FOLDERS:
        folder = root / name
        if not folder.exists():
            continue
        _path(folder)
        for path in folder.rglob("*"):
            _path(path)
            if path.is_dir():
                continue
            if not path.is_file():
                raise RecoveryError("Unexpected legacy research entry")
            if verified_sources and path in verified_sources:
                from paper_daily import file_change

                if file_change.version(path) != verified_sources[path]:
                    raise RecoveryError("Owned source cache changed during backup")
                continue
            if represented and path in represented and _fingerprint(path) == represented[path]:
                continue
            if (
                name == "pdf"
                and path.parent == folder
                and path.name in aliases
                and _fingerprint(path) == aliases[path.name]
            ):
                continue
            raise RecoveryError("Legacy research files require complete migration before backup")


def _fingerprint(path):
    digest, size = hashlib.sha256(), 0
    with _path(path).open("rb") as stream:
        while chunk := stream.read(1024**2):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def create(database, output, *, blob_store=None, legacy_root=None, pdf_roots=None):
    """Create a complete archive or leave the source and requested output untouched."""
    source, output = _path(database), _path(output)
    if not source.is_file() or output.exists():
        raise RecoveryError("Select an existing database and a new backup filename")
    if output.parent == source.parent and output.name in {
        source.name + suffix for suffix in ("", "-wal", "-shm", "-journal")
    }:
        raise RecoveryError("Backup cannot replace a database sidecar")
    if blob_store is not None and not isinstance(blob_store, BlobStore):
        raise RecoveryError("Expected an explicitly owned BlobStore")
    if blob_store is not None and output.is_relative_to(blob_store.root):
        raise RecoveryError("Backup cannot be written inside the owned blob store")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="paperfact-recovery-") as temporary:
        snapshot = Path(temporary) / "snapshot.sqlite"
        with (
            closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as incoming,
            closing(sqlite3.connect(snapshot)) as saved,
        ):
            incoming.backup(saved)
        with closing(sqlite3.connect(snapshot)) as conn:
            conn.row_factory = sqlite3.Row
            registry = _registry()
            present = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "recovery_records" in present:
                raise RecoveryError(
                    "Keep the original archive: detached re-export needs reviewed recovery"
                )
            if not present >= RESEARCH_TABLES:
                raise RecoveryError("An initialized research database is required")
            unknown = (
                {n for n in present if n.startswith(("research_", "paperfact_sync_"))}
                - set(registry)
                - EXCLUDED_PROTOCOL
            )
            if unknown:
                raise RecoveryError("Unsupported research schema must be enrolled before backup")
            for table in ("research_capture_dirty", "research_capture_bases"):
                if table in present and conn.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone():
                    raise RecoveryError("Capture transaction has uncommitted research intents")
            binding = (
                conn.execute(
                    "SELECT workspace,device FROM paperfact_sync_identity WHERE id=1"
                ).fetchone()
                if "paperfact_sync_identity" in present
                else None
            )
            workspace, device = tuple(binding) if binding else (None, None)
            cursor = (
                conn.execute("SELECT sequence FROM paperfact_sync_cursor WHERE id=1").fetchone()[0]
                if "paperfact_sync_cursor" in present
                else 0
            )
            from paper_daily.legacy_brief_recovery import collect as collect_briefs

            brief_rows, brief_objects, brief_aliases = collect_briefs(
                conn, source, temporary, legacy_root=legacy_root, blob_store=blob_store
            )
            records = _Records(workspace, cursor)
            papers = {r[0] for r in conn.execute("SELECT id FROM papers")}
            table_files, metadata_bytes, count = [], 0, 0
            for name in sorted(present & set(registry)):
                section, columns = registry[name]
                actual = [r[1] for r in conn.execute(f'PRAGMA table_info("{name}")')]
                if set(actual) != set(columns):
                    raise RecoveryError("Recovery table schema differs from its explicit registry")
                filename = Path(temporary) / (name + ".jsonl")
                rows = 0
                primary = [
                    r[1]
                    for r in sorted(
                        conn.execute(f'PRAGMA table_info("{name}")'), key=lambda r: r[5]
                    )
                    if r[5]
                ]
                order = ",".join('"' + c + '"' for c in primary)
                with filename.open("wb") as stream:
                    for raw in conn.execute(
                        f'SELECT * FROM "{name}"' + (f" ORDER BY {order}" if order else "")
                    ):
                        row = dict(raw)
                        if name == "kv" and not _kv_allowed(row["key"], papers):
                            continue
                        _check_row(row, columns)
                        records.row(name, row)
                        encoded = (_json(row) + "\n").encode()
                        metadata_bytes += len(encoded)
                        count += 1
                        if (
                            len(encoded) > MAX_ROW
                            or metadata_bytes > MAX_METADATA
                            or count > MAX_RECORDS
                        ):
                            raise RecoveryError("Recovery metadata exceeds its bounded format")
                        stream.write(encoded)
                        rows += 1
                digest, size = _fingerprint(filename)
                table_files.append(
                    dict(
                        name=name,
                        section=section,
                        columns=columns,
                        count=rows,
                        sha256=digest,
                        size=size,
                    )
                )
            from paper_daily import (
                research_chat,
                research_compound,
                research_generation,
                sync_slide_recovery,
            )
            from paper_daily.sync_legacy_sources import LegacySources

            if pdf_roots is not None and not isinstance(pdf_roots, (list, tuple)):
                raise RecoveryError("Explicit PDF roots must be a list of trusted directories")
            selected_roots = [source.parent / "pdf"]
            if legacy_root is not None:
                selected_roots.append(_path(legacy_root) / "pdf")
            selected_roots.extend(pdf_roots or [])
            legacy_sources = LegacySources(selected_roots, temporary)
            legacy_decks = []
            slide_rows, slide_objects, slide_aliases = sync_slide_recovery.collect(
                source,
                [source.parent] + ([legacy_root] if legacy_root is not None else []),
                temporary,
                records.refs,
                blob_store,
                source_resolver=legacy_sources,
                legacy_slots=legacy_decks,
            )

            def adopted_sources():
                for digest in sorted(records.research_sources):
                    if digest in source_caches:
                        # This exact location was resolved from a closed owned
                        # receipt and independently hashed/version-checked. Feed
                        # it through maintained immutable PDF staging, without
                        # broadening trusted roots or following context paths.
                        legacy_sources._scan()
                        legacy_sources._index.setdefault(digest, []).insert(
                            0, source_caches[digest]
                        )
                    if digest in records.refs and blob_store is not None:
                        try:
                            owned = blob_store.verified_path(
                                BlobManifest(digest, records.refs[digest])
                            )
                        except (OSError, ValueError):
                            owned = None
                        if owned is not None:
                            continue
                    found = legacy_sources.find(digest, records.refs.get(digest))
                    if found is None and digest not in records.refs:
                        raise RecoveryError(
                            "Original source PDF is missing or changed in the trusted PDF roots"
                        )
                return list(legacy_sources.manifests.values())

            from paper_daily.source_snapshots import list_owned

            source_aliases, source_caches, source_cache_bytes = {}, {}, 0
            for name, loader in (
                ("research_source_snapshot_recovery", list_owned),
                ("research_generation_recovery", research_generation.list_recovery_requests),
                ("research_chat_recovery", research_chat.list_recovery_requests),
                ("research_compound_recovery", research_compound.list_recovery_requests),
                ("research_slide_revision_recovery", lambda _source: slide_rows),
                ("research_legacy_deck_recovery", lambda _source: legacy_decks),
                ("research_legacy_brief_recovery", lambda _source: brief_rows),
                ("research_legacy_source_recovery", lambda _source: adopted_sources()),
            ):
                sidecars = loader(source)
                if name == "research_source_snapshot_recovery":
                    for receipt in sidecars:
                        location, proof = _verified_source_cache(source, receipt)
                        source_aliases[location] = proof
                        previous = source_caches.get(receipt["sha256"])
                        if previous is None:
                            source_cache_bytes += receipt["size"]
                        elif previous[1] != receipt["size"]:
                            raise RecoveryError("One original source hash has inconsistent sizes")
                        source_caches[receipt["sha256"]] = (location, receipt["size"])
                        if source_cache_bytes > MAX_TOTAL:
                            raise RecoveryError(
                                "Owned original sources exceed the backup byte budget"
                            )
                if sidecars:
                    if name in present:
                        raise RecoveryError("Reserved recovery archive table already exists")
                    filename = Path(temporary) / (name + ".jsonl")
                    columns = registry[name][1]
                    with filename.open("wb") as stream:
                        for row in sidecars:
                            _check_row(row, columns)
                            records.row(name, row)
                            encoded = (_json(row) + "\n").encode()
                            metadata_bytes += len(encoded)
                            count += 1
                            if (
                                len(encoded) > MAX_ROW
                                or metadata_bytes > MAX_METADATA
                                or count > MAX_RECORDS
                            ):
                                raise RecoveryError("Recovery metadata exceeds its bounded format")
                            stream.write(encoded)
                    digest, size = _fingerprint(filename)
                    table_files.append(
                        dict(
                            name=name,
                            section="protocol",
                            columns=columns,
                            count=len(sidecars),
                            sha256=digest,
                            size=size,
                        )
                    )
            records.finish()
            represented = {**slide_aliases, **legacy_sources.aliases, **brief_aliases}
            _legacy_check(
                source.parent, records.pdf_aliases(), represented, verified_sources=source_aliases
            )
            if legacy_root is not None and _path(legacy_root) != source.parent:
                _legacy_check(
                    legacy_root, records.pdf_aliases(), represented, verified_sources=source_aliases
                )
            objects = []
            for digest, size in sorted(records.refs.items()):
                if digest in brief_objects:
                    path = brief_objects[digest]
                elif digest in slide_objects:
                    path = slide_objects[digest]
                elif digest in legacy_sources.objects:
                    path = legacy_sources.objects[digest]
                elif blob_store is not None:
                    path = blob_store.verified_path(BlobManifest(digest, size))
                else:
                    raise RecoveryError(
                        "Referenced research bytes require an explicit owned BlobStore"
                    )
                if path is None:
                    raise RecoveryError("Referenced historical or pending bytes are unavailable")
                objects.append((dict(sha256=digest, size=size), path))
            if metadata_bytes + sum(item[0]["size"] for item in objects) > MAX_TOTAL:
                raise RecoveryError("Recovery package exceeds its total byte bound")
            position_paths = {item[0]["sha256"]: item[1] for item in objects}

            def read_position_source(descriptor):
                with position_paths[descriptor["sha256"]].open("rb") as stream:
                    return stream.read(descriptor["size"] + 1)

            _validate_positions(records, read_position_source)
            manifest = dict(
                format=FORMAT,
                version=VERSION,
                backup_id=str(uuid4()),
                workspace_id=workspace,
                origin_device_id=device,
                cursor=cursor,
                tables=table_files,
                blobs=[item[0] for item in objects],
            )
        with tempfile.NamedTemporaryFile(
            prefix=".paperfact-recovery-", suffix=".zip", dir=output.parent, delete=False
        ) as staged:
            stage = Path(staged.name)
        try:
            with zipfile.ZipFile(stage, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", _json(manifest))
                for table in table_files:
                    archive.write(
                        Path(temporary) / (table["name"] + ".jsonl"),
                        "tables/" + table["name"] + ".jsonl",
                    )
                for item, path in objects:
                    archive.write(path, "objects/" + item["sha256"])
            inspect(stage)
            from paper_daily import file_change

            for location, proof in source_aliases.items():
                try:
                    if file_change.version(location) != proof:
                        raise RecoveryError("Owned source cache changed during backup")
                except (OSError, ValueError) as error:
                    raise RecoveryError("Owned source cache changed during backup") from error
            # Hard-link publication is exclusive, unlike replace() after an exists check.
            os.link(stage, output)
        finally:
            stage.unlink(missing_ok=True)
    return manifest


def _manifest(archive):
    names = archive.namelist()
    if (
        len(names) != len(set(names))
        or len(names) > MAX_BLOBS + 100
        or "manifest.json" not in names
    ):
        raise RecoveryError("Invalid archive member inventory")
    for info in archive.infolist():
        if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
            raise RecoveryError(
                "Recovery archives cannot contain links, directories or encrypted entries"
            )
    if archive.getinfo("manifest.json").file_size > 4 * 1024**2:
        raise RecoveryError("Recovery manifest is too large")
    value = _load(archive.read("manifest.json"))
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "format",
            "version",
            "backup_id",
            "workspace_id",
            "origin_device_id",
            "cursor",
            "tables",
            "blobs",
        }
        or value["format"] != FORMAT
        or type(value["version"]) is not int
        or value["version"] != VERSION
    ):
        raise RecoveryError("Unsupported recovery format")
    try:
        if str(UUID(value["backup_id"])) != value["backup_id"]:
            raise ValueError("Noncanonical backup ID")
        if (value["workspace_id"] is None) != (value["origin_device_id"] is None):
            raise ValueError("Incomplete backup identity")
        if value["workspace_id"] is not None:
            _identifier(value["workspace_id"])
            _identifier(value["origin_device_id"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise RecoveryError("Invalid backup identity") from exc
    if type(value["cursor"]) is not int or value["cursor"] < 0:
        raise RecoveryError("Invalid captured cursor")
    if not isinstance(value["tables"], list) or not isinstance(value["blobs"], list):
        raise RecoveryError("Invalid recovery inventory")
    registry, expected, tables, blobs = _registry(), {"manifest.json"}, set(), set()
    metadata, total, count = 0, 0, 0
    for table in value["tables"]:
        if not isinstance(table, dict) or set(table) != {
            "name",
            "section",
            "columns",
            "count",
            "sha256",
            "size",
        }:
            raise RecoveryError("Invalid recovery table manifest")
        name = table["name"]
        if (
            not isinstance(name, str)
            or name not in registry
            or name in tables
            or (table["section"], table["columns"]) != registry[name]
        ):
            raise RecoveryError("Unregistered or duplicate recovery table")
        if type(table["count"]) is not int or table["count"] < 0:
            raise RecoveryError("Invalid recovery row count")
        _entry(table)
        metadata += table["size"]
        count += table["count"]
        tables.add(name)
        expected.add("tables/" + name + ".jsonl")
    if not tables >= RESEARCH_TABLES:
        raise RecoveryError("Recovery archive omits research tables")
    for item in value["blobs"]:
        if not isinstance(item, dict) or set(item) != {"sha256", "size"}:
            raise RecoveryError("Invalid blob manifest")
        _entry(item)
        if item["sha256"] in blobs or not 0 < item["size"] <= 150 * 1024**2:
            raise RecoveryError("Invalid or duplicate blob")
        blobs.add(item["sha256"])
        total += item["size"]
        expected.add("objects/" + item["sha256"])
    if (
        set(names) != expected
        or len(blobs) > MAX_BLOBS
        or metadata > MAX_METADATA
        or count > MAX_RECORDS
        or total + metadata > MAX_TOTAL
    ):
        raise RecoveryError("Recovery inventory exceeds its bounds or has extra members")
    return value


def _entry(item):
    if (
        not isinstance(item["sha256"], str)
        or not HASH.fullmatch(item["sha256"])
        or type(item["size"]) is not int
        or item["size"] < 0
    ):
        raise RecoveryError("Invalid entry hash/size")


def _stream(archive, name, expected, destination=None):
    if archive.getinfo(name).file_size != expected["size"]:
        raise RecoveryError("Archive size differs from its manifest")
    digest, size = hashlib.sha256(), 0
    with archive.open(name) as source:
        while chunk := source.read(1024**2):
            size += len(chunk)
            if size > expected["size"]:
                raise RecoveryError("Archive entry exceeds its declared size")
            digest.update(chunk)
            if destination:
                destination.write(chunk)
    if size != expected["size"] or digest.hexdigest() != expected["sha256"]:
        raise RecoveryError("Archive integrity check failed")


def _table_rows(archive, table):
    digest, size = hashlib.sha256(), 0
    with archive.open("tables/" + table["name"] + ".jsonl") as stream:
        count = 0
        while line := stream.readline(MAX_ROW + 1):
            if len(line) > MAX_ROW or not line.endswith(b"\n"):
                raise RecoveryError("Invalid or oversized recovery row")
            size += len(line)
            digest.update(line)
            if size > table["size"]:
                raise RecoveryError("Table bytes exceed declared size")
            row = _load(line)
            _check_row(row, table["columns"])
            count += 1
            if count > table["count"]:
                raise RecoveryError("Recovery row count differs from its manifest")
            yield row
        if size != table["size"] or digest.hexdigest() != table["sha256"]:
            raise RecoveryError("Archive integrity check failed")
        if count != table["count"]:
            raise RecoveryError("Recovery row count differs from its manifest")


def inspect(package):
    """Verify the complete archive without touching an active workspace."""
    with zipfile.ZipFile(_path(package)) as archive:
        manifest = _manifest(archive)
        records = _Records(manifest["workspace_id"], manifest["cursor"])
        for table in manifest["tables"]:
            _stream(archive, "tables/" + table["name"] + ".jsonl", table)
            for row in _table_rows(archive, table):
                records.row(table["name"], row)
        records.finish()
        declared = {item["sha256"]: item["size"] for item in manifest["blobs"]}
        if declared != records.refs:
            raise RecoveryError("Archive does not contain its exact retained blob closure")
        for item in manifest["blobs"]:
            _stream(archive, "objects/" + item["sha256"], item)
        _validate_closures(records, lambda row: archive.read("objects/" + row["sha256"]))
        return manifest


def _validate_positions(records, read):
    from paper_daily.reading_positions import verify_page

    for row in records.reading_positions.values():
        descriptor = {"sha256": row["document_hash"], "size": records.refs[row["document_hash"]]}
        data = read(descriptor)
        if len(data) != descriptor["size"]:
            raise RecoveryError("Reading position original changed during verification")
        verify_page(row, data)


def _validate_closures(records, read):
    """Validate independent original archive groups without merging their identities."""
    from paper_daily.legacy_briefs import validate_markdown
    from paper_daily.recovery_decks import legacy_snapshot
    from paper_daily.sync_files import validate_closure
    from paper_daily.sync_legacy_sources import validate_pdf
    from paper_daily.sync_slide_recovery import read_retained

    _validate_positions(records, read)
    for row in records.legacy_briefs.values():
        validate_markdown(read(row))
    for payload in records.artifacts.values():
        validate_closure(payload, read)
    for row in records.slide_revisions.values():
        read_retained(row, read)
    for row in records.legacy_decks.values():
        legacy_snapshot(row, records.slide_revisions, read)
    for row in [*records.legacy_sources.values(), *records.archived_sources.values()]:
        validate_pdf(read(row))
    for group in getattr(records, "_recovered_groups", ()):
        _validate_closures(group, read)


def _detached_files(stage, records):
    """Derive local reader files exclusively from validated applied manifests."""
    import shutil

    from paper_daily.sync_files import canonical_json, validate_closure

    for name, (digest, _size) in records.pdf_aliases().items():
        folder = stage / "pdf"
        folder.mkdir(exist_ok=True)
        shutil.copyfile(stage / "objects" / digest, folder / name)
    from paper_daily.recovery_decks import restore_legacy

    restore_legacy(stage, records.legacy_decks, records.slide_revisions)
    from paper_daily.legacy_brief_recovery import restore as restore_briefs

    restore_briefs(stage, records)
    for operation in records.applied_files.values():
        if operation["entity_id"] in records.hidden_files:
            continue
        payload = operation["payload"]
        local = records.paper_map.get(payload["paper_id"])
        if local is None or local not in records.paper_ids:
            raise RecoveryError("Applied deck has no exact local paper mapping")
        body = validate_closure(
            payload, lambda row: (stage / "objects" / row["sha256"]).read_bytes()
        )
        if payload["feature"] == "original_source":
            from paper_daily.claim_content import hashed

            folder = stage / "pdf" / ".claim-evidence" / hashed(["claim-source-owner", local])[:24]
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / (body["document_hash"] + ".pdf")
            shutil.copyfile(stage / "objects" / body["document_hash"], target)
            continue
        if payload["feature"] == "legacy_brief":
            continue  # Current log-owned text is separately projected from its typed closure.
        raw = body["deck"]
        raw["paper_id"] = local
        folder = stage / "presentations" / hashlib.sha256(local.encode()).hexdigest()[:24]
        folder.mkdir(parents=True, exist_ok=True)
        descriptors = {row["id"]: row for row in payload["assets"]}
        for figure in raw["figures"]:
            asset = descriptors[figure.pop("asset_id")]
            figure["asset"] = asset["sha256"] + ".png"
        for asset in payload["assets"]:
            source = stage / "objects" / asset["sha256"]
            if asset["role"] == "figure":
                target = folder / "assets" / (asset["sha256"] + ".png")
            elif asset["role"] == "evidence":
                evidence = _load(source.read_bytes())
                if evidence.get("source_hash") != raw.get("source_hash"):
                    raise RecoveryError("Evidence identity differs from its applied deck")
                if not isinstance(evidence["source_hash"], str) or not HASH.fullmatch(
                    evidence["source_hash"]
                ):
                    from paper_daily.sync_slide_recovery import recovered_evidence_target

                    target = recovered_evidence_target(folder, raw, asset)
                else:
                    target = folder / "evidence" / (evidence["source_hash"] + ".json")
            else:
                raise RecoveryError("Unsupported detached asset role")
            target.parent.mkdir(exist_ok=True)
            if target.exists() and target.read_bytes() != source.read_bytes():
                raise RecoveryError("Conflicting detached asset identity")
            shutil.copyfile(source, target)
        destination = folder / (payload["slot"] + ".json")
        if destination.exists():
            raise RecoveryError("Duplicate detached deck slot")
        destination.write_bytes(canonical_json(raw))


def restore_detached(package, destination):
    """Rebuild research and archived protocol evidence in a fresh isolated directory."""
    package, destination = _path(package), _path(destination)
    if destination.exists():
        raise RecoveryError("Restore requires a new destination directory")
    manifest = inspect(package)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".paperfact-restore-", dir=destination.parent
    ) as temporary:
        stage = Path(temporary) / "workspace"
        stage.mkdir()
        # Archive protocol state; never install a previous device's live journal/binding.
        with (
            closing(sqlite3.connect(stage / "papers.db")) as conn,
            zipfile.ZipFile(package) as archive,
        ):
            conn.executescript(SCHEMA)
            _migrate(conn)
            records = _Records(manifest["workspace_id"], manifest["cursor"])
            if any(item["name"] == "research_source_archive" for item in manifest["tables"]):
                from paper_daily.source_provenance import SCHEMA as archive_schema

                # Compatibility shape only: actual provenance stays in recovery_records.
                conn.execute(archive_schema)
            conn.execute(
                "CREATE TABLE recovery_records(table_name TEXT NOT NULL,"
                "row_number INTEGER NOT NULL,"
                "data TEXT NOT NULL,PRIMARY KEY(table_name,row_number))"
            )
            conn.execute(
                "CREATE TABLE recovery_identity(id INTEGER PRIMARY KEY CHECK(id=1),"
                "backup_id TEXT NOT NULL,"
                "origin_workspace TEXT,origin_device TEXT,recovery_device TEXT NOT NULL)"
            )
            recovery_device = str(uuid4())
            conn.execute(
                "INSERT INTO recovery_identity VALUES(1,?,?,?,?)",
                (
                    manifest["backup_id"],
                    manifest["workspace_id"],
                    manifest["origin_device_id"],
                    recovery_device,
                ),
            )
            conn.execute(
                "CREATE TABLE research_chat_links(local_id INTEGER PRIMARY "
                "KEY,message_id TEXT NOT NULL UNIQUE,exchange_id TEXT NOT "
                "NULL,reply_to TEXT,source_hash TEXT)"
            )
            for table in manifest["tables"]:
                for index, row in enumerate(_table_rows(archive, table)):
                    records.row(table["name"], row)
                    if table["section"] == "research" or table["name"] in {
                        "research_chat_links", "paper_annotation_known"
                    }:
                        columns = ",".join('"' + name + '"' for name in table["columns"])
                        placeholders = ",".join("?" for _ in table["columns"])
                        verb = ("INSERT OR IGNORE" if table["name"] == "paper_annotation_known"
                                else "INSERT")
                        conn.execute(
                            f'{verb} INTO "{table["name"]}" ({columns}) VALUES({placeholders})',
                            [row[name] for name in table["columns"]],
                        )
                    else:
                        conn.execute(
                            "INSERT INTO recovery_records VALUES(?,?,?)",
                            (table["name"], index, _json(row)),
                        )
                    if table["name"] in INBOX_DETACHED_ORIGINALS:
                        # Preserve source rows before fresh receiver versions are minted.
                        conn.execute(
                            "INSERT INTO recovery_records VALUES(?,?,?)",
                            (table["name"], index, _json(row)),
                        )
            records.finish()
            from paper_daily.inbox_recovery import fresh_receiver_in

            fresh_receiver_in(conn, recovery_device=recovery_device)
            objects = stage / "objects"
            objects.mkdir()
            for item in manifest["blobs"]:
                with (objects / item["sha256"]).open("xb") as output:
                    _stream(archive, "objects/" + item["sha256"], item, output)
            from paper_daily.sync_slide_recovery import read_retained

            for row in records.slide_revisions.values():
                read_retained(row, lambda item: (objects / item["sha256"]).read_bytes())
            from paper_daily.sync_legacy_sources import validate_pdf

            for row in [*records.legacy_sources.values(), *records.archived_sources.values()]:
                validate_pdf(objects / row["sha256"])
            conn.commit()
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RecoveryError("Restored research database failed integrity checking")
        _detached_files(stage, records)
        (stage / "recovery.json").write_text(_json(manifest), encoding="utf-8")
        if destination.exists():
            raise RecoveryError("Restore destination appeared during staging")
        publish_directory(stage, destination)
    return {"destination": str(destination), "backup_id": manifest["backup_id"], "detached": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("create")
    backup.add_argument("database", type=Path)
    backup.add_argument("output", type=Path)
    backup.add_argument("--blob-root", type=Path)
    backup.add_argument("--legacy-root", type=Path)
    backup.add_argument("--pdf-root", type=Path, action="append", dest="pdf_roots")
    check = commands.add_parser("inspect")
    check.add_argument("package", type=Path)
    restore = commands.add_parser("restore-detached")
    restore.add_argument("package", type=Path)
    restore.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            result = create(
                args.database,
                args.output,
                blob_store=BlobStore(args.blob_root) if args.blob_root else None,
                legacy_root=args.legacy_root,
                pdf_roots=args.pdf_roots,
            )
        elif args.command == "inspect":
            result = inspect(args.package)
        else:
            result = restore_detached(args.package, args.destination)
        print(_json(result))
    except (ValueError, OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Recovery failed: {exc}\n")


if __name__ == "__main__":
    main()
