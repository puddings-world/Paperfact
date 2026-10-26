"""Explicit bounded artifact transfers; metadata sync remains independently usable."""

from __future__ import annotations

import hashlib
from threading import Lock

from paper_daily.sync_artifacts import (
    activate,
    desired_file,
    materialize,
    register_paths,
    verify_closure,
)
from paper_daily.sync_blobs import BlobManifest, BlobStore
from paper_daily.sync_files import referenced_blobs
from paper_daily.sync_transfers import CHUNK_BYTES, _origin


class FileTransfers:
    """One chunk per step, one fixed workspace/device/store/origin. Tokens stay in RAM."""

    def __init__(self, client, store, transport, *, origin, token=None, version_root=None):
        if not isinstance(store, BlobStore):
            raise ValueError("An explicit BlobStore is required")
        self.client, self.store, self.transport = client, store, transport
        self.origin = _origin(origin)
        if hasattr(transport, "base_url") and _origin(transport.base_url) != self.origin:
            raise ValueError("Transport endpoint differs from binding")
        self.endpoint = hashlib.sha256(self.origin.encode()).hexdigest()
        self.root = version_root or store.root / "research-versions"
        self._guard, self._running = Lock(), Lock()
        self._generation, self._cancelled = 0, {}
        self._verified = {}
        self._token = None
        journal = client.journal
        binding = (journal.workspace_id, journal.device_id, str(journal.path.resolve()))
        with store._transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS transfer_binding (id INTEGER PRIMARY "
                "KEY,workspace TEXT,device TEXT,research_path TEXT)"
            )
            row = conn.execute(
                "SELECT workspace,device,research_path FROM transfer_binding WHERE id=1"
            ).fetchone()
            if row is not None and tuple(row) != binding:
                raise ValueError("Blob store belongs to another workspace/device/database")
            conn.execute("INSERT OR IGNORE INTO transfer_binding VALUES(1,?,?,?)", binding)
        with journal.transaction() as conn:
            register_paths(conn, journal.workspace_id, store, self.root)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS research_file_transfers (operation_id "
                "TEXT,digest TEXT,endpoint TEXT,state TEXT NOT NULL,PRIMARY "
                "KEY(operation_id,digest,endpoint))"
            )
        self.set_session(token)

    def set_session(self, token):
        if token is not None and (not isinstance(token, str) or not token):
            raise ValueError("Expected an in-memory token or None")
        with self._guard:
            self._generation += 1
            self._token = token
            self._verified.clear()

    def close(self):
        self.set_session(None)

    def cancel(self, identity):
        with self._guard:
            self._cancelled[identity] = self._cancelled.get(identity, 0) + 1

    def _live(self, generation, identity, cancellation):
        return self._generation == generation and self._cancelled.get(identity, 0) == cancellation

    def authenticate(self):
        with self._guard:
            generation, token = self._generation, self._token
        if token is None:
            return False
        identity = self.transport.session_info(token)
        if identity != {
            "workspace_id": self.client.journal.workspace_id,
            "device_id": self.client.journal.device_id,
        }:
            raise PermissionError("Session does not belong to this workspace/device")
        with self._guard:
            return generation == self._generation

    def ready_to_push(self, operation):
        if operation["entity_type"] != "research_file" or operation["action"] != "put":
            return True
        with self.client.journal.transaction() as conn:
            return all(
                conn.execute(
                    (
                        "SELECT 1 FROM research_file_transfers WHERE operation_id=? AND "
                        "digest=? AND endpoint=? AND state='uploaded'"
                    ),
                    (operation["operation_id"], row["sha256"], self.endpoint),
                ).fetchone()
                for row in referenced_blobs(operation)
            )

    def upload(self, operation, *, retry=False):
        if operation["device_id"] != self.client.journal.device_id:
            raise ValueError("Cannot upload another device's operation")
        return self._step(operation, uploading=True, retry=retry)

    def download(self, identity, *, retry=False):
        with self.client.journal.transaction() as conn:
            operation = desired_file(conn, identity)
        if operation is None:
            return {"state": "absent"}
        return self._step(operation, uploading=False, retry=retry)

    def _step(self, operation, *, uploading, retry):
        rows = referenced_blobs(operation)
        if (
            operation["action"] != "put"
            or operation["workspace_id"] != self.client.journal.workspace_id
        ):
            raise ValueError("Expected a current-workspace artifact put")
        if not self._running.acquire(blocking=False):
            return {"state": "busy"}
        try:
            identity = operation["entity_id"]
            with self._guard:
                if retry:
                    self._cancelled.pop(identity, None)
                elif self._cancelled.get(identity):
                    return {"state": "cancelled"}
                generation, cancellation, token = (
                    self._generation,
                    self._cancelled.get(identity, 0),
                    self._token,
                )
            if token is None:
                return {"state": "signed_out"}
            if not self.authenticate():
                return {"state": "interrupted"}

            def live():
                with self._guard:
                    return self._live(generation, identity, cancellation)

            if not live():
                return {"state": "interrupted"}
            if uploading:
                verified = self._verified.get(operation["operation_id"])
                if verified is None or not verified.matches(operation):
                    verified, _, _ = verify_closure(self.store, operation)
                    if len(self._verified) >= 16:
                        self._verified.clear()
                    self._verified[operation["operation_id"]] = verified
            transferred = False
            completed = 0
            for row in rows:
                manifest = BlobManifest(row["sha256"], row["size"])
                if not live():
                    return {"state": "interrupted"}
                if uploading:
                    with self.client.journal.transaction() as conn:
                        done = conn.execute(
                            (
                                "SELECT 1 FROM research_file_transfers WHERE operation_id=? AND "
                                "digest=? AND endpoint=? AND state='uploaded'"
                            ),
                            (operation["operation_id"], manifest.sha256, self.endpoint),
                        ).fetchone()
                    if done:
                        completed += 1
                        continue
                    begun = self.transport.blob_begin(
                        token, {"sha256": manifest.sha256, "size": manifest.size}
                    )
                else:
                    begun = self.store.begin(manifest)
                offset = begun["offset"]
                if (
                    type(offset) is not int
                    or not 0 <= offset <= manifest.size
                    or type(begun["complete"]) is not bool
                ):
                    raise ValueError("Invalid blob resume acknowledgment")
                if begun["complete"] and offset != manifest.size:
                    raise ValueError("Invalid complete blob offset")
                if not live():
                    return {"state": "interrupted"}
                if not begun["complete"]:
                    if offset < manifest.size:
                        if transferred:
                            break
                        amount = min(CHUNK_BYTES, manifest.size - offset)
                        if uploading:
                            data = verified.read_chunk(manifest.sha256, offset, amount)
                            reply = self.transport.blob_append(
                                token, begun["upload_id"], offset, data
                            )
                            if (
                                not isinstance(reply, dict)
                                or set(reply) != {"offset"}
                                or type(reply["offset"]) is not int
                                or not offset + len(data) <= reply["offset"] <= manifest.size
                            ):
                                raise ValueError("Invalid append acknowledgment")
                            offset = reply["offset"]
                        else:
                            data = self.transport.blob_read(
                                token, manifest.sha256, manifest.size, offset, limit=amount
                            )
                            if not isinstance(data, bytes) or len(data) != amount:
                                raise ValueError("Invalid artifact download chunk")
                            offset = self.store.append(manifest, offset, data)
                        transferred = True
                    if not live():
                        return {"state": "interrupted"}
                    if offset != manifest.size:
                        break
                    if uploading:
                        reply = self.transport.blob_commit(token, begun["upload_id"])
                        if reply != {
                            "sha256": manifest.sha256,
                            "size": manifest.size,
                            "complete": True,
                        }:
                            raise ValueError("Invalid commit acknowledgment")
                    else:
                        try:
                            self.store.finalize(manifest)
                        except ValueError:
                            self.store.discard_partial(manifest)
                            raise
                if not live():
                    return {"state": "interrupted"}
                if uploading:
                    with self._guard:
                        if not self._live(generation, identity, cancellation):
                            return {"state": "interrupted"}
                        with self.client.journal.transaction() as conn:
                            conn.execute(
                                (
                                    "INSERT OR REPLACE INTO research_file_transfers VALUES(?,?,?,"
                                    "'uploaded')"
                                ),
                                (operation["operation_id"], manifest.sha256, self.endpoint),
                            )
                completed += 1
            if completed != len(rows):
                return {
                    "state": "uploading" if uploading else "downloading",
                    "completed": completed,
                    "total": len(rows),
                }
            if uploading:
                if not verified.matches(operation):
                    raise ValueError("Artifact changed before upload completed")
                return {"state": "uploaded", "completed": completed, "total": len(rows)}
            directory = materialize(self.store, self.root, operation)
            # Reauthenticate after expensive closure validation, before activation.
            if not self.authenticate():
                return {"state": "interrupted"}
            with self._guard:
                if not self._live(generation, identity, cancellation):
                    return {"state": "interrupted"}
                with self.client.journal.transaction() as conn:
                    bound = activate(conn, operation, directory)
            return {
                "state": "bound" if bound else "stale",
                "completed": completed,
                "total": len(rows),
            }
        finally:
            self._running.release()
