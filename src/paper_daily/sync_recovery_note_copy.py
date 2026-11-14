"""Explicit copy-as-new note recovery through the native target transaction.

Old operation envelopes are immutable review input, never re-keyed for replay.
Positioned notes require owned exact-original bytes; compound recovery remains separate.
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


def _original(conn, operation, check):
    """Verify this note's exact owned PDF without activating or projecting it."""
    payload = operation["payload"]
    if payload.get("page") is None and payload.get("anchor") is None:
        return None
    anchor = payload.get("anchor")
    if not anchor or not anchor.get("document_hash"):
        raise ValueError("Original-bound notes require exact original verification before recovery")
    from paper_daily import note_positions, sync_source_files
    from paper_daily.sync_documents import (
        _paper_current,
        desired_document,
        verify_document,
    )
    from paper_daily.workspace_service import _ReadOnlyStore

    check()
    paper, digest = payload["paper_id"], anchor["document_hash"]
    # Immutable retained originals may differ from the currently active PDF.
    source = sync_source_files.inspectable(conn, paper, digest)
    if source is None:
        document = desired_document(conn, paper)
        if document is None or document["sha256"] != digest or not _paper_current(conn, document):
            raise ValueError("The note's exact original is not owned by the recovery target")
        row = conn.execute(
            "SELECT workspace,blob_root FROM document_reader_paths WHERE id=1"
        ).fetchone() if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='document_reader_paths'"
        ).fetchone() else None
        if row is None or row[0] != operation["workspace_id"]:
            raise ValueError("The note's original has no matching native storage registration")
        verified = verify_document(_ReadOnlyStore(row[1]), document)
        source = verified._path
    from paper_daily.sync_documents import _identity

    version = _identity(source)
    import hashlib

    from paper_daily.sync_documents import MAX_PDF_BYTES

    if not 0 < source.stat().st_size <= MAX_PDF_BYTES:
        raise ValueError("The note's original exceeds its byte budget")
    with source.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError("The note's original differs from its recorded hash")
    import pymupdf

    check()
    with pymupdf.open(source) as pdf:
        if pdf.needs_pass or pdf.page_count < 1:
            raise ValueError("The note's original is not a readable PDF")
        note_positions.verify(pdf, anchor)
    check()
    if _identity(source) != version:
        raise ValueError("The note's original changed during verification")
    return source, version


def _original_current(proof):
    if proof is not None:
        from paper_daily.sync_documents import _identity

        if _identity(proof[0]) != proof[1]:
            raise ValueError("The note's original changed before recovery committed")


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
                proof = _original(conn, operation, check) if previous is None else None
                receipt = client.journal.apply_in(conn, operation, client.writer)
                _original_current(proof)
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
    blocked = set(comparison["blocking_reasons"]) - {
        "target_restore_requires_confirmation",
        "target_entity_lifetime_changed",
        "target_parent_lifetime_changed",
        "note_original_verification_required",
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
        conn.set_progress_handler(lambda: (check(), 0)[1], 1000)
        conn.execute("BEGIN")
        _binding_in(conn, observed)
        # Reuse the metadata adapter's bounded source/receipt proof. Matching an
        # ID or incarnation alone is not authority to attach a recovered note.
        from paper_daily.sync_recovery_choices import _parent_mapper

        mapped = _parent_mapper(conn, observed, source, check)
        parents = [mapped(parent) for parent in source["parents"]]
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
                or operation["parents"] != parents
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
            if operation["parents"] != parents:
                raise ValueError("Note parent differs from its verified recovery mapping")
            if operation["base_revision"] or operation["depends_on"] is not None:
                raise ValueError("Recovery copy identity already exists")
            encoded = canonical_operation(operation)
            _original(conn, operation, check)
    observed._check(check)
    return NoteCopy(observed, change_id, encoded, _sign(observed, change_id, encoded))
