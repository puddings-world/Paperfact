"""Explicit, local Workspace/Backup preparation of enrolled legacy originals.

Discovery is read-only. Staging and publication are separate explicit operations.
The configured root is supplied by the owning window, never inferred here.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock
from uuid import uuid4

from paper_daily import file_change
from paper_daily import legacy_primary_migration as migration
from paper_daily.desktop.window_workspace import WindowWorkspace
from paper_daily.document_reader import _registration, _tables, from_workspace
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_client import SyncClient
from paper_daily.sync_operations import ResearchOperations
from paper_daily.sync_research import research_projection_writer, research_writer
from paper_daily.workspace_service import (
    Cancelled,
    Ticket,
    WorkspaceChanged,
    WorkspaceService,
    _read,
    _ReadOnlyStore,
)
from paper_daily.workspace_sync import GuardedJournal, local_binding

PAGE_SIZE = 256
MAX_SELECTED = 16
MAX_BATCH_BYTES = 512 * 1024**2
_SEAL = object()


def _identity(path):
    try:
        info = Path(path).stat()
        return (info.st_dev, info.st_ino) if info.st_ino else None
    except OSError:
        return None


@dataclass(frozen=True)
class MigrationSource:
    """Additional native caller admission, not a paper/source ownership receipt."""

    owner: WindowWorkspace = field(repr=False)
    database: Path
    identity: tuple[int, int]
    legacy_root: Path
    root_identity: tuple[int, int] | None
    _seal: object = field(repr=False, compare=False)

    @classmethod
    def capture(cls, owner, legacy_root):
        if not isinstance(owner, WindowWorkspace) or not owner.current() or not owner.identity:
            raise WorkspaceChanged("The original window no longer owns this workspace")
        root = Path(legacy_root).absolute()
        return cls(owner, owner.database, owner.identity, root, _identity(root), _SEAL)

    def workspace_current(self):
        return (
            self._seal is _SEAL
            and self.owner.current()
            and self.owner.database == self.database
            and self.owner.identity == self.identity
            and _identity(self.database) == self.identity
        )

    def current(self):
        return (
            self.workspace_current()
            and self.root_identity is not None
            and _identity(self.legacy_root) == self.root_identity
        )


@dataclass(frozen=True)
class CatalogItem:
    paper_id: str
    title: str
    status: str


@dataclass(frozen=True)
class Catalog:
    items: tuple[CatalogItem, ...]
    after: str | None
    bootstrap: bool
    _state: str = field(repr=False)
    _store: tuple = field(repr=False)
    _owner: object = field(repr=False)


@dataclass(frozen=True)
class StagedItem:
    paper_id: str
    title: str
    sha256: str
    size: int


@dataclass(frozen=True)
class StagePlan:
    items: tuple[StagedItem, ...]
    _prepared: tuple = field(repr=False)
    _files: tuple = field(repr=False)
    _store: tuple = field(repr=False)
    _stop: object = field(repr=False)
    _registration: tuple = field(repr=False)
    _owner: object = field(repr=False)


@dataclass(frozen=True)
class CommittedItem:
    paper_id: str
    sha256: str
    operation_id: str


@dataclass(frozen=True)
class BatchResult:
    committed: tuple[CommittedItem, ...]
    remaining: tuple[str, ...]
    outcome: str


class Stop:
    """Nonblocking GUI cancellation; an already committed leaf remains committed."""

    def __init__(self):
        self.event = Event()

    def cancel(self):
        self.event.set()

    @property
    def cancelled(self):
        return self.event.is_set()

    def check(self):
        if self.cancelled:
            raise Cancelled()


class PrimaryMigration:
    """Worker-only operations; current/cancel/dispose are metadata/event-only."""

    def __init__(self, service, source):
        if not isinstance(source, MigrationSource) or source.database != service.path:
            raise WorkspaceChanged("Migration requires the original window/source context")
        if source.identity != service.identity or not source.workspace_current():
            raise WorkspaceChanged("Migration workspace was replaced")
        self.service, self.source = service, source
        self._closed = Event()
        self._running = Lock()
        self.stop = Stop()
        self.needs_refresh = False
        self._plan = None
        self._key = object()
        self._binding = None
        self._registration = None

    def current(self):
        return not self._closed.is_set() and self.source.current()

    def catalog_current(self, catalog):
        try:
            return (
                isinstance(catalog, Catalog)
                and catalog._owner is self._key
                and self.current()
                and _identity(catalog._store[0]) == catalog._store[1]
            )
        except (OSError, ValueError):
            return False

    def plan_current(self, plan):
        """GUI rejection witness only; run() still performs full sealed checks."""
        try:
            return (
                isinstance(plan, StagePlan)
                and plan._owner is self._key
                and plan._stop is self.stop
                and not self.stop.cancelled
                and self.current()
                and _identity(plan._store[0]) == plan._store[1]
                and all(file_change.version(path) == version for path, version in plan._files)
            )

        except (OSError, ValueError):
            return False

    def cancel(self):
        self.stop.cancel()

    def dispose(self):
        self._closed.set()
        self.cancel()
        self._plan = None

    def reset(self):
        """Explicit new action admission, before starting its worker."""
        if not self._running.acquire(blocking=False):
            raise ValueError("Local PDF preparation is already running")
        try:
            self.stop.cancel()
            self.stop = Stop()
            self._plan = None
        finally:
            self._running.release()

    def _check(self):
        self.stop.check()
        if not self.current():
            raise WorkspaceChanged("Migration source or caller changed")

    def _begin(self):
        if not self._running.acquire(blocking=False):
            raise ValueError("Local PDF preparation is already running")
        try:
            self._check()
        except BaseException:
            self._running.release()
            raise

    def _context(self):
        self._check()
        self.service.check()
        binding = local_binding(self.service.path, require_capture=True)
        if self.service.blob_root is None:
            raise ValueError("No registered, owned local file store is available")
        store = _ReadOnlyStore(self.service.blob_root)
        store_identity = migration._store_scope(
            store, self.service.path, binding["workspace_id"], binding["device_id"]
        )
        reader = from_workspace(self.service.path, legacy_root=self.source.legacy_root)
        registration = reader._registered
        if registration is not None and (
            Path(registration[1]).resolve() != store.root
            or Path(registration[3]).resolve() != self.source.legacy_root.resolve()
        ):
            raise WorkspaceChanged("Configured and registered source roots disagree")
        self._check()
        return binding, store, store_identity, reader

    def _client(self, binding, live=None):
        journal = GuardedJournal.attach_existing(
            self.service.path,
            workspace_id=binding["workspace_id"],
            device_id=binding["device_id"],
        )
        journal.live = live or self._check
        return SyncClient.attach_existing(
            journal,
            research_writer,
            projection_writer=research_projection_writer,
        )

    @staticmethod
    def _states(conn, client, identities):
        graph = client._optimistic_graph(conn)[0]
        result = {}
        for identity in identities:
            row = conn.execute("SELECT * FROM papers WHERE id=?", (identity,)).fetchone()
            mapping = conn.execute(
                "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (identity,)
            ).fetchone()
            result[identity] = {
                "row": dict(row) if row is not None else None,
                "portable": mapping[0] if mapping else None,
                "lifecycle": parent_lifecycle(conn, "paper", identity),
                "parent": graph.get(("paper", mapping[0])) if mapping else None,
            }
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > 32 * 1024**2:
            raise ValueError("Paper review observations exceed 32 MiB")
        return encoded

    def catalog(self, *, after=""):
        self._begin()
        try:
            self._plan = None
            if self.needs_refresh:
                raise WorkspaceChanged("Refresh backup readiness before reviewing more PDFs")
            if not isinstance(after, str) or len(after.encode("utf-8")) > 2048:
                raise ValueError("Invalid catalog cursor")
            binding, observed_store, store_identity, reader = self._context()
            store_index = observed_store.root / "index.sqlite"
            client = self._client(binding)
            with _read(self.service.path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT id,title FROM papers WHERE id>? ORDER BY id LIMIT ?",
                    (after, PAGE_SIZE + 1),
                ).fetchall()
                visible = rows[:PAGE_SIZE]
                identities = [row[0] for row in visible]
                states = reader.inspect_many(identities, conn=conn)
                observed = self._states(conn, client, identities)
            result = []
            for paper_id, title in visible:
                if (
                    not isinstance(paper_id, str)
                    or not paper_id
                    or len(paper_id.encode("utf-8")) > 2048
                    or not isinstance(title, str)
                    or len(title.encode("utf-8")) > 8192
                ):
                    raise ValueError("Paper identity or title exceeds review bounds")
                state = states[paper_id]
                status = (
                    "legacy"
                    if not state.managed
                    and state.status in {"unchecked", "available", "missing", "invalid", "quota"}
                    else ("managed" if state.managed else "unavailable")
                )
                result.append(CatalogItem(paper_id, title, status))
            self._context()
            if _identity(store_index) != store_identity:
                raise WorkspaceChanged("File store was replaced during review")
            self._check()
            return Catalog(
                tuple(result),
                visible[-1][0] if len(rows) > PAGE_SIZE else None,
                reader._registered is None,
                observed,
                (store_index, store_identity),
                self._key,
            )
        finally:
            self._running.release()

    def stage(self, catalog, selected):
        """Explicit metadata setup, then stage every selected current source or fail."""
        self._begin()
        try:
            self._plan = None
            if self.needs_refresh:
                raise WorkspaceChanged("Refresh backup readiness before staging more PDFs")
            if not isinstance(catalog, Catalog) or catalog._owner is not self._key:
                raise ValueError("Review this workspace before selecting PDFs")
            if (
                not isinstance(selected, tuple)
                or not 1 <= len(selected) <= MAX_SELECTED
                or any(not isinstance(value, str) for value in selected)
                or len(set(selected)) != len(selected)
            ):
                raise ValueError("Select between one and sixteen distinct reviewed papers")
            allowed = {item.paper_id: item for item in catalog.items if item.status == "legacy"}
            if any(value not in allowed for value in selected):
                raise ValueError("Selection is not an eligible reviewed paper")
            if catalog.bootstrap and len(selected) != 1:
                raise ValueError("Prepare one PDF first, then review remaining papers again")
            binding, observed_store, store_identity, reader = self._context()
            stop, source, closed = self.stop, self.source, self._closed

            def live():
                stop.check()
                if closed.is_set() or not source.current():
                    raise WorkspaceChanged("Original migration caller changed")

            def current():
                return not stop.cancelled and not closed.is_set() and source.current()

            client = self._client(binding, live)
            expected = json.loads(catalog._state)
            with _read(self.service.path) as conn:
                conn.row_factory = sqlite3.Row
                actual = json.loads(self._states(conn, client, selected))
            if any(actual[value] != expected[value] for value in selected):
                raise WorkspaceChanged("Reviewed paper or parent changed; review again")
            self._binding = tuple(sorted(binding.items()))
            self._registration = reader._registered
            # This is the explicit setup step, before any source preparation.
            actions = ResearchOperations(
                client, expected=(self.source.database, self.source.identity)
            )
            self.needs_refresh = True
            live()
            if (
                migration._store_scope(
                    observed_store,
                    self.service.path,
                    binding["workspace_id"],
                    binding["device_id"],
                )
                != store_identity
            ):
                raise WorkspaceChanged("The reviewed file store was replaced")
            store = BlobStore(observed_store.root)
            prepared, items, files, total = [], [], [], 0
            projection = (
                Path(reader._registered[2])
                if reader._registered
                else self.service.path.parent / "reader-documents"
            )
            registration = reader._registered or (
                binding["workspace_id"],
                str(store.root),
                str(projection.resolve()),
                str(self.source.legacy_root.resolve()),
                1,
            )
            for identity in selected:
                live()
                with _read(self.service.path) as conn:
                    conn.row_factory = sqlite3.Row
                    now = json.loads(self._states(conn, client, (identity,)))
                if now[identity] != expected[identity]:
                    raise WorkspaceChanged("Reviewed paper or parent changed; review again")
                document = reader.resolve(identity)
                live()
                if not document.available or document.managed:
                    raise ValueError("Selected local PDF is unavailable or already managed")
                total += document.path.stat().st_size
                if total > MAX_BATCH_BYTES:
                    raise ValueError("Selected PDFs exceed the 512 MiB batch limit")
                try:
                    value = migration.prepare(
                        actions,
                        document,
                        store,
                        request_id=str(uuid4()),
                        ticket=Ticket(),
                        current=current,
                        projection_root=projection,
                    )
                except Exception:
                    stop.check()
                    raise
                prepared.append(value)
                files.append((document.path, document._identity))
                items.append(
                    StagedItem(
                        identity,
                        allowed[identity].title,
                        document.sha256,
                        value._manifest.size,
                    )
                )
            live()
            store_index = store.root / "index.sqlite"
            with _read(self.service.path) as conn:
                conn.row_factory = sqlite3.Row
                for value in prepared:
                    value._check_in(conn)
            live()
            if _identity(store_index) != store_identity:
                raise WorkspaceChanged("File store was replaced while checking staged PDFs")
            plan = StagePlan(
                tuple(items),
                tuple(prepared),
                tuple(files),
                (store_index, store_identity),
                stop,
                tuple(registration),
                self._key,
            )
            self._binding = tuple(sorted(binding.items()))
            self._plan = plan
            return plan
        finally:
            self._running.release()

    def commit(self, plan):
        """Serial per-paper atomic commits; cancellation never erases prior successes."""
        self._begin()
        try:
            if (
                not isinstance(plan, StagePlan)
                or plan._owner is not self._key
                or self._plan is not plan
                or plan._stop is not self.stop
            ):
                raise ValueError("Check and stage the selected PDFs again")
            committed, outcome = [], "complete"
            for item, prepared in zip(plan.items, plan._prepared, strict=True):
                try:
                    self._check()
                    result = migration.run(prepared)
                except Cancelled:
                    outcome = "cancelled"
                    break
                except Exception:
                    outcome = (
                        "cancelled"
                        if self.stop.cancelled
                        else ("changed" if not self.current() else "failed")
                    )
                    break
                committed.append(
                    CommittedItem(
                        item.paper_id,
                        result["source_document_hash"],
                        result["action"]["operation_id"],
                    )
                )
                self.needs_refresh = True
                self._registration = plan._registration
                if self.stop.cancelled:
                    outcome = "cancelled"
                    break
            done = {item.paper_id for item in committed}
            return BatchResult(
                tuple(committed),
                tuple(item.paper_id for item in plan.items if item.paper_id not in done),
                outcome,
            )
        finally:
            self._plan = None
            self._running.release()

    def refresh_readiness(self):
        """Explicit fresh review after our own registration; never resume old backup."""
        self._begin()
        try:
            if not self.needs_refresh or self._binding is None:
                raise ValueError("No committed preparation requires a new backup review")
            binding = local_binding(self.service.path, require_capture=True)
            if tuple(sorted(binding.items())) != self._binding:
                raise WorkspaceChanged("Original workspace binding changed")
            with _read(self.service.path) as conn:
                actual = _registration(conn, _tables(conn))
                if (tuple(actual) if actual is not None else None) != self._registration:
                    raise WorkspaceChanged("Prepared reader path ownership changed")
            service = WorkspaceService(self.service.path, current_path=self.service.current_path)
            if service.identity != self.source.identity:
                raise WorkspaceChanged("Original workspace was replaced")
            status = service.status()
            self._check()
            # A fresh status is not permission to adopt another device/root.
            binding = local_binding(self.service.path, require_capture=True)
            if tuple(sorted(binding.items())) != self._binding:
                raise WorkspaceChanged("Original workspace binding changed")
            with _read(self.service.path) as conn:
                actual = _registration(conn, _tables(conn))
                if (tuple(actual) if actual is not None else None) != self._registration:
                    raise WorkspaceChanged("Prepared reader path ownership changed")
            self._check()
            self.service = service
            self.needs_refresh = False
            return service, status
        finally:
            self._running.release()
