"""Explicit bounded peer byte staging and existing caller-transaction file publication.

This grants no lineage row or private source-owner receipt. Those typed shared
installers remain separate; unbound local ownership is not silently invented.
"""

from __future__ import annotations

import hmac
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import file_change, research_lineage
from paper_daily import lineage_observation as observation
from paper_daily import research_generation as generation
from paper_daily.lineage_jobs import _worker
from paper_daily.sync_artifacts import desired_file, stage_bytes
from paper_daily.sync_blobs import BlobManifest, BlobStore
from paper_daily.sync_client import SyncClient
from paper_daily.sync_files import file_id
from paper_daily.sync_source_files import prepare_source, publish_source_in
from paper_daily.workspace_service import _binding, _paths, _tables

_KEY = secrets.token_bytes(32)


def _fail(code):
    raise research_lineage.LineageError(code) from None


@dataclass(frozen=True, slots=True)
class _Entry:
    source_id: str
    sha256: str
    size: int
    path: Path = field(repr=False)
    version: tuple = field(repr=False)
    intent: object = field(repr=False)


def _seal(observed, entries, store, root):
    value = [
        observed._seal,
        str(store.root),
        str(root),
        [[e.source_id, e.sha256, e.size, str(e.path), e.version, id(e.intent)] for e in entries],
    ]
    return hmac.new(_KEY, research_lineage._json(value).encode(), "sha256").hexdigest()


@dataclass(frozen=True, slots=True)
class PreparedPeerSources:
    _observation: observation.LineageObservation = field(repr=False)
    _entries: tuple = field(repr=False)
    _store: BlobStore = field(repr=False)
    _root: Path = field(repr=False)
    _seal: str = field(repr=False)

    @property
    def descriptors(self):
        return [dict(source_id=e.source_id, sha256=e.sha256, size=e.size) for e in self._entries]


def _storage_in(conn, observed, store, root):
    data = observation.checked(observed)
    blob, _legacy, registrations = _paths(conn, _tables(conn), _binding(conn, _tables(conn)))
    if blob is not None and blob != store.root.resolve():
        _fail("lineage_blob_root_changed")
    for name, row in registrations:
        if name == "research_file_paths" and Path(row[2]).resolve() != root.resolve():
            _fail("lineage_version_root_changed")
    index = store.root / "index.sqlite"
    with closing(sqlite3.connect(index.as_uri() + "?mode=ro", uri=True)) as metadata:
        if metadata.execute("SELECT 1 FROM sqlite_master WHERE name='transfer_binding'").fetchone():
            row = metadata.execute(
                "SELECT workspace,device,research_path FROM transfer_binding WHERE id=1"
            ).fetchone()
            binding = data["binding"]
            if (
                binding is None
                or row is None
                or tuple(row) != (binding["workspace_id"], binding["device_id"], data["database"])
            ):
                _fail("lineage_blob_scope_changed")


def prepare(observed, *, store, version_root, client=None, cancelled=lambda: False):
    """Stage actual captured peer bytes only; no graph or lineage ownership yet."""
    _worker()
    data = observation.checked(observed)
    if not isinstance(store, BlobStore):
        _fail("lineage_blob_store_required")
    if data["binding"] is not None:
        if (
            not isinstance(client, SyncClient)
            or client.journal.path.resolve() != Path(data["database"])
            or (client.journal.workspace_id, client.journal.device_id)
            != (data["binding"]["workspace_id"], data["binding"]["device_id"])
        ):
            _fail("lineage_client_scope_changed")
    elif client is not None:
        _fail("lineage_client_scope_changed")
    research_lineage.current(observed._corpus)
    root = Path(version_root).absolute()
    with closing(generation._connect(data["database"])) as conn:
        conn.execute("BEGIN")
        observation.check_in(conn, observed)
        _storage_in(conn, observed, store, root)
    entries = []
    for source, document, snapshot in zip(
        data["sources"], observed._corpus._documents, observed._corpus._snapshots, strict=True
    ):
        if cancelled():
            _fail("cancelled")
        if snapshot is None:
            continue
        metadata, raw = research_lineage.evidence._checked_snapshot(snapshot)
        if metadata["document_hash"] != source["document_hash"] or len(raw) != source["size"]:
            _fail("lineage_source_capture_changed")
        stage_bytes(store, {source["document_hash"]: raw})
        path = store.verified_path(BlobManifest(source["document_hash"], source["size"]))
        intent = None
        if client is not None:
            intent = prepare_source(
                client,
                source["parent"]["id"],
                document.path,
                document_hash=source["document_hash"],
                parent_incarnation=source["parent"]["incarnation"],
                store=store,
                version_root=root,
                request_id=observation.source_request_id(observed, source["source_id"]),
            )
        entries.append(
            _Entry(
                source["source_id"],
                source["document_hash"],
                source["size"],
                path,
                file_change.version(path),
                intent,
            )
        )
    if cancelled():
        _fail("cancelled")
    research_lineage.current(observed._corpus)
    with closing(generation._connect(data["database"])) as conn:
        conn.execute("BEGIN")
        observation.check_in(conn, observed)
        _storage_in(conn, observed, store, root)
    entries = tuple(entries)
    return PreparedPeerSources(
        observed, entries, store, root, _seal(observed, entries, store, root)
    )


def publish_in(conn, client, prepared):
    """Existing file/outbox operations share caller rollback; never commit here."""
    _worker()
    if not isinstance(prepared, PreparedPeerSources) or not hmac.compare_digest(
        prepared._seal,
        _seal(prepared._observation, prepared._entries, prepared._store, prepared._root),
    ):
        _fail("invalid_lineage_peer_staging")
    data = observation.checked(prepared._observation)
    if data["binding"] is None:
        _fail("lineage_local_owner_install_required")
    if not isinstance(client, SyncClient) or client.journal.path.resolve() != Path(
        data["database"]
    ):
        _fail("lineage_client_scope_changed")
    try:
        observation.check_in(conn, prepared._observation, client=client)
    except research_lineage.LineageError:
        # A retry may see exactly this intent's already-published originals.
        # It must still pass the complete target/parent/byte metadata comparison.
        operations = {
            source["source_id"]: desired_file(
                conn, file_id(source["parent"]["id"], "original_source", source["document_hash"])
            )
            for source in data["sources"]
            if source["document_hash"] is not None
        }
        if any(value is None for value in operations.values()):
            raise
        observation.check_after_sources_in(conn, prepared._observation, operations, client=client)
    _storage_in(conn, prepared._observation, prepared._store, prepared._root)
    operations = {}
    savepoint = "lineage_peers_" + secrets.token_hex(8)
    conn.execute("SAVEPOINT " + savepoint)
    try:
        for entry in prepared._entries:
            if file_change.version(entry.path) != entry.version:
                _fail("lineage_staged_bytes_changed")
            operations[entry.source_id] = publish_source_in(conn, client, entry.intent)
        observation.check_after_sources_in(conn, prepared._observation, operations, client=client)
    except BaseException:
        conn.execute("ROLLBACK TO " + savepoint)
        conn.execute("RELEASE " + savepoint)
        if hasattr(conn, "_capture_graph_cache"):
            conn._capture_graph_cache = None
        raise
    conn.execute("RELEASE " + savepoint)
    return operations
