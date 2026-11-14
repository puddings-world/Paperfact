"""Typed recovery choices with native writes and payload-bound local receipts.

This preserves the old workspace. It does not replay old envelopes, transfer file
ownership, implement destructive recovery or claim complete reconciliation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field

from paper_daily import research_generation as generation
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_note_copy as native
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_journal import MAX_BYTES, _identifier, canonical_operation

FORMAT = "paperfact.recovery-choice.v1"
KINDS = frozenset(
    {"list", "paper", "membership", "reading_state", "note", "list_order", "workspace_list_order"}
)
ORDERS = frozenset({"list_order", "workspace_list_order"})
CHOICES = frozenset({"keep", "add", "replace", "restore"})
MAX_RECEIPT = 8192
_KEY = secrets.token_bytes(32)


def _schema(conn):
    rows = conn.execute("PRAGMA table_info(integration_operations)").fetchall()
    if [row[1] for row in rows] != ["id", "fingerprint", "result", "created_at"] or not rows[0][5]:
        raise ValueError("Recovery receipts require the existing native application schema")


def _fingerprint(observed, source, choice):
    document = [
        FORMAT,
        observed.identity,
        observed.binding,
        source["workspace_id"],
        source["device_id"],
        source["operation_id"],
        candidates._fingerprint(source),
        choice,
    ]
    return hashlib.sha256(candidates._json(document).encode("utf-8")).hexdigest()


def _seal(observed, change_id, request_id, fingerprint, operation):
    data = candidates._json([observed._seal, change_id, request_id, fingerprint, operation])
    return hmac.new(_KEY, data.encode("utf-8"), "sha256").hexdigest()


def _operation(conn, request_id):
    row = conn.execute(
        "SELECT CASE WHEN length(CAST(envelope AS BLOB))<=? THEN envelope END,fingerprint "
        "FROM paperfact_sync_operations WHERE operation_id=?",
        (MAX_BYTES, request_id),
    ).fetchone()
    if row is None:
        return None
    if row[0] is None:
        raise ValueError("Recovery native receipt exceeds its input budget")
    operation = backup._decode(row[0])
    encoded = canonical_operation(operation)
    fingerprint = candidates._fingerprint(operation)
    if fingerprint != row[1]:
        raise ValueError("Recovery native receipt is inconsistent")
    return operation, encoded, fingerprint


def _prior(conn, request_id, fingerprint, context):
    _schema(conn)
    row = conn.execute(
        "SELECT fingerprint,CASE WHEN length(CAST(result AS BLOB))<=? THEN result END "
        "FROM integration_operations WHERE id=?",
        (MAX_RECEIPT, request_id),
    ).fetchone()
    if row is None:
        return None
    if row[0] != fingerprint:
        raise ValueError("Recovery request ID was reused for a different decision or source")
    if row[1] is None:
        raise ValueError("Recovery decision receipt exceeds its input budget")
    receipt = backup._decode(row[1])
    required = {
        "format",
        "state",
        "request_id",
        "choice",
        "source_workspace_id",
        "source_device_id",
        "source_operation_id",
        "source_fingerprint",
        "workspace_id",
        "device_id",
        "entity_type",
        "entity_id",
        "operation_id",
        "operation_fingerprint",
        "sequence",
    }
    if (
        not isinstance(receipt, dict)
        or set(receipt) != required
        or receipt["format"] != FORMAT
        or receipt["request_id"] != request_id
        or not isinstance(receipt["choice"], str)
        or receipt["choice"] not in CHOICES
    ):
        raise ValueError("Recovery decision receipt is invalid")
    if any(receipt[key] != value for key, value in context.items() if key != "sequence"):
        raise ValueError("Recovery receipt differs from its source or prepared decision")
    saved = _operation(conn, request_id)
    if receipt["choice"] == "keep":
        if (
            saved is not None
            or receipt["state"] != "kept_current"
            or any(
                receipt[key] is not None
                for key in ("operation_id", "operation_fingerprint", "sequence")
            )
        ):
            raise ValueError("Keep-current receipt must not contain a research write")
        return receipt, None
    if saved is None:
        raise ValueError("Recovery decision lost its native operation receipt")
    operation, encoded, native_fingerprint = saved
    if (
        receipt["state"] != "saved_locally"
        or receipt["operation_id"] != request_id
        or receipt["operation_fingerprint"] != native_fingerprint
        or type(receipt["sequence"]) is not int
        or receipt["sequence"] <= 0
        or any(
            receipt[key] != operation[key]
            for key in ("workspace_id", "device_id", "entity_type", "entity_id")
        )
    ):
        raise ValueError("Recovery decision and native operation disagree")
    actual = conn.execute(
        "SELECT sequence FROM paperfact_sync_operations WHERE operation_id=?",
        (request_id,),
    ).fetchone()[0]
    if receipt["sequence"] != actual:
        raise ValueError("Recovery decision sequence changed")
    return receipt, encoded


def _write_receipt(conn, request_id, fingerprint, receipt):
    from paper_daily.store import now

    encoded = candidates._json(receipt)
    if len(encoded.encode("utf-8")) > MAX_RECEIPT:
        raise ValueError("Recovery decision receipt exceeds its output budget")
    conn.execute(
        "INSERT INTO integration_operations VALUES(?,?,?,?)",
        (request_id, fingerprint, encoded, now()),
    )


def _result(receipt, *, applied, reused):
    return dict(
        receipt,
        applied=applied,
        request_reused=reused,
        replayed=False,
        source_discarded=False,
        recovery_complete=False,
        originals_verified=False,
        remote_accepted=None,
        remote_acceptance_checked=False,
    )


@dataclass(frozen=True)
class Decision:
    observed: object = field(repr=False)
    change_id: str
    request_id: str
    fingerprint: str = field(repr=False)
    receipt_json: str = field(repr=False)
    operation_json: str | None = field(repr=False)
    _seal: str = field(repr=False)

    def apply(self, *, seconds=30, cancelled=lambda: False):
        check = backup._guard(seconds, cancelled)
        native._auth(self.observed, check)
        expected = _seal(
            self.observed,
            self.change_id,
            self.request_id,
            self.fingerprint,
            [self.receipt_json, self.operation_json],
        )
        if not hmac.compare_digest(expected, self._seal):
            raise ValueError("Use the original prepared recovery decision")
        path = self.observed.database
        with closing(
            sqlite3.connect(
                path.as_uri() + "?mode=rw", uri=True, timeout=0.1, factory=CaptureConnection
            )
        ) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.set_progress_handler(lambda: (check(), 0)[1], 1000)
                native._binding_in(conn, self.observed)
                receipt = backup._decode(self.receipt_json)
                previous = _prior(conn, self.request_id, self.fingerprint, receipt)
                if previous is not None:
                    receipt, encoded = previous
                    if encoded != self.operation_json:
                        raise ValueError("Prepared recovery differs from its stored decision")
                    check()
                    return _result(receipt, applied=False, reused=True)
                self.observed._check(check)
                if _operation(conn, self.request_id) is not None:
                    raise ValueError("Recovery request collides with another native operation")
                client = conn._capture_client
                if client is None:
                    raise ValueError("Recovery requires the actual native target writer")
                if self.operation_json is not None:
                    operation = backup._decode(self.operation_json)
                    saved = client.journal.apply_in(conn, operation, client.writer)
                    if not saved["applied"]:
                        raise ValueError(
                            "Recovery native write lacks its matching decision receipt"
                        )
                    receipt["sequence"] = saved["sequence"]
                _write_receipt(conn, self.request_id, self.fingerprint, receipt)
                self.observed.source._check(check)
                native._binding_in(conn, self.observed)
                if tuple(generation._identity(path)) != self.observed.identity:
                    raise ValueError("Recovery target database was replaced")
                check()
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return _result(receipt, applied=self.operation_json is not None, reused=False)


def _build(conn, observed, comparison, choice, request_id):
    source = comparison["source"]["operation"]
    if choice == "keep":
        return None
    if source["version"] != 2 or source["entity_type"] not in KINDS or source["action"] != "put":
        raise ValueError("This content requires its own typed recovery action; retain it pending")
    blockers = set(comparison["blocking_reasons"])
    if choice == "restore":
        blockers.discard("target_restore_requires_confirmation")
    if blockers:
        raise ValueError("Resolve exact parent/source requirements before this recovery choice")
    current = comparison["target"]["entity_state"]
    if choice == "add" and current is not None:
        raise ValueError("Add requires an absent target; inspect replace or restore explicitly")
    if choice == "replace" and (current is None or not current["active"]):
        raise ValueError("Replace requires an active target; inspect add or restore explicitly")
    if choice == "restore" and (current is None or current["active"]):
        raise ValueError("Restore requires a known deleted target")
    client = conn._capture_client
    if source["entity_type"] in ORDERS:
        operation = client.new_order_operation_in(
            conn,
            source["entity_type"],
            source["entity_id"],
            [item["id"] for item in source["payload"]["items"]],
            operation_id=request_id,
            restore=choice == "restore",
        )
        if operation["payload"]["items"] != source["payload"]["items"]:
            raise ValueError("Ordering member lifetimes changed; review a new complete order")
    else:
        operation = client.new_graph_operation_in(
            conn,
            source["entity_type"],
            source["entity_id"],
            source["payload"],
            operation_id=request_id,
            restore=choice == "restore",
        )
    if operation["parents"] != source["parents"]:
        raise ValueError("Recovery must preserve the exact observed parent lifetimes")
    return canonical_operation(operation)


def prepare(observed, change_id, choice, request_id, *, seconds=30, cancelled=lambda: False):
    """Review explicit keep/add/replace/restore; never convert arbitrary research."""
    _identifier(request_id)
    if not isinstance(choice, str) or choice not in CHOICES:
        raise ValueError("Choose keep, add, replace or restore explicitly")
    check = backup._guard(seconds, cancelled)
    native._auth(observed, check)
    comparison = observed.compare(change_id, seconds=seconds, cancelled=cancelled)
    source = comparison["source"]["operation"]
    fingerprint = _fingerprint(observed, source, choice)
    context = dict(
        format=FORMAT,
        state="kept_current" if choice == "keep" else "saved_locally",
        request_id=request_id,
        choice=choice,
        source_workspace_id=source["workspace_id"],
        source_device_id=source["device_id"],
        source_operation_id=source["operation_id"],
        source_fingerprint=candidates._fingerprint(source),
        workspace_id=observed.binding["workspace_id"],
        device_id=observed.binding["device_id"],
        entity_type=source["entity_type"],
        entity_id=source["entity_id"],
    )
    with closing(_readonly_connection(observed.database)) as conn:
        conn.execute("BEGIN")
        native._binding_in(conn, observed)
        previous = _prior(conn, request_id, fingerprint, context)
        if previous is not None:
            receipt, encoded = previous
        else:
            if _operation(conn, request_id) is not None:
                raise ValueError("Recovery request collides with another native operation")
            encoded = _build(conn, observed, comparison, choice, request_id)
            operation = json.loads(encoded) if encoded is not None else None
            receipt = dict(
                context,
                operation_id=request_id if operation is not None else None,
                operation_fingerprint=candidates._fingerprint(operation)
                if operation is not None
                else None,
                sequence=None,
            )
    observed._check(check)
    receipt_json = candidates._json(receipt)
    return Decision(
        observed,
        change_id,
        request_id,
        fingerprint,
        receipt_json,
        encoded,
        _seal(observed, change_id, request_id, fingerprint, [receipt_json, encoded]),
    )
