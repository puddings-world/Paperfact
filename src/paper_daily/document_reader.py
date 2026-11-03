"""Explicit hash-aware document resolution and owned PDF projections.

Importing this module discovers no workspace and creates no files. Verification
and projection belong on a worker; metadata inspection is suitable for row loading.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import RLock

from paper_daily.sync_blobs import BlobError, BlobManifest, BlobQuotaError, BlobStore, _no_link
from paper_daily.sync_documents import (
    MAX_PDF_BYTES,
    _identity,
    _paper_current,
    applied_document,
    desired_document,
    verify_document,
)

_FACTORIES = {}
_FACTORY_GUARD = RLock()


def _safe_name(identity):
    return re.sub(r"[^A-Za-z0-9._-]", "_", identity)


def _connect(path):
    return sqlite3.connect(_owned_path(path).as_uri() + "?mode=ro", uri=True, timeout=5)


def _matching(conn, sql, values, *, whole=False):
    """Run `sql` with its `IN ({})` filled in batches under SQLite's variable limit;
    the first column of each row, or the whole row with `whole`."""
    values = list(values)
    for start in range(0, len(values), 500):
        batch = values[start : start + 500]
        for row in conn.execute(sql.format(",".join("?" * len(batch))), batch):
            yield tuple(row) if whole else row[0]


FEW_NAMES = 25


def _aliases(conn, name):
    """Papers whose PDF file name is `name`. In LIKE, "_" matches any one character,
    so the file name itself finds every id that could map to it (a superset, as LIKE
    also ignores ASCII case); the exact mapping then decides."""
    return sum(
        1
        for (identity,) in conn.execute("SELECT id FROM papers WHERE id LIKE ?", (name,))
        if _safe_name(identity) == name
    )


def _alias_counts(conn, names):
    """How many papers map to each PDF file name.

    A name is the paper's own id when the id is already a safe file name; only ids
    with other characters map elsewhere. So an indexed lookup of the names plus one
    pass over those few ids answers every name. A LIKE per name scanned the whole
    table each time, and a list of a few thousand papers froze the window for
    seconds on every return to the list. That one pass costs about as much as thirty
    single lookups, so a few names (one paper opened in the reader) still go one by one.
    """
    if len(names) <= FEW_NAMES:
        return {name: _aliases(conn, name) for name in names}
    counts = dict.fromkeys(names, 0)
    for identity in _matching(conn, "SELECT id FROM papers WHERE id IN ({})", counts):
        counts[identity] += 1
    for (identity,) in conn.execute("SELECT id FROM papers WHERE id GLOB '*[^A-Za-z0-9._-]*'"):
        name = _safe_name(identity)
        if name in counts:
            counts[name] += 1
    return counts


def _tables(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _binding(conn, tables):
    if "research_sync_binding" not in tables:
        return None
    row = conn.execute("SELECT workspace,origin FROM research_sync_binding WHERE id=1").fetchone()
    return tuple(row) if row is not None else None


def _registration(conn, tables):
    if "document_reader_paths" not in tables:
        return None
    row = conn.execute(
        "SELECT workspace,blob_root,projection_root,legacy_root,generation "
        "FROM document_reader_paths WHERE id=1"
    ).fetchone()
    return tuple(row) if row is not None else None


def _owned_path(value):
    path = Path(value).absolute()
    for entry in (path, *path.parents):
        _no_link(entry)
    return path.resolve()


def register_document_paths(conn, *, workspace_id, blob_root, projection_root, legacy_root):
    """Explicit device-local registration; caller owns commit and no directory is created."""
    if not conn.in_transaction:
        raise ValueError("Reader path registration requires a caller transaction")
    tables = _tables(conn)
    binding = _binding(conn, tables)
    if binding is None or binding[0] != workspace_id:
        raise ValueError("Reader paths belong to another workspace")
    roots = tuple(_owned_path(value) for value in (blob_root, projection_root, legacy_root))
    blob, projection, legacy = roots
    if (
        projection in (legacy, blob)
        or projection.is_relative_to(legacy)
        or legacy.is_relative_to(projection)
        or projection.is_relative_to(blob / "objects")
        or projection.is_relative_to(blob / "partial")
    ):
        raise ValueError("Reader projections must have their own directory")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS document_reader_paths (id INTEGER PRIMARY KEY CHECK(id=1),"
        "workspace TEXT NOT NULL,blob_root TEXT NOT NULL,projection_root TEXT NOT NULL,"
        "legacy_root TEXT NOT NULL,generation INTEGER NOT NULL)"
    )
    conn.execute(
        "INSERT INTO document_reader_paths VALUES(1,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET "
        "workspace=excluded.workspace,blob_root=excluded.blob_root,"
        "projection_root=excluded.projection_root,legacy_root=excluded.legacy_root,"
        "generation=document_reader_paths.generation+1 WHERE "
        "workspace!=excluded.workspace OR blob_root!=excluded.blob_root OR "
        "projection_root!=excluded.projection_root OR legacy_root!=excluded.legacy_root",
        (workspace_id, *(str(root) for root in roots)),
    )


@dataclass(frozen=True)
class ResolvedDocument:
    mode: str
    status: str
    local_id: str
    paper_id: str | None = None
    path: Path | None = None
    sha256: str | None = None
    reason: str | None = None
    _target: str | None = field(default=None, repr=False)
    _identity: tuple | None = field(default=None, repr=False)
    _context: tuple | None = field(default=None, repr=False)
    _generation: int = field(default=0, repr=False)
    _owner: object = field(default=None, repr=False, compare=False)

    @property
    def available(self):
        return self.status == "available" and self.path is not None

    @property
    def managed(self):
        return self.mode == "managed"

    @property
    def target(self):
        return json.loads(self._target) if self._target else None


class DocumentReader:
    def __init__(
        self,
        db_path,
        *,
        blob_store=None,
        projection_root,
        legacy_root,
        projection_quota_bytes=1024**3,
    ):
        if blob_store is not None and not isinstance(blob_store, BlobStore):
            raise ValueError("Reader requires an explicit BlobStore")
        if type(projection_quota_bytes) is not int or projection_quota_bytes <= 0:
            raise ValueError("Reader projection quota must be positive")
        self.db_path = Path(db_path).absolute()
        self.blob_store = blob_store
        self.projection_root = (
            Path(projection_root).absolute() if projection_root is not None else None
        )
        self.legacy_root = Path(legacy_root).absolute() if legacy_root is not None else None
        self.projection_quota_bytes = projection_quota_bytes
        self._blob_root = None
        self._registered = None
        self._cache = {}
        self._guard = RLock()
        self._generation = 0
        self._closed = False

    @classmethod
    def from_workspace(cls, db_path, *, legacy_root=None, projection_root=None):
        return from_workspace(db_path, legacy_root=legacy_root, projection_root=projection_root)

    def invalidate(self, paper_id=None):
        with self._guard:
            self._generation += 1
            if paper_id is None:
                self._cache.clear()
            else:
                self._cache.pop(paper_id, None)

    def close(self):
        self.invalidate()
        self._closed = True

    def _legacy_inspection(self, identities):
        """An absent/un-enrolled database cannot establish a portable identity."""
        return {
            identity: ResolvedDocument(
                "legacy",
                "unchecked",
                identity,
                _context=(None, None),
                _generation=self._generation,
                _owner=self,
            )
            for identity in identities
        }

    def inspect_many(self, local_ids, *, conn=None):
        """One metadata snapshot; no PDF stat, hash, parsing or directory creation."""
        identities = list(local_ids)
        if any(not isinstance(value, str) or not value for value in identities):
            raise ValueError("Expected local paper identities")
        owned = conn is None
        if owned:
            if not _owned_path(self.db_path).exists():
                return self._legacy_inspection(identities)
            conn = _connect(self.db_path)
        transaction = not conn.in_transaction
        if transaction:
            conn.execute("BEGIN")
        try:
            main = next(
                (row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"), None
            )
            if not main or Path(main).resolve() != self.db_path.resolve():
                raise ValueError("Reader connection belongs to another research database")
            tables = _tables(conn)
            if "papers" not in tables:
                if any(name.startswith(("research_", "paperfact_sync_")) for name in tables):
                    raise ValueError("Managed research database has no paper table")
                return self._legacy_inspection(identities)
            binding, registration = _binding(conn, tables), _registration(conn, tables)
            context = (binding, registration)
            # Every query is limited to the asked-for papers: the reader inspects on
            # each click, and reading whole tables made a jump to the source take
            # most of a second in a workspace of ~80,000 papers.
            papers = set(_matching(conn, "SELECT id FROM papers WHERE id IN ({})", identities))
            aliases = _alias_counts(conn, {_safe_name(i) for i in papers})
            mappings = (
                dict(
                    _matching(
                        conn,
                        "SELECT local_id,sync_id FROM research_paper_identity "
                        "WHERE local_id IN ({})",
                        identities,
                        whole=True,
                    )
                )
                if "research_paper_identity" in tables
                else {}
            )
            portables = list(set(mappings.values()))
            history = set()
            for table in (
                "research_document_desired",
                "research_document_applied",
                "research_document_intents",
            ):
                if table in tables:
                    history.update(
                        _matching(
                            conn,
                            f"SELECT paper_id FROM {table} WHERE paper_id IN ({{}})",
                            portables,
                        )
                    )
            for table in ("paperfact_sync_heads", "paperfact_sync_operations"):
                if table in tables:
                    history.update(
                        _matching(
                            conn,
                            f"SELECT entity_id FROM {table} "
                            "WHERE entity_type='paper_document' AND entity_id IN ({})",
                            portables,
                        )
                    )
            result = {}
            for identity in identities:
                portable = mappings.get(identity)
                managed = portable is not None and portable in history
                status, target, reason = "unchecked", None, None
                if identity not in papers:
                    status, reason = "missing", "paper_missing"
                elif managed:
                    target = (
                        desired_document(conn, portable)
                        if "research_document_desired" in tables
                        else None
                    )
                    applied = (
                        applied_document(conn, portable)
                        if "research_document_applied" in tables
                        else None
                    )
                    if target is None:
                        status = "detached"
                    elif applied != target:
                        status = "unbound"
                    elif "research_paper_projection" not in tables or not _paper_current(
                        conn, target
                    ):
                        status = "stale"
                    elif self.blob_store is None and self._blob_root is None:
                        status = "unconfigured"
                elif aliases.get(_safe_name(identity), 0) > 1:
                    status = "ambiguous"
                if self._registered is not None and registration != self._registered:
                    status, reason = "stale", "reader_paths_changed"
                encoded = json.dumps(target, sort_keys=True) if target else None
                item = ResolvedDocument(
                    "managed" if managed else "legacy",
                    status,
                    identity,
                    portable,
                    sha256=target["sha256"] if target else None,
                    reason=reason,
                    _target=encoded,
                    _context=context,
                    _generation=self._generation,
                    _owner=self,
                )
                cached = self._cache.get(identity)
                if (
                    status == "unchecked"
                    and cached is not None
                    and (cached._target, cached._context, cached._generation, cached.mode)
                    == (item._target, context, self._generation, item.mode)
                ):
                    item = cached
                result[identity] = item
            return result
        finally:
            if transaction:
                conn.rollback()
            if owned:
                conn.close()

    def inspect(self, paper_id, *, portable=False, conn=None):
        if portable:
            owned = conn is None
            if owned:
                conn = _connect(self.db_path)
                conn.execute("BEGIN")
            try:
                row = conn.execute(
                    "SELECT local_id FROM research_paper_identity WHERE sync_id=?", (paper_id,)
                ).fetchone()
                if row is None:
                    return ResolvedDocument(
                        "managed", "missing", "", paper_id, reason="paper_missing", _owner=self
                    )
                return self.inspect_many([row[0]], conn=conn)[row[0]]
            finally:
                if owned:
                    conn.close()
        return self.inspect_many([paper_id], conn=conn)[paper_id]

    def _store(self, result):
        if self.blob_store is not None:
            return self.blob_store
        if self._blob_root is None:
            raise FileNotFoundError("Document store is not configured")
        root = _owned_path(self._blob_root)
        with closing(_connect(root / "index.sqlite")) as conn, conn:
            row = conn.execute(
                "SELECT workspace,device,research_path FROM transfer_binding WHERE id=1"
            ).fetchone()
        binding = result._context[0]
        expected = (*binding, str(self.db_path.resolve())) if binding is not None else None
        if row is None or tuple(row) != expected:
            raise ValueError("Document store does not match this workspace/device/database")
        # This constructor only sees an existing, explicitly registered store.
        return BlobStore(root)

    def _project(self, source, manifest):
        if self.projection_root is None:
            raise ValueError("Reader projection root is not configured")
        root = _owned_path(self.projection_root)
        if self.legacy_root is not None and (
            root.is_relative_to(self.legacy_root) or self.legacy_root.is_relative_to(root)
        ):
            raise ValueError("Reader projection cannot overwrite legacy PDFs")
        blob_root = self.blob_store.root if self.blob_store is not None else self._blob_root
        if blob_root is not None and (
            root == blob_root
            or root.is_relative_to(blob_root / "objects")
            or root.is_relative_to(blob_root / "partial")
        ):
            raise ValueError("Reader projection cannot share blob storage directories")
        root.mkdir(parents=True, exist_ok=True)
        index = root / "projection-index.sqlite"
        for suffix in ("", "-journal", "-wal", "-shm"):
            _no_link(Path(str(index) + suffix))
        final, staged = root / (manifest.sha256 + ".pdf"), root / (manifest.sha256 + ".part")
        with closing(sqlite3.connect(index, timeout=5)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            for path in (final, staged):
                _no_link(path)
            if final.exists():
                BlobStore._verify(final, manifest)
                return final
            # Recover only the known private staging name while holding the cache lock.
            staged.unlink(missing_ok=True)
            used = 0
            for entry in root.iterdir():
                if entry.name.startswith("projection-index.sqlite"):
                    continue
                _no_link(entry)
                if entry.is_file():
                    used += entry.stat().st_size
                else:
                    raise ValueError("Unexpected entry in reader projection directory")
            if used + manifest.size > self.projection_quota_bytes:
                raise BlobQuotaError("Reader projection quota would be exceeded")
            try:
                with source.open("rb") as incoming, staged.open("xb") as output:
                    total = 0
                    while chunk := incoming.read(1024**2):
                        total += len(chunk)
                        if total > manifest.size:
                            raise BlobError("Document changed while preparing reader copy")
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                BlobStore._verify(staged, manifest)
                os.replace(staged, final)
            finally:
                staged.unlink(missing_ok=True)
            return final

    def resolve(self, paper_id, *, portable=False):
        """Verify and prepare a reader path off-thread; never fetch URLs or invoke AI."""
        item = self.inspect(paper_id, portable=portable)
        if self._closed:
            return replace(item, status="stale", path=None)
        if (
            item.status not in ("unchecked", "available", "missing", "invalid", "quota")
            or item.reason == "paper_missing"
        ):
            return item
        try:
            if item.managed:
                store = self._store(item)
                verified = verify_document(store, item.target)
                manifest = BlobManifest(item.sha256, item.target["size"])
                path = self._project(verified._path, manifest)
                if not verified.matches(item.target):
                    raise BlobError("Document changed while preparing reader copy")
                digest = item.sha256
            else:
                if self.legacy_root is None:
                    return replace(item, status="unconfigured", path=None)
                path = _owned_path(self.legacy_root / (_safe_name(item.local_id) + ".pdf"))
                before = _identity(path)
                if not 0 < path.stat().st_size <= MAX_PDF_BYTES:
                    raise ValueError("Legacy PDF exceeds reader limits")
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                import pymupdf

                try:
                    with pymupdf.open(path) as document:
                        if document.needs_pass or document.page_count < 1:
                            raise ValueError("Unreadable legacy PDF")
                        document.load_page(0)
                except pymupdf.FileDataError as exc:
                    raise ValueError("Unreadable legacy PDF") from exc
                if _identity(path) != before:
                    raise ValueError("Legacy document changed during verification")
            result = replace(
                item, status="available", path=path, sha256=digest, _identity=_identity(path)
            )
            if not self.current(result):
                result = replace(item, status="stale", path=None)
        except BlobQuotaError:
            result = replace(item, status="quota", path=None)
        except FileNotFoundError:
            result = replace(item, status="missing", path=None)
        except (OSError, ValueError, sqlite3.DatabaseError):
            result = replace(item, status="invalid", path=None)
        self._cache[item.local_id] = result
        return result

    def current(self, result):
        if not self.intact(result):
            return False
        try:
            now = self.inspect(result.local_id)
            return (
                now.reason != "paper_missing"
                and now.mode == result.mode
                and now._target == result._target
                and now.status not in ("detached", "unbound", "unconfigured", "ambiguous", "stale")
            )
        except (OSError, ValueError, sqlite3.DatabaseError):
            return False

    def intact(self, result):
        """Check an already-open version without requiring it to remain the desired one.

        This never authorizes new activation. It preserves old-version navigation
        while its exact bytes and original workspace/device context remain intact.
        """
        if (
            not isinstance(result, ResolvedDocument)
            or result._owner is not self
            or not result.available
            or self._closed
        ):
            return False
        if result._generation != self._generation:
            return False
        try:
            now = self.inspect(result.local_id)
            if (
                now.reason == "paper_missing"
                or now.mode != result.mode
                or now.paper_id != result.paper_id
                or now._context != result._context
                or now.reason == "reader_paths_changed"
                or now.status == "ambiguous"
            ):
                return False
            return _identity(result.path) == result._identity
        except (OSError, ValueError, sqlite3.DatabaseError):
            return False


def from_workspace(db_path, *, legacy_root=None, projection_root=None):
    """Read existing local registration; never create a missing database or blob store."""
    path = Path(db_path).absolute()
    registration, binding = None, None
    if _owned_path(path).exists():
        with closing(_connect(path)) as conn, conn:
            conn.execute("BEGIN")
            tables = _tables(conn)
            registration = _registration(conn, tables)
            binding = _binding(conn, tables)
    if registration is not None and (binding is None or registration[0] != binding[0]):
        raise ValueError("Reader path registration belongs to another workspace")
    legacy = legacy_root if legacy_root is not None else (registration[3] if registration else None)
    projection = (
        projection_root
        if projection_root is not None
        else (registration[2] if registration else None)
    )
    key = (str(path), registration, str(legacy), str(projection))
    with _FACTORY_GUARD:
        reader = _FACTORIES.get(key)
        if reader is None or reader._closed:
            reader = DocumentReader(path, projection_root=projection, legacy_root=legacy)
            if registration:
                reader._blob_root = Path(registration[1])
                reader._registered = registration
            _FACTORIES[key] = reader
        return reader


def _runtime_reader(*, db_path=None, legacy_root=None, projection_root=None):
    if db_path is None:
        from paper_daily.config import PDF_DIR
        from paper_daily.store import DB_PATH

        db_path = DB_PATH
        if legacy_root is None:
            legacy_root = PDF_DIR
    return from_workspace(db_path, legacy_root=legacy_root, projection_root=projection_root)


def resolve_document(paper_id, *, db_path=None, legacy_root=None, projection_root=None):
    return _runtime_reader(
        db_path=db_path, legacy_root=legacy_root, projection_root=projection_root
    ).resolve(paper_id)


def document_status(paper_id, *, db_path=None, legacy_root=None, projection_root=None):
    return _runtime_reader(
        db_path=db_path, legacy_root=legacy_root, projection_root=projection_root
    ).inspect(paper_id)


def document_current(result):
    return (
        isinstance(result, ResolvedDocument)
        and isinstance(result._owner, DocumentReader)
        and result._owner.current(result)
    )
