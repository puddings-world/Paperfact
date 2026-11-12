"""Explicit local artifact-index ownership, without enrollment or source authority.

The helper observes the actual client/database at admission. An outer importer or
window must still guard any lifetime captured earlier. allow_existing is an
explicit compatibility choice, never proof of the existing bytes' source owner.
"""

from __future__ import annotations

import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from paper_daily.sync_blobs import BlobStore, _no_link
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal

SCHEMA = (
    "CREATE TABLE transfer_binding (id INTEGER PRIMARY KEY CHECK(id=1),"
    "workspace TEXT NOT NULL,device TEXT NOT NULL,research_path TEXT NOT NULL)"
)
LEGACY_SCHEMA = (
    "CREATE TABLE transfer_binding (id INTEGER PRIMARY KEY,"
    "workspace TEXT,device TEXT,research_path TEXT)"
)


def _path(value):
    path = Path(value).absolute()
    for part in (path, *path.parents):
        _no_link(part)
    return path.resolve(strict=True)


def _native(path, *, directory=False):
    path = _path(path)
    info = path.stat()
    if not info.st_ino or not (
        stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    ):
        raise ValueError("Local binding requires known native file/directory identities")
    return info.st_dev, info.st_ino


def _read(path):
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, cached_statements=0)


@dataclass(frozen=True)
class _Owner:
    client: object
    journal: object
    database: Path
    native: tuple
    workspace: str
    device: str


def _owner_current(owner):
    journal = owner.journal
    if (
        owner.client.journal is not journal
        or (journal.workspace_id, journal.device_id) != (owner.workspace, owner.device)
        or _path(journal.path) != owner.database
        or _native(owner.database) != owner.native
    ):
        raise ValueError("Original local research client/database changed")
    with closing(_read(owner.database)) as conn:
        actual = next(row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main")
        if _path(actual) != owner.database:
            raise ValueError("Research connection belongs to another native database")
        for table, fields in (
            ("paperfact_sync_identity", "workspace,device"),
            ("research_sync_binding", "workspace,origin"),
        ):
            rows = conn.execute("SELECT id," + fields + " FROM " + table + " LIMIT 2").fetchall()
            if len(rows) != 1 or tuple(rows[0]) != (1, owner.workspace, owner.device):
                raise ValueError("Research workspace/device bindings disagree with the client")
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_capture_binding'"
        ).fetchone():
            rows = conn.execute(
                "SELECT id,workspace,device FROM research_capture_binding LIMIT 2"
            ).fetchall()
            if len(rows) != 1 or tuple(rows[0]) != (1, owner.workspace, owner.device):
                raise ValueError("Present research capture binding disagrees with the client")
    if _native(owner.database) != owner.native:
        raise ValueError("Original research database changed during binding inspection")


def _owner(client):
    if not isinstance(client, SyncClient) or not isinstance(client.journal, Journal):
        raise ValueError("An actual local research client/journal is required")
    journal = client.journal
    path = _path(journal.path)
    owner = _Owner(client, journal, path, _native(path), journal.workspace_id, journal.device_id)
    _owner_current(owner)
    return owner


@dataclass(frozen=True)
class _Store:
    store: object
    root: Path
    index: Path
    root_native: tuple
    index_native: tuple
    objects_native: tuple
    partial_native: tuple


def _store_current(scope, conn=None):
    if (
        _path(scope.store.root) != scope.root
        or _native(scope.root, directory=True) != scope.root_native
    ):
        raise ValueError("Original local artifact directory changed")
    if _native(scope.index) != scope.index_native:
        raise ValueError("Original local artifact index changed")
    if (
        _native(scope.root / "objects", directory=True) != scope.objects_native
        or _native(scope.root / "partial", directory=True) != scope.partial_native
    ):
        raise ValueError("Original local artifact subdirectory changed")
    for suffix in ("-journal", "-wal", "-shm"):
        _no_link(Path(str(scope.index) + suffix))
    if conn is not None:
        actual = next(row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main")
        if _path(actual) != scope.index:
            raise ValueError("Artifact connection belongs to another index")


def _store(store):
    if not isinstance(store, BlobStore):
        raise ValueError("An explicitly initialized BlobStore is required")
    root = _path(store.root)
    index = root / "index.sqlite"
    result = _Store(
        store,
        root,
        index,
        _native(root, directory=True),
        _native(index),
        _native(root / "objects", directory=True),
        _native(root / "partial", directory=True),
    )
    _store_current(result)
    return result


def _normalize(sql):
    return "".join(sql.split()).lower()


def _binding(conn, binding):
    found = conn.execute(
        "SELECT type,sql FROM sqlite_master WHERE name='transfer_binding'"
    ).fetchone()
    if found is None:
        return False
    if found[0] != "table" or not isinstance(found[1], str):
        raise ValueError("Artifact ownership requires an actual recognized binding table")
    columns = [tuple(row) for row in conn.execute("PRAGMA table_info(transfer_binding)")]
    legacy = [
        (0, "id", "INTEGER", 0, None, 1),
        (1, "workspace", "TEXT", 0, None, 0),
        (2, "device", "TEXT", 0, None, 0),
        (3, "research_path", "TEXT", 0, None, 0),
    ]
    strict = [
        row if n == 0 else (row[0], row[1], row[2], 1, None, 0) for n, row in enumerate(legacy)
    ]
    if (_normalize(found[1]), columns) not in [
        (_normalize(LEGACY_SCHEMA), legacy),
        (_normalize(SCHEMA), strict),
    ]:
        raise ValueError("Artifact ownership schema is incompatible or damaged")
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name='transfer_binding'"
    ).fetchone():
        raise ValueError("Artifact ownership has an unsupported writer trigger")
    rows = conn.execute(
        "SELECT id,workspace,device,research_path FROM transfer_binding LIMIT 2"
    ).fetchall()
    if len(rows) != 1 or tuple(rows[0]) != (1, *binding):
        raise ValueError(
            "Artifact store belongs to another workspace/device/database or has damaged binding"
        )
    return True


def _empty(conn, scope):
    if conn.execute("SELECT 1 FROM blobs LIMIT 1").fetchone():
        raise ValueError(
            "Unbound artifact store is not empty; explicit legacy admission is required"
        )
    for name in ("objects", "partial"):
        if next((scope.root / name).iterdir(), None) is not None:
            raise ValueError("Unbound artifact directory is not empty")
    allowed = {
        "index.sqlite",
        "index.sqlite-journal",
        "index.sqlite-wal",
        "index.sqlite-shm",
        "objects",
        "partial",
    }
    if any(path.name not in allowed for path in scope.root.iterdir()):
        raise ValueError("Unbound artifact directory contains unexpected existing data")
    objects = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view','trigger')"
    ).fetchall()
    if {row[0] for row in objects} != {"blobs"}:
        raise ValueError("Unbound artifact index is not a fresh empty blob catalog")


def bind(client, store, *, allow_existing=False):
    """Bind one local store atomically; do not enroll, stage bytes, or contact a service.

    Existing exact legacy/strict bindings are read-only/idempotent. Explicit
    allow_existing accepts pre-staged bytes for old callers, without validating
    their content or granting any paper/source ownership.
    """
    if type(allow_existing) is not bool:
        raise ValueError("allow_existing must be an explicit boolean")
    owner = _owner(client)
    scope = _store(store)
    binding = (owner.workspace, owner.device, str(owner.database))
    conn = None
    try:
        # mode=rw cannot create a replacement index if the admitted one vanished.
        conn = sqlite3.connect(scope.index.as_uri() + "?mode=rw", uri=True, cached_statements=0)
        conn.execute("BEGIN IMMEDIATE")
        _store_current(scope, conn)
        _owner_current(owner)
        if not _binding(conn, binding):
            if not allow_existing:
                _empty(conn, scope)
            conn.execute(SCHEMA)
            conn.execute("INSERT INTO transfer_binding VALUES(1,?,?,?)", binding)
        _store_current(scope, conn)
        _owner_current(owner)
        conn.commit()
    except sqlite3.Error as error:
        if conn is not None:
            conn.rollback()
        raise ValueError("Local artifact binding metadata requires review") from error
    except BaseException:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()
    _store_current(scope)
    return scope.index_native
