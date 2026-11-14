"""Explicit note/manual-highlight copies through the native target transaction.

Old operation envelopes are immutable review input, never re-keyed for replay.
Positioned notes use exact originals; scientific-group recovery remains separate.
"""

from __future__ import annotations

import hmac
import secrets
import sqlite3
from contextlib import closing
from copy import deepcopy
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
MANUAL_FORMAT = "paperfact.recovery-manual-highlight-copy.v1"


def _sign(observed, change_id, operation_json, with_original=False):
    message = candidates._json([observed._seal, change_id, operation_json, with_original])
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


def is_manual_highlight(operation):
    return (operation["entity_type"] == "research_content"
            and operation["payload"].get("feature") == "manual_highlight")


def _position(operation):
    payload = operation["payload"]
    if is_manual_highlight(operation):
        return (payload["scope"]["id"], payload["source_document_hash"],
                payload["data"]["anchor"], payload["data"]["quote"])
    anchor = payload.get("anchor")
    if payload.get("page") is None and anchor is None:
        return None
    if not anchor or not anchor.get("document_hash"):
        raise ValueError("Original-bound notes require exact original verification before recovery")
    return payload["paper_id"], anchor["document_hash"], anchor, None


def _original(conn, operation, check, *, allow_retained=False):
    position = _position(operation)
    if position is None:
        return None
    paper, digest, anchor, quote = position
    return inspect_original(conn, paper, operation["parents"][0], digest, check,
                            anchor=anchor, quote=quote, allow_retained=allow_retained)


def inspect_original(conn, paper, parent, digest, check, *, anchor=None, quote=None,
                     allow_retained=False):
    """Read exact native-owned original bytes; no activation or write authority."""
    from paper_daily import note_positions, sync_source_files
    from paper_daily.sync_documents import (
        _paper_current,
        desired_document,
        verify_document,
    )
    from paper_daily.workspace_service import _ReadOnlyStore

    check()
    if type(allow_retained) is not bool:
        raise ValueError("Choose historical original inspection explicitly")
    if (parent["kind"] != "paper" or parent["id"] != paper or not _paper_current(
        conn, dict(paper_id=paper, parent_incarnation=parent["incarnation"])
    )):
        raise ValueError("The original belongs to another paper lifetime")
    # Immutable retained originals may differ from the currently active PDF.
    source = sync_source_files.inspectable(conn, paper, digest)
    if source is None and allow_retained:
        from paper_daily.sync_recovery_original import inspect_retained

        retained = inspect_retained(conn, paper, parent, digest, check)
        source = retained[0] if retained is not None else None
    if source is None:
        document = desired_document(conn, paper)
        if document is None or document["sha256"] != digest or not _paper_current(conn, document):
            raise ValueError("The exact original is not owned by the recovery target")
        row = conn.execute(
            "SELECT workspace,blob_root FROM document_reader_paths WHERE id=1"
        ).fetchone() if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='document_reader_paths'"
        ).fetchone() else None
        binding = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
        if row is None or binding is None or row[0] != binding[0]:
            raise ValueError("The original has no matching native storage registration")
        verified = verify_document(_ReadOnlyStore(row[1]), document)
        source = verified._path
    from paper_daily.sync_documents import _identity

    version = _identity(source)
    import hashlib

    from paper_daily.sync_documents import MAX_PDF_BYTES

    if not 0 < source.stat().st_size <= MAX_PDF_BYTES:
        raise ValueError("The original exceeds its byte budget")
    with source.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError("The original differs from its recorded hash")
    import pymupdf

    check()
    with pymupdf.open(source) as pdf:
        if pdf.needs_pass or pdf.page_count < 1:
            raise ValueError("The original is not a readable PDF")
        if anchor is not None:
            note_positions.verify(pdf, anchor)
        if quote is not None:
            from paper_daily.manual_highlight_ops import selection_quote

            actual = selection_quote(pdf, anchor)
            if " ".join(actual.split()) != " ".join(quote.split()):
                raise ValueError("Highlight quotation differs from its exact PDF position")
    check()
    if _identity(source) != version:
        raise ValueError("The original changed during verification")
    return source, version


def _original_current(proof):
    if proof is not None:
        from paper_daily.sync_documents import _identity

        if _identity(proof[0]) != proof[1]:
            raise ValueError("The original changed before recovery committed")


def _manual_slot(conn, operation):
    if not is_manual_highlight(operation):
        return
    paper, digest, anchor, _quote = _position(operation)
    row = conn.execute(
        "SELECT local_id FROM research_paper_identity WHERE sync_id=?", (paper,),
    ).fetchone()
    if row is None:
        raise ValueError("The manual highlight has no native paper mapping")
    duplicate = conn.execute(
        "SELECT 1 FROM pdf_highlights WHERE paper_id=? AND document_hash=? AND CASE "
        "WHEN length(CAST(anchor AS BLOB))<=32768 THEN CASE WHEN json_valid(anchor) THEN "
        "json_extract(anchor,'$.p0')=? AND json_extract(anchor,'$.o0')=? AND "
        "json_extract(anchor,'$.p1')=? AND json_extract(anchor,'$.o1')=? ELSE 0 END "
        "ELSE 0 END LIMIT 1",
        (row[0], digest, *(anchor[key] for key in ("p0", "o0", "p1", "o1"))),
    ).fetchone()
    if duplicate:
        raise ValueError("Target already contains this manual selection; keep the existing mark")


def _source_input(observed, source, operation, check):
    """Read the recorded owned original; never infer it from an untrusted path."""
    from paper_daily.sync_source_files import _inspection_paths

    with closing(_readonly_connection(observed.source.database)) as old:
        old.execute("BEGIN")
        proof = _original(old, source, check, allow_retained=True)
        if proof is None:
            raise ValueError("Only positioned notes can include an original")
    # Inspection may take time; fence destination replacement before staging bytes.
    _auth(observed, check)
    observed._check(check)
    with closing(_readonly_connection(observed.database)) as conn:
        conn.execute("BEGIN")
        _binding_in(conn, observed)
        registered = _inspection_paths(conn)
        if registered is None:
            raise ValueError("The restored workspace has no registered original storage")
        client = conn._capture_client
        from paper_daily.sync_files import file_id
        from paper_daily.sync_source_files import FEATURE

        paper, digest, _anchor, _quote = _position(source)
        identity = file_id(paper, FEATURE, digest)
        current = client._optimistic_graph(conn)[0].get(("research_file", identity))
        if current and (not current["active"] or current["parents"] != operation["parents"]):
            raise ValueError("Deleted or retired original requires explicit source restoration")
    _original_current(proof)
    observed.source._check(check)
    observed._check(check)
    return proof, registered, client


def _stage_original(plan, operation, check):
    from pathlib import Path

    from paper_daily.sync_blobs import BlobStore
    from paper_daily.sync_source_files import prepare_source

    source = plan.observed.source.details(plan.change_id)["operation"]
    proof, (store, root), client = _source_input(plan.observed, source, operation, check)
    request = str(uuid5(
        NAMESPACE_URL, "paperfact:recovery-note-original:" + operation["operation_id"]
    ))
    paper, digest, _anchor, _quote = _position(operation)
    staged = prepare_source(
        client, paper, proof[0],
        document_hash=digest,
        parent_incarnation=operation["parents"][0]["incarnation"],
        store=BlobStore(store.root), version_root=Path(root), request_id=request,
    )
    _original_current(proof)
    plan.observed.source._check(check)
    check()
    return staged


@dataclass(frozen=True)
class NoteCopy:
    observed: object = field(repr=False)
    change_id: str
    operation_json: str = field(repr=False)
    _seal: str = field(repr=False)
    with_original: bool = False

    @property
    def manual_highlight(self):
        return is_manual_highlight(backup._decode(self.operation_json))

    def apply(self, *, seconds=30, cancelled=lambda: False):
        """Commit new research and its retry receipt/outbox together; no network."""
        check = backup._guard(seconds, cancelled)
        _auth(self.observed, check)
        expected = _sign(self.observed, self.change_id, self.operation_json, self.with_original)
        if not hmac.compare_digest(expected, self._seal):
            raise ValueError("Use the original prepared note-copy decision")
        operation = backup._decode(self.operation_json)
        canonical_operation(operation)
        path = self.observed.database
        staged = None
        if self.with_original:
            with closing(_readonly_connection(path)) as prior:
                saved = prior.execute(
                    "SELECT 1 FROM paperfact_sync_operations WHERE operation_id=?",
                    (operation["operation_id"],),
                ).fetchone()
            if saved is None:
                self.observed._check(check)
                staged = _stage_original(self, operation, check)
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
                    _manual_slot(conn, operation)
                    if self.with_original:
                        from paper_daily.sync_source_files import publish_source_in

                        if staged is None:
                            raise ValueError("The original needs its verified staging proof")
                        publish_source_in(conn, client, staged)
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
            format=MANUAL_FORMAT if self.manual_highlight else FORMAT,
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


def prepare(
    observed, change_id, request_id, *, with_original=False, seconds=30, cancelled=lambda: False,
):
    """Prepare a distinct native note/manual-mark copy, optionally with its original."""
    if type(with_original) is not bool:
        raise ValueError("Choose explicitly whether to include the original")
    _identifier(request_id)
    check = backup._guard(seconds, cancelled)
    _auth(observed, check)
    comparison = observed.compare(change_id, seconds=seconds, cancelled=cancelled)
    source = comparison["source"]["operation"]
    manual = is_manual_highlight(source)
    if (source["version"] != 2 or source["action"] != "put"
            or source["entity_type"] != "note" and not manual):
        raise ValueError(
            "This action copies manual-highlight or note puts only (version 2); "
            "keep other changes pending"
        )
    blocked = set(comparison["blocking_reasons"]) - {
        "target_restore_requires_confirmation",
        "target_entity_lifetime_changed",
        "target_parent_lifetime_changed",
        "note_original_verification_required",
    }
    if manual:
        # The typed mark adapter verifies this closure through _original/_source_input.
        blocked.discard("scientific_source_closure_required")
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
    kind = "manual-highlight" if manual else "note"
    copied_key = str(uuid5(NAMESPACE_URL, "paperfact:recovery-" + kind + "-copy:" + address))
    payload = deepcopy(source["payload"])
    if manual:
        from paper_daily.sync_content import content_id

        payload["key"] = copied_key
        entity_id = content_id(payload["scope"], "manual_highlight", copied_key)
    else:
        entity_id = copied_key
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
                or operation["entity_type"] != source["entity_type"]
                or operation["entity_id"] != entity_id
                or operation["operation_id"] != request_id
                or operation["action"] != "put"
                or operation["payload"] != payload
                or operation["parents"] != parents
                or operation["incarnation"] != request_id
                or operation["base_revision"] != 0
                or operation["depends_on"] is not None
            ):
                raise ValueError("Recovery request ID was reused with different content")
        else:
            operation = conn._capture_client.new_graph_operation_in(
                conn,
                source["entity_type"],
                entity_id,
                payload,
                operation_id=request_id,
            )
            if operation["parents"] != parents:
                raise ValueError("Note parent differs from its verified recovery mapping")
            if operation["base_revision"] or operation["depends_on"] is not None:
                raise ValueError("Recovery copy identity already exists")
            encoded = canonical_operation(operation)
            _manual_slot(conn, operation)
            if with_original:
                _source_input(observed, source, operation, check)
            else:
                _original(conn, operation, check)
    observed._check(check)
    return NoteCopy(observed, change_id, encoded,
                    _sign(observed, change_id, encoded, with_original), with_original)
