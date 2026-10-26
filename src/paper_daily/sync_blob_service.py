"""Explicit workspace-owned transfer methods for the local reference authority.

The authority transaction always precedes BlobStore locks. Physical publication
and authority ownership are distinct commits; ownership gates all reads/manifests.
"""

from __future__ import annotations

import re
import secrets
from pathlib import Path

from paper_daily.sync_blobs import BlobError, BlobManifest, BlobQuotaError, BlobStore

BLOB_CHUNK_BYTES = 256 * 1024


class BlobUnavailableError(FileNotFoundError):
    """Retry after completing or repairing explicitly owned attachment bytes."""


class BlobDisabledError(RuntimeError):
    """This authority has no explicitly configured attachment storage."""


class BlobServiceMixin:
    def _configure_blobs(self, root, quota, maximum, uploads):
        for value in (quota, maximum, uploads):
            if type(value) is not int or not 0 < value <= 2**63 - 1:
                raise ValueError("Blob limits must be bounded positive integers")
        self.blob_root = Path(root).absolute() if root is not None else None
        self.blob_quota_bytes = quota
        self.blob_max_bytes = maximum
        self.blob_max_uploads = uploads

    @staticmethod
    def _blob_schema(conn):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sync_blob_namespaces ("
            "workspace TEXT PRIMARY KEY, directory TEXT NOT NULL UNIQUE)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sync_workspace_blobs ("
            "workspace TEXT NOT NULL, digest TEXT NOT NULL, size INTEGER NOT NULL, "
            "state TEXT NOT NULL CHECK(state IN ('reserved','committed')), "
            "PRIMARY KEY(workspace,digest))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sync_blob_uploads ("
            "upload_id TEXT PRIMARY KEY, workspace TEXT NOT NULL, device TEXT NOT NULL, "
            "digest TEXT NOT NULL, size INTEGER NOT NULL, "
            "state TEXT NOT NULL CHECK(state IN ('open','committed','cancelled')))"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS sync_blob_open_upload ON "
            "sync_blob_uploads(workspace,digest) WHERE state='open'"
        )

    def _blob_enabled(self):
        if self.blob_root is None:
            raise BlobDisabledError("Attachment storage is not configured")

    @staticmethod
    def _manifest(value):
        if not isinstance(value, dict) or set(value) != {"sha256", "size"}:
            raise BlobError("A blob manifest requires sha256 and size only")
        return BlobManifest(value["sha256"], value["size"])

    def _blob_store(self, conn, workspace):
        self._blob_enabled()
        row = conn.execute(
            "SELECT directory FROM sync_blob_namespaces WHERE workspace=?", (workspace,)
        ).fetchone()
        if row is None:
            raise BlobUnavailableError("Workspace attachment storage is unavailable")
        directory = row["directory"]
        if not re.fullmatch(r"[0-9a-f]{32}", directory):
            raise BlobError("Invalid private storage namespace")
        return BlobStore(
            self.blob_root / directory,
            quota_bytes=self.blob_quota_bytes,
            max_blob_bytes=self.blob_max_bytes,
            chunk_bytes=BLOB_CHUNK_BYTES,
        )

    @staticmethod
    def _blob_session(conn, workspace, device, upload_id):
        if not isinstance(upload_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,64}", upload_id):
            raise ValueError("Invalid upload session identifier")
        row = conn.execute(
            "SELECT * FROM sync_blob_uploads WHERE upload_id=?", (upload_id,)
        ).fetchone()
        if row is None or (row["workspace"], row["device"]) != (workspace, device):
            raise PermissionError("Upload session is unavailable to this device")
        return row

    @staticmethod
    def _blob_mark_committed(conn, workspace, manifest, upload_id):
        conn.execute(
            "UPDATE sync_workspace_blobs SET state='committed' WHERE workspace=? AND digest=?",
            (workspace, manifest.sha256),
        )
        conn.execute(
            "UPDATE sync_blob_uploads SET state='committed' WHERE upload_id=?", (upload_id,)
        )

    def _blob_owned_path(self, conn, workspace, manifest, *, download=False):
        self._blob_enabled()
        row = conn.execute(
            "SELECT size,state FROM sync_workspace_blobs WHERE workspace=? AND digest=?",
            (workspace, manifest.sha256),
        ).fetchone()
        if row is None or row["state"] != "committed" or row["size"] != manifest.size:
            if download:
                raise PermissionError("Attachment is not committed to this workspace")
            raise BlobUnavailableError("Commit the owned attachment before publishing its manifest")
        try:
            return self._blob_store(conn, workspace).verified_path(manifest)
        except (BlobError, FileNotFoundError):
            raise BlobUnavailableError("Owned attachment bytes require repair") from None

    def _require_document_blob(self, conn, workspace, operation):
        if operation["entity_type"] == "paper_document" and operation["action"] == "put":
            payload = operation["payload"]
            self._blob_owned_path(conn, workspace, BlobManifest(payload["sha256"], payload["size"]))

    def blob_begin(self, token, manifest):
        # Persist the opaque namespace before touching files; a failed begin cannot
        # strand physical reservations under an unrecorded random directory.
        with self._transaction(write=True) as conn:
            workspace, _ = self._authenticate(conn, token)
            self._blob_enabled()
            item = self._manifest(manifest)
            if item.size > self.blob_max_bytes:
                raise BlobQuotaError("Attachment exceeds the per-file limit")
            conn.execute(
                "INSERT OR IGNORE INTO sync_blob_namespaces VALUES(?,?)",
                (workspace, secrets.token_hex(16)),
            )
        with self._transaction(write=True) as conn:
            workspace, device = self._authenticate(conn, token)
            row = conn.execute(
                "SELECT size,state FROM sync_workspace_blobs WHERE workspace=? AND digest=?",
                (workspace, item.sha256),
            ).fetchone()
            if row and row["size"] != item.size:
                raise BlobError("The digest was already registered with a different size")
            if row and row["state"] == "committed":
                self._blob_owned_path(conn, workspace, item)
                return {
                    "upload_id": None,
                    "sha256": item.sha256,
                    "size": item.size,
                    "offset": item.size,
                    "complete": True,
                }
            session = conn.execute(
                "SELECT * FROM sync_blob_uploads WHERE workspace=? AND digest=? AND state='open'",
                (workspace, item.sha256),
            ).fetchone()
            if session and session["device"] != device:
                raise PermissionError("An unfinished upload belongs to another device")
            if session is None:
                count = conn.execute(
                    "SELECT COUNT(*) FROM sync_blob_uploads WHERE workspace=? AND state='open'",
                    (workspace,),
                ).fetchone()[0]
                if count >= self.blob_max_uploads:
                    raise BlobQuotaError("Workspace active-upload limit would be exceeded")
                if row is None:
                    reserved = conn.execute(
                        "SELECT COALESCE(SUM(size),0) FROM sync_workspace_blobs WHERE workspace=?",
                        (workspace,),
                    ).fetchone()[0]
                    if reserved + item.size > self.blob_quota_bytes:
                        raise BlobQuotaError("Workspace attachment quota would be exceeded")
                    conn.execute(
                        "INSERT INTO sync_workspace_blobs VALUES(?,?,?,'reserved')",
                        (workspace, item.sha256, item.size),
                    )
                upload_id = secrets.token_urlsafe(32)
                conn.execute(
                    "INSERT INTO sync_blob_uploads VALUES(?,?,?,?,?,'open')",
                    (upload_id, workspace, device, item.sha256, item.size),
                )
            else:
                upload_id = session["upload_id"]
            result = self._blob_store(conn, workspace).begin(item)
            if result["complete"]:
                # Repair a crash after verified publication but before ownership commit.
                self._blob_mark_committed(conn, workspace, item, upload_id)
            return {
                "upload_id": None if result["complete"] else upload_id,
                "sha256": item.sha256,
                "size": item.size,
                **result,
            }

    def blob_append(self, token, upload_id, offset, data):
        with self._transaction(write=True) as conn:
            workspace, device = self._authenticate(conn, token)
            self._blob_enabled()
            session = self._blob_session(conn, workspace, device, upload_id)
            if session["state"] == "cancelled":
                raise BlobError("Upload session was cancelled")
            item = BlobManifest(session["digest"], session["size"])
            result = self._blob_store(conn, workspace).append(item, offset, data)
            return {"offset": result}

    def blob_commit(self, token, upload_id):
        with self._transaction(write=True) as conn:
            workspace, device = self._authenticate(conn, token)
            self._blob_enabled()
            session = self._blob_session(conn, workspace, device, upload_id)
            if session["state"] == "cancelled":
                raise BlobError("Upload session was cancelled")
            item = BlobManifest(session["digest"], session["size"])
            self._blob_store(conn, workspace).finalize(item)
            self._blob_mark_committed(conn, workspace, item, upload_id)
            return {"sha256": item.sha256, "size": item.size, "complete": True}

    def blob_cancel(self, token, upload_id):
        with self._transaction(write=True) as conn:
            workspace, device = self._authenticate(conn, token)
            self._blob_enabled()
            session = self._blob_session(conn, workspace, device, upload_id)
            if session["state"] == "committed":
                raise BlobError("Committed history attachments cannot be cancelled")
            if session["state"] == "open":
                item = BlobManifest(session["digest"], session["size"])
                self._blob_store(conn, workspace).discard_partial(item)
                conn.execute(
                    "DELETE FROM sync_workspace_blobs WHERE workspace=? AND digest=? "
                    "AND state='reserved'",
                    (workspace, item.sha256),
                )
                conn.execute(
                    "UPDATE sync_blob_uploads SET state='cancelled' WHERE upload_id=?", (upload_id,)
                )
            return {"cancelled": True}

    def blob_read(self, token, sha256, size, offset, limit=BLOB_CHUNK_BYTES):
        with self._transaction(write=True) as conn:
            workspace, _ = self._authenticate(conn, token)
            self._blob_enabled()
            item = BlobManifest(sha256, size)
            if type(offset) is not int or not 0 <= offset <= item.size:
                raise BlobError("Invalid attachment read offset")
            if type(limit) is not int or not 0 < limit <= BLOB_CHUNK_BYTES:
                raise BlobError("Invalid attachment read limit")
            path = self._blob_owned_path(conn, workspace, item, download=True)
            with path.open("rb") as stream:
                stream.seek(offset)
                return stream.read(min(limit, item.size - offset))
