"""Durable desired/applied artifact versions; byte absence never blocks inbox progress."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from paper_daily.sync_blobs import BlobError, BlobManifest, BlobStore, _no_link
from paper_daily.sync_files import canonical_json, referenced_blobs, validate_closure
from paper_daily.sync_journal import canonical_operation

_SEAL = object()


def _identity(path, stream=None):
    for entry in (path, *path.parents):
        _no_link(entry)
    if not path.is_file():
        raise ValueError("Artifact entry is not a regular file")
    from paper_daily.file_change import version

    try:
        return version(path, stream=stream)
    except OSError as error:
        raise ValueError("Artifact path or handle identity changed or is unavailable") from error


@dataclass(frozen=True, init=False)
class VerifiedClosure:
    operation: str
    files: dict
    blocks: dict
    seal: object

    def matches(self, operation):
        if getattr(self, "seal", None) is not _SEAL or self.operation != canonical_operation(
            operation
        ):
            return False
        try:
            return all(_identity(path) == identity for path, identity in self.files.values())
        except (OSError, ValueError):
            return False

    def read_chunk(self, sha256, offset, amount):
        path, identity = self.files[sha256]
        block_size = 256 * 1024
        if (
            type(offset) is not int
            or type(amount) is not int
            or offset < 0
            or not 0 < amount <= block_size
            or offset + amount > identity[2]
        ):
            raise ValueError("Artifact range exceeds bounded transfer limits")
        first, last = offset // block_size, (offset + amount - 1) // block_size
        chunks = []
        with path.open("rb") as stream:
            for index in range(first, last + 1):
                stream.seek(index * block_size)
                data = stream.read(min(block_size, identity[2] - index * block_size))
                if hashlib.sha256(data).hexdigest() != self.blocks[sha256][index]:
                    raise ValueError("Artifact block changed during transfer")
                chunks.append(data)
        if _identity(path) != identity:
            raise ValueError("Artifact changed during transfer")
        start = offset - first * block_size
        return b"".join(chunks)[start : start + amount]


def verify_closure(store, operation):
    files, blocks, blobs = {}, {}, {}
    for row in referenced_blobs(operation):
        manifest = BlobManifest(row["sha256"], row["size"])
        path = store._path(manifest)
        # Reject an impossible size before opening even a metadata-only handle.
        # The guarded identity and bounded read below still close the race.
        if path.stat().st_size != manifest.size:
            raise ValueError("Artifact size differs from its manifest")
        identity = _identity(path)
        if identity[2] != manifest.size:
            raise ValueError("Artifact size differs from its manifest")
        with path.open("rb") as stream:
            if _identity(path, stream) != identity:
                raise ValueError("Artifact changed before verification")
            data = stream.read(manifest.size + 1)
            if len(data) != manifest.size or _identity(path, stream) != identity:
                raise ValueError("Artifact size or identity changed during verification")
        files[manifest.sha256] = (path, identity)
        blocks[manifest.sha256] = [
            hashlib.sha256(data[n : n + 256 * 1024]).hexdigest()
            for n in range(0, len(data), 256 * 1024)
        ]
        blobs[manifest.sha256] = data
    body = validate_closure(operation["payload"], lambda row: blobs[row["sha256"]])
    result = object.__new__(VerifiedClosure)
    for key, value in {
        "operation": canonical_operation(operation),
        "files": files,
        "blocks": blocks,
        "seal": _SEAL,
    }.items():
        object.__setattr__(result, key, value)
    if not result.matches(operation):
        raise ValueError("Artifact changed after verification")
    return result, body, blobs


@dataclass(frozen=True, init=False)
class MaterializedVersion:
    path: Path
    operation: str
    files: dict
    seal: object

    def __fspath__(self):
        return str(self.path)

    def __truediv__(self, name):
        return self.path / name

    def matches(self, operation):
        if getattr(self, "seal", None) is not _SEAL or self.operation != canonical_operation(
            operation
        ):
            return False
        try:
            return all(
                _identity(self.path / name) == identity for name, identity in self.files.items()
            )
        except (OSError, ValueError):
            return False


def initialize(conn):
    if not conn.in_transaction:
        raise ValueError("Artifact initialization requires a caller transaction")
    for table, definition in {
        "research_file_desired": (
            "entity_id TEXT PRIMARY KEY,operation TEXT NOT NULL,active INTEGER NOT NULL"
        ),
        "research_file_applied": "entity_id TEXT PRIMARY KEY,operation TEXT NOT NULL",
        "research_file_versions": (
            "operation_id TEXT PRIMARY KEY,entity_id TEXT NOT NULL,operation TEXT NOT NULL"
        ),
        "research_file_intents": (
            "operation_id TEXT PRIMARY KEY,entity_id TEXT NOT NULL,state TEXT NOT NULL"
        ),
        "research_file_candidates": (
            "candidate_id TEXT PRIMARY KEY,entity_id TEXT NOT NULL,payload "
            "TEXT NOT NULL,observation TEXT NOT NULL"
        ),
        "research_file_drafts": (
            "candidate_id TEXT PRIMARY KEY,entity_id TEXT NOT NULL,deck TEXT "
            "NOT NULL,observation TEXT NOT NULL"
        ),
        "research_file_paths": (
            "id INTEGER PRIMARY KEY CHECK(id=1),workspace TEXT NOT "
            "NULL,blob_root TEXT NOT NULL,version_root TEXT NOT NULL"
        ),
    }.items():
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({definition})")


def register_paths(conn, workspace, store, version_root):
    if not conn.in_transaction or not isinstance(store, BlobStore):
        raise ValueError("Artifact paths require a transaction and explicit store")
    root = Path(version_root).absolute()
    for part in (root, *root.parents):
        _no_link(part)
    binding = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
    if binding is None or binding[0] != workspace:
        raise ValueError("Artifact paths belong to another workspace")
    row = conn.execute(
        "SELECT workspace,blob_root,version_root FROM research_file_paths WHERE id=1"
    ).fetchone()
    expected = (workspace, str(store.root), str(root))
    if row is not None and tuple(row) != expected:
        raise ValueError("Changing artifact storage requires explicit migration")
    conn.execute("INSERT OR IGNORE INTO research_file_paths VALUES(1,?,?,?)", expected)


def paths(conn):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='research_file_paths'").fetchone():
        return None
    row = conn.execute(
        "SELECT workspace,blob_root,version_root FROM research_file_paths WHERE id=1"
    ).fetchone()
    if row is None:
        return None
    binding = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
    if binding is None or binding[0] != row[0]:
        raise ValueError("Artifact paths have the wrong workspace")
    return BlobStore(Path(row[1])), Path(row[2])


def _read(conn, table, identity, *, active=False):
    row = conn.execute(
        f"SELECT operation FROM {table} WHERE entity_id=?" + (" AND active=1" if active else ""),
        (identity,),
    ).fetchone()
    if row is None:
        return None
    operation = json.loads(row[0])
    canonical_operation(operation)
    binding = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
    if (
        operation["entity_type"] != "research_file"
        or operation["entity_id"] != identity
        or not binding
        or binding[0] != operation["workspace_id"]
    ):
        raise ValueError("Invalid stored artifact binding")
    return operation


def desired_file(conn, identity):
    return _read(conn, "research_file_desired", identity, active=True)


def applied_file(conn, identity):
    return _read(conn, "research_file_applied", identity)


def paper_current(conn, operation):
    parent = operation["parents"][0]
    row = conn.execute(
        (
            "SELECT g.incarnation FROM research_paper_projection g JOIN "
            "research_paper_identity p ON p.sync_id=g.sync_id JOIN papers r "
            "ON r.id=p.local_id WHERE g.sync_id=?"
        ),
        (parent["id"],),
    ).fetchone()
    return row is not None and row[0] == parent["incarnation"]


def write_file(conn, operation):
    canonical_operation(operation)
    if not conn.in_transaction or operation["entity_type"] != "research_file":
        raise ValueError("Artifact metadata requires its research transaction")
    binding = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
    if binding is None or binding[0] != operation["workspace_id"]:
        raise ValueError("Artifact belongs to another workspace")
    identity, oid = operation["entity_id"], operation["operation_id"]
    if operation["action"] == "delete":
        previous = desired_file(conn, identity)
        if previous and (previous["incarnation"], previous["parents"]) == (
            operation["incarnation"],
            operation["parents"],
        ):
            conn.execute("UPDATE research_file_desired SET active=0 WHERE entity_id=?", (identity,))
            conn.execute(
                (
                    "UPDATE research_file_intents SET state='superseded' WHERE "
                    "entity_id=? AND state='pending'"
                ),
                (identity,),
            )
        return
    if not paper_current(conn, operation):
        raise ValueError("Artifact requires its projected paper incarnation")
    if operation["payload"]["feature"] == "legacy_brief":
        from paper_daily.legacy_workflow import require_ready

        require_ready(conn)
    encoded = canonical_operation(operation)
    row = conn.execute(
        "SELECT operation FROM research_file_versions WHERE operation_id=?", (oid,)
    ).fetchone()
    if row and row[0] != encoded:
        raise ValueError("Artifact operation identity reused")
    conn.execute(
        "INSERT OR IGNORE INTO research_file_versions VALUES(?,?,?)", (oid, identity, encoded)
    )
    conn.execute(
        (
            "UPDATE research_file_intents SET state='superseded' WHERE "
            "entity_id=? AND operation_id!=? AND state='pending'"
        ),
        (identity, oid),
    )
    conn.execute(
        (
            "INSERT INTO research_file_desired VALUES(?,?,1) ON "
            "CONFLICT(entity_id) DO UPDATE SET "
            "operation=excluded.operation,active=1"
        ),
        (identity, encoded),
    )
    conn.execute(
        "INSERT OR IGNORE INTO research_file_intents VALUES(?,?,'pending')", (oid, identity)
    )


def stage_bytes(store, blobs):
    for sha256, data in blobs.items():
        manifest = BlobManifest(sha256, len(data))
        status = store.begin(manifest)
        if status["complete"]:
            continue
        offset = status["offset"]
        while offset < len(data):
            offset = store.append(manifest, offset, data[offset : offset + store.chunk_bytes])
        try:
            store.finalize(manifest)
        except BlobError:
            store.discard_partial(manifest)
            raise


def version_directory(root, operation):
    identity = hashlib.sha256(canonical_operation(operation).encode()).hexdigest()
    path = Path(root).absolute() / identity
    for part in (path, *path.parents):
        _no_link(part)
    return path


def materialize(store, root, operation):
    """Build a complete immutable revision outside the research write lock."""
    from paper_daily.presentations import deck_from_dict

    verified, body, blobs = verify_closure(store, operation)
    directory = version_directory(root, operation)
    directory.mkdir(parents=True, exist_ok=True)
    if operation["payload"]["feature"] == "original_source":
        files = {"source.json": canonical_json(body), "source.pdf": blobs[body["document_hash"]]}
    elif operation["payload"]["feature"] == "legacy_brief":
        from paper_daily.legacy_briefs import filename

        files = {
            "brief.json": canonical_json(body),
            filename(body): blobs[operation["payload"]["assets"][0]["sha256"]],
        }
    else:
        raw = body["deck"]
        descriptors = {row["id"]: row for row in operation["payload"]["assets"]}
        for figure in raw["figures"]:
            description = descriptors[figure.pop("asset_id")]
            figure["asset"] = description["sha256"] + ".png"
        deck_from_dict(raw)
        files = {"deck.json": canonical_json(raw)}
        for description in operation["payload"]["assets"]:
            suffix = ".png" if description["role"] == "figure" else ".json"
            files[description["sha256"] + suffix] = blobs[description["sha256"]]
    for name, data in files.items():
        destination = directory / name
        _no_link(destination)
        if destination.exists():
            if destination.read_bytes() != data:
                raise ValueError("Existing immutable artifact version is damaged")
            continue
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".stage-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    if not verified.matches(operation):
        raise ValueError("Artifact source changed during materialization")
    installed = {}
    for name, expected in files.items():
        path = directory / name
        before = _identity(path)
        if path.read_bytes() != expected or _identity(path) != before:
            raise ValueError("Installed artifact changed during materialization")
        installed[name] = before
    snapshot = object.__new__(MaterializedVersion)
    for key, value in {
        "path": directory,
        "operation": canonical_operation(operation),
        "files": installed,
        "seal": _SEAL,
    }.items():
        object.__setattr__(snapshot, key, value)
    if operation["payload"]["feature"] == "legacy_brief":
        object.__setattr__(snapshot, "_legacy_brief_body", canonical_json(body))
    return snapshot


def activate(conn, operation, directory):
    """Recheck desired target/parent; paths are fixed by the registered binding."""
    if not conn.in_transaction:
        raise ValueError("Artifact activation requires a transaction")
    registered = paths(conn)
    if registered is None or Path(directory) != version_directory(registered[1], operation):
        raise ValueError("Artifact version is outside its registered storage")
    if desired_file(conn, operation["entity_id"]) != operation or not paper_current(
        conn, operation
    ):
        return False
    if not isinstance(directory, MaterializedVersion) or not directory.matches(operation):
        raise ValueError("Installed artifact changed before activation")
    if operation["payload"]["feature"] == "legacy_brief":
        from paper_daily.legacy_briefs import bind_in

        if not bind_in(conn, operation, directory):
            return False
    conn.execute(
        (
            "INSERT INTO research_file_applied VALUES(?,?) ON "
            "CONFLICT(entity_id) DO UPDATE SET operation=excluded.operation"
        ),
        (operation["entity_id"], canonical_operation(operation)),
    )
    conn.execute(
        "UPDATE research_file_intents SET state='bound' WHERE operation_id=?",
        (operation["operation_id"],),
    )
    return True
