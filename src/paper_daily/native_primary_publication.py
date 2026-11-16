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


def observe(database, local_id, *, ticket=None, current=lambda: True, first_only=False):
    """Return an enrolled source observation, or None only for a legacy workspace.

    Partially enrolled workspaces are refused; they must not fall back to legacy
    filesystem replacement. Existing reader/store ownership must be configured.
    """
    if type(first_only) is not bool:
        raise ValueError("First-original admission must be explicit")
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
        observed = _scope(conn, actions, document)
        if first_only and any(observed[key] is not None for key in (
            "document_head", "desired", "applied",
        )):
            raise ValueError(
                "A managed original appeared; use workspace attachment synchronization"
            )
        scope = _encoded(observed)
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
    pdf_url: str | None
    running: object = field(repr=False)
    seal: object = field(repr=False)

    @property
    def fingerprint(self):
        return hashlib.sha256(_encoded(dict(
            observation=json.loads(self.observation.scope), pdf_url=self.pdf_url,
        ))).hexdigest()

    def _check_in(self, conn):
        self.observation.check_in(conn)

    def _final(self, conn, target, *, metadata=False):
        source = self.observation
        source.live()
        before = json.loads(source.scope)
        if metadata and self.pdf_url is not None:
            before["paper"]["pdf_url"] = self.pdf_url
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
        source = self.observation
        if applied_document(conn, source.document.paper_id) != target:
            raise ValueError("PDF publication did not retain its verified original")
        if self.pdf_url is not None:
            from paper_daily.sync_capture import _payload

            row = json.loads(source.scope)["paper"]
            payload = _payload(conn, "papers", {**row, "pdf_url": self.pdf_url})
            client = source.actions.client
            operation = client.new_graph_operation_in(
                conn, "paper", source.document.paper_id, payload,
                operation_id=source.actions._id(self.request_id, "pdf-url-op"),
            )

            def write_url(connection, value):
                # Preserve rich legacy metadata locally. The complete ordinary
                # paper payload still travels through the shared graph outbox.
                if value != operation:
                    raise ValueError("PDF URL publication changed its prepared operation")
                if connection.execute(
                    "UPDATE papers SET pdf_url=? WHERE id=?", (self.pdf_url, row["id"]),
                ).rowcount != 1:
                    raise ValueError("PDF URL publication lost its paper")

            client.journal.apply_in(conn, operation, write_url)
            self._final(conn, target, metadata=True)
        conn.execute(
            "DELETE FROM kv WHERE key=?",
            ("analyze.failed.pdf." + source.document.local_id,),
        )
        source.live()

    def _replay_in(self, conn, result):
        source = self.observation
        target = desired_document(conn, source.document.paper_id)
        if not target or target["operation_id"] != result["operation_id"]:
            raise ValueError("PDF publication retry cannot revive a newer or retired original")
        self._final(conn, target, metadata=True)
        if applied_document(conn, source.document.paper_id) != target:
            raise ValueError("PDF publication retry lost its verified original")

    def _publish(self, action):
        result = []
        self.observation.ticket.publish(lambda: result.append(action()))
        return result[0]


def prepare(observation, path, *, request_id=None, pdf_url=None):
    """Stage immutable bytes after the caller has captured the old original."""
    if not isinstance(observation, PrimaryObservation) or observation.seal is not _SEAL:
        raise ValueError("Expected an owned native primary observation")
    if pdf_url is not None:
        from paper_daily.pdf_sources import web_url

        if not isinstance(pdf_url, str) or len(pdf_url) > 8192 or web_url(pdf_url) != pdf_url:
            raise ValueError("PDF source URL must be an HTTP(S) URL without credentials")
    with observation.actions.client.journal.transaction() as conn:
        observation.check_in(conn)
    manifest = stage_file(observation.store, path)
    with observation.actions.client.journal.transaction() as conn:
        observation.check_in(conn)
    return PreparedNativePrimary(
        observation, manifest, request_id or str(uuid4()), pdf_url, Lock(), _SEAL,
    )


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
