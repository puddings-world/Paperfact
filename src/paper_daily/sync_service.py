"""Local reference sync authority for isolated tests and transport integration.

Enrollment/revocation are trusted administrative seams, not public endpoints.
Attachment storage is optional and explicit; no HTTP, identity provider or AI calls.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from paper_daily.sync_blob_service import BlobServiceMixin
from paper_daily.sync_graph import apply_accepted, check_preconditions
from paper_daily.sync_journal import ID, canonical_operation
from paper_daily.sync_ordering import ORDER_KINDS, validate_order


class ReferenceService(BlobServiceMixin):
    """Serialize workspace changes and retain conflicting operations durably."""

    def __init__(
        self,
        path: Path,
        *,
        blob_root: Path | None = None,
        blob_quota_bytes: int = 4 * 1024**3,
        blob_max_bytes: int = 150 * 1024**2,
        blob_max_uploads: int = 16,
    ):
        self._configure_blobs(blob_root, blob_quota_bytes, blob_max_bytes, blob_max_uploads)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction(write=True) as conn:
            self._blob_schema(conn)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sync_devices ("
                "token_hash TEXT PRIMARY KEY, workspace TEXT NOT NULL, device TEXT NOT NULL, "
                "revoked INTEGER NOT NULL DEFAULT 0, UNIQUE(workspace,device))"
            )
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

    @contextmanager
    def _transaction(self, *, write=False):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn
            conn.commit()
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

    def enroll(self, workspace_id: str, device_id: str) -> str:
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

    def push(self, token: str, operation: dict) -> dict:
        """Accept a causal edit or preserve it as a conflict; replay exactly once."""
        with self._transaction() as conn:
            self._authenticate(conn, token)
        # Close the envelope before verification so caller mutation cannot race it.
        encoded = canonical_operation(operation)
        operation = json.loads(encoded)
        prepared = self._prepare_research_file(token, operation, encoded)
        with self._transaction(write=True) as conn:
            workspace, device = self._authenticate(conn, token)
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
                return json.loads(previous["event"])

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
            return event

    def pull(self, token: str, after: int = 0, limit: int = 100) -> list[dict]:
        """Read bounded workspace events after a durable client cursor."""
        with self._transaction() as conn:
            workspace, _device = self._authenticate(conn, token)
            if type(after) is not int or after < 0:
                raise ValueError("Invalid sync cursor")
            if type(limit) is not int or not 1 <= limit <= 1000:
                raise ValueError("Batch size must be between 1 and 1000")
            if after > self._high_water(conn, workspace):
                raise ValueError("Sync cursor is ahead of this workspace")
            rows = conn.execute(
                "SELECT event FROM sync_events WHERE workspace=? AND sequence>? "
                "ORDER BY sequence LIMIT ?",
                (workspace, after, limit),
            )
            return [json.loads(row["event"]) for row in rows]
