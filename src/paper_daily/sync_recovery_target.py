"""Read-only recovery-target history proof and per-change comparison; no replay."""

from __future__ import annotations

import hmac
import json
import secrets
from contextlib import closing
from dataclasses import dataclass, field

from paper_daily import research_generation as generation
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_authority_restore as restore
from paper_daily import sync_recovery_candidates as candidates
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_client import validate_event
from paper_daily.sync_journal import MAX_BYTES, _identifier, canonical_operation
from paper_daily.workspace_sync import local_binding

_KEY = secrets.token_bytes(32)
MAX_STATE_BYTES = 16 * 1024 * 1024
MAX_PREVIEW_BYTES = 8 * MAX_BYTES


def _sign(source, database, identity, binding, versions, graph, pending, cursor):
    data = candidates._json(
        [source._seal, str(database), identity, binding, versions, graph, pending, cursor]
    ).encode("utf-8")
    return hmac.new(_KEY, data, "sha256").hexdigest()


def _bounded(conn, table, column, where="", args=()):
    # Only fixed module-owned table/column/predicate constants reach this helper.
    count, size = conn.execute(
        "SELECT COUNT(*),COALESCE(SUM(length(CAST("
        + column
        + " AS BLOB))),0) FROM "
        + table
        + where,
        args,
    ).fetchone()
    if count > candidates.review.MAX_RECORDS or size > MAX_STATE_BYTES:
        raise ValueError("Recovery target state budget exceeded")


def _validate_graph(graph, cursor, check):
    required = {"incarnation", "structure_revision", "active", "parents"}
    for (kind, identity), metadata in graph.items():
        check()
        _identifier(kind)
        _identifier(identity)
        if (
            not isinstance(metadata, dict)
            or not required <= set(metadata)
            or not set(metadata) <= required | {"content_address"}
            or type(metadata["active"]) is not bool
            or type(metadata["structure_revision"]) is not int
            or not 0 <= metadata["structure_revision"] <= cursor
            or not isinstance(metadata["parents"], list)
            or len(metadata["parents"]) > 128
        ):
            raise ValueError("Recovery target graph metadata is invalid")
        _identifier(metadata["incarnation"])
        if "content_address" in metadata and not isinstance(metadata["content_address"], dict):
            raise ValueError("Recovery target graph address is invalid")
        seen = set()
        for parent in metadata["parents"]:
            if not isinstance(parent, dict) or set(parent) != {"kind", "id", "incarnation"}:
                raise ValueError("Recovery target parent metadata is invalid")
            for value in parent.values():
                _identifier(value)
            key = (parent["kind"], parent["id"])
            if key in seen:
                raise ValueError("Recovery target parent metadata is duplicated")
            seen.add(key)


@dataclass(frozen=True)
class TargetObservation:
    source: object = field(repr=False)
    database: object = field(repr=False)
    binding: dict
    identity: tuple = field(repr=False)
    versions: tuple = field(repr=False)
    graph_json: str = field(repr=False)
    pending_json: str = field(repr=False)
    cursor: int
    _seal: str = field(repr=False)

    def _check(self, check):
        self.source._check(check)
        expected = _sign(
            self.source,
            self.database,
            self.identity,
            self.binding,
            self.versions,
            self.graph_json,
            self.pending_json,
            self.cursor,
        )
        if not hmac.compare_digest(expected, self._seal):
            raise ValueError("Recovery target requires its original prepared observation")
        if (
            tuple(generation._identity(self.database)) != self.identity
            or candidates.review._version(self.database) != self.versions
        ):
            raise ValueError("Recovery target changed; prepare a new comparison")
        check()

    def compare(self, change_id, *, seconds=30, cancelled=lambda: False):
        check = backup._guard(seconds, cancelled)
        self._check(check)
        detail = self.source.details(
            change_id, seconds=seconds, cancelled=lambda: (check(), False)[1]
        )
        operation = detail["operation"]
        key = (operation["entity_type"], operation["entity_id"])
        graph = {(kind, identity): value for kind, identity, value in json.loads(self.graph_json)}
        pending = [
            value
            for value in json.loads(self.pending_json)
            if (value["entity_type"], value["entity_id"]) == key
        ]
        with closing(_readonly_connection(self.database)) as conn:
            conn.execute("BEGIN")
            head = conn.execute(
                "SELECT revision,CASE WHEN length(CAST(operation AS BLOB))<=? "
                "THEN operation END FROM paperfact_sync_heads WHERE entity_type=? AND entity_id=?",
                (MAX_BYTES, *key),
            ).fetchone()
            if head is not None and (
                type(head[0]) is not int
                or not 0 <= head[0] <= self.cursor
                or head[0] == 0
                and head[1] is not None
            ):
                raise ValueError("Current target head revision is invalid")
            if head is not None and head[0] and head[1] is None:
                raise ValueError("Current target head exceeds its input budget")
            current = None if head is None or head[1] is None else backup._decode(head[1])
            if current is not None:
                canonical_operation(current)
                if (
                    current["workspace_id"] != self.binding["workspace_id"]
                    or (current["entity_type"], current["entity_id"]) != key
                ):
                    raise ValueError("Current target head belongs to another scope")
        effective = pending[-1] if pending else current
        state = graph.get(key)
        reasons, parents = [], []
        if operation["version"] != 2:
            reasons.append("legacy_protocol_requires_mapping")
        for reference in operation.get("parents", []):
            parent = graph.get((reference["kind"], reference["id"]))
            parents.append(dict(expected=reference, current=parent))
            if parent is None:
                reasons.append("target_parent_absent")
            elif not parent["active"]:
                reasons.append("target_parent_retired")
            elif parent["incarnation"] != reference["incarnation"]:
                reasons.append("target_parent_lifetime_changed")
        if state is None:
            difference = "absent"
        elif not state["active"]:
            difference = "retired"
            reasons.append("target_restore_requires_confirmation")
        elif operation.get("incarnation") != state["incarnation"]:
            difference = "different_lifetime"
            reasons.append("target_entity_lifetime_changed")
        elif (
            effective is not None
            and effective["action"] == operation["action"]
            and effective["payload"] == operation["payload"]
        ):
            difference = "same_payload"
        else:
            difference = "different_payload"
        if operation["entity_type"] in {"research_file", "paper_document"}:
            reasons.append("file_ownership_verification_required")
        if operation.get("source_dependencies") or (
            operation["entity_type"] == "research_content"
            and operation["payload"].get("source_document_hash") is not None
        ):
            reasons.append("scientific_source_closure_required")
        if operation["entity_type"] == "note" and (
            operation["payload"].get("anchor") is not None
            or operation["payload"].get("page") is not None
        ):
            reasons.append("note_original_verification_required")
        result = dict(
            format="paperfact.recovery-target-comparison.v1",
            state="compared",
            source=detail,
            target=dict(
                workspace_id=self.binding["workspace_id"],
                device_id=self.binding["device_id"],
                cursor=self.cursor,
                head_revision=head[0] if head else 0,
                accepted_operation=current,
                pending_operations=pending,
                effective_operation=effective,
                entity_state=state,
                parents=parents,
                difference=difference,
            ),
            blocking_reasons=sorted(set(reasons)),
            typed_apply_implemented=False,
            replayed=False,
            originals_verified=False,
            dependency_effects_checked=False,
        )
        if len(candidates._json(result).encode("utf-8")) > MAX_PREVIEW_BYTES:
            raise ValueError("Recovery comparison exceeds its preview budget")
        self._check(check)
        return result


def observe(source, database, *, seconds=30, cancelled=lambda: False):
    check = backup._guard(seconds, cancelled)
    if not isinstance(source, candidates.ReviewIndex):
        raise ValueError("Use a prepared source recovery review")
    source._check(check)
    database = backup._path(database)
    identity = tuple(generation._identity(database))
    if identity == tuple(generation._identity(source.database)) or database.is_relative_to(
        source.snapshot
    ):
        raise ValueError("Select a separate fresh recovered client workspace")
    binding = local_binding(database, require_capture=True)
    if binding["workspace_id"] == source.workspace:
        raise ValueError("Recovery target must use a fresh workspace identity")
    before = candidates.review._version(database)
    with (
        closing(_readonly_connection(database)) as target,
        closing(backup._connect(source.snapshot / "authority.sqlite")) as saved,
    ):
        for conn in (target, saved):
            conn.set_progress_handler(lambda: (check(), 0)[1], 1000)
            conn.execute("BEGIN")
        client = target._capture_client
        if client is None:
            raise ValueError("Target requires its actual native capture connection")
        client.journal._binding(target)
        if (client.journal.workspace_id, client.journal.device_id) != (
            binding["workspace_id"],
            binding["device_id"],
        ):
            raise ValueError("Target native capture binding changed")
        rows = target.execute("SELECT sequence FROM paperfact_sync_cursor LIMIT 2").fetchall()
        if (
            len(rows) != 1
            or type(rows[0][0]) is not int
            or not 0 <= rows[0][0] <= candidates.review.MAX_RECORDS
        ):
            raise ValueError("Target received cursor exceeds its supported scope")
        cursor = rows[0][0]
        count, first, last = target.execute(
            "SELECT COUNT(*),MIN(sequence),MAX(sequence) FROM paperfact_sync_inbox"
        ).fetchone()
        if count != cursor or cursor and (first != 1 or last != cursor):
            raise ValueError("Target received history is incomplete")
        summary = json.loads(source._summary_json)
        if cursor < summary["backup_sequence"]:
            raise ValueError("Target has not received the complete recovered backup")
        for sequence, raw in saved.execute(
            "SELECT sequence,CASE WHEN length(CAST(event AS BLOB))<=? THEN event END "
            "FROM sync_events WHERE workspace=? ORDER BY sequence",
            (candidates.review.MAX_EVENT, source.workspace),
        ):
            check()
            if raw is None:
                raise ValueError("Recovered backup event exceeds its input budget")
            expected = restore._event(raw, binding["workspace_id"])
            received = target.execute(
                "SELECT CASE WHEN length(CAST(event AS BLOB))<=? THEN event END "
                "FROM paperfact_sync_inbox WHERE sequence=?",
                (candidates.review.MAX_EVENT, sequence),
            ).fetchone()
            if received is None or received[0] is None:
                raise ValueError("Target recovered history is unavailable")
            actual = backup._decode(received[0])
            validate_event(actual, binding["workspace_id"])
            if actual != expected:
                raise ValueError("Target does not share this exact recovered backup prefix")
        _bounded(target, "paperfact_sync_graph", "metadata")
        _bounded(
            target,
            "paperfact_sync_operations",
            "envelope",
            " WHERE server_revision IS NULL OR server_revision>?",
            (cursor,),
        )
        pending = client._pending_graph(target, cursor)
        for operation in pending:
            check()
            canonical_operation(operation)
            if (operation["workspace_id"], operation["device_id"]) != (
                binding["workspace_id"],
                binding["device_id"],
            ):
                raise ValueError("Pending target operation belongs to another binding")
        graph = client._optimistic_graph(target)[0]
        _validate_graph(graph, cursor, check)
        graph_json = candidates._json(
            [[kind, identity, value] for (kind, identity), value in sorted(graph.items())]
        )
        pending_json = candidates._json(pending)
    source._check(check)
    if candidates.review._version(database) != before:
        raise ValueError("Target changed during comparison preparation; retry")
    result = TargetObservation(
        source,
        database,
        binding,
        identity,
        before,
        graph_json,
        pending_json,
        cursor,
        _sign(source, database, identity, binding, before, graph_json, pending_json, cursor),
    )
    result._check(check)
    return result
