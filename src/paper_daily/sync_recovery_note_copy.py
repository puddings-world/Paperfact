"""Explicit copy-as-new note recovery through the native target transaction.

Old operation envelopes are immutable review input, never re-keyed for replay.
Other domains and original-bound notes remain pending for typed recovery actions.
"""

from __future__ import annotations

import hmac
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from uuid import NAMESPACE_URL, uuid5

from paper_daily import research_generation as generation
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_target as target
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_journal import _identifier, canonical_operation
from paper_daily.workspace_service import _binding
from paper_daily.workspace_sync import local_binding

_KEY = secrets.token_bytes(32)
FORMAT = "paperfact.recovery-note-copy.v1"


def _sign(observed, change_id, operation_json):
    message = candidates._json([observed._seal, change_id, operation_json])
    return hmac.new(_KEY, message.encode("utf-8"), "sha256").hexdigest()


def _auth(observed, check):
    if not isinstance(observed, target.TargetObservation):
        raise ValueError("Use a prepared recovery target comparison")
    observed.source._check(check)
    expected = target._sign(
        observed.source,
        observed.database,
        observed.identity,
        observed.binding,
        observed.versions,
        observed.graph_json,
        observed.pending_json,
        observed.cursor,
    )
    if not hmac.compare_digest(expected, observed._seal):
        raise ValueError("Recovery target requires its original prepared observation")
    if tuple(generation._identity(observed.database)) != observed.identity:
        raise ValueError("Recovery target database was replaced")
    if local_binding(observed.database, require_capture=True) != observed.binding:
        raise ValueError("Recovery target binding changed")
    check()


def _binding_in(conn, observed):
    expected = tuple(observed.binding[key] for key in ("workspace_id", "device_id"))
    tables = {"paperfact_sync_identity", "research_sync_binding", "research_capture_binding"}
    rows = dict(_binding(conn, tables))
    if set(rows) != tables or any(value != expected for value in rows.values()):
        raise ValueError("Recovery target native binding changed")


@dataclass(frozen=True)
class NoteCopy:
    observed: object = field(repr=False)
    change_id: str
    operation_json: str = field(repr=False)
    _seal: str = field(repr=False)

    def apply(self, *, seconds=30, cancelled=lambda: False):
        """Commit new research and its retry receipt/outbox together; no network."""
        check = backup._guard(seconds, cancelled)
        _auth(self.observed, check)
        expected = _sign(self.observed, self.change_id, self.operation_json)
        if not hmac.compare_digest(expected, self._seal):
            raise ValueError("Use the original prepared note-copy decision")
        operation = backup._decode(self.operation_json)
        canonical_operation(operation)
        path = self.observed.database
        # mode=rw cannot create a missing/replaced database directory.
        with closing(
            sqlite3.connect(
                path.as_uri() + "?mode=rw",
                uri=True,
                timeout=0.1,
                factory=CaptureConnection,
            )
        ) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.set_progress_handler(lambda: (check(), 0)[1], 1000)
                _binding_in(conn, self.observed)
                client = conn._capture_client
                if client is None:
                    raise ValueError("Recovery requires the native target writer")
                previous = conn.execute(
                    "SELECT 1 FROM paperfact_sync_operations WHERE operation_id=?",
                    (operation["operation_id"],),
                ).fetchone()
                if previous is None:
                    # Hold the SQLite writer lock before the final preview fence.
                    self.observed._check(check)
                receipt = client.journal.apply_in(conn, operation, client.writer)
                self.observed.source._check(check)
                _binding_in(conn, self.observed)
                if tuple(generation._identity(path)) != self.observed.identity:
                    raise ValueError("Recovery target database was replaced")
                check()
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return dict(
            format=FORMAT,
            state="saved_locally",
            applied=receipt["applied"],
            sequence=receipt["sequence"],
            operation_id=operation["operation_id"],
            entity_id=operation["entity_id"],
            source_change_id=self.change_id,
            workspace_id=operation["workspace_id"],
            replayed=False,
            remote_accepted=None,
            remote_acceptance_checked=False,
        )


def prepare(observed, change_id, request_id, *, seconds=30, cancelled=lambda: False):
    """Prepare an explicit copy of a v2 note; never silently replace or restore."""
    _identifier(request_id)
    check = backup._guard(seconds, cancelled)
    _auth(observed, check)
    comparison = observed.compare(change_id, seconds=seconds, cancelled=cancelled)
    source = comparison["source"]["operation"]
    if source["version"] != 2 or source["entity_type"] != "note" or source["action"] != "put":
        raise ValueError("This action copies version-2 note puts only; keep other changes pending")
    if source["payload"].get("page") is not None or source["payload"].get("anchor") is not None:
        raise ValueError("Original-bound notes require exact original verification before recovery")
    blocked = set(comparison["blocking_reasons"]) - {
        "target_restore_requires_confirmation",
        "target_entity_lifetime_changed",
    }
    if blocked:
        raise ValueError(
            "Resolve note parent/source requirements before copying: " + ", ".join(sorted(blocked))
        )
    # Stable identity binds this request to the exact old operation, not its title
    # or a mutable note body. Reusing the request for another input must conflict.
    address = candidates._json(
        [
            observed.binding,
            request_id,
            source["workspace_id"],
            source["device_id"],
            source["operation_id"],
            candidates._fingerprint(source),
        ]
    )
    entity_id = str(uuid5(NAMESPACE_URL, "paperfact:recovery-note-copy:" + address))
    with closing(_readonly_connection(observed.database)) as conn:
        conn.execute("BEGIN")
        _binding_in(conn, observed)
        previous = conn.execute(
            "SELECT CASE WHEN length(CAST(envelope AS BLOB))<=? THEN envelope END,"
            "fingerprint FROM paperfact_sync_operations WHERE operation_id=?",
            (candidates.MAX_BYTES, request_id),
        ).fetchone()
        if previous is not None:
            if previous[0] is None:
                raise ValueError("Existing recovery receipt exceeds its input budget")
            operation = backup._decode(previous[0])
            encoded = canonical_operation(operation)
            if (
                candidates._fingerprint(operation) != previous[1]
                or operation["version"] != 2
                or operation["workspace_id"] != observed.binding["workspace_id"]
                or operation["device_id"] != observed.binding["device_id"]
                or operation["entity_type"] != "note"
                or operation["entity_id"] != entity_id
                or operation["operation_id"] != request_id
                or operation["action"] != "put"
                or operation["payload"] != source["payload"]
                or operation["parents"] != source["parents"]
                or operation["incarnation"] != request_id
                or operation["base_revision"] != 0
                or operation["depends_on"] is not None
            ):
                raise ValueError("Recovery request ID was reused with different content")
        else:
            operation = conn._capture_client.new_graph_operation_in(
                conn,
                "note",
                entity_id,
                source["payload"],
                operation_id=request_id,
            )
            if operation["parents"] != source["parents"]:
                raise ValueError("Note's exact original paper lifetime must be preserved")
            if operation["base_revision"] or operation["depends_on"] is not None:
                raise ValueError("Recovery copy identity already exists")
            encoded = canonical_operation(operation)
    observed._check(check)
    return NoteCopy(observed, change_id, encoded, _sign(observed, change_id, encoded))
