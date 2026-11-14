"""Rebuild one backed-up authority workspace under an explicit fresh identity."""

from __future__ import annotations

import json
import os
from contextlib import closing
from itertools import zip_longest
from pathlib import Path

from paper_daily import sync_authority_backup as backup
from paper_daily.sync_blob_service import BLOB_CHUNK_BYTES
from paper_daily.sync_journal import ID
from paper_daily.sync_service import ReferenceService

TABLES = {
    "sync_devices",
    "sync_events",
    "sync_heads",
    "sync_graph",
    "sync_blob_namespaces",
    "sync_workspace_blobs",
    "sync_blob_uploads",
    "sync_blob_integrity",
    "sync_blob_blocks",
}


def _remap(operation, workspace):
    if operation is not None:
        from paper_daily.sync_ordering import ORDER_KINDS, observed_set

        # Ordering CAS is scoped to its workspace. Re-key only a proof that is
        # self-consistent with the supplied observed membership set. Opaque stale
        # proofs stay opaque; exact replay must still preserve their conflict.
        rekey = (
            operation["entity_type"] in ORDER_KINDS
            and operation["action"] == "put"
            and operation["payload"]["observed_set"]
            == observed_set(operation, operation["payload"]["items"])
        )
        operation["workspace_id"] = workspace
        if rekey:
            operation["payload"]["observed_set"] = observed_set(
                operation, operation["payload"]["items"]
            )
    return operation


def _event(raw, workspace):
    value = backup._decode(raw)
    _remap(value["operation"], workspace)
    _remap(value["head"]["operation"], workspace)
    return value


def _scope(conn, workspace, replacement):
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if tables != TABLES:
        raise ValueError("Authority recovery requires the supported reference schema")
    known = set()
    for table in (
        "sync_devices",
        "sync_events",
        "sync_heads",
        "sync_graph",
        "sync_workspace_blobs",
        "sync_blob_namespaces",
        "sync_blob_uploads",
    ):
        known.update(row[0] for row in conn.execute(f"SELECT DISTINCT workspace FROM {table}"))
    if workspace not in known:
        raise ValueError("Select an existing backed-up workspace")
    if replacement in known:
        raise ValueError("Recovery requires a fresh workspace identity")


def _same_state(source, service, old, new, check):
    with service._transaction() as restored:
        for table, field in (("sync_heads", "operation"), ("sync_graph", "metadata")):
            revision = ",revision" if table == "sync_heads" else ""
            sql = (
                f"SELECT entity_type,entity_id,{field}{revision} FROM {table} "
                "WHERE workspace=? ORDER BY entity_type,entity_id"
            )
            for before, after in zip_longest(
                source.execute(sql, (old,)), restored.execute(sql, (new,))
            ):
                check()
                if before is None or after is None:
                    raise ValueError("Recovered research heads or lifecycle state differ")
                expected, actual = backup._decode(before[2]), backup._decode(after[2])
                if field == "operation":
                    _remap(expected, new)
                if (
                    tuple(before[:2]) != tuple(after[:2])
                    or expected != actual
                    or tuple(before[3:]) != tuple(after[3:])
                ):
                    raise ValueError("Recovered research heads or lifecycle state differ")


def restore(
    snapshot,
    state,
    workspace,
    replacement,
    *,
    seconds=30,
    cancelled=lambda: False,
    progress=lambda _value: None,
):
    """Rebuild a new service, retain provenance, discard sessions; never start it.

    Only the selected workspace is restored. Event/graph identity is preserved
    except for its new workspace ID. Every event must replay to its exact prior
    accepted/conflict outcome. Old devices and unfinished uploads are not restored.
    Publication of the service marker is the final success boundary.
    """
    from paper_daily.sync_admin import DATABASE, FORMAT, MARKER

    for value in (workspace, replacement):
        if not isinstance(value, str) or not ID.fullmatch(value):
            raise ValueError("Use bounded workspace identifiers")
    if workspace == replacement:
        raise ValueError("Recovery requires a fresh workspace identity")
    check = backup._guard(seconds, cancelled)
    root, target = backup._path(snapshot), backup._path(state)
    if root == target or root.is_relative_to(target) or target.is_relative_to(root):
        raise ValueError("Keep recovery state separate from its backup")
    if target.exists():
        raise FileExistsError("Choose a new recovery directory")
    manifest = root / backup.MANIFEST
    progress({"phase": "verify"})
    _receipt, value, before, identities = backup._inspect(
        root, seconds=seconds, cancelled=lambda: (check(), False)[1]
    )

    def live():
        check()
        if backup._identity(manifest) != before:
            raise ValueError("Backup changed during recovery")

    live()
    if any(backup._identity(root / name) != identity for name, identity in identities.items()):
        raise ValueError("Backup changed after verification")

    with closing(backup._connect(root / DATABASE)) as source:
        source.execute("BEGIN")
        backup._schema(source, live)
        _scope(source, workspace, replacement)
        count = source.execute(
            "SELECT count(*) FROM sync_events WHERE workspace=?", (workspace,)
        ).fetchone()[0]
        omitted = source.execute(
            "SELECT count(*) FROM sync_blob_uploads WHERE workspace=? AND state='open'",
            (workspace,),
        ).fetchone()[0]
        devices = source.execute(
            "SELECT count(*) FROM sync_devices WHERE workspace=?", (workspace,)
        ).fetchone()[0]
        objects = source.execute(
            "SELECT n.directory,b.digest,b.size FROM sync_workspace_blobs b "
            "JOIN sync_blob_namespaces n ON n.workspace=b.workspace "
            "WHERE b.workspace=? AND b.state='committed' ORDER BY b.digest",
            (workspace,),
        )
        live()
        target.mkdir(mode=0o700)
        service = ReferenceService(target / DATABASE, blob_root=target / "blobs")
        os.chmod(target / DATABASE, 0o600)
        tokens = {}

        def token(device):
            if device not in tokens:
                tokens[device] = service.enroll(replacement, device)
            return tokens[device]

        copied, size = 0, 0
        for directory, digest, length in objects:
            live()
            name = f"blobs/{directory}/objects/{digest}"
            path = root / name
            if backup._identity(path) != identities[name]:
                raise ValueError("Backup object changed before recovery")
            declared = {"sha256": digest, "size": length}
            credential = token("recovery-helper")
            upload = service.blob_begin(credential, declared)
            if not upload["complete"]:
                with path.open("rb") as stream:
                    info = os.fstat(stream.fileno())
                    if (info.st_dev, info.st_ino) != identities[name][:2]:
                        raise ValueError("Backup object changed before opening")
                    offset = 0
                    while chunk := stream.read(BLOB_CHUNK_BYTES):
                        live()
                        result = service.blob_append(credential, upload["upload_id"], offset, chunk)
                        offset = result["offset"]
                service.blob_commit(credential, upload["upload_id"])
            if backup._identity(path) != identities[name]:
                raise ValueError("Backup object changed during recovery")
            copied += 1
            size += length
            progress({"phase": "objects", "objects": copied, "bytes": size})
        replayed = 0
        for (raw,) in source.execute(
            "SELECT event FROM sync_events WHERE workspace=? ORDER BY sequence", (workspace,)
        ):
            live()
            expected = _event(raw, replacement)
            operation = expected["operation"]
            actual = service.push(token(operation["device_id"]), operation)
            if actual != expected:
                raise ValueError("Recovery changed an accepted or conflicting event")
            replayed += 1
            progress({"phase": "events", "events": replayed, "total": count})
        live()
        _same_state(source, service, workspace, replacement, live)
        # Tokens existed only to use the ordinary validated reconstruction paths.
        # No source token hash, device session or label survives in active state.
        with service._transaction(write=True) as conn:
            conn.execute("DELETE FROM sync_devices")
        tokens.clear()
        live()
        for name, identity in identities.items():
            if backup._identity(root / name) != identity:
                raise ValueError("Backup changed during recovery")
        if replayed != count:
            raise ValueError("Recovery did not retain every selected event")
        receipt = {
            "state": "restored",
            "workspace_id": replacement,
            "events": replayed,
            "objects": copied,
            "bytes": size,
            "unfinished_uploads_discarded": omitted,
            "previous_devices_discarded": devices,
            "requires_enrollment": True,
        }
        provenance = {
            "format": "paperfact-authority-recovery-v1",
            **receipt,
            "source_workspace_id": workspace,
            "source_database_sha256": next(
                item["sha256"] for item in value["files"] if item["path"] == DATABASE
            ),
        }
        backup._write(
            target / "recovery.json",
            lambda stream: stream.write(json.dumps(provenance, sort_keys=True).encode("utf-8")),
        )
        # Flush the new state before making the authority recognizable to serve.
        for folder, _dirs, files in os.walk(target, topdown=False):
            live()
            for filename in files:
                with (Path(folder) / filename).open("r+b") as stream:
                    os.fsync(stream.fileno())
            backup._sync_directory(Path(folder))
        backup._write(
            target / ".service.pending",
            lambda stream: stream.write(json.dumps(FORMAT).encode("utf-8")),
        )
        live()
        (target / ".service.pending").rename(target / MARKER)
        backup._sync_directory(target)
        backup._sync_directory(target.parent)
    return receipt
