"""Local reference sync authority for isolated tests and transport integration.

Administrative enrollment/revocation remain trusted seams. Device pairing is explicit.
Attachment storage is optional and explicit; no HTTP, identity provider or AI calls.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import stat
from contextlib import contextmanager, nullcontext
from pathlib import Path

from paper_daily.sync_blob_service import BlobServiceMixin
from paper_daily.sync_device_management import DeviceManagementMixin
from paper_daily.sync_graph import apply_accepted, check_preconditions
from paper_daily.sync_journal import (
    ID,
    MAX_BYTES,
    SyncHistoryAdvanced,
    SyncHistoryUnavailable,
    canonical_operation,
    history_seed,
    history_step,
)
from paper_daily.sync_ordering import ORDER_KINDS, validate_order


class AuthorityInUseError(ValueError):
    """Another cooperating listener still owns this local authority database."""


class ReferenceService(BlobServiceMixin, DeviceManagementMixin):
    """Serialize workspace changes and retain conflicting operations durably."""

    def __init__(
        self,
        path: Path,
        *,
        blob_root: Path | None = None,
        blob_quota_bytes: int = 4 * 1024**3,
        blob_max_bytes: int = 150 * 1024**2,
        blob_max_uploads: int = 16,
        expected_database_identity: tuple[int, int] | None = None,
        authority_marker: Path | None = None,
    ):
        if (expected_database_identity is not None and (
                not isinstance(expected_database_identity, tuple)
                or len(expected_database_identity) != 2
                or any(type(value) is not int for value in expected_database_identity)
                or expected_database_identity[0] < 0 or expected_database_identity[1] <= 0)):
            raise ValueError("Invalid expected authority database identity")
        if authority_marker is not None and expected_database_identity is None:
            raise ValueError("A control marker requires the expected authority database identity")
        self._authority_marker = Path(authority_marker) if authority_marker is not None else None
        self._configure_blobs(blob_root, blob_quota_bytes, blob_max_bytes, blob_max_uploads)
        self.path = Path(path).absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._database_identity = None
        if self.path.exists() or self.path.is_symlink():
            self._database_identity = self._database_file_identity()
        if (expected_database_identity is not None
                and self._database_identity != expected_database_identity):
            raise SyncHistoryUnavailable("Authority database identity changed before opening")
        with self._transaction(write=True) as conn:
            self._blob_schema(conn)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sync_devices ("
                "token_hash TEXT PRIMARY KEY, workspace TEXT NOT NULL, device TEXT NOT NULL, "
                "revoked INTEGER NOT NULL DEFAULT 0, UNIQUE(workspace,device))"
            )
            self._device_schema(conn)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sync_events ("
                "workspace TEXT NOT NULL, sequence INTEGER NOT NULL, operation_id TEXT NOT NULL, "
                "fingerprint TEXT NOT NULL, event TEXT NOT NULL, "
                "PRIMARY KEY(workspace,sequence), UNIQUE(workspace,operation_id))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sync_heads ("
                "workspace TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, "
                "revision INTEGER NOT NULL, operation TEXT NOT NULL, "
                "PRIMARY KEY(workspace,entity_type,entity_id))"
            )

            conn.execute(
                "CREATE TABLE IF NOT EXISTS sync_graph ("
                "workspace TEXT NOT NULL,entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,"
                "metadata TEXT NOT NULL,PRIMARY KEY(workspace,entity_type,entity_id))"
            )

            conn.execute(
                "CREATE TABLE IF NOT EXISTS sync_history ("
                "workspace TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence>0),"
                "sha256 TEXT NOT NULL CHECK(length(sha256)=64),"
                "PRIMARY KEY(workspace,sequence))"
            )

    @contextmanager
    def listener_claim(self):
        """Own this local database until the listener and its request workers drain."""
        from paper_daily.research_job_lock import claim
        from paper_daily.sync_blobs import _no_link

        self._require_database_identity()
        candidate = self.path.absolute()
        for part in (candidate, *candidate.parents):
            _no_link(part)
        database = candidate.resolve(strict=True)
        if not database.is_file() or database.stat().st_nlink != 1:
            raise ValueError("Serve a regular authority database without hard-link aliases")
        _no_link(database.parent / ".research-jobs")
        with claim(database, "sync-authority-listener", "authority") as acquired:
            if not acquired:
                raise AuthorityInUseError("This authority already has an active local listener")
            self._require_database_identity()
            yield

    @staticmethod
    def _graph_entity(conn, workspace, kind, identity):
        row = conn.execute(
            "SELECT metadata FROM sync_graph WHERE workspace=? AND entity_type=? AND entity_id=?",
            (workspace, kind, identity),
        ).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _set_graph_entity(conn, workspace, kind, identity, value):
        conn.execute(
            "INSERT INTO sync_graph VALUES(?,?,?,?) "
            "ON CONFLICT(workspace,entity_type,entity_id) DO UPDATE SET metadata=excluded.metadata",
            (workspace, kind, identity, json.dumps(value, sort_keys=True, separators=(",", ":"))),
        )

    def _database_file_identity(self):
        try:
            info = self.path.lstat()
        except OSError as error:
            raise SyncHistoryUnavailable("Authority database lifetime is unavailable") from error
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_ino <= 0:
            raise SyncHistoryUnavailable("Authority database lifetime changed")
        return info.st_dev, info.st_ino

    def _require_database_identity(self):
        if self._database_identity != self._database_file_identity():
            raise SyncHistoryUnavailable(
                "Authority database lifetime changed; stop and review recovery")

    @contextmanager
    def _transaction(self, *, write=False):
        from paper_daily import sync_authority_control as control

        existing = self._database_identity is not None
        if existing:
            self._require_database_identity()
        try:
            conn = (sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=10)
                    if existing else sqlite3.connect(self.path, timeout=10))
        except sqlite3.Error:
            if existing:
                self._require_database_identity()
            raise
        conn.row_factory = sqlite3.Row
        guarded = self._authority_marker is not None
        try:
            with control.transaction_lock(self.path) if guarded else nullcontext():
                if not existing:
                    self._database_identity = self._database_file_identity()
                self._require_database_identity()
                conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                self._require_database_identity()
                before = (control.observe(conn, self._authority_marker, self.path,
                                          self._database_identity) if guarded else None)
                yield conn
                self._require_database_identity()
                if guarded:
                    after = control.fingerprint(conn)
                    if after != before["control_sha256"]:
                        if not write:
                            raise SyncHistoryUnavailable("Unexpected read-only control change")
                        control.publish(self._authority_marker, self.path, before, after)
                conn.commit()
                self._require_database_identity()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _token_hash(token):
        if not isinstance(token, str) or not token or len(token) > 4096:
            raise PermissionError("Invalid or revoked sync credential")
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @classmethod
    def _authenticate(cls, conn, token):
        row = conn.execute(
            "SELECT workspace,device,revoked FROM sync_devices WHERE token_hash=?",
            (cls._token_hash(token),),
        ).fetchone()
        if row is None or row["revoked"]:
            raise PermissionError("Invalid or revoked sync credential")
        return row["workspace"], row["device"]

    @staticmethod
    def _high_water(conn, workspace):
        return conn.execute(
            "SELECT COALESCE(MAX(sequence),0) FROM sync_events WHERE workspace=?", (workspace,)
        ).fetchone()[0]

    def session_info(self, token: str) -> dict:
        """Read the authenticated immutable token binding without creating state.

        Transfer coordinators must compare both IDs to their local workspace and
        device before sending bytes, and repeat this for each session generation.
        """
        with self._transaction() as conn:
            workspace, device = self._authenticate(conn, token)
            return {"workspace_id": workspace, "device_id": device}

    def enroll(self, workspace_id: str, device_id: str, *, before_commit=None) -> str:
        """Trusted admin only: issue a token once for a new workspace/device pair."""
        for value in (workspace_id, device_id):
            if not isinstance(value, str) or not ID.fullmatch(value):
                raise ValueError("Invalid sync identifier")
        token = secrets.token_urlsafe(32)
        with self._transaction(write=True) as conn:
            found = conn.execute(
                "SELECT 1 FROM sync_devices WHERE workspace=? AND device=?",
                (workspace_id, device_id),
            ).fetchone()
            if found:
                raise ValueError("Device identity already enrolled; use a new device identity")
            conn.execute(
                "INSERT INTO sync_devices(token_hash,workspace,device) VALUES(?,?,?)",
                (self._token_hash(token), workspace_id, device_id),
            )
            if before_commit is not None:
                before_commit(token)
        return token

    def revoke(self, token: str) -> None:
        """Trusted admin only; repeated revocation of the same credential is safe."""
        token_hash = self._token_hash(token)
        with self._transaction(write=True) as conn:
            row = conn.execute(
                "SELECT 1 FROM sync_devices WHERE token_hash=?", (token_hash,)
            ).fetchone()
            if row is None:
                raise PermissionError("Invalid or revoked sync credential")
            conn.execute("UPDATE sync_devices SET revoked=1 WHERE token_hash=?", (token_hash,))

    def push(self, token: str, operation: dict, *, checkpoint=None) -> dict:
        """Accept a causal edit or preserve it as a conflict; replay exactly once."""
        with self._transaction() as conn:
            workspace, _device = self._authenticate(conn, token)
            if checkpoint is not None:
                self._require_history(conn, workspace, checkpoint)
        # Close the envelope before verification so caller mutation cannot race it.
        encoded = canonical_operation(operation)
        operation = json.loads(encoded)
        prepared = self._prepare_research_file(token, operation, encoded)
        with self._transaction(write=True) as conn:
            workspace, device = self._authenticate(conn, token)
            if checkpoint is not None:
                self._require_history(conn, workspace, checkpoint)
            encoded = canonical_operation(operation)
            value = json.loads(encoded)
            if (value["workspace_id"], value["device_id"]) != (workspace, device):
                raise PermissionError("Operation does not belong to this workspace/device")
            fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            previous = conn.execute(
                "SELECT fingerprint,event FROM sync_events WHERE workspace=? AND operation_id=?",
                (workspace, value["operation_id"]),
            ).fetchone()
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise ValueError("Operation ID was reused with different content")
                return self._verified_result(
                    conn, workspace, json.loads(previous["event"]), checkpoint)

            if (checkpoint is not None
                    and checkpoint["sequence"] != self._high_water(conn, workspace)):
                raise SyncHistoryAdvanced("History advanced; receive before retrying this edit")

            self._require_document_blob(conn, workspace, value)
            self._require_prepared_file(conn, workspace, value, prepared)

            if "resolution_of" in value:
                target = conn.execute(
                    "SELECT event FROM sync_events WHERE workspace=? AND operation_id=?",
                    (workspace, value["resolution_of"]),
                ).fetchone()
                if target is None:
                    raise ValueError("Resolution refers to an unknown conflict")
                target = json.loads(target["event"])
                original = target["operation"]
                if target["outcome"] != "conflict" or (
                    original["entity_type"],
                    original["entity_id"],
                ) != (value["entity_type"], value["entity_id"]):
                    raise ValueError("Resolution must reference a conflict for this entity")
            key = (workspace, value["entity_type"], value["entity_id"])
            row = conn.execute(
                "SELECT revision,operation FROM sync_heads "
                "WHERE workspace=? AND entity_type=? AND entity_id=?",
                key,
            ).fetchone()
            head = {
                "revision": row["revision"] if row else 0,
                "operation": json.loads(row["operation"]) if row else None,
            }

            def get_entity(kind, identity):
                return self._graph_entity(conn, workspace, kind, identity)

            def get_receipt(identity):
                row = conn.execute(
                    "SELECT event FROM sync_events WHERE workspace=? AND operation_id=?",
                    (workspace, identity),
                ).fetchone()
                return json.loads(row[0]) if row else None

            if value["version"] == 1 and value["entity_type"] == "note":
                previous_note = head["operation"]
                if (
                    value["action"] == "delete"
                    and previous_note
                    and (
                        previous_note["action"] == "put"
                        and get_entity("paper", previous_note["payload"]["paper_id"]) is not None
                    )
                ):
                    raise ValueError("Version 1 cannot bypass an enrolled paper parent")
            graph_ready = check_preconditions(get_entity, get_receipt, value)
            from paper_daily import lineage_capacity, lineage_dependencies

            if graph_ready and lineage_dependencies.requires_readiness(value):
                graph_ready = lineage_capacity.authority_room_in(conn, value)
            if graph_ready and value["entity_type"] in ORDER_KINDS:
                graph = {
                    (row["entity_type"], row["entity_id"]): json.loads(row["metadata"])
                    for row in conn.execute(
                        "SELECT entity_type,entity_id,metadata FROM sync_graph WHERE workspace=?",
                        (workspace,),
                    )
                }
                graph_ready = validate_order(value, graph)
            base, parent_conflicted = value["base_revision"], False
            if value["depends_on"] is not None:
                parent = conn.execute(
                    "SELECT event FROM sync_events WHERE workspace=? AND operation_id=?",
                    (workspace, value["depends_on"]),
                ).fetchone()
                if parent is None:
                    raise ValueError("Missing predecessor")
                parent = json.loads(parent["event"])
                source = parent["operation"]
                if (source["device_id"], source["entity_type"], source["entity_id"]) != (
                    device,
                    value["entity_type"],
                    value["entity_id"],
                ):
                    raise ValueError("Unrelated predecessor")
                base = parent["sequence"]
                parent_conflicted = parent["outcome"] == "conflict"

            sequence = self._high_water(conn, workspace) + 1
            accepted = graph_ready and not parent_conflicted and base == head["revision"]
            if accepted:
                head = {"revision": sequence, "operation": value}
                conn.execute(
                    "INSERT INTO sync_heads VALUES(?,?,?,?,?) "
                    "ON CONFLICT(workspace,entity_type,entity_id) DO UPDATE SET "
                    "revision=excluded.revision,operation=excluded.operation",
                    (*key, sequence, encoded),
                )
                apply_accepted(
                    get_entity,
                    lambda kind, identity, metadata: self._set_graph_entity(
                        conn, workspace, kind, identity, metadata
                    ),
                    value,
                    sequence,
                )
            event = {
                "sequence": sequence,
                "outcome": "accepted" if accepted else "conflict",
                "operation": value,
                "head": head,
            }
            conn.execute(
                "INSERT INTO sync_events VALUES(?,?,?,?,?)",
                (
                    workspace,
                    sequence,
                    value["operation_id"],
                    fingerprint,
                    json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                ),
            )
            self._append_history(conn, workspace, sequence, event)
            return self._verified_result(conn, workspace, event, checkpoint)

    def pull(self, token: str, after: int = 0, limit: int = 100) -> list[dict]:
        """Read bounded workspace events after a durable client cursor."""
        with self._transaction() as conn:
            workspace, _device = self._authenticate(conn, token)
            if type(after) is not int or after < 0:
                raise ValueError("Invalid sync cursor")
            if type(limit) is not int or not 1 <= limit <= 1000:
                raise ValueError("Batch size must be between 1 and 1000")
            if after > self._high_water(conn, workspace):
                raise SyncHistoryUnavailable("Sync cursor is ahead of this workspace")
            rows = conn.execute(
                "SELECT event FROM sync_events WHERE workspace=? AND sequence>? "
                "ORDER BY sequence LIMIT ?",
                (workspace, after, limit),
            )
            return [json.loads(row["event"]) for row in rows]

    _history_seed = staticmethod(history_seed)

    @staticmethod
    def _history_step(previous, raw, workspace, sequence):
        from paper_daily.sync_client import validate_event

        digest = history_step(previous, raw)
        try:
            event = json.loads(raw)
            validate_event(event, workspace)
            canonical = json.dumps(event, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"), allow_nan=False)
        except (ValueError, TypeError, OverflowError, RecursionError) as error:
            raise SyncHistoryUnavailable("History event is invalid") from error
        if canonical != raw or event["sequence"] != sequence:
            raise SyncHistoryUnavailable("History event identity is inconsistent")
        return digest

    @classmethod
    def _require_history(cls, conn, workspace, checkpoint):
        if (not isinstance(checkpoint, dict) or set(checkpoint) != {"sequence", "sha256"}
                or type(checkpoint.get("sequence")) is not int
                or not 0 <= checkpoint["sequence"] <= 2**63 - 1
                or checkpoint["sha256"] != cls._history_prefix(
                    conn, workspace, checkpoint["sequence"])):
            raise SyncHistoryUnavailable("Retained history checkpoint does not match")

    @classmethod
    def _verified_result(cls, conn, workspace, event, checkpoint):
        if checkpoint is None:
            return event
        sequence = event["sequence"]
        row = conn.execute(
            "SELECT CASE WHEN length(CAST(event AS BLOB))<=? THEN event END "
            "FROM sync_events WHERE workspace=? AND sequence=?",
            (2 * MAX_BYTES + 8192, workspace, sequence),
        ).fetchone()
        if row is None or row[0] is None:
            raise SyncHistoryUnavailable("Verified acknowledgment record is unavailable")
        return {"record": row[0], "checkpoint": {
            "sequence": sequence, "sha256": cls._history_prefix(conn, workspace, sequence),
        }}

    def push_verified(self, token, operation, *, checkpoint):
        """Require continuity again inside the same transaction that accepts an edit."""
        if checkpoint is None:
            raise SyncHistoryUnavailable("A retained history checkpoint is required")
        return self.push(token, operation, checkpoint=checkpoint)

    @classmethod
    def _history_prefix(cls, conn, workspace, sequence):
        if sequence == 0:
            return cls._history_seed(workspace)
        row = conn.execute(
            "SELECT sha256 FROM sync_history WHERE workspace=? AND sequence=?",
            (workspace, sequence),
        ).fetchone()
        value = row[0] if row else None
        if (not isinstance(value, str) or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)):
            raise SyncHistoryUnavailable("History commitments need preparation or recovery review")
        return value

    @classmethod
    def _append_history(cls, conn, workspace, sequence, event):
        if sequence > 1 and conn.execute(
            "SELECT 1 FROM sync_history WHERE workspace=? AND sequence=?",
            (workspace, sequence - 1),
        ).fetchone() is None:
            # Old authorities keep their pre-existing API until explicit preparation.
            # Once preparation starts, finish it before accepting further writes.
            if conn.execute("SELECT 1 FROM sync_history WHERE workspace=? LIMIT 1",
                            (workspace,)).fetchone():
                raise SyncHistoryUnavailable("Finish preparing retained history before writing")
            return
        previous = cls._history_prefix(conn, workspace, sequence - 1)
        raw = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = cls._history_step(previous, raw, workspace, sequence)
        conn.execute("INSERT INTO sync_history VALUES(?,?,?)", (workspace, sequence, digest))

    def prepare_history(self, token: str, *, limit: int = 100) -> dict:
        """Explicit bounded backfill of legacy commitments; no event/content rewrite."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("History batch size must be between 1 and 1000")
        with self._transaction(write=True) as conn:
            workspace, _device = self._authenticate(conn, token)
            sequence = conn.execute(
                "SELECT COALESCE(MAX(sequence),0) FROM sync_history WHERE workspace=?",
                (workspace,),
            ).fetchone()[0]
            high = self._high_water(conn, workspace)
            if sequence > high:
                raise SyncHistoryUnavailable("History commitments exceed retained events")
            digest = self._history_prefix(conn, workspace, sequence)
            rows = conn.execute(
                "SELECT sequence,CASE WHEN length(CAST(event AS BLOB))<=? THEN event END "
                "FROM sync_events WHERE workspace=? AND sequence>? ORDER BY sequence LIMIT ?",
                (2 * MAX_BYTES + 8192, workspace, sequence, limit),
            )
            spent = 0
            for next_sequence, raw in rows:
                if raw is None or next_sequence != sequence + 1:
                    raise SyncHistoryUnavailable("Retained history is incomplete or oversized")
                size = len(raw.encode("utf-8"))
                if spent + size > 2 * 1024**2:
                    break
                digest = self._history_step(digest, raw, workspace, next_sequence)
                conn.execute("INSERT INTO sync_history VALUES(?,?,?)",
                             (workspace, next_sequence, digest))
                sequence, spent = next_sequence, spent + size
            return {"version": 1, "workspace_id": workspace,
                    "checkpoint": {"sequence": sequence, "sha256": digest},
                    "ready": sequence == high, "remaining_events": high - sequence}

    def history_page(self, token: str, after: int = 0, limit: int = 100, *,
                     checkpoint: dict | None = None) -> dict:
        """Bounded exact canonical event strings and their linked prefix commitment.

        This local authority API does not upgrade or authorize any remote client.
        Nonzero continuation must present the previous page's exact checkpoint.
        """
        if type(after) is not int or not 0 <= after <= 2**63 - 1:
            raise ValueError("Invalid history cursor")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("History batch size must be between 1 and 1000")
        with self._transaction() as conn:
            workspace, _device = self._authenticate(conn, token)
            high = self._high_water(conn, workspace)
            if after > high:
                raise SyncHistoryUnavailable("History cursor is ahead of retained events")
            digest = self._history_prefix(conn, workspace, after)
            observed = {"sequence": after, "sha256": digest}
            if checkpoint is not None:
                if (not isinstance(checkpoint, dict) or set(checkpoint) != set(observed)
                        or type(checkpoint.get("sequence")) is not int
                        or checkpoint != observed):
                    raise SyncHistoryUnavailable("Retained history checkpoint does not match")
            elif after:
                raise SyncHistoryUnavailable("Continue with an explicitly retained checkpoint")
            events, sequence, spent = [], after, 1024
            rows = conn.execute(
                "SELECT sequence,CASE WHEN length(CAST(event AS BLOB))<=? THEN event END "
                "FROM sync_events WHERE workspace=? AND sequence>? ORDER BY sequence LIMIT ?",
                (2 * MAX_BYTES + 8192, workspace, after, limit),
            )
            for next_sequence, raw in rows:
                if raw is None or next_sequence != sequence + 1:
                    raise SyncHistoryUnavailable("Retained history is incomplete or oversized")
                size = len(json.dumps(raw, ensure_ascii=False).encode("utf-8")) + 2
                if spent + size > 2 * 1024**2:
                    break
                candidate = self._history_step(digest, raw, workspace, next_sequence)
                if candidate != self._history_prefix(conn, workspace, next_sequence):
                    raise SyncHistoryUnavailable("Retained event does not match its commitment")
                sequence, digest, spent = next_sequence, candidate, spent + size
                events.append(raw)
            return {"version": 1, "workspace_id": workspace, "after": observed,
                    "events": events, "checkpoint": {"sequence": sequence, "sha256": digest},
                    "caught_up": sequence == high}
