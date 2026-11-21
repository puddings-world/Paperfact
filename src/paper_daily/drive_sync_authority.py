"""Personal Drive replica of the existing authority, never a live research database.

Known-schema row checkpoints reuse ReferenceService conflict/history semantics.
Drive conditional publication is the commit point. A failed publication discards
only the derived local authority cache; caller outboxes keep their original intent.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from contextlib import closing, nullcontext
from pathlib import Path

from paper_daily import sync_admin
from paper_daily.drive_sync_files import (
    DriveUnavailable,
    decode,
    encode,
    head_body,
)
from paper_daily.drive_sync_log import DriveLog, transaction
from paper_daily.drive_sync_objects import DriveObjects
from paper_daily.presentations import _atomic_json
from paper_daily.sync_blobs import BlobManifest, BlobStore, _no_link
from paper_daily.sync_journal import SyncHistoryUnavailable

FORMAT = "paperfact.drive-authority-rows.v1"
MAX_STATE = 64 * 1024**2
CHECKPOINT_EVERY = 32
DELTA_FORMAT = "paperfact.drive-row-delta.v1"
DERIVED = {"sync_blob_integrity", "sync_blob_blocks"}
METHODS = frozenset(
    {
        "session_info",
        "control_session",
        "enroll",
        "push",
        "pull",
        "push_verified",
        "history_page",
        "device_catalog",
        "rename_device",
        "revoke_peer",
        "create_pairing",
        "redeem_pairing",
        "blob_begin",
        "blob_append",
        "blob_commit",
        "blob_cancel",
        "blob_read",
    }
)


class DriveAuthority:
    def __init__(self, files, folder, head_id, workspace, owner_id, root):
        self.files, self.workspace, self.owner_id = files, workspace, owner_id
        self.root = Path(root).absolute()
        for entry in (self.root, *self.root.parents):
            _no_link(entry)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_root = self.root / "authority"
        sync_admin.initialize(self.state_root)
        self.database = self.state_root / sync_admin.DATABASE
        self.log = DriveLog(files, folder, head_id, workspace)
        self.objects = DriveObjects(files, folder, workspace, self.root / "receipts")
        self.bytes = BlobStore(self.root / "state-bytes", max_blob_bytes=MAX_STATE)
        self._lock = threading.RLock()
        self._loaded = None
        self._payload = None
        self._ready_blobs = {}
        with closing(sqlite3.connect(self.database)) as conn:
            self.columns = {}
            for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                if name == "drive_anchor":
                    continue
                if not name.startswith("sync_"):
                    raise ValueError("Drive authority cache contains unexpected research")
                self.columns[name] = tuple(
                    row[1] for row in conn.execute(f'PRAGMA table_info("{name}")')
                )
            conn.execute("CREATE TABLE IF NOT EXISTS drive_anchor(value TEXT NOT NULL)")
            conn.commit()
        self._empty_path = self.root / "genesis.json"
        _no_link(self._empty_path)
        if not self._empty_path.exists():
            if self._anchor() is not None:
                raise ValueError("Private Drive cache has no genesis record")
            _atomic_json(self._empty_path, self._rows())
        # The private anchor survives restart independently of the cloud listing.
        self._check_account()

    def _check_account(self):
        self.account = self.files.account()
        if self.account["id"] != self.owner_id:
            raise PermissionError("Google account changed; reconnect the selected workspace")

    def _rows(self):
        tables = {}
        with closing(sqlite3.connect(self.database)) as conn:
            for name, columns in self.columns.items():
                if name in DERIVED:
                    continue
                rows = [list(row) for row in conn.execute(f'SELECT * FROM "{name}"')]
                rows.sort(key=lambda row: encode(row, MAX_STATE))
                tables[name] = dict(columns=list(columns), rows=rows)
        return dict(
            format=FORMAT,
            workspace_id=self.workspace,
            tables=tables,
            blobs={} if self._payload is None else self._payload["blobs"],
        )

    def _anchor(self):
        with closing(sqlite3.connect(self.database)) as conn:
            row = conn.execute("SELECT value FROM drive_anchor").fetchone()
        return None if row is None else head_body(decode(row[0].encode()))

    def _commit_bytes(self, ref):
        # Cache only exact hash-verified immutable chain links, never permission.
        path = self.root / (ref["sha256"] + ".commit")
        _no_link(path)
        if path.exists():
            raw = path.read_bytes()
            if len(raw) != ref["size"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
                raise SyncHistoryUnavailable("Private Drive chain cache is damaged")
            return raw
        raw = self.files.read_small(ref, self.log.folder, self.workspace)
        path.write_bytes(raw)
        return raw

    def _prove(self, current, prior):
        if prior is None:
            return
        before, after = decode(prior), current.value()
        if after["generation"] < before["generation"]:
            raise SyncHistoryUnavailable("Drive history moved behind locally retained work")
        ref, generation = after["commit"], after["generation"]
        deadline = time.monotonic() + 8
        while generation > before["generation"]:
            self.files.check()
            if time.monotonic() > deadline:
                raise DriveUnavailable("Catching up Drive history; verified progress is retained")
            value = transaction(self._commit_bytes(ref), self.workspace)
            if value["generation"] != generation:
                raise SyncHistoryUnavailable("Drive history has an ancestry gap")
            ref, generation = value["previous"], generation - 1
        if ref != before["commit"]:
            raise SyncHistoryUnavailable("Drive replaced a locally retained history prefix")

    def _validate(self, payload):
        if (
            not isinstance(payload, dict)
            or set(payload) != {"format", "workspace_id", "tables", "blobs"}
            or payload["format"] != FORMAT
            or payload["workspace_id"] != self.workspace
            or not isinstance(payload["tables"], dict)
            or set(payload["tables"]) != self.columns.keys() - DERIVED
            or not isinstance(payload["blobs"], dict)
        ):
            raise ValueError("Unsupported Drive research authority checkpoint")
        count = 0
        for name, table in payload["tables"].items():
            if (
                not isinstance(table, dict)
                or set(table) != {"columns", "rows"}
                or table["columns"] != list(self.columns[name])
                or not isinstance(table["rows"], list)
            ):
                raise ValueError("Drive checkpoint schema differs from this app version")
            for row in table["rows"]:
                count += 1
                if (
                    count > 100_000
                    or not isinstance(row, list)
                    or len(row) != len(self.columns[name])
                    or any(type(value) not in (str, int, float, type(None)) for value in row)
                ):
                    raise ValueError("Invalid bounded Drive authority row")
                if (
                    "workspace" in self.columns[name]
                    and row[self.columns[name].index("workspace")] != self.workspace
                ):
                    raise PermissionError("Drive checkpoint includes another workspace")
        encode(payload, MAX_STATE)

    def _restore(self, payload, anchor):
        self._validate(payload)
        with closing(sqlite3.connect(self.database)) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                for name in self.columns:
                    conn.execute(f'DELETE FROM "{name}"')
                for name, table in payload["tables"].items():
                    slots = ",".join("?" for _ in self.columns[name])
                    conn.executemany(f'INSERT INTO "{name}" VALUES({slots})', table["rows"])
                from paper_daily.sync_authority_control import fingerprint

                fingerprint(conn)
                conn.execute("DELETE FROM drive_anchor")
                conn.execute("INSERT INTO drive_anchor VALUES(?)", (anchor.decode(),))
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        marker = sync_admin.marker_for(self.database)
        _atomic_json(self.state_root / sync_admin.MARKER, marker)
        self._payload = payload
        self._ready_blobs.clear()

    def _delta(self, before, after):
        changes = {}
        for name in before["tables"]:
            left = {encode(row, MAX_STATE): row for row in before["tables"][name]["rows"]}
            right = {encode(row, MAX_STATE): row for row in after["tables"][name]["rows"]}
            if left != right:
                changes[name] = dict(
                    removed=[left[key] for key in sorted(left.keys() - right.keys())],
                    added=[right[key] for key in sorted(right.keys() - left.keys())],
                )
        return dict(
            format=DELTA_FORMAT,
            before=hashlib.sha256(encode(before, MAX_STATE)).hexdigest(),
            after=hashlib.sha256(encode(after, MAX_STATE)).hexdigest(),
            changes=changes,
            blobs={
                key: value
                for key, value in after["blobs"].items()
                if before["blobs"].get(key) != value
            },
        )

    def _apply_delta(self, before, delta):
        if (
            not isinstance(delta, dict)
            or set(delta) != {"format", "before", "after", "changes", "blobs"}
            or delta["format"] != DELTA_FORMAT
            or delta["before"] != hashlib.sha256(encode(before, MAX_STATE)).hexdigest()
            or not isinstance(delta["changes"], dict)
            or not isinstance(delta["blobs"], dict)
            or not delta["changes"].keys() <= before["tables"].keys()
        ):
            raise SyncHistoryUnavailable("Drive delta does not continue the verified state")
        result = decode(encode(before, MAX_STATE), MAX_STATE)
        for name, change in delta["changes"].items():
            if (
                not isinstance(change, dict)
                or set(change) != {"removed", "added"}
                or not isinstance(change["removed"], list)
                or not isinstance(change["added"], list)
            ):
                raise ValueError("Invalid Drive row delta")
            rows = {encode(row, MAX_STATE): row for row in result["tables"][name]["rows"]}
            for row in change["removed"]:
                key = encode(row, MAX_STATE)
                if key not in rows:
                    raise SyncHistoryUnavailable("Drive delta removes an unknown research row")
                del rows[key]
            for row in change["added"]:
                key = encode(row, MAX_STATE)
                if key in rows:
                    raise ValueError("Drive delta repeats an existing research row")
                rows[key] = row
            result["tables"][name]["rows"] = [rows[key] for key in sorted(rows)]
        result["blobs"].update(delta["blobs"])
        self._validate(result)
        if hashlib.sha256(encode(result, MAX_STATE)).hexdigest() != delta["after"]:
            raise SyncHistoryUnavailable("Drive delta failed its resulting-state hash")
        return result

    def _state_from(self, record):
        pending = []
        deadline = time.monotonic() + 8
        while set(record["payload"]) != {"state"}:
            if set(record["payload"]) != {"delta"} or len(pending) >= CHECKPOINT_EVERY:
                raise ValueError("Drive state has no bounded checkpoint")
            pending.append(record["payload"]["delta"])
            previous = record["previous"]
            if previous is None:
                raise ValueError("Drive delta has no checkpoint ancestor")
            if time.monotonic() > deadline:
                raise DriveUnavailable("Preparing Drive checkpoint; verified links are retained")
            parent = transaction(self._commit_bytes(previous), self.workspace)
            if parent["generation"] != record["generation"] - 1:
                raise SyncHistoryUnavailable("Drive checkpoint ancestry has a gap")
            record = parent
        path = self.objects.get(record["payload"]["state"], self.bytes)
        state = decode(path.read_bytes(), MAX_STATE)
        self._validate(state)
        for manifest in reversed(pending):
            path = self.objects.get(manifest, self.bytes)
            state = self._apply_delta(state, decode(path.read_bytes(), MAX_STATE))
        return state

    def _refresh(self):
        head = self.log.head()
        if self._loaded != head.body:
            self._prove(head, self._anchor())
            ref = head.value()["commit"]
            if ref is not None:
                record = transaction(self._commit_bytes(ref), self.workspace)
                if record["generation"] != head.value()["generation"]:
                    raise SyncHistoryUnavailable("Drive head and transaction disagree")
                self._restore(self._state_from(record), head.body)
            elif self._anchor() is not None and decode(self._anchor())["generation"] > 0:
                raise SyncHistoryUnavailable("A populated Drive workspace became empty")
            else:
                self._restore(decode(self._empty_path.read_bytes(), MAX_STATE), head.body)
            self._loaded = head.body
        return head

    def _store(self, service, workspace, digest, size):
        if workspace != self.workspace:
            raise PermissionError("Attachment belongs to another workspace")
        with service._transaction() as conn:
            return service._blob_owned_store(conn, workspace, BlobManifest(digest, size))

    def _supply(self, service, digest, size):
        key = digest, size
        manifest = None if self._payload is None else self._payload["blobs"].get(digest)
        if manifest is None:
            return
        if manifest.get("sha256") != digest or manifest.get("size") != size:
            raise ValueError("Drive attachment index does not match its owner")
        store = self._store(service, self.workspace, digest, size)
        path = store._path(BlobManifest(digest, size))
        identity = None if not path.exists() else (path.stat().st_size, path.stat().st_mtime_ns)
        if self._ready_blobs.get(key) != identity or identity is None:
            path = self.objects.get(manifest, store)
            self._ready_blobs[key] = path.stat().st_size, path.stat().st_mtime_ns

    def _upload_blobs(self, service, payload):
        for workspace, digest, size, state in payload["tables"]["sync_workspace_blobs"]["rows"]:
            if state != "committed" or digest in payload["blobs"]:
                continue
            store = self._store(service, workspace, digest, size)
            owner = BlobManifest(digest, size)
            path = store.verified_path(owner)
            payload["blobs"][digest] = self.objects.put(path, expected=owner)

    def invoke(self, method, *args, control=None, **kwargs):
        if method not in METHODS:
            raise ValueError("Unknown Drive research operation")
        with self._lock:
            head = self._refresh()
            service = sync_admin.authority(self.state_root)
            before = encode(self._rows(), MAX_STATE)
            try:
                # Materialize only the exact owned bytes required by this request.
                if method == "blob_read":
                    self._supply(service, args[1], args[2])
                elif method == "blob_begin":
                    self._supply(service, args[1]["sha256"], args[1]["size"])
                elif method in {"push", "push_verified"}:
                    op = args[1]
                    if op["entity_type"] == "paper_document" and op["action"] == "put":
                        self._supply(service, op["payload"]["sha256"], op["payload"]["size"])
                    elif op["entity_type"] == "research_file" and op["action"] == "put":
                        from paper_daily.sync_files import referenced_blobs

                        for ref in referenced_blobs(op):
                            self._supply(service, ref["sha256"], ref["size"])
                with service.control_execution(control) if control is not None else nullcontext():
                    if method == "enroll" and "credential" in kwargs:
                        from paper_daily.sync_device_management import pairing_secret
                        from paper_daily.sync_journal import _identifier

                        workspace, device = args
                        _identifier(device)
                        if workspace != self.workspace:
                            raise PermissionError("Enroll only in the selected Drive workspace")
                        credential = pairing_secret(kwargs["credential"])
                        token_hash = service._token_hash(credential)
                        with service._transaction(write=True) as conn:
                            old = conn.execute(
                                "SELECT token_hash,revoked FROM sync_devices "
                                "WHERE workspace=? AND device=?",
                                (workspace, device),
                            ).fetchone()
                            if old is not None and (old[0] != token_hash or old[1]):
                                raise PermissionError("Device already enrolled with another grant")
                            if old is None:
                                conn.execute(
                                    "INSERT INTO sync_devices VALUES(?,?,?,0,NULL)",
                                    (token_hash, workspace, device),
                                )
                        result = credential
                    else:
                        result = getattr(service, method)(*args, **kwargs)
                payload = self._rows()
                if encode(payload, MAX_STATE) != before:
                    self._upload_blobs(service, payload)
                    checkpoint = head.value()["generation"] % CHECKPOINT_EVERY == 0
                    outgoing = (
                        payload if checkpoint else self._delta(decode(before, MAX_STATE), payload)
                    )
                    raw = encode(outgoing, MAX_STATE)
                    staging = self.root / "checkpoint.pending"
                    _no_link(staging)
                    staging.write_bytes(raw)
                    manifest = self.objects.put(staging)
                    self.bytes.import_file(
                        BlobManifest(manifest["sha256"], manifest["size"]),
                        staging,
                        check=self.files.check,
                    )
                    published = self.log.append(
                        head,
                        self.files.new_ids()[0],
                        {"state" if checkpoint else "delta": manifest},
                    )
                    # The cloud has committed. A lost local acknowledgment is repaired on reload.
                    with closing(sqlite3.connect(self.database)) as conn:
                        conn.execute("DELETE FROM drive_anchor")
                        conn.execute(
                            "INSERT INTO drive_anchor VALUES(?)", (published.body.decode(),)
                        )
                        conn.commit()
                    self._loaded, self._payload = published.body, payload
                return result
            except BaseException:
                self._loaded = None
                raise
