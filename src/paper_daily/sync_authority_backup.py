"""Private, bounded authority snapshots; never enroll, restore, upload or serve."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from paper_daily.sync_blobs import BlobManifest, _no_link

FORMAT = "paperfact-authority-backup-v1"
MANIFEST = "manifest.json"
POLICY = "committed-objects-only; incomplete-uploads-must-restart; no-live-restore"
MAX_FILES = 100_000
MAX_MANIFEST = 24 * 1024**2
CHUNK = 1024**2
OBJECT = re.compile(r"blobs/[0-9a-f]{32}/objects/[0-9a-f]{64}")
TABLES = {
    "sync_devices",
    "sync_events",
    "sync_heads",
    "sync_blob_namespaces",
    "sync_workspace_blobs",
}


class BackupCancelled(ValueError):
    """Cancellation or a bounded snapshot deadline was reached."""


def _guard(seconds, cancelled):
    if type(seconds) not in (int, float) or not 0 < seconds <= 300:
        raise ValueError("Backup time budget must be greater than zero and at most 300 seconds")
    end = time.monotonic() + seconds

    def check(*_args):
        if cancelled() or time.monotonic() >= end:
            raise BackupCancelled("Backup stopped before completion")

    return check


def _path(value):
    path = Path(value).absolute()
    for entry in (path, *path.parents):
        _no_link(entry)
    return path.resolve()


def _identity(path):
    _path(path)
    info = path.stat()
    if not path.is_file():
        raise ValueError("Backup entries must be regular files")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _connect(path):
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA trusted_schema=OFF")
    return conn


def _schema(conn, check):
    conn.set_progress_handler(lambda: (check(), 0)[1], 1000)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not tables >= TABLES or "papers" in tables:
        raise ValueError("Expected a reference sync authority")
    if conn.execute("PRAGMA quick_check").fetchone() != ("ok",):
        raise ValueError("Authority database integrity check failed")


def _objects(conn, check):
    # Include committed bytes even if only retained history/conflicts reference them.
    rows = conn.execute(
        "SELECT b.digest,b.size,n.directory FROM sync_workspace_blobs b "
        "LEFT JOIN sync_blob_namespaces n ON n.workspace=b.workspace "
        "WHERE b.state='committed' ORDER BY n.directory,b.digest"
    )
    result = {}
    for digest, size, directory in rows:
        check()
        item = BlobManifest(digest, size)
        if not isinstance(directory, str) or not re.fullmatch(r"[0-9a-f]{32}", directory):
            raise ValueError("Committed attachment has no valid storage namespace")
        name = f"blobs/{directory}/objects/{item.sha256}"
        result[name] = {"path": name, "sha256": item.sha256, "size": item.size}
        if len(result) > MAX_FILES:
            raise ValueError("Backup entry budget exceeded")
    _references(conn, check)
    return result


def _references(conn, check):
    from paper_daily.sync_client import validate_event
    from paper_daily.sync_files import referenced_blobs
    from paper_daily.sync_journal import MAX_BYTES, canonical_operation

    previous = {}
    rows = conn.execute(
        "SELECT workspace,sequence,operation_id,fingerprint,"
        "CASE WHEN length(CAST(event AS BLOB))<=? THEN event END FROM sync_events "
        "ORDER BY workspace,sequence",
        (2 * MAX_BYTES + 8192,),
    )
    for workspace, sequence, operation_id, fingerprint, raw in rows:
        check()
        if raw is None or sequence != previous.get(workspace, 0) + 1:
            raise ValueError("Authority event prefix is incomplete or oversized")
        event = _decode(raw)
        validate_event(event, workspace)
        operation = event["operation"]
        encoded = canonical_operation(operation).encode("utf-8")
        if (
            event["sequence"] != sequence
            or operation["operation_id"] != operation_id
            or hashlib.sha256(encoded).hexdigest() != fingerprint
        ):
            raise ValueError("Authority event receipt is inconsistent")
        previous[workspace] = sequence
        if operation["action"] == "delete":
            continue
        if operation["entity_type"] == "paper_document":
            references = [operation["payload"]]
        elif operation["entity_type"] == "research_file":
            references = referenced_blobs(operation)
        else:
            references = []
        for reference in references:
            row = conn.execute(
                "SELECT state,size FROM sync_workspace_blobs WHERE workspace=? AND digest=?",
                (workspace, reference["sha256"]),
            ).fetchone()
            if row != ("committed", reference["size"]):
                raise ValueError("Retained event references uncommitted or missing bytes")


def _hash(path, check, target=None):
    before = _identity(path)
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        opened = os.fstat(source.fileno())
        if (opened.st_dev, opened.st_ino) != before[:2]:
            raise ValueError("Backup source changed before reading")
        while chunk := source.read(CHUNK):
            check()
            digest.update(chunk)
            size += len(chunk)
            if target is not None:
                target.write(chunk)
    if _identity(path) != before:
        raise ValueError("Backup source changed during reading")
    check()
    return {"sha256": digest.hexdigest(), "size": size}


def _sync_directory(path):
    # Windows directory durability requires platform APIs; file fsync is retained.
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _decode(raw):
    try:
        return json.loads(raw, object_pairs_hook=_unique)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid bounded backup JSON") from exc


def _json(path):
    try:
        return _decode(path.read_text(encoding="utf-8"))
    except UnicodeError as exc:
        raise ValueError("Invalid bounded backup JSON") from exc


def _write(path, callback):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        result = callback(stream)
        stream.flush()
        os.fsync(stream.fileno())
    return result


def export(state, output, *, seconds=30, cancelled=lambda: False):
    """Write a new private snapshot directory; completion manifest is published last.

    A bounded SQLite writer reservation pauses authority writes during capture.
    Failed output is deliberately retained without a completion manifest. Retry
    with a new empty pathname; never overwrite or delete operator-owned files.
    """
    from paper_daily.sync_admin import DATABASE, MARKER
    from paper_daily.sync_admin import FORMAT as SERVICE_FORMAT

    check = _guard(seconds, cancelled)
    root, output = _path(state), _path(output)
    if root == output or output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError("Keep backups separate from authority state")
    marker, database = root / MARKER, root / DATABASE
    _identity(marker)
    if marker.stat().st_size > 256 or _json(marker) != SERVICE_FORMAT:
        raise ValueError("Initialize a dedicated authority first")
    original = _identity(database)
    for suffix in ("-wal", "-shm", "-journal"):
        _path(Path(str(database) + suffix))
    check()
    # Fail if another process reserved the pathname, even if it is an empty folder.
    output.mkdir(mode=0o700)
    with closing(sqlite3.connect(database.as_uri() + "?mode=rw", uri=True, timeout=1)) as lock:
        try:
            lock.execute("BEGIN IMMEDIATE")
            with closing(_connect(database)) as source:
                _schema(source, check)
                destination = output / DATABASE
                with closing(sqlite3.connect(destination)) as snapshot:
                    os.chmod(destination, 0o600)
                    source.backup(snapshot, pages=128, progress=check, sleep=0.01)
                    snapshot.execute("PRAGMA journal_mode=DELETE")
                with closing(_connect(destination)) as captured:
                    _schema(captured, check)
                    objects = _objects(captured, check)
                files = [{"path": DATABASE, **_hash(destination, check)}]
                for name, expected in objects.items():
                    check()
                    target = output / name
                    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    actual = _write(
                        target, lambda stream, name=name: _hash(root / name, check, stream)
                    )
                    if actual != {key: expected[key] for key in ("sha256", "size")}:
                        raise ValueError("Committed attachment bytes require repair")
                    files.append(expected)
            # Identity continuity matters; sqlite's own writes can change mtime.
            if _identity(database)[:2] != original[:2]:
                raise ValueError("Authority was replaced during backup")
            value = {"format": FORMAT, "policy": POLICY, "files": files}
            body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if len(body) > MAX_MANIFEST:
                raise ValueError("Backup manifest budget exceeded")
            check()
            # Verify the exported SQLite bytes were flushed before publication.
            with destination.open("r+b") as stream:
                os.fsync(stream.fileno())
            for directory, _folders, _files in os.walk(output, topdown=False):
                check()
                _sync_directory(Path(directory))
            _write(output / ".manifest.pending", lambda stream: stream.write(body))
            check()
            (output / ".manifest.pending").rename(output / MANIFEST)
            _sync_directory(output)
            _sync_directory(output.parent)
        finally:
            lock.rollback()
    return {"state": "backed_up", "files": len(files), "bytes": sum(item["size"] for item in files)}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate backup manifest field")
        result[key] = value
    return result


def _inspect(output, *, seconds=30, cancelled=lambda: False, manifest_name=MANIFEST):
    """Read-only hash/schema/coverage inspection; grants no authority to restore."""
    check = _guard(seconds, cancelled)
    root = _path(output)
    if manifest_name not in {MANIFEST, ".manifest.pending"}:
        raise ValueError("Unsupported backup completion filename")
    path = root / manifest_name
    manifest_identity = _identity(path)
    if path.stat().st_size > MAX_MANIFEST:
        raise ValueError("Backup manifest budget exceeded")
    value = _json(path)
    if (
        not isinstance(value, dict)
        or set(value) != {"format", "policy", "files"}
        or value["format"] != FORMAT
        or value["policy"] != POLICY
        or not isinstance(value["files"], list)
        or not 1 <= len(value["files"]) <= MAX_FILES + 1
    ):
        raise ValueError("Unsupported authority backup manifest")
    entries, identities = {}, {}
    for item in value["files"]:
        check()
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "size"}:
            raise ValueError("Invalid backup entry")
        name = item["path"]
        if (
            not isinstance(name, str)
            or not (name == "authority.sqlite" or OBJECT.fullmatch(name))
            or name in entries
        ):
            raise ValueError("Invalid or duplicate backup entry path")
        BlobManifest(item["sha256"], item["size"])
        identities[name] = _identity(root / name)
        if _hash(root / name, check) != {key: item[key] for key in ("sha256", "size")}:
            raise ValueError("Backup bytes do not match their manifest")
        entries[name] = item
    if "authority.sqlite" not in entries:
        raise ValueError("Authority snapshot is missing")
    # Reject stray bytes, links and SQLite sidecars; verification cannot replay WAL.
    seen = set()
    for directory, folders, files in os.walk(root, followlinks=False):
        check()
        for name in folders + files:
            _path(Path(directory) / name)
        seen.update((Path(directory) / name).relative_to(root).as_posix() for name in files)
    if seen != set(entries) | {manifest_name}:
        raise ValueError("Backup contains unexpected files")
    with closing(_connect(root / "authority.sqlite")) as conn:
        _schema(conn, check)
        objects = _objects(conn, check)
    if objects != {key: item for key, item in entries.items() if key != "authority.sqlite"}:
        raise ValueError("Backup does not cover committed authority attachments")
    check()
    if _identity(path) != manifest_identity or any(
        _identity(root / name) != identity for name, identity in identities.items()
    ):
        raise ValueError("Backup changed during verification")
    receipt = {
        "state": "verified",
        "files": len(entries),
        "bytes": sum(item["size"] for item in entries.values()),
        "live_restore": False,
    }
    return receipt, value, manifest_identity, identities


def verify(output, *, seconds=30, cancelled=lambda: False):
    """Read-only integrity receipt; does not grant later restoration authority."""
    return _inspect(output, seconds=seconds, cancelled=cancelled)[0]
