"""Read-only comparison of one old device journal with a verified authority backup."""

from __future__ import annotations

import hashlib
from collections import Counter
from contextlib import closing

from paper_daily import file_change
from paper_daily import sync_authority_backup as backup
from paper_daily.sync_client import validate_event
from paper_daily.sync_journal import MAX_BYTES, _identifier, canonical_operation
from paper_daily.workspace_service import _binding, _tables

MAX_RECORDS = 100_000
MAX_EVENT = 2 * MAX_BYTES + 8192


def _version(path):
    result = []
    for candidate in (path, path.with_name(path.name + "-wal")):
        backup._path(candidate)
        observed = file_change.version(candidate) if candidate.exists() else None
        # A read-only WAL open/close can create/remove a zero-byte sidecar. It has
        # no header or transaction pages. Keep strict versions for the main file
        # and every nonempty WAL; real commits/checkpoints still invalidate leases.
        result.append(None if candidate != path and observed and observed[2] == 0 else observed)
    return tuple(result)


def review(database, snapshot, workspace, *, seconds=30, cancelled=lambda: False):
    """Count observed work beyond an exact backup without transferring authority.

    This is neither a replay plan nor complete research/file preservation. A null
    journal acknowledgment can mean an unsent operation or a lost server reply.
    Keep the old workspace and make an independent research backup before migration.
    """
    _identifier(workspace)
    check = backup._guard(seconds, cancelled)
    check()
    database, root = backup._path(database), backup._path(snapshot)
    if database.is_relative_to(root):
        raise ValueError("Keep the device database and authority backup separate")
    _receipt, _manifest, marker_identity, identities = backup._inspect(
        root, seconds=seconds, cancelled=lambda: (check(), False)[1]
    )
    observed = _version(database)
    if observed[0] is None:
        raise ValueError("Select an existing device database")
    counts = Counter(
        journal_already_in_backup=0,
        unconfirmed_not_in_backup=0,
        acknowledged_after_backup=0,
        received_after_backup=0,
    )
    domains = Counter()
    with (
        closing(backup._connect(database)) as local,
        closing(backup._connect(root / "authority.sqlite")) as remote,
    ):
        for conn in (local, remote):
            conn.set_progress_handler(lambda: (check(), 0)[1], 1000)
            conn.execute("BEGIN")
        tables = _tables(local)
        required = {
            "paperfact_sync_identity",
            "paperfact_sync_cursor",
            "paperfact_sync_inbox",
            "paperfact_sync_operations",
        }
        if not required <= tables:
            raise ValueError("Select an existing journal with a received-event cursor")
        bindings = dict(_binding(local, tables))
        identity = bindings["paperfact_sync_identity"]
        if identity[0] != workspace:
            raise ValueError("Device and backed-up workspace differ")
        _identifier(identity[1])
        known = remote.execute(
            "SELECT 1 FROM sync_devices WHERE workspace=? LIMIT 1", (workspace,)
        ).fetchone()
        if not known:
            raise ValueError("Select an existing backed-up workspace")
        backed = remote.execute(
            "SELECT coalesce(max(sequence),0) FROM sync_events WHERE workspace=?", (workspace,)
        ).fetchone()[0]
        rows = local.execute("SELECT sequence FROM paperfact_sync_cursor LIMIT 2").fetchall()
        if len(rows) != 1 or type(rows[0][0]) is not int or rows[0][0] < 0:
            raise ValueError("Device cursor is invalid")
        cursor = rows[0][0]
        if cursor > MAX_RECORDS:
            raise ValueError("Device review record budget exceeded")
        previous = 0
        for sequence, raw, outcome in local.execute(
            "SELECT sequence,CASE WHEN length(CAST(event AS BLOB))<=? THEN event END,outcome "
            "FROM paperfact_sync_inbox ORDER BY sequence",
            (MAX_EVENT,),
        ):
            check()
            if raw is None or sequence != previous + 1 or sequence > cursor:
                raise ValueError("Device received history is incomplete or oversized")
            event = backup._decode(raw)
            validate_event(event, workspace)
            if event["sequence"] != sequence or event["outcome"] != outcome:
                raise ValueError("Device received receipt is inconsistent")
            if sequence <= backed:
                match = remote.execute(
                    "SELECT event FROM sync_events WHERE workspace=? AND sequence=?",
                    (workspace, sequence),
                ).fetchone()
                if match is None or backup._decode(match[0]) != event:
                    raise ValueError("Device and backup do not share the exact received prefix")
            else:
                counts["received_after_backup"] += 1
            previous = sequence
        if previous != cursor:
            raise ValueError("Device cursor exceeds retained received history")
        for total, (op_id, fingerprint, kind, entity, raw, revision) in enumerate(
            local.execute(
                "SELECT operation_id,fingerprint,entity_type,entity_id,"
                "CASE WHEN length(CAST(envelope AS BLOB))<=? THEN envelope END,server_revision "
                "FROM paperfact_sync_operations ORDER BY sequence",
                (MAX_BYTES,),
            ),
            1,
        ):
            check()
            if total > MAX_RECORDS or raw is None:
                raise ValueError("Device journal exceeds the bounded review budget")
            operation = backup._decode(raw)
            encoded = canonical_operation(operation)
            if (
                hashlib.sha256(encoded.encode("utf-8")).hexdigest() != fingerprint
                or (operation["workspace_id"], operation["device_id"]) != identity
                or (operation["operation_id"], operation["entity_type"], operation["entity_id"])
                != (op_id, kind, entity)
                or revision is not None
                and (type(revision) is not int or revision < 1)
            ):
                raise ValueError("Device journal receipt is inconsistent")
            match = remote.execute(
                "SELECT sequence,fingerprint FROM sync_events WHERE workspace=? AND operation_id=?",
                (workspace, op_id),
            ).fetchone()
            if match:
                if match[1] != fingerprint or revision not in (None, match[0]):
                    raise ValueError("Device operation differs from its backed-up receipt")
                counts["journal_already_in_backup"] += 1
            else:
                if revision is not None and revision <= backed:
                    raise ValueError("Device acknowledgment differs from the backed-up prefix")
                category = (
                    "unconfirmed_not_in_backup" if revision is None else "acknowledged_after_backup"
                )
                counts[category] += 1
                domains[kind] += 1
    check()
    if (
        _version(database) != observed
        or backup._identity(root / backup.MANIFEST) != marker_identity
        or any(backup._identity(root / name) != value for name, value in identities.items())
    ):
        raise ValueError("Device or backup changed during review; retry the read-only comparison")
    return {
        "state": "reviewed",
        "workspace_id": workspace,
        "device_id": identity[1],
        "backup_sequence": backed,
        "device_cursor": cursor,
        "device_behind_by": max(0, backed - cursor),
        **counts,
        "uncovered_journal_domains": dict(sorted(domains.items())),
        "requires_preservation": any(
            counts[key]
            for key in (
                "unconfirmed_not_in_backup",
                "acknowledged_after_backup",
                "received_after_backup",
            )
        ),
        "replayed": False,
        "research_and_files_fully_audited": False,
    }
