"""Bounded, explicit document transfers, independent of metadata sync and readers.

One step transfers at most one chunk. Credentials and cancellation generations
stay in memory. Durable progress is advisory; the byte stores own resume offsets.
"""

from __future__ import annotations

import hashlib
import json
from threading import Lock
from urllib.parse import urlsplit

from paper_daily.sync_blobs import BlobError, BlobManifest, BlobStore
from paper_daily.sync_documents import (
    bind_verified_document,
    desired_document,
    verify_document,
)
from paper_daily.sync_journal import canonical_operation

CHUNK_BYTES = 256 * 1024


def _origin(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("An explicit bounded service URL is required")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"})
    ):
        raise ValueError("Use HTTPS or explicit loopback without credentials or query parameters")
    _ = parsed.port  # Validate a malformed port before persisting a binding.
    return value.rstrip("/")


def _target(operation):
    canonical_operation(operation)
    if operation["entity_type"] != "paper_document" or operation["action"] != "put":
        raise ValueError("Expected a primary PDF put operation")
    return {
        **operation["payload"],
        "workspace_id": operation["workspace_id"],
        "operation_id": operation["operation_id"],
        "incarnation": operation["incarnation"],
        "parent_incarnation": operation["parents"][0]["incarnation"],
    }


class DocumentTransfers:
    """One workspace/device/store and one fixed service endpoint per coordinator.

    Call on a worker, never the UI thread. set_session/close/cancel are fast local
    invalidations. They prevent late binding, but do not retract already sent
    bytes or delete resumable partials. Server cancellation is an explicit API.
    """

    def __init__(self, client, store, transport, *, origin, token=None):
        if not isinstance(store, BlobStore):
            raise ValueError("An explicitly owned BlobStore is required")
        self.client, self.store, self.transport = client, store, transport
        self.origin = _origin(origin)
        if hasattr(transport, "base_url") and _origin(transport.base_url) != self.origin:
            raise ValueError("Transport endpoint does not match the transfer binding")
        self.endpoint = hashlib.sha256(self.origin.encode()).hexdigest()
        self._guard, self._running = Lock(), Lock()
        self._generation, self._cancelled, self._verified = 0, {}, {}
        self._authenticated_generation = None
        if token is not None and (not isinstance(token, str) or not token):
            raise ValueError("Expected a nonempty token or None")
        self._token = token
        journal = client.journal
        binding = (journal.workspace_id, journal.device_id, str(journal.path.resolve()))
        with store._transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS transfer_binding "
                "(id INTEGER PRIMARY KEY,workspace TEXT,device TEXT,research_path TEXT)"
            )
            row = conn.execute(
                "SELECT workspace,device,research_path FROM transfer_binding WHERE id=1"
            ).fetchone()
            if row is not None and tuple(row) != binding:
                raise ValueError("Blob store belongs to another workspace/device/database")
            conn.execute("INSERT OR IGNORE INTO transfer_binding VALUES(1,?,?,?)", binding)
        with journal.transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS research_document_transfers "
                "(operation_id TEXT,direction TEXT,endpoint TEXT,target TEXT NOT NULL,"
                "state TEXT NOT NULL,offset INTEGER NOT NULL,error TEXT,"
                "PRIMARY KEY(operation_id,direction,endpoint))"
            )

    def set_session(self, token):
        """Invalidate in-flight work before using a replacement in-memory token."""
        if token is not None and (not isinstance(token, str) or not token):
            raise ValueError("Expected a nonempty token or None")
        with self._guard:
            self._generation += 1
            self._authenticated_generation = None
            self._token = token
            self._verified.clear()

    def close(self):
        self.set_session(None)

    def cancel(self, paper_id):
        """Stop both directions for this paper; retry=True explicitly resumes."""
        with self._guard:
            self._cancelled[paper_id] = self._cancelled.get(paper_id, 0) + 1
            with self.client.journal.transaction() as conn:
                conn.execute(
                    "UPDATE research_document_transfers SET state='cancelled',error=NULL "
                    "WHERE endpoint=? AND json_extract(target,'$.paper_id')=? "
                    "AND state NOT IN ('bound','stale')",
                    (self.endpoint, paper_id),
                )

    def _key(self, target, direction):
        return (target["operation_id"], direction, self.endpoint)

    def _record(self, conn, target, direction, state, offset, error=None):
        encoded = json.dumps(target, sort_keys=True, separators=(",", ":"))
        conn.execute(
            "INSERT INTO research_document_transfers VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(operation_id,direction,endpoint) DO UPDATE SET "
            "state=excluded.state,offset=excluded.offset,error=excluded.error",
            (*self._key(target, direction), encoded, state, offset, error),
        )

    def _state(self, conn, target, direction):
        row = conn.execute(
            "SELECT target,state,offset,error FROM research_document_transfers "
            "WHERE operation_id=? AND direction=? AND endpoint=?",
            self._key(target, direction),
        ).fetchone()
        if row is None:
            return None
        if json.loads(row[0]) != target:
            raise ValueError("Transfer identity was reused with a different manifest")
        return {"state": row[1], "offset": row[2], "error": row[3]}

    def ready_to_push(self, operation):
        """Trusted SyncClient.prepare_push callback; performs no network or hashing."""
        with self._guard:
            if self._token is None or self._authenticated_generation != self._generation:
                return False
            if operation["entity_type"] != "paper_document" or operation["action"] != "put":
                return True
            target = _target(operation)
            with self.client.journal.transaction() as conn:
                state = self._state(conn, target, "upload")
            return state is not None and state["state"] == "uploaded"

    def upload(self, operation, *, retry=False):
        target = _target(operation)
        if operation["device_id"] != self.client.journal.device_id:
            raise ValueError("Only this device's pending document operations may be uploaded")
        return self._step(target, "upload", retry=retry)

    def download(self, paper_id, *, retry=False):
        with self.client.journal.transaction() as conn:
            target = desired_document(conn, paper_id)
        if target is None:
            return {"state": "absent", "offset": 0}
        return self._step(target, "download", retry=retry)

    def _current(self, generation, target, cancellation):
        return (
            self._generation == generation
            and self._cancelled.get(target["paper_id"], 0) == cancellation
        )

    def _interrupted(self, generation, target, cancellation):
        with self._guard:
            return not self._current(generation, target, cancellation)

    def authenticate(self):
        """Verify the bound identity before a metadata-only pass; no blob is sent.

        Transfer steps call this handshake internally. Replacements of an existing
        credential always need a fresh handshake, even if its old uploads finished.
        """
        with self._guard:
            generation, token = self._generation, self._token
            if token is None:
                return False
        return self._authenticate(generation, token)

    def _authenticate(self, generation, token):
        with self._guard:
            if generation != self._generation:
                return False
            if self._authenticated_generation == generation:
                return True
        discover = getattr(self.transport, "session_info", None)
        if not callable(discover):
            raise ValueError("The service must support authenticated session discovery")
        identity = discover(token)
        if identity != {
            "workspace_id": self.client.journal.workspace_id,
            "device_id": self.client.journal.device_id,
        }:
            raise PermissionError("Session does not belong to the bound workspace and device")
        with self._guard:
            if generation != self._generation:
                return False
            self._authenticated_generation = generation
        return True

    def _authorize(self, generation, token, target, cancellation):
        if self._interrupted(generation, target, cancellation):
            return False
        if not self._authenticate(generation, token):
            return False
        return not self._interrupted(generation, target, cancellation)

    def _verify(self, target):
        key = target["operation_id"]
        snapshot = self._verified.get(key)
        if snapshot is None or not snapshot.matches(target):
            snapshot = verify_document(self.store, target)
            if len(self._verified) >= 16:
                self._verified.clear()
            self._verified[key] = snapshot
        return snapshot

    def _step(self, target, direction, *, retry):
        if target["workspace_id"] != self.client.journal.workspace_id:
            raise ValueError("Transfer belongs to another workspace")
        if not self._running.acquire(blocking=False):
            return {"state": "busy", "offset": 0}
        try:
            with self._guard:
                generation, token = self._generation, self._token
                cancellation = self._cancelled.get(target["paper_id"], 0)
                if token is None:
                    return {"state": "signed_out", "offset": 0}
                with self.client.journal.transaction() as conn:
                    previous = self._state(conn, target, direction)
                    if previous and previous["state"] in {"cancelled", "failed"} and not retry:
                        return previous
                    self._record(conn, target, direction, "running", 0)
            manifest = BlobManifest(target["sha256"], target["size"])
            offset = 0
            error_code = "transfer_failed"
            try:
                if not self._authorize(generation, token, target, cancellation):
                    return {"state": "interrupted", "offset": offset}
                verified = None
                if direction == "upload":
                    verified = self._verify(target)
                    if self._interrupted(generation, target, cancellation):
                        return {"state": "interrupted", "offset": offset}
                    reply = self.transport.blob_begin(
                        token, {"sha256": manifest.sha256, "size": manifest.size}
                    )
                    offset = reply["offset"]
                    if self._interrupted(generation, target, cancellation):
                        return {"state": "interrupted", "offset": offset}
                    if type(offset) is not int or not 0 <= offset <= manifest.size:
                        raise ValueError("Invalid remote upload offset")
                    if not reply["complete"]:
                        if offset < manifest.size:
                            with verified._path.open("rb") as stream:
                                stream.seek(offset)
                                chunk = stream.read(min(CHUNK_BYTES, manifest.size - offset))
                            if not verified.matches(target) or not chunk:
                                raise ValueError("Document changed during upload")
                            if self._interrupted(generation, target, cancellation):
                                return {"state": "interrupted", "offset": offset}
                            next_offset = self.transport.blob_append(
                                token, reply["upload_id"], offset, chunk
                            )["offset"]
                            if (
                                type(next_offset) is not int
                                or not offset + len(chunk) <= next_offset <= manifest.size
                            ):
                                raise ValueError("Invalid upload acknowledgment")
                            offset = next_offset
                        if self._interrupted(generation, target, cancellation):
                            return {"state": "interrupted", "offset": offset}
                        if offset == manifest.size:
                            committed = self.transport.blob_commit(token, reply["upload_id"])
                            if committed != {
                                "sha256": manifest.sha256,
                                "size": manifest.size,
                                "complete": True,
                            }:
                                raise ValueError("Invalid committed blob acknowledgment")
                    elif offset != manifest.size:
                        raise ValueError("Incomplete remote object")
                    state = "uploaded" if offset == manifest.size else "uploading"
                else:
                    if retry and previous and previous["error"] == "invalid_partial":
                        try:
                            self.store.discard_partial(manifest)
                        except BlobError:
                            error_code = "repair_required"
                            raise
                    reply = self.store.begin(manifest)
                    offset = reply["offset"]
                    if not reply["complete"]:
                        if offset < manifest.size:
                            if self._interrupted(generation, target, cancellation):
                                return {"state": "interrupted", "offset": offset}
                            chunk = self.transport.blob_read(
                                token,
                                manifest.sha256,
                                manifest.size,
                                offset,
                                limit=min(CHUNK_BYTES, manifest.size - offset),
                            )
                            if not isinstance(chunk, bytes) or len(chunk) != min(
                                CHUNK_BYTES, manifest.size - offset
                            ):
                                raise ValueError("Invalid download chunk")
                            offset = self.store.append(manifest, offset, chunk)
                        if offset == manifest.size:
                            try:
                                self.store.finalize(manifest)
                            except BlobError:
                                error_code = "invalid_partial"
                                raise
                    if offset == manifest.size:
                        verified = self._verify(target)
                    state = "downloaded" if verified is not None else "downloading"
                with self._guard:
                    if not self._current(generation, target, cancellation):
                        return {"state": "interrupted", "offset": offset}
                    with self.client.journal.transaction() as conn:
                        if (
                            direction == "download"
                            and desired_document(conn, target["paper_id"]) != target
                        ):
                            state = "stale"
                        elif direction == "download" and verified is not None:
                            state = (
                                "bound"
                                if bind_verified_document(conn, target, verified)
                                else "stale"
                            )
                        self._record(conn, target, direction, state, offset)
                return {"state": state, "offset": offset, "size": manifest.size}
            except (OSError, ValueError, RuntimeError):
                with self._guard:
                    if not self._current(generation, target, cancellation):
                        return {"state": "interrupted", "offset": offset}
                    with self.client.journal.transaction() as conn:
                        self._record(conn, target, direction, "failed", offset, error_code)
                # Do not persist provider messages, credentials, paths or document text.
                return {"state": "failed", "offset": offset, "error": error_code}
        finally:
            self._running.release()
