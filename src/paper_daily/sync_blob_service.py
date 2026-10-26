"""Explicit workspace-owned transfer methods for the local reference authority.

The authority transaction always precedes BlobStore locks. Physical publication
and authority ownership are distinct commits; ownership gates all reads/manifests.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from pathlib import Path
from threading import BoundedSemaphore

from paper_daily.sync_blobs import BlobError, BlobManifest, BlobQuotaError, BlobStore, _no_link

BLOB_CHUNK_BYTES = 256 * 1024
_VERIFICATION_SLOTS = BoundedSemaphore(2)


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
        BlobServiceMixin._blob_integrity_schema(conn)

    @staticmethod
    def _blob_integrity_schema(conn):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sync_blob_integrity ("
            "workspace TEXT NOT NULL,digest TEXT NOT NULL,size INTEGER NOT NULL,"
            "version INTEGER NOT NULL,block_size INTEGER NOT NULL,block_count INTEGER NOT NULL,"
            "identity TEXT NOT NULL,PRIMARY KEY(workspace,digest))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sync_blob_blocks ("
            "workspace TEXT NOT NULL,digest TEXT NOT NULL,block_index INTEGER NOT NULL,"
            "block_hash TEXT NOT NULL,PRIMARY KEY(workspace,digest,block_index))"
        )

    def _prepare_research_file(self, token, operation, encoded):
        """Verify bounded closure without holding the authority write lock."""
        if operation["entity_type"] != "research_file" or operation["action"] != "put":
            return None
        from paper_daily.sync_files import referenced_blobs, validate_closure

        fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        with _VERIFICATION_SLOTS:
            with self._transaction() as conn:
                workspace, device = self._authenticate(conn, token)
                if (operation["workspace_id"], operation["device_id"]) != (workspace, device):
                    raise PermissionError("Operation does not belong to this workspace/device")
                previous = conn.execute(
                    "SELECT fingerprint FROM sync_events WHERE workspace=? AND operation_id=?",
                    (workspace, operation["operation_id"]),
                ).fetchone()
                if previous:
                    if previous[0] != fingerprint:
                        raise ValueError("Operation ID was reused with different content")
                    return None  # The commit transaction still reauthenticates the retry.
                paths = {}
                for row in referenced_blobs(operation):
                    manifest = BlobManifest(row["sha256"], row["size"])
                    store = self._blob_owned_store(conn, workspace, manifest)
                    paths[manifest.sha256] = (manifest, store._path(manifest))
            identities = {}

            def read_blob(row):
                manifest, path = paths[row["sha256"]]
                try:
                    before = self._file_identity(path)
                    with path.open("rb") as stream:
                        self._file_identity(path, stream)
                        data = stream.read(manifest.size + 1)
                        after = self._file_identity(path, stream)
                    if before != after or len(data) != manifest.size:
                        raise BlobUnavailableError(
                            "Owned attachment bytes changed during validation"
                        )
                    if hashlib.sha256(data).hexdigest() != manifest.sha256:
                        raise BlobUnavailableError("Owned attachment bytes require repair")
                    identities[manifest.sha256] = after
                    return data
                except (BlobError, FileNotFoundError) as exc:
                    raise BlobUnavailableError("Owned attachment bytes require repair") from exc

            validate_closure(operation["payload"], read_blob)
            return (paths, identities)

    def _require_prepared_file(self, conn, workspace, operation, prepared):
        if operation["entity_type"] != "research_file" or operation["action"] != "put":
            return
        if prepared is None:
            raise BlobUnavailableError("Artifact validation must precede publication")
        paths, identities = prepared
        for digest, (manifest, path) in paths.items():
            store = self._blob_owned_store(conn, workspace, manifest)
            try:
                if store._path(manifest) != path or self._file_identity(path) != identities[digest]:
                    raise BlobUnavailableError("Owned attachment changed before publication")
            except (BlobError, FileNotFoundError) as exc:
                raise BlobUnavailableError("Owned attachment bytes require repair") from exc

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

    def _blob_owned_store(self, conn, workspace, manifest, *, download=False):
        self._blob_enabled()
        row = conn.execute(
            "SELECT size,state FROM sync_workspace_blobs WHERE workspace=? AND digest=?",
            (workspace, manifest.sha256),
        ).fetchone()
        if row is None or row["state"] != "committed" or row["size"] != manifest.size:
            if download:
                raise PermissionError("Attachment is not committed to this workspace")
            raise BlobUnavailableError("Commit the owned attachment before publishing its manifest")
        return self._blob_store(conn, workspace)

    def _blob_owned_path(self, conn, workspace, manifest, *, download=False):
        try:
            store = self._blob_owned_store(conn, workspace, manifest, download=download)
            return store.verified_path(manifest)
        except (BlobError, FileNotFoundError):
            raise BlobUnavailableError("Owned attachment bytes require repair") from None

    @staticmethod
    def _file_identity(path, stream=None):
        for entry in (path, *path.parents):
            _no_link(entry)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise BlobUnavailableError("Attachment is not a regular file")
        identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if stream is not None:
            opened = os.fstat(stream.fileno())
            actual = (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
                opened.st_ctime_ns,
            )
            if not stat.S_ISREG(opened.st_mode) or actual != identity:
                raise BlobUnavailableError("Attachment changed while opening")
        return identity

    def _compute_integrity(self, path, manifest):
        """Compute server-owned blocks, trusted only after full hash verification."""
        before = self._file_identity(path)
        if before[2] != manifest.size:
            raise BlobUnavailableError("Attachment size changed")
        full, blocks = hashlib.sha256(), []
        with path.open("rb") as stream:
            if self._file_identity(path, stream) != before:
                raise BlobUnavailableError("Attachment changed before verification")
            remaining = manifest.size
            while remaining:
                expected = min(BLOB_CHUNK_BYTES, remaining)
                data = stream.read(expected)
                if len(data) != expected:
                    raise BlobUnavailableError("Attachment ended during verification")
                full.update(data)
                blocks.append(hashlib.sha256(data).hexdigest())
                remaining -= expected
            if stream.read(1) or self._file_identity(path, stream) != before:
                raise BlobUnavailableError("Attachment changed during verification")
        if full.hexdigest() != manifest.sha256:
            raise BlobUnavailableError("Attachment full hash does not match")
        return {"identity": before, "blocks": blocks}

    @staticmethod
    def _publish_integrity(conn, workspace, manifest, verified):
        conn.execute(
            "DELETE FROM sync_blob_blocks WHERE workspace=? AND digest=?",
            (workspace, manifest.sha256),
        )
        conn.execute(
            "INSERT INTO sync_blob_integrity VALUES(?,?,?,1,?,?,?) "
            "ON CONFLICT(workspace,digest) DO UPDATE SET size=excluded.size,"
            "version=excluded.version,"
            "block_size=excluded.block_size,block_count=excluded.block_count,identity=excluded.identity",
            (
                workspace,
                manifest.sha256,
                manifest.size,
                BLOB_CHUNK_BYTES,
                len(verified["blocks"]),
                json.dumps(verified["identity"], separators=(",", ":")),
            ),
        )
        conn.executemany(
            "INSERT INTO sync_blob_blocks VALUES(?,?,?,?)",
            [
                (workspace, manifest.sha256, index, digest)
                for index, digest in enumerate(verified["blocks"])
            ],
        )

    @staticmethod
    def _load_integrity(conn, workspace, manifest):
        count = (manifest.size + BLOB_CHUNK_BYTES - 1) // BLOB_CHUNK_BYTES
        row = conn.execute(
            "SELECT size,version,block_size,block_count,"
            "CASE WHEN length(identity)<=512 THEN identity ELSE NULL END FROM sync_blob_integrity "
            "WHERE workspace=? AND digest=?",
            (workspace, manifest.sha256),
        ).fetchone()
        blocks = conn.execute(
            "SELECT block_index,CASE WHEN length(block_hash)=64 THEN block_hash ELSE NULL END "
            "FROM sync_blob_blocks WHERE workspace=? AND digest=? "
            "ORDER BY block_index LIMIT ?",
            (workspace, manifest.sha256, count + 1),
        ).fetchall()
        if row is None and not blocks:
            return None  # Legacy ownership; no partially written index is trusted.
        try:
            if row is None or tuple(row[:4]) != (manifest.size, 1, BLOB_CHUNK_BYTES, count):
                raise ValueError("Invalid integrity header")
            if any(type(value) is not int for value in row[:4]) or len(blocks) != count:
                raise ValueError("Incomplete integrity index")
            identity = json.loads(row[4])
            if (
                not isinstance(identity, list)
                or len(identity) != 5
                or any(type(value) is not int for value in identity)
                or identity[2] != manifest.size
            ):
                raise ValueError("Invalid verified file identity")
            for index, block in enumerate(blocks):
                if (
                    type(block[0]) is not int
                    or block[0] != index
                    or not isinstance(block[1], str)
                    or re.fullmatch(r"[0-9a-f]{64}", block[1]) is None
                ):
                    raise ValueError("Invalid integrity block")
        except (ValueError, TypeError, RecursionError):
            raise BlobUnavailableError("Attachment integrity index requires repair") from None
        return {"identity": tuple(identity), "blocks": [block[1] for block in blocks]}

    def _backfill_integrity(self, token, manifest):
        with self._transaction() as conn:
            workspace, _ = self._authenticate(conn, token)
            store = self._blob_owned_store(conn, workspace, manifest, download=True)
            path = store._path(manifest)
        with _VERIFICATION_SLOTS:
            verified = self._compute_integrity(path, manifest)
        with self._transaction(write=True) as conn:
            current_workspace, _ = self._authenticate(conn, token)
            if current_workspace != workspace:
                raise PermissionError("Workspace binding changed")
            current_path = self._blob_owned_store(conn, workspace, manifest, download=True)._path(
                manifest
            )
            if current_path != path or self._file_identity(path) != verified["identity"]:
                raise BlobUnavailableError("Attachment changed after verification")
            existing = self._load_integrity(conn, workspace, manifest)
            if existing is None:
                self._publish_integrity(conn, workspace, manifest, verified)

    def _read_integrity_range(self, path, manifest, verified, offset, limit):
        identity = verified["identity"]
        amount = min(limit, manifest.size - offset)
        with path.open("rb") as stream:
            if self._file_identity(path, stream) != identity:
                raise BlobUnavailableError("Attachment identity changed")
            if amount == 0:
                return b""
            first, last = offset // BLOB_CHUNK_BYTES, (offset + amount - 1) // BLOB_CHUNK_BYTES
            chunks = []
            for index in range(first, last + 1):
                expected = min(BLOB_CHUNK_BYTES, manifest.size - index * BLOB_CHUNK_BYTES)
                stream.seek(index * BLOB_CHUNK_BYTES)
                data = stream.read(expected)
                if (
                    len(data) != expected
                    or hashlib.sha256(data).hexdigest() != verified["blocks"][index]
                ):
                    raise BlobUnavailableError("Requested attachment block is damaged")
                chunks.append(data)
            if self._file_identity(path, stream) != identity:
                raise BlobUnavailableError("Attachment changed during read")
        start = offset - first * BLOB_CHUNK_BYTES
        return b"".join(chunks)[start : start + amount]

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
            if not result["complete"]:
                return {"upload_id": upload_id, "sha256": item.sha256, "size": item.size, **result}
        # Physical publication survived a previous interrupted ownership commit.
        self.blob_commit(token, upload_id)
        return {
            "upload_id": None,
            "sha256": item.sha256,
            "size": item.size,
            "offset": item.size,
            "complete": True,
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
        with self._transaction() as conn:
            workspace, device = self._authenticate(conn, token)
            self._blob_enabled()
            session = self._blob_session(conn, workspace, device, upload_id)
            if session["state"] == "cancelled":
                raise BlobError("Upload session was cancelled")
            item = BlobManifest(session["digest"], session["size"])
            store = self._blob_store(conn, workspace)
        # Full scans are bounded by the configured file limit and a process-local
        # admission semaphore, and never hold an authority write transaction.
        with _VERIFICATION_SLOTS:
            path = store.finalize(item)
            verified = self._compute_integrity(path, item)
        with self._transaction(write=True) as conn:
            current_workspace, current_device = self._authenticate(conn, token)
            session = self._blob_session(conn, current_workspace, current_device, upload_id)
            if session["state"] == "cancelled":
                raise BlobError("Upload session was cancelled")
            if (current_workspace, current_device, session["digest"], session["size"]) != (
                workspace,
                device,
                item.sha256,
                item.size,
            ):
                raise PermissionError("Upload binding changed")
            if self._file_identity(path) != verified["identity"]:
                raise BlobUnavailableError("Attachment changed before ownership commit")
            self._publish_integrity(conn, workspace, item, verified)
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
        for attempt in range(2):
            with self._transaction() as conn:
                workspace, _ = self._authenticate(conn, token)
                self._blob_enabled()
                item = BlobManifest(sha256, size)
                if type(offset) is not int or not 0 <= offset <= item.size:
                    raise BlobError("Invalid attachment read offset")
                if type(limit) is not int or not 0 < limit <= BLOB_CHUNK_BYTES:
                    raise BlobError("Invalid attachment read limit")
                try:
                    store = self._blob_owned_store(conn, workspace, item, download=True)
                except (BlobError, FileNotFoundError):
                    raise BlobUnavailableError("Owned attachment storage requires repair") from None
                verified = self._load_integrity(conn, workspace, item)
                if verified is not None:
                    try:
                        return self._read_integrity_range(
                            store._path(item), item, verified, offset, limit
                        )
                    except (BlobError, FileNotFoundError):
                        raise BlobUnavailableError(
                            "Owned attachment bytes require repair"
                        ) from None
            if attempt == 0:
                self._backfill_integrity(token, item)
        raise BlobUnavailableError("Attachment integrity upgrade did not complete")
