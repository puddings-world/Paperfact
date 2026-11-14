"""Read-only, process-sealed per-change observations beyond a verified backup.

This is a preservation review input, never an operation replay or file grant.
All domains remain visible; actual reconciliation requires separate typed actions.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from contextlib import closing
from dataclasses import dataclass, field

from paper_daily import sync_authority_backup as backup
from paper_daily import sync_device_recovery as review
from paper_daily.sync_client import validate_event
from paper_daily.sync_journal import MAX_BYTES, canonical_operation

FORMAT = "paperfact.device-recovery-candidates.v1"
_KEY = secrets.token_bytes(32)
MAX_INDEX_BYTES = 16 * 1024 * 1024
MAX_PAGE = 50


def _json(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def _versions(database, root):
    return tuple(
        (str(path), review._version(path))
        for path in (database, root / "authority.sqlite", root / backup.MANIFEST)
    )


def _sign(database, root, workspace, summary, rows, versions, nonce):
    message = _json([str(database), str(root), workspace, summary, rows, versions, nonce])
    return hmac.new(_KEY, message.encode("utf-8"), "sha256").hexdigest()


def _fingerprint(operation):
    return hashlib.sha256(canonical_operation(operation).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReviewIndex:
    database: object = field(repr=False)
    snapshot: object = field(repr=False)
    workspace: str
    _summary_json: str = field(repr=False)
    _rows_json: str = field(repr=False)
    _versions: tuple = field(repr=False)
    _nonce: str = field(repr=False)
    _seal: str = field(repr=False)

    def _check(self, check):
        check()
        expected = _sign(
            self.database,
            self.snapshot,
            self.workspace,
            self._summary_json,
            self._rows_json,
            self._versions,
            self._nonce,
        )
        if not hmac.compare_digest(expected, self._seal):
            raise ValueError("Recovery review requires its original prepared observation")
        if _versions(self.database, self.snapshot) != self._versions:
            raise ValueError("Recovery inputs changed; prepare a new review")

    def page(self, *, after=0, limit=20, seconds=30, cancelled=lambda: False):
        check = backup._guard(seconds, cancelled)
        self._check(check)
        if (
            type(after) is not int
            or after < 0
            or type(limit) is not int
            or not 1 <= limit <= MAX_PAGE
        ):
            raise ValueError("Use a nonnegative offset and a page limit from 1 to 50")
        rows = json.loads(self._rows_json)
        if after > len(rows):
            raise ValueError("Recovery offset exceeds the prepared change count")
        end = min(after + limit, len(rows))
        result = dict(
            format=FORMAT,
            state="review_candidates",
            items=rows[after:end],
            change_count=len(rows),
            next_offset=end if end < len(rows) else None,
            summary=json.loads(self._summary_json),
            replayed=False,
            research_and_files_fully_audited=False,
        )
        self._check(check)
        return result

    def details(self, change_id, *, seconds=30, cancelled=lambda: False):
        check = backup._guard(seconds, cancelled)
        self._check(check)
        if (
            not isinstance(change_id, str)
            or len(change_id) != 64
            or any(letter not in "0123456789abcdef" for letter in change_id)
        ):
            raise ValueError("Select a change from this prepared review")
        selected = next(
            (
                row
                for row in json.loads(self._rows_json)
                if hmac.compare_digest(row["change_id"], change_id)
            ),
            None,
        )
        if selected is None:
            raise ValueError("Select a change from this prepared review")
        with closing(backup._connect(self.database)) as conn:
            conn.set_progress_handler(lambda: (check(), 0)[1], 1000)
            conn.execute("BEGIN")
            event = None
            if selected["stream"] == "journal":
                raw = conn.execute(
                    "SELECT CASE WHEN length(CAST(envelope AS BLOB))<=? THEN envelope END "
                    "FROM paperfact_sync_operations WHERE sequence=? AND operation_id=?",
                    (MAX_BYTES, selected["local_sequence"], selected["operation_id"]),
                ).fetchone()
                if raw is None or raw[0] is None:
                    raise ValueError("Selected recovery operation is unavailable")
                operation = backup._decode(raw[0])
            else:
                operation = None
            if selected["received_sequence"] is not None:
                raw = conn.execute(
                    "SELECT CASE WHEN length(CAST(event AS BLOB))<=? THEN event END "
                    "FROM paperfact_sync_inbox WHERE sequence=?",
                    (review.MAX_EVENT, selected["received_sequence"]),
                ).fetchone()
                if raw is None or raw[0] is None:
                    raise ValueError("Selected received change is unavailable")
                event = backup._decode(raw[0])
                validate_event(event, self.workspace)
                if operation is None:
                    operation = event["operation"]
                elif event["operation"] != operation:
                    raise ValueError("Selected local and received changes disagree")
            if (
                operation["workspace_id"] != self.workspace
                or _fingerprint(operation) != selected["fingerprint"]
            ):
                raise ValueError("Selected recovery operation changed")
        self._check(check)
        return dict(
            change=selected,
            operation=operation,
            received_event=event,
            replayed=False,
            files_verified_for_change=False,
            payload_is_private=True,
        )


def prepare(database, snapshot, workspace, *, seconds=30, cancelled=lambda: False):
    check = backup._guard(seconds, cancelled)
    check()
    database, root = backup._path(database), backup._path(snapshot)
    before = _versions(database, root)
    summary = review.review(
        database, root, workspace, seconds=seconds, cancelled=lambda: (check(), False)[1]
    )
    if _versions(database, root) != before:
        raise ValueError("Recovery inputs changed; prepare a new review")
    rows, positions, received_ids = [], {}, set()
    nonce = secrets.token_hex(32)
    total_bytes = 0

    def add(operation, stream, local_sequence, category):
        nonlocal total_bytes
        fingerprint = _fingerprint(operation)
        row = dict(
            protocol_version=operation["version"],
            stream=stream,
            local_sequence=local_sequence,
            received_sequence=None,
            received_outcome=None,
            operation_id=operation["operation_id"],
            fingerprint=fingerprint,
            entity_type=operation["entity_type"],
            entity_id=operation["entity_id"],
            action=operation["action"],
            category=category,
        )
        row["change_id"] = hmac.new(_KEY, _json([nonce, row]).encode("utf-8"), "sha256").hexdigest()
        total_bytes += len(_json(row).encode("utf-8")) + 2
        if len(rows) >= review.MAX_RECORDS or total_bytes > MAX_INDEX_BYTES:
            raise ValueError("Recovery candidate index budget exceeded")
        positions[operation["operation_id"]] = len(rows)
        rows.append(row)
        return row

    with (
        closing(backup._connect(database)) as local,
        closing(backup._connect(root / "authority.sqlite")) as remote,
    ):
        for conn in (local, remote):
            conn.set_progress_handler(lambda: (check(), 0)[1], 1000)
            conn.execute("BEGIN")
        for sequence, raw, revision in local.execute(
            "SELECT sequence,CASE WHEN length(CAST(envelope AS BLOB))<=? THEN envelope END,"
            "server_revision FROM paperfact_sync_operations ORDER BY sequence",
            (MAX_BYTES,),
        ):
            check()
            if raw is None:
                raise ValueError("Recovery operation exceeds its input budget")
            operation = backup._decode(raw)
            canonical_operation(operation)
            found = remote.execute(
                "SELECT 1 FROM sync_events WHERE workspace=? AND operation_id=?",
                (workspace, operation["operation_id"]),
            ).fetchone()
            if found:
                continue
            add(
                operation,
                "journal",
                sequence,
                "unconfirmed_not_in_backup" if revision is None else "acknowledged_after_backup",
            )
        for sequence, raw in local.execute(
            "SELECT sequence,CASE WHEN length(CAST(event AS BLOB))<=? THEN event END "
            "FROM paperfact_sync_inbox WHERE sequence>? ORDER BY sequence",
            (review.MAX_EVENT, summary["backup_sequence"]),
        ):
            check()
            if raw is None:
                raise ValueError("Received recovery event exceeds its input budget")
            event = backup._decode(raw)
            validate_event(event, workspace)
            operation = event["operation"]
            identity = operation["operation_id"]
            if identity in received_ids:
                raise ValueError("Received recovery history repeats an operation identity")
            received_ids.add(identity)
            if remote.execute(
                "SELECT 1 FROM sync_events WHERE workspace=? AND operation_id=?",
                (workspace, identity),
            ).fetchone():
                raise ValueError("Received recovery event contradicts the backup identity")
            if identity in positions:
                row = rows[positions[identity]]
                if row["fingerprint"] != _fingerprint(operation):
                    raise ValueError("Local and received recovery changes disagree")
            else:
                row = add(operation, "received", None, "received_after_backup")
            row.update(received_sequence=sequence, received_outcome=event["outcome"])
    check()
    if _versions(database, root) != before:
        raise ValueError("Recovery inputs changed; prepare a new review")
    summary_json, rows_json = _json(summary), _json(rows)
    if len(rows_json.encode("utf-8")) > MAX_INDEX_BYTES:
        raise ValueError("Recovery candidate index budget exceeded")
    return ReviewIndex(
        database,
        root,
        workspace,
        summary_json,
        rows_json,
        before,
        nonce,
        _sign(database, root, workspace, summary_json, rows_json, before, nonce),
    )
