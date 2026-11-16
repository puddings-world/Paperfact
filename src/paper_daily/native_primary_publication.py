"""Source-observed native PDF publication through the shared attachment action.

Capture before fetching/staging. No HTTP, legacy alias writes, or note reanchoring
belongs here. The existing immutable store and transaction own publication.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from uuid import uuid4

from paper_daily.document_reader import _owned_path, _registration
from paper_daily.legacy_primary_migration import _encoded, _identity, _read, _scope, _store_scope
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_client import SyncClient
from paper_daily.sync_document_actions import attach_document, stage_file
from paper_daily.sync_documents import applied_document, bind_verified_document, desired_document
from paper_daily.sync_operations import ResearchOperations
from paper_daily.sync_research import research_writer
from paper_daily.workspace_service import Ticket, _binding, _tables
from paper_daily.workspace_sync import GuardedJournal, local_binding

_SEAL = object()


@dataclass(frozen=True)
class PrimaryObservation:
    """An exact local lifetime and document base, observed before external work."""

    actions: object = field(repr=False)
    store: object = field(repr=False)
    document: object = field(repr=False)
    database: Path
    identity: tuple
    store_identity: tuple
    scope: bytes = field(repr=False)
    ticket: object = field(repr=False)
    current: object = field(repr=False)
    seal: object = field(repr=False)

    def live(self):
        self.ticket.check()
        if not self.current() or _identity(self.database) != self.identity:
            raise ValueError("PDF publication workspace lifetime changed")
        journal = self.actions.client.journal
        if Path(journal.path).resolve() != self.database:
            raise ValueError("PDF publication database changed")
        if _store_scope(self.store, self.database, journal.workspace_id, journal.device_id) != (
            self.store_identity
        ):
            raise ValueError("PDF publication store changed")

    def check_in(self, conn):
        self.live()
        if _encoded(_scope(conn, self.actions, self.document)) != self.scope:
            raise ValueError("PDF publication paper, original or workspace changed; retry")


def observe(database, local_id, *, ticket=None, current=lambda: True):
    """Return an enrolled source observation, or None only for a legacy workspace.

    Partially enrolled workspaces are refused; they must not fall back to legacy
    filesystem replacement. Existing reader/store ownership must be configured.
    """
    database = _owned_path(database)
    identity = _identity(database)
    with closing(_read(database)) as conn:
        tables = _tables(conn)
        binding = _binding(conn, tables)
    if not binding:
        if tables & {
            "paperfact_sync_identity", "research_sync_binding", "research_capture_binding",
        }:
            raise ValueError("Incomplete workspace binding; legacy PDF replacement refused")
        return None
    owner = local_binding(database, require_capture=True)
    ticket = ticket or Ticket()
    if not isinstance(ticket, Ticket) or ticket.published or not callable(current):
        raise ValueError("PDF publication requires a fresh ticket and current caller")
    ticket.check()
    if not current():
        raise ValueError("PDF publication caller changed")
    journal = GuardedJournal.attach_existing(database, **owner)

    def live():
        ticket.check()
        if not current() or _identity(database) != identity:
            raise ValueError("PDF publication workspace lifetime changed")

    journal.live = live
    actions = ResearchOperations(
        SyncClient(journal, research_writer), expected=(database, identity),
    )
    with journal.transaction() as conn:
        mapping = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (local_id,)
        ).fetchone()
        registration = _registration(conn, _tables(conn))
        if mapping is None or registration is None or registration[0] != owner["workspace_id"]:
            raise ValueError("Configure owned workspace PDF storage before replacing an original")
        document = SimpleNamespace(local_id=local_id, paper_id=mapping[0])
        scope = _encoded(_scope(conn, actions, document))
    blob_root = _owned_path(registration[1])
    if not (blob_root / "index.sqlite").is_file():
        raise ValueError("Configured PDF store is unavailable; restore its owned storage")
    blobs = BlobStore(blob_root)
    value = PrimaryObservation(
        actions, blobs, document, database, identity,
        _store_scope(blobs, database, owner["workspace_id"], owner["device_id"]),
        scope, ticket, current, _SEAL,
    )
    with journal.transaction() as conn:
        value.check_in(conn)
    return value


@dataclass(frozen=True)
class PreparedNativePrimary:
    observation: PrimaryObservation = field(repr=False)
    manifest: object
    request_id: str
    running: object = field(repr=False)
    seal: object = field(repr=False)

    @property
    def fingerprint(self):
        return hashlib.sha256(self.observation.scope).hexdigest()

    def _check_in(self, conn):
        self.observation.check_in(conn)

    def _final(self, conn, target):
        source = self.observation
        source.live()
        before = json.loads(source.scope)
        now = _scope(conn, source.actions, source.document)
        for key in ("binding", "paper", "parent", "lifecycle", "registration"):
            if _encoded(now[key]) != _encoded(before[key]):
                raise ValueError("PDF publication owner changed during commit")
        if desired_document(conn, source.document.paper_id) != target:
            raise ValueError("PDF publication target changed during commit")

    def _bind_in(self, conn, target, verified):
        self._final(conn, target)
        if not bind_verified_document(conn, target, verified):
            raise ValueError("PDF publication could not bind verified original")

    def _before_receipt(self, conn, target):
        self._final(conn, target)
        if applied_document(conn, self.observation.document.paper_id) != target:
            raise ValueError("PDF publication did not retain its verified original")

    def _replay_in(self, conn, result):
        source = self.observation
        target = desired_document(conn, source.document.paper_id)
        if not target or target["operation_id"] != result["operation_id"]:
            raise ValueError("PDF publication retry cannot revive a newer or retired original")
        self._before_receipt(conn, target)

    def _publish(self, action):
        result = []
        self.observation.ticket.publish(lambda: result.append(action()))
        return result[0]


def prepare(observation, path, *, request_id=None):
    """Stage immutable bytes after the caller has captured the old original."""
    if not isinstance(observation, PrimaryObservation) or observation.seal is not _SEAL:
        raise ValueError("Expected an owned native primary observation")
    with observation.actions.client.journal.transaction() as conn:
        observation.check_in(conn)
    manifest = stage_file(observation.store, path)
    with observation.actions.client.journal.transaction() as conn:
        observation.check_in(conn)
    return PreparedNativePrimary(observation, manifest, request_id or str(uuid4()), Lock(), _SEAL)


def validate_for_attach(value, actions, paper_id, manifest, store, request_id):
    if not isinstance(value, PreparedNativePrimary) or value.seal is not _SEAL:
        raise ValueError("Expected a sealed native primary publication")
    source = value.observation
    if (source.seal is not _SEAL or source.actions is not actions or source.store is not store
            or source.document.paper_id != paper_id or value.manifest != manifest
            or value.request_id != request_id):
        raise ValueError("Native primary publication changed its prepared action")
    source.live()
    return value


def run(prepared):
    """One retry-safe publication; cancellation covers the actual SQL commit."""
    if not isinstance(prepared, PreparedNativePrimary) or prepared.seal is not _SEAL:
        raise ValueError("Expected a sealed native primary publication")
    if not prepared.running.acquire(blocking=False):
        raise ValueError("This PDF publication is already running")
    try:
        source = prepared.observation
        return attach_document(
            source.actions, source.document.paper_id, prepared.manifest,
            store=source.store, request_id=prepared.request_id, _native=prepared,
        )
    finally:
        prepared.running.release()
