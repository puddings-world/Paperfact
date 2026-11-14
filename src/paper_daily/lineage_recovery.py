"""Typed complete local Lineage recovery; archived records never grant replay rights."""

from __future__ import annotations

import json

from paper_daily import (
    claim_content,
    lineage_candidates,
    lineage_projection,
    lineage_sets,
    source_snapshots,
)
from paper_daily import research_generation as generation

PUBLICATIONS = "research_lineage_publications"
COLUMNS = "request_id candidate_id row_json sources_json"


def publication(row):
    """Validate a closed archive receipt; cross-record ownership is checked at finish."""
    claim_content.closed(row, COLUMNS.split())
    lineage_sets.uuid(row["request_id"])
    claim_content.digest(row["candidate_id"])
    saved = lineage_candidates._read(row["row_json"])
    lineage_sets.validate_row(saved)
    originals = lineage_candidates._read(row["sources_json"])
    if not isinstance(originals, list) or len(originals) > 4:
        raise ValueError("Lineage publication requires its bounded selected originals")
    for original in originals:
        source_snapshots.validate(original)
        owner = json.loads(original["owner_json"])
        if (
            owner["format"] != source_snapshots.LINEAGE_FORMAT
            or owner["generation_request_id"] != row["request_id"]
        ):
            raise ValueError("Lineage publication original belongs to another request")
    return saved, originals


def linked_publication(receipt, candidate):
    """Join archive data only; current native ownership requires separate checks."""
    row, originals = publication(receipt)
    lineage_candidates.validate(candidate)
    context = lineage_candidates._read(candidate["context_json"])
    if (
        candidate["request_id"] != receipt["request_id"]
        or candidate["candidate_id"] != receipt["candidate_id"]
        or candidate["row_json"] != receipt["row_json"]
        or context["inputs"]["originals"] != originals
        or "publication_base" not in context
    ):
        raise ValueError("Lineage publication differs from its retained request")
    if context["binding"] is not None:
        raise ValueError("Bound Lineage publication requires compound sync support")
    return row, originals, context


class Records:
    def __init__(self):
        self.rows, self.publications, self.candidates, self.sources = {}, {}, {}, {}
        self.actions = {}
        self.action_bytes = 0
        self.bound = BoundRecords()
        from paper_daily.lineage_import_recovery import ImportRecords

        self.imported = ImportRecords()

    @staticmethod
    def _add(target, key, row):
        if key in target and target[key] != row:
            raise ValueError("Conflicting Lineage recovery identity")
        target[key] = row

    def add(self, name, row):
        self.bound.add(name, row)
        self.imported.add(name, row)
        if name == "research_lineage_actions":
            from paper_daily import lineage_lifecycle as lifecycle

            body = lifecycle.validate_record(row)
            self.action_bytes += len(row["body_json"].encode())
            if (
                row["request_id"] in self.actions
                or len(self.actions) >= lifecycle.MAX_ACTIONS
                or self.action_bytes > lifecycle.MAX_HISTORY
            ):
                raise ValueError("Duplicate or oversized Lineage lifecycle recovery history")
            self.actions[row["request_id"]] = body
        elif name == lineage_sets.TABLE:
            lineage_sets.validate_row(row)
            key = row["paper_id"], row["corpus_key"]
            if key in self.rows:
                raise ValueError("Duplicate canonical Lineage recovery row")
            self.rows[key] = row
        elif name == PUBLICATIONS:
            publication(row)
            self._add(self.publications, row["request_id"], row)
        elif name in {"research_generation_requests", "research_generation_recovery"}:
            context = lineage_candidates._read(row["context_json"])
            if isinstance(context, dict) and context.get("format") == lineage_candidates.FORMAT:
                lineage_candidates.validate(row)
                self._add(self.candidates, row["request_id"], row)
        elif name == "research_local_source_owners":
            source_snapshots.validate(row)
            if json.loads(row["owner_json"])["format"] == source_snapshots.LINEAGE_FORMAT:
                self._add(self.sources, row["request_id"], row)

    def finish(self, records):
        represented = set()
        for receipt in self.publications.values():
            candidate = self.candidates.get(receipt["request_id"])
            if candidate is None:
                raise ValueError("Lineage publication lacks its exact retained candidate")
            row, originals, _context = linked_publication(receipt, candidate)
            body = lineage_sets.decode(row["body_json"])
            if any(binding["paper_id"] not in records.paper_ids for binding in body["bindings"]):
                raise ValueError("Lineage publication lacks an actual selected paper")
            for original in originals:
                if self.sources.get(original["request_id"]) != original:
                    raise ValueError("Lineage publication lacks its exact original association")
            represented.add(generation._json(row))
        represented.update(self.bound.finish(records, self.rows))
        represented.update(self.imported.finish(records))
        self._actions(records)
        for row in self.rows.values():
            if generation._json(row) not in represented:
                raise ValueError("Canonical Lineage lacks a complete publication receipt")

    def _actions(self, records):
        for body in self.actions.values():
            origin = body["origin"]
            row = json.loads(body["row_json"])
            if origin["kind"] == "generated":
                publication = self.publications.get(origin["id"])
                if publication is None or publication["row_json"] != body["row_json"]:
                    raise ValueError("Lineage lifecycle lacks its exact generation provenance")
            elif origin["kind"] == "import":
                imported = self.imported.actions.get(origin["id"])
                if imported is None or not any(
                    item["row_json"] == body["row_json"] for item in imported["records"]
                ):
                    raise ValueError("Lineage lifecycle lacks its exact import provenance")
            else:
                source = self.bound.history.get(origin["id"])
                action = self.bound.history.get(body["operation_id"])
                owner = json.loads(body["owner_json"])
                if (
                    source is None
                    or source["action"] != "put"
                    or action is None
                    or self.bound._local_row(source, records) != row
                    or action["entity_id"] != source["entity_id"]
                    or action["workspace_id"] != owner["binding"]["workspace_id"]
                    or action["device_id"] != owner["binding"]["device_id"]
                    or action["action"] != ("delete" if body["action"] == "retire" else "put")
                ):
                    raise ValueError("Lineage lifecycle lacks its exact native action provenance")
                if body["action"] == "restore" and (
                    self.bound._local_row(action, records) != row
                    or action["source_dependencies"] != source["source_dependencies"]
                ):
                    raise ValueError("Lineage lifecycle restore changed its historical sources")


class BoundRecords:
    """Archive closure only: retained operations are not authenticated replay grants."""

    def __init__(self):
        self.markers, self.history, self.originals = {}, {}, {}
        self.papers, self.desired, self.states, self.heads = {}, {}, {}, {}
        self.queued = []
        self._snapshot_graph = None

    @staticmethod
    def _unique(target, key, value):
        if key in target:
            raise ValueError("Duplicate bound Lineage recovery identity")
        target[key] = value

    def add(self, name, row):
        self._snapshot_graph = None
        if name == lineage_projection.TABLE:
            operation = lineage_projection.validate_record(row)
            self._unique(self.markers, row["entity_id"], (row, operation))
        elif name == lineage_projection.HISTORY:
            operation = lineage_projection.validate_history(row)
            self._unique(self.history, operation["operation_id"], operation)
        elif name == "research_paper_projection":
            lineage_sets.uuid(row["sync_id"])
            self._unique(self.papers, row["sync_id"], row["incarnation"])
        elif name == "paperfact_sync_graph":
            from paper_daily.lineage_address import metadata

            state = json.loads(row["metadata"])
            metadata(row["entity_type"], row["entity_id"], state)
            self._unique(self.states, (row["entity_type"], row["entity_id"]), state)
        elif name in {"paperfact_sync_operations", "paperfact_sync_heads", "research_file_desired"}:
            from paper_daily.sync_journal import canonical_operation

            raw = row.get("envelope", row.get("operation"))
            operation = json.loads(canonical_operation(json.loads(raw))) if raw else None
            if operation is not None and (
                operation["entity_id"] != row["entity_id"]
                or row.get("entity_type", operation["entity_type"]) != operation["entity_type"]
            ):
                raise ValueError("Retained Lineage input differs from its graph identity")
            if name == "research_file_desired":
                if type(row["active"]) is not int or row["active"] not in (0, 1):
                    raise ValueError("Invalid retained Lineage input activity")
                self._unique(self.desired, row["entity_id"], (row["active"] == 1, operation))
            elif name == "paperfact_sync_heads":
                self._unique(self.heads, (row["entity_type"], row["entity_id"]), operation)
            else:
                if operation is None or type(row["sequence"]) is not int or row["sequence"] <= 0:
                    raise ValueError("Invalid retained Lineage local operation order")
                revision = row["server_revision"]
                if revision is not None and (type(revision) is not int or revision <= 0):
                    raise ValueError("Invalid retained Lineage acknowledgement sequence")
                self.queued.append((row["sequence"], revision, operation))
        elif name == "research_file_versions":
            from paper_daily.sync_journal import canonical_operation

            operation = json.loads(canonical_operation(json.loads(row["operation"])))
            if (
                operation["operation_id"] != row["operation_id"]
                or operation["entity_id"] != row["entity_id"]
            ):
                raise ValueError("Lineage original version differs from its retained identity")
            if (
                operation["action"] == "put"
                and operation["entity_type"] == "research_file"
                and operation["payload"]["feature"] == "original_source"
            ):
                key = operation["entity_id"], operation["incarnation"]
                value = operation["workspace_id"], operation["parents"], operation["payload"]
                if key in self.originals and self.originals[key] != value:
                    raise ValueError("Conflicting Lineage original incarnation")
                self.originals[key] = value

    def optimistic(self, cursor):
        """Pure snapshot calculation, never a live old client/journal or replay grant."""
        from copy import deepcopy

        from paper_daily.sync_client import SyncClient

        if self._snapshot_graph is not None and self._snapshot_graph[0] == cursor:
            return self._snapshot_graph[1]
        if len({entry[0] for entry in self.queued}) != len(self.queued):
            raise ValueError("Duplicate retained local operation sequence")
        graph = (deepcopy(self.states), {}, {})
        for _sequence, revision, operation in sorted(self.queued, key=lambda entry: entry[0]):
            if revision is None or revision > cursor:
                SyncClient._overlay_optimistic(graph, operation)
        result = graph[0], {**self.heads, **graph[2]}
        self._snapshot_graph = cursor, result
        return result

    @staticmethod
    def _local_row(operation, records):
        body = json.loads(lineage_sets.canonical(operation["payload"]["data"]["body_json"]))
        for binding in body["bindings"]:
            local = records.paper_map.get(binding["paper_id"])
            if local is None or local not in records.paper_ids:
                raise ValueError("Bound Lineage lacks an exact retained selected paper")
            binding["paper_id"] = local
        row = dict(
            paper_id=body["bindings"][0]["paper_id"],
            corpus_key=body["corpus_id"],
            body_json=lineage_sets.canonical(body),
            **{
                k: operation["payload"]["data"][k]
                for k in ("source_hash", "document_hash", "written_at")
            },
        )
        return lineage_sets.validate_row(row)

    def _sources(self, operation, workspace):
        from paper_daily.lineage_wire import required_originals

        parents = {p["id"]: p for p in operation["parents"]}
        for pin, selected in zip(
            operation["source_dependencies"], required_originals(operation["payload"]), strict=True
        ):
            original = self.originals.get((pin["file_id"], pin["incarnation"]))
            if original is None:
                raise ValueError("Bound Lineage lacks its exact retained original incarnation")
            original_workspace, original_parents, payload = original
            if (
                original_workspace != workspace
                or original_parents != [parents[pin["paper_id"]]]
                or payload["paper_id"] != pin["paper_id"]
                or payload["source_document_hash"] != selected["document_hash"]
            ):
                raise ValueError("Bound Lineage original belongs to another source owner")

    def finish(self, records, rows):
        represented, groups = set(), {}
        for operation in self.history.values():
            if operation["workspace_id"] != records.workspace:
                raise ValueError("Bound Lineage history belongs to another workspace")
            groups.setdefault(operation["entity_id"], []).append(operation)
        if set(groups) != set(self.markers):
            raise ValueError("Bound Lineage projection/history closure is incomplete")
        for identity, (marker, current) in self.markers.items():
            if self.history.get(current["operation_id"]) != current:
                raise ValueError("Bound Lineage projection lacks its exact retained operation")

            def signature(op):
                return op["content_address"], [(p["kind"], p["id"]) for p in op["parents"]]

            known_rows = {}
            for operation in groups[identity]:
                if signature(operation) != signature(current):
                    raise ValueError("Bound Lineage history moves its known corpus/source owners")
                if any(
                    records.paper_map.get(p["id"]) not in records.paper_ids
                    for p in operation["parents"]
                ):
                    raise ValueError("Bound Lineage history lacks its selected paper")
                if operation["action"] == "put":
                    self._sources(operation, records.workspace)
                    row = self._local_row(operation, records)
                    known_rows[claim_content.hashed(row)] = row
            if records.paper_map.get(current["parents"][0]["id"]) != marker["paper_id"]:
                raise ValueError("Bound Lineage projection differs from its exact focal alias")
            if marker["fingerprint"] is not None and marker["fingerprint"] not in known_rows:
                raise ValueError("Bound Lineage projection lacks its exact scientific history")
            saved = rows.get((marker["paper_id"], marker["corpus_key"]))
            if marker["active"] == 1:
                expected = self._local_row(current, records)
                if saved != expected or marker["fingerprint"] != claim_content.hashed(expected):
                    raise ValueError("Bound Lineage canonical row differs from its projection")
                represented.add(generation._json(expected))
            elif saved is not None:
                raise ValueError("Hidden bound Lineage has an unexpected canonical row")
        return represented
