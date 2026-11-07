"""Explicit, source-observed legacy PDF materialization. No read-time migration.

All preparation/run work belongs on a worker. The private attach hook arbitrates
cancellation through the existing transaction commit; it is not a generic writer.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from uuid import UUID

from paper_daily import file_change
from paper_daily.document_reader import (
    DocumentReader,
    ResolvedDocument,
    _owned_path,
    _registration,
    register_document_paths,
)
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_document_actions import stage_file
from paper_daily.sync_documents import applied_document, bind_verified_document, desired_document
from paper_daily.sync_files import canonical_json
from paper_daily.sync_operations import ResearchOperations
from paper_daily.workspace_service import Ticket, _binding, _tables

_SEAL = object()
MAX_METADATA = 1024 * 1024


def _encoded(value):
    result = canonical_json(value)
    if len(result) > MAX_METADATA:
        raise ValueError("Legacy migration metadata exceeds its bounded observation")
    return result


def _identity(path):
    info = _owned_path(path).stat()
    if not info.st_ino:
        raise ValueError("Legacy migration requires known native identity")
    return info.st_dev, info.st_ino


def _read(path):
    conn = sqlite3.connect(
        _owned_path(path).as_uri() + "?mode=ro", uri=True, cached_statements=0, timeout=5
    )
    conn.row_factory = sqlite3.Row
    return conn


def _store_scope(store, database, workspace, device):
    index = _owned_path(store.root / "index.sqlite")
    identity = _identity(index)
    with closing(_read(index)) as conn:
        row = conn.execute(
            "SELECT workspace,device,research_path FROM transfer_binding WHERE id=1"
        ).fetchone()
        if row is None or tuple(row) != (workspace, device, str(database)):
            raise ValueError("Legacy migration store belongs to another workspace/device")
    if _identity(index) != identity:
        raise ValueError("Legacy migration store was replaced while observing it")
    return identity


def _reader_scope(reader):
    return dict(
        database=str(_owned_path(reader.db_path)),
        legacy=str(_owned_path(reader.legacy_root)),
        projection=str(_owned_path(reader.projection_root)) if reader.projection_root else None,
        blob=str(_owned_path(reader.blob_store.root)) if reader.blob_store else None,
        cached_blob=str(_owned_path(reader._blob_root)) if reader._blob_root else None,
        registered=reader._registered,
    )


def _scope(conn, actions, document):
    journal = actions.client.journal
    tables = _tables(conn)
    binding = _binding(conn, tables)
    if {item[0] for item in binding} != {
        "paperfact_sync_identity",
        "research_sync_binding",
        "research_capture_binding",
    } or any(item[1] != (journal.workspace_id, journal.device_id) for item in binding):
        raise ValueError("Legacy migration requires complete matching workspace/device binding")
    mapping = conn.execute(
        "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (document.local_id,)
    ).fetchone()
    paper = conn.execute("SELECT * FROM papers WHERE id=?", (document.local_id,)).fetchone()
    epoch = parent_lifecycle(conn, "paper", document.local_id)
    if mapping is None or mapping[0] != document.paper_id or paper is None or not epoch:
        raise ValueError("Legacy migration paper/lifetime is unavailable")
    graph = actions.client._optimistic_graph(conn)[0]
    parent = graph.get(("paper", document.paper_id))
    if parent is None or not parent["active"]:
        raise ValueError("Legacy migration requires its active portable paper")
    return dict(
        binding=binding,
        paper=dict(paper),
        parent=parent,
        lifecycle=epoch,
        document_head=graph.get(("paper_document", document.paper_id)),
        desired=desired_document(conn, document.paper_id),
        applied=applied_document(conn, document.paper_id),
        registration=_registration(conn, tables),
    )


@dataclass(frozen=True, init=False)
class PreparedLegacyPrimary:
    _actions: object = field(repr=False)
    _client: object = field(repr=False)
    _journal: object = field(repr=False)
    _store: object = field(repr=False)
    _document: ResolvedDocument = field(repr=False)
    _database: Path
    _identity: tuple
    _store_identity: tuple
    _source_version: tuple
    _reader_generation: int
    _reader_scope_json: bytes = field(repr=False)
    _scope_json: bytes = field(repr=False)
    _registration_json: bytes = field(repr=False)
    _manifest: object
    _request_id: str
    _ticket: Ticket = field(repr=False)
    _current: object = field(repr=False)
    _running: object = field(repr=False)
    _seal: object = field(repr=False)

    @property
    def fingerprint(self):
        return hashlib.sha256(
            _encoded(
                dict(
                    database=str(self._database),
                    identity=self._identity,
                    source_version=self._source_version,
                    reader=json.loads(self._reader_scope_json),
                    scope=json.loads(self._scope_json),
                    registration=json.loads(self._registration_json),
                    store_identity=self._store_identity,
                )
            )
        ).hexdigest()

    def _live(self):
        self._ticket.check()
        if (
            not self._current()
            or self._actions.client is not self._client
            or self._client.journal is not self._journal
            or Path(self._journal.path).resolve() != self._database
            or _identity(self._database) != self._identity
        ):
            raise ValueError("Legacy migration workspace or caller lifetime changed")
        owner = self._document._owner
        if (
            owner._closed
            or owner._generation != self._reader_generation
            or _encoded(_reader_scope(owner)) != self._reader_scope_json
        ):
            raise ValueError("Legacy migration reader was closed or invalidated")
        if file_change.version(_owned_path(self._document.path)) != self._source_version:
            raise ValueError("Legacy migration source changed")
        if (
            _store_scope(
                self._store, self._database, self._journal.workspace_id, self._journal.device_id
            )
            != self._store_identity
        ):
            raise ValueError("Legacy migration store was replaced")

    def _check_in(self, conn):
        self._live()
        if _encoded(_scope(conn, self._actions, self._document)) != self._scope_json:
            raise ValueError("Legacy migration paper, target or binding changed")
        inspected = self._document._owner.inspect(self._document.local_id, conn=conn)
        if (
            inspected.managed
            or inspected.paper_id != self._document.paper_id
            or inspected._context != self._document._context
            or inspected.status in {"missing", "ambiguous", "stale"}
        ):
            raise ValueError("Legacy migration no longer owns this selected legacy source")

    def _final(self, conn, target):
        self._live()
        before = json.loads(self._scope_json)
        now = _scope(conn, self._actions, self._document)
        for key in ("binding", "paper", "parent", "lifecycle"):
            if _encoded(now[key]) != _encoded(before[key]):
                raise ValueError("Legacy migration parent changed during publication")
        if desired_document(conn, self._document.paper_id) != target:
            raise ValueError("Legacy migration target changed during publication")

    def _bind_in(self, conn, target, verified):
        self._final(conn, target)
        if not bind_verified_document(conn, target, verified):
            raise ValueError("Legacy migration target could not be bound")
        registration = json.loads(self._registration_json)
        register_document_paths(
            conn,
            workspace_id=registration[0],
            blob_root=registration[1],
            projection_root=registration[2],
            legacy_root=registration[3],
        )
        self._before_receipt(conn, target)

    def _before_receipt(self, conn, target):
        self._final(conn, target)
        if (
            applied_document(conn, self._document.paper_id) != target
            or _encoded(_registration(conn, _tables(conn))) != self._registration_json
        ):
            raise ValueError("Legacy migration binding or reader registration changed")
        self._ticket.check()

    def _replay_in(self, conn, result):
        self._live()
        target = desired_document(conn, self._document.paper_id)
        if (
            not target
            or target["operation_id"] != result["operation_id"]
            or target["sha256"] != self._manifest.sha256
            or target["size"] != self._manifest.size
        ):
            raise ValueError("Legacy migration retry cannot revive a newer or retired source")
        self._before_receipt(conn, target)

    def _publish(self, action):
        result = []

        def commit():
            self._live()
            result.append(action())

        self._ticket.publish(commit)  # Callback includes journal context exit/commit.
        if len(result) != 1:
            raise ValueError("Legacy migration publication did not return its action receipt")
        return result[0]


def validate_for_attach(value, actions, paper_id, manifest, store, request_id):
    if (
        not isinstance(value, PreparedLegacyPrimary)
        or getattr(value, "_seal", None) is not _SEAL
        or value._actions is not actions
        or value._store is not store
        or value._manifest != manifest
        or value._request_id != request_id
        or value._document.paper_id != paper_id
    ):
        raise ValueError("Legacy materialization requires its exact sealed prepared action")
    value._live()
    return value


def prepare(
    actions, document, store, *, request_id, ticket=None, current=lambda: True, projection_root=None
):
    """Capture and stage one explicit current legacy original; no SQL writes or AI.

    Caller owns the existing actions/store/reader. The captured lifetime predicate
    is an additional rejection gate, never paper/source authority.
    """
    if (
        not isinstance(actions, ResearchOperations)
        or not isinstance(store, BlobStore)
        or not isinstance(document, ResolvedDocument)
        or not isinstance(document._owner, DocumentReader)
        or not document.available
        or document.managed
        or not callable(current)
        or not isinstance(request_id, str)
        or str(UUID(request_id)) != request_id
    ):
        raise ValueError("Select one current enrolled legacy original and a canonical request UUID")
    ticket = ticket or Ticket()
    if not isinstance(ticket, Ticket) or ticket.published:
        raise ValueError("Legacy migration requires a fresh owned cancellation ticket")
    ticket.check()
    if not current():
        raise ValueError("Legacy migration caller is no longer current")
    journal = actions.client.journal
    database = _owned_path(journal.path)
    identity = _identity(database)  # Known before the first source/SQL read.
    if _owned_path(document._owner.db_path) != database:
        raise ValueError("Legacy migration source belongs to another database")
    reader_generation = document._owner._generation
    reader_scope_json = _encoded(_reader_scope(document._owner))
    source_version = file_change.version(_owned_path(document.path))
    if source_version != document._identity or not document._owner.current(document):
        raise ValueError("Legacy migration requires the actual selected source version")
    store_identity = _store_scope(store, database, journal.workspace_id, journal.device_id)
    with closing(_read(database)) as conn:
        conn.execute("BEGIN")
        journal._binding(conn)
        scope = _scope(conn, actions, document)
    if (
        scope["document_head"] is not None
        or scope["desired"] is not None
        or scope["applied"] is not None
    ):
        raise ValueError("A managed or retired original cannot be revived as legacy")
    scope_json = _encoded(scope)
    registered = scope["registration"]
    projection = _owned_path(
        projection_root
        if projection_root is not None
        else (registered[2] if registered else database.parent / "reader-documents")
    )
    legacy_root = _owned_path(document._owner.legacy_root)
    blob_root = _owned_path(store.root)
    if (
        projection in (legacy_root, blob_root)
        or projection.is_relative_to(legacy_root)
        or legacy_root.is_relative_to(projection)
        or projection.is_relative_to(blob_root / "objects")
        or projection.is_relative_to(blob_root / "partial")
    ):
        raise ValueError("Legacy migration reader projection requires its own owned directory")
    registration = (
        journal.workspace_id,
        str(_owned_path(store.root)),
        str(projection),
        str(_owned_path(document._owner.legacy_root)),
        registered[4] if registered else 1,
    )
    if registered is not None and _encoded(registered) != _encoded(registration):
        raise ValueError("Legacy migration cannot replace existing reader path ownership")
    manifest = stage_file(store, document.path)
    ticket.check()
    if manifest.sha256 != document.sha256 or manifest.size != source_version[2]:
        raise ValueError("Staged bytes differ from the selected original")
    value = object.__new__(PreparedLegacyPrimary)
    fields = dict(
        _actions=actions,
        _client=actions.client,
        _journal=journal,
        _store=store,
        _document=document,
        _database=database,
        _identity=identity,
        _store_identity=store_identity,
        _source_version=source_version,
        _reader_generation=reader_generation,
        _reader_scope_json=reader_scope_json,
        _scope_json=scope_json,
        _registration_json=_encoded(registration),
        _manifest=manifest,
        _request_id=request_id,
        _ticket=ticket,
        _current=current,
        _running=Lock(),
        _seal=_SEAL,
    )
    for key, item in fields.items():
        object.__setattr__(value, key, item)
    with closing(_read(database)) as conn:
        conn.execute("BEGIN")
        value._check_in(conn)
    return value


def run(prepared):
    """Atomically attach, bind, register and receipt one explicit prepared migration."""
    if (
        not isinstance(prepared, PreparedLegacyPrimary)
        or getattr(prepared, "_seal", None) is not _SEAL
    ):
        raise ValueError("Expected a sealed legacy migration")
    if not prepared._running.acquire(blocking=False):
        raise ValueError("This legacy migration is already running")
    try:
        from paper_daily.sync_document_actions import attach_document

        result = attach_document(
            prepared._actions,
            prepared._document.paper_id,
            prepared._manifest,
            store=prepared._store,
            request_id=prepared._request_id,
            _legacy=prepared,
        )
        return dict(
            status="migrated",
            paper_id=prepared._document.local_id,
            source_document_hash=prepared._manifest.sha256,
            action=result,
        )
    finally:
        prepared._running.release()
