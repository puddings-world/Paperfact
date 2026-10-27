"""Read-only workspace visibility and explicitly staged independent recovery.

No enrollment, transport, credentials, workspace activation or AI calls live here.
Caller must quiesce research producers before backup (including external writers).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from paper_daily import runtime, sync_recovery
from paper_daily.sync_blobs import BlobManifest, BlobStore, _no_link
from paper_daily.sync_recovery_fs import publish_directory

COUNT_LIMIT = 100_000
FILE_LIMIT = 256
VERIFY_BYTES = 64 * 1024**2


class WorkspaceChanged(ValueError):
    """The selected workspace or its durable binding changed."""


class SnapshotChanged(ValueError):
    """Research changed during the independent snapshot; retry is safe."""


class Cancelled(Exception):
    """Cancelled before publication; the destination was not published."""


class Ticket:
    """One final publication or cancellation wins under the same lock."""

    def __init__(self):
        self._lock = threading.Lock()
        self.cancelled = False
        self.published = False

    def cancel(self):
        with self._lock:
            if not self.published:
                self.cancelled = True

    def check(self):
        if self.cancelled:
            raise Cancelled()

    def publish(self, action):
        with self._lock:
            self.check()
            action()
            self.published = True


def _safe_path(value):
    path = Path(value).absolute()
    for part in (path, *path.parents):
        _no_link(part)
    return path.resolve()


def location_policy(path, *, env=None, frozen=None):
    env = os.environ if env is None else env
    frozen = runtime.FROZEN if frozen is None else frozen
    path = Path(path).resolve()
    for name in ("PAPERFACT_DATA", "PAPER_DAILY_DATA"):
        if env.get(name):
            return name if Path(env[name]).resolve() == path else "explicit"
    default = runtime.user_data_dir(env=env) if frozen else runtime.bundle_root() / "data"
    return (
        ("installed-default" if frozen else "source-default")
        if default.resolve() == path
        else "explicit"
    )


@contextmanager
def _read(path, *, budget=2.0):
    conn = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True, timeout=0.2)
    deadline = time.monotonic() + budget
    conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 2000)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        yield conn
    finally:
        conn.close()


def _tables(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _binding(conn, tables):
    binding = []
    for table, columns in (
        ("paperfact_sync_identity", "workspace,device"),
        ("research_sync_binding", "workspace,origin"),
        ("research_capture_binding", "workspace,device"),
    ):
        if table in tables:
            rows = conn.execute(f"SELECT {columns} FROM {table} LIMIT 2").fetchall()
            if len(rows) != 1:
                raise WorkspaceChanged("Workspace binding is incomplete")
            binding.append((table, tuple(rows[0])))
    if len({item[1][0] for item in binding}) > 1:
        raise WorkspaceChanged("Workspace bindings disagree")
    return tuple(binding)


def _paths(conn, tables, binding):
    workspace = binding[0][1][0] if binding else None
    roots, legacy, registrations = set(), set(), []
    for table, columns in (
        ("document_reader_paths", "workspace,blob_root,legacy_root"),
        ("research_file_paths", "workspace,blob_root,version_root"),
    ):
        if table not in tables:
            continue
        rows = conn.execute(f"SELECT {columns} FROM {table} LIMIT 2").fetchall()
        if len(rows) > 1:
            raise WorkspaceChanged("Workspace file registration is ambiguous")
        for row in rows:
            if row[0] != workspace:
                raise WorkspaceChanged("Workspace file registration belongs elsewhere")
            roots.add(_safe_path(row[1]))
            registrations.append((table, tuple(row)))
            if table == "document_reader_paths":
                legacy.add(_safe_path(row[2]))
    if len(roots) > 1 or len(legacy) > 1:
        raise WorkspaceChanged("Multiple file stores need explicit reconciliation")
    return next(iter(roots), None), next(iter(legacy), None), tuple(registrations)


class _ReadOnlyStore(BlobStore):
    """Use the existing verifier without creating directories or index tables."""

    def __init__(self, root):
        self.root = _safe_path(root)
        self.quota_bytes = 4 * 1024**3
        self.max_blob_bytes = 1024**3
        self.chunk_bytes = 1024**2
        if not (self.root / "index.sqlite").is_file():
            raise ValueError("Registered file store is unavailable")
        _safe_path(self.root / "index.sqlite")


def _file_identity(info):
    # A read may update access time on a valid file; it is not content identity.
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _count(conn, query):
    value = conn.execute(f"SELECT COUNT(*) FROM ({query} LIMIT {COUNT_LIMIT + 1})").fetchone()[0]
    return {"value": min(value, COUNT_LIMIT), "capped": value > COUNT_LIMIT}


class WorkspaceService:
    def __init__(self, database, *, current_path=None):
        self.path = _safe_path(database)
        info = self.path.stat()
        if not self.path.is_file():
            raise ValueError("Workspace database is unavailable")
        self.identity = info.st_dev, info.st_ino
        self.current_path = current_path or (lambda: self.path)
        self._baseline = None
        self._inspected = None
        self.blob_root = self.legacy_root = None

    def _context(self):
        if Path(self.current_path()).resolve() != self.path:
            raise WorkspaceChanged("The active workspace changed")
        info = _safe_path(self.path).stat()
        if (info.st_dev, info.st_ino) != self.identity:
            raise WorkspaceChanged("The workspace database was replaced")
        with _read(self.path) as conn:
            tables = _tables(conn)
            binding = _binding(conn, tables)
            blob, legacy, registration = _paths(conn, tables, binding)
        return binding, registration, blob, legacy

    def check(self):
        context = self._context()
        if self._baseline is None or context != self._baseline:
            raise WorkspaceChanged("Refresh the workspace before continuing")

    def status(self, ticket=None):
        ticket = ticket or Ticket()
        ticket.check()
        context = self._context()
        if self._baseline is not None and self._baseline != context:
            raise WorkspaceChanged("The workspace binding changed")
        self._baseline = context
        self.blob_root, self.legacy_root = context[2:]
        with _read(self.path) as conn:
            tables = _tables(conn)
            counts = {}
            for name in ("lists", "papers", "notes"):
                counts[name] = _count(conn, f"SELECT 1 FROM {name}") if name in tables else None
            sync = None
            if "paperfact_sync_identity" in tables:
                cursor = conn.execute(
                    "SELECT sequence FROM paperfact_sync_cursor WHERE id=1"
                ).fetchone()[0]
                sync = {
                    "cursor": cursor,
                    "pending": _count(
                        conn,
                        "SELECT 1 FROM paperfact_sync_operations WHERE server_revision IS NULL",
                    ),
                    "awaiting": _count(
                        conn,
                        "SELECT 1 FROM paperfact_sync_operations "
                        f"WHERE server_revision>{int(cursor)}",
                    ),
                    "conflicts": _count(
                        conn, "SELECT 1 FROM paperfact_sync_conflicts WHERE resolved_by IS NULL"
                    ),
                }
        try:
            files = self._files(ticket)
        except (OSError, ValueError, sqlite3.Error):
            files = {
                "registered": self.blob_root is not None,
                "checked": 0,
                "verified_bytes": 0,
                "unavailable": None,
                "partial": True,
                "error": "unavailable",
            }
        ticket.check()
        self.check()
        return {
            "path": str(self.path.parent),
            "database": str(self.path),
            "policy": location_policy(self.path.parent),
            "counts": counts,
            "sync": sync,
            "files": files,
            "free_bytes": shutil.disk_usage(self.path.parent).free,
        }

    def _files(self, ticket):
        result = {
            "registered": self.blob_root is not None,
            "checked": 0,
            "verified_bytes": 0,
            "unavailable": 0,
            "partial": True,
        }
        if self.blob_root is None:
            return result
        store = _ReadOnlyStore(self.blob_root)
        with _read(store.root / "index.sqlite") as conn:
            rows = conn.execute(
                "SELECT digest,size,complete FROM blobs ORDER BY digest LIMIT ?", (FILE_LIMIT + 1,)
            ).fetchall()
        deadline = time.monotonic() + 2.0
        spent = 0
        for digest, size, complete in rows[:FILE_LIMIT]:
            ticket.check()
            manifest = BlobManifest(digest, size)
            if spent + size > VERIFY_BYTES or time.monotonic() > deadline:
                break
            result["checked"] += 1
            if not complete:
                result["unavailable"] += 1
                continue
            path = store._path(manifest)
            try:
                before = path.stat()
                if before.st_size != size:
                    raise ValueError("File size changed")
                hashed = hashlib.sha256()
                with path.open("rb") as stream:
                    remaining = size
                    while remaining:
                        ticket.check()
                        if time.monotonic() > deadline:
                            return result
                        part = stream.read(min(256 * 1024, remaining))
                        if not part:
                            raise ValueError("File is incomplete")
                        remaining -= len(part)
                        spent += len(part)
                        hashed.update(part)
                    if stream.read(1):
                        raise ValueError("File grew")
                if (
                    _file_identity(path.stat()) != _file_identity(before)
                    or hashed.hexdigest() != digest
                ):
                    raise ValueError("File verification failed")
                result["verified_bytes"] += size
            except (OSError, ValueError):
                result["unavailable"] += 1
        result["partial"] = result["checked"] != len(rows) or len(rows) > FILE_LIMIT
        return result

    def _sidecars(self):
        from paper_daily import research_chat, research_compound, research_generation

        digest = hashlib.sha256()
        import json

        for loader in (
            research_chat.list_recovery_requests,
            research_compound.list_recovery_requests,
            research_generation.list_recovery_requests,
        ):
            records = loader(self.path)
            # Each typed loader has its own closed schema and scan/byte bounds.
            for record in sorted(records, key=lambda item: item["request_id"]):
                digest.update(
                    json.dumps(
                        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                    ).encode()
                )
        return digest.digest()

    def backup(self, output, ticket, progress=lambda _text: None):
        self.check()
        ticket.check()
        output = self._destination(output)
        progress("snapshot")
        watch = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=0.2)
        try:
            watch.execute("PRAGMA query_only=ON")
            before = watch.execute("PRAGMA data_version").fetchone()[0]
            sidecars = self._sidecars()
            with tempfile.TemporaryDirectory(
                prefix=".paperfact-backup-ui-", dir=output.parent
            ) as stage:
                package = Path(stage) / "research.zip"
                store = _ReadOnlyStore(self.blob_root) if self.blob_root else None
                manifest = sync_recovery.create(
                    self.path, package, blob_store=store, legacy_root=self.legacy_root
                )
                progress("publish")
                self.check()
                if (
                    self._sidecars() != sidecars
                    or watch.execute("PRAGMA data_version").fetchone()[0] != before
                ):
                    raise SnapshotChanged(
                        "Research changed during backup; retry when writers finish"
                    )
                ticket.publish(lambda: os.link(package, output))
        finally:
            watch.close()
        return {"path": str(output), "manifest": manifest}

    @staticmethod
    def _copy_package(package, target, ticket):
        package = _safe_path(package)
        digest = hashlib.sha256()
        total = 0
        with package.open("rb") as source, target.open("xb") as output:
            while True:
                ticket.check()
                block = source.read(256 * 1024)
                if not block:
                    break
                total += len(block)
                if total > sync_recovery.MAX_TOTAL + sync_recovery.MAX_METADATA:
                    raise ValueError("Backup exceeds its bounded format")
                output.write(block)
                digest.update(block)
        return digest.hexdigest()

    def inspect(self, package, ticket, progress=lambda _text: None):
        self.check()
        ticket.check()
        self._inspected = None
        progress("verify")
        # Inspect an owned immutable copy, so the preview binds to exact bytes.
        with tempfile.TemporaryDirectory(prefix=".paperfact-inspect-ui-") as stage:
            copied = Path(stage) / "backup.zip"
            digest = self._copy_package(package, copied, ticket)
            manifest = sync_recovery.inspect(copied)
        ticket.check()
        self.check()
        self._inspected = (_safe_path(package), digest, manifest["backup_id"])
        return manifest

    def restore(self, package, destination, expected_backup, ticket, progress=lambda _text: None):
        self.check()
        ticket.check()
        package = _safe_path(package)
        if (
            self._inspected is None
            or self._inspected[0] != package
            or self._inspected[2] != expected_backup
        ):
            raise ValueError("Inspect the selected backup before restoring")
        expected_digest = self._inspected[1]
        destination = self._destination(destination)
        progress("restore")
        with tempfile.TemporaryDirectory(
            prefix=".paperfact-restore-ui-", dir=destination.parent
        ) as stage:
            copied = Path(stage) / "backup.zip"
            if self._copy_package(package, copied, ticket) != expected_digest:
                raise ValueError("The selected backup changed; inspect it again")
            restored = Path(stage) / "workspace"
            result = sync_recovery.restore_detached(copied, restored)
            if result["backup_id"] != expected_backup:
                raise ValueError("The selected backup changed; inspect it again")
            self.check()
            progress("publish")
            ticket.publish(lambda: publish_directory(restored, destination))
        return {"path": str(destination), "backup_id": expected_backup, "detached": True}

    def _destination(self, value):
        if not str(value).strip():
            raise ValueError("Choose a new destination")
        path = _safe_path(value)
        if path.exists() or not path.parent.is_dir():
            raise ValueError("Choose a new name inside an existing folder")
        if path == self.path or path.is_relative_to(self.path.parent):
            raise ValueError("Choose a destination outside the active workspace")
        for root in (self.blob_root, self.legacy_root):
            if root and path.is_relative_to(root):
                raise ValueError("Choose a destination outside managed research storage")
        return path
