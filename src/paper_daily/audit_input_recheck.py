"""Worker-only renewal of a read-only Audit input proof, never writer authority.

A physical DB/WAL change may be interference without a changed saved-output
corpus. One real bounded capture can prove equality; it cannot rewrite the old
capture, repair unknown ownership, choose a new PDF, or authorize publication.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from paper_daily import audit_inputs, file_change, manual_highlight_ops, research_audit
from paper_daily import research_evidence as evidence
from paper_daily import research_generation as generation
from paper_daily.document_reader import DocumentReader, ResolvedDocument


def _fail(code):
    raise research_audit.AuditError(code) from None


def _scope(current, cancelled):
    if not callable(current) or not callable(cancelled):
        _fail("invalid_recheck_scope")
    stopped = cancelled()
    if type(stopped) is not bool:
        _fail("invalid_recheck_scope")
    if stopped:
        _fail("cancelled")
    admitted = current()
    if type(admitted) is not bool:
        _fail("invalid_recheck_scope")
    if not admitted:
        _fail("stale_context")


def _bounded_json(text):
    if (
        not isinstance(text, str)
        or len(text) > research_audit.MAX_BYTES
        or len(text.encode("utf-8")) > research_audit.MAX_BYTES
    ):
        _fail("input_limit")

    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value:
                _fail("invalid_capture")
            value[key] = item
        return value

    return json.loads(
        text, object_pairs_hook=pairs, parse_constant=lambda _value: _fail("invalid_capture")
    )


def _known_identity(value):
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(item) is not int for item in value)
        or value[0] < 0
        or value[1] <= 0
    ):
        _fail("unknown_database_identity")
    return value


def _owner(capture, owner):
    if type(owner) is not manual_highlight_ops.HighlightOwner:
        _fail("invalid_recheck_owner")
    state = _bounded_json(capture._state_json)
    if not isinstance(state, dict) or set(state) != {"identity", "binding", "parent"}:
        _fail("invalid_capture")
    identity = _known_identity(state["identity"])
    parent = state["parent"]
    if (
        not isinstance(parent, str)
        or len(parent) != 32
        or any(char not in "0123456789abcdef" for char in parent)
    ):
        _fail("unknown_owner")
    observed = _bounded_json(owner._json)
    if (
        not isinstance(observed, dict)
        or set(observed) != {"database_identity", "binding", "parent", "graph"}
        or owner.database != capture.database
        or owner.paper_id != capture.paper_id
        or observed["database_identity"] != identity
        or observed["binding"] != state["binding"]
        or observed["parent"] != parent
    ):
        _fail("invalid_recheck_owner")
    _bounded_json(capture._items_json)
    return identity


def _document(capture, document):
    if (
        type(document) is not ResolvedDocument
        or not document.available
        or capture.snapshot._origin is not document
        or not isinstance(document._owner, DocumentReader)
        or document.local_id != capture.paper_id
        or not isinstance(document._owner.db_path, Path)
        or document._owner.db_path.resolve() != capture.database
    ):
        _fail("source_identity_mismatch")
    resolver = document._owner
    if resolver._closed or resolver._generation != document._generation:
        _fail("source_changed")
    return (
        id(document),
        id(resolver),
        document._generation,
        document._context,
        document._target,
        document._identity,
        document.path,
        document.sha256,
        document.mode,
        document.local_id,
        document.paper_id,
        resolver._generation,
        resolver._closed,
        resolver.db_path,
        resolver.legacy_root,
        resolver.projection_root,
    )


def recheck(capture, *, document, owner, current, cancelled):
    """Return one fresh actual AuditCapture only for identical meaningful inputs.

    Both predicates are required, cheap worker-safe caller-scope observations.
    At most one core capture is attempted; its own stable reads are preserved.
    This does not make an original strict capture current or resume a model job.
    """
    if threading.current_thread() is threading.main_thread():
        _fail("audit_recheck_worker_required")
    try:
        _scope(current, cancelled)
        if (
            type(capture) is not audit_inputs.AuditCapture
            or capture._seal is not audit_inputs._SEAL
        ):
            _fail("invalid_capture")
        if (
            not isinstance(capture.database, Path)
            or not isinstance(capture.paper_id, str)
            or not capture.paper_id
            or type(capture.snapshot) is not evidence.EvidenceSnapshot
        ):
            _fail("invalid_capture")
        identity = _owner(capture, owner)
        if generation._identity(capture.database) != identity:
            _fail("saved_content_changed")
        source_context = _document(capture, document)
        # Validate the original process-sealed immutable bytes, not a caller hash.
        evidence._checked_snapshot(capture.snapshot)
        source_version = file_change.version(document.path)
        if source_version != document._identity:
            _fail("source_changed")
        _scope(current, cancelled)
        try:
            fresh = audit_inputs.AuditCapture.capture(
                capture.database, capture.paper_id, document=document, owner=owner
            )
        except research_audit.AuditError as error:
            if error.code == "saved_content_changed":
                _fail("recheck_interference")
            raise
        _scope(current, cancelled)
        if fresh._state_json != capture._state_json or fresh._items_json != capture._items_json:
            _fail("saved_content_changed")
        if (
            fresh.snapshot._origin is not document
            or fresh.snapshot._source_json != capture.snapshot._source_json
            or fresh.snapshot._bytes != capture.snapshot._bytes
        ):
            _fail("source_changed")
        # No stat retry: late interference requires another explicit invocation.
        _scope(current, cancelled)
        if (
            generation._identity(capture.database) != identity
            or _document(capture, document) != source_context
            or file_change.version(document.path) != source_version
        ):
            _fail("source_changed")
        if not fresh.current():
            _fail("recheck_interference")
        _scope(current, cancelled)
        if (
            _document(capture, document) != source_context
            or file_change.version(document.path) != source_version
        ):
            _fail("source_changed")
        if not fresh.current():
            _fail("recheck_interference")
        return fresh
    except research_audit.AuditError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RecursionError, sqlite3.Error):
        _fail("recheck_unavailable")
