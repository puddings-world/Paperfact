"""Explicit desktop/library Lineage action over the maintained native boundaries.

No login, remote download or model selection occurs inside this coordinator.
The host admits a frozen route and supplies its actual loaded paper owner.
"""

from __future__ import annotations

import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from paper_daily import (
    lineage_observation,
    lineage_peer_sources,
    lineage_publication,
    lineage_sets,
    lineage_shared_publication,
    research_lineage,
)
from paper_daily import research_generation as generation
from paper_daily.lineage_jobs import LineageJob, _worker
from paper_daily.manual_highlight_ops import HighlightOwner
from paper_daily.sync_blobs import BlobStore
from paper_daily.workspace_service import _binding, _paths, _tables


@contextmanager
def _transaction(database):
    """Keep the actual capture-aware connection for loaded owner checks."""
    with closing(generation._connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


@dataclass(frozen=True)
class Outcome:
    state: str
    result: object = field(repr=False)
    operation_id: str | None = None


class LineageWorkflow:
    """One admitted analysis and publication; all methods require a worker."""

    def __init__(self, owner, job, client, sources):
        self._owner, self._job, self._client, self._sources = owner, job, client, sources
        self._lock = threading.Lock()
        self._outcome = None
        self._prepared = None

    @classmethod
    def prepare(
        cls,
        owner,
        peers,
        *,
        connections,
        legacy_root,
        document=None,
        cancelled=lambda: False,
        current=lambda: True,
        route_current=lambda: True,
    ):
        _worker()
        if not isinstance(owner, HighlightOwner):
            raise ValueError("Lineage requires the actual loaded paper owner")
        if cancelled() or not current():
            raise research_lineage.LineageError("cancelled")
        with closing(generation._connect(owner.database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            owner.check(conn)
            client = getattr(conn, "_capture_client", None)
            if client is None:
                # Explicit unbound action initializes storage, not scientific rows.
                conn.execute(lineage_sets.SCHEMA)
            else:
                from paper_daily.lineage_projection import initialize_in

                # Explicit analysis owns this transaction; low-level writes stay strict.
                from paper_daily.sync_capture import suppress_capture

                with suppress_capture(conn):
                    initialize_in(conn)
            if cancelled() or not current():
                raise research_lineage.LineageError("cancelled")
            conn.commit()
        corpus = research_lineage.capture(
            owner.database,
            owner.paper_id,
            peers,
            legacy_root=legacy_root,
            documents={owner.paper_id: document} if document is not None else None,
            cancelled=cancelled,
        )
        observation = lineage_observation.observe(corpus, str(uuid4()), str(uuid4()))
        sources = None
        if observation.data["binding"] is not None:
            if client is None:
                raise ValueError("Finish native workspace setup before Lineage analysis")
            with _transaction(owner.database) as conn:
                owner.check(conn)
                root, _legacy, registrations = _paths(
                    conn, _tables(conn), _binding(conn, _tables(conn))
                )
            paths = dict(registrations)
            if root is None or "research_file_paths" not in paths:
                raise ValueError("Register the native original-file store before Lineage analysis")
            if not root.is_dir() or not (root / "index.sqlite").is_file():
                raise ValueError("Registered native original-file store is unavailable")
            sources = lineage_peer_sources.prepare(
                observation,
                store=BlobStore(root),
                version_root=Path(paths["research_file_paths"][2]),
                client=client,
                cancelled=cancelled,
            )
        elif client is not None:
            raise ValueError("Lineage workspace binding changed")
        job = LineageJob.prepare(
            corpus,
            connections=connections,
            publication_observation=observation,
            cancelled=cancelled,
            current=current,
            route_current=route_current,
        )
        return cls(owner, job, client, sources)

    def run(self, *, cancelled=lambda: False, current=lambda: True, progress=lambda stage: None):
        _worker()
        if not self._lock.acquire(blocking=False):
            raise research_lineage.LineageError("already_running")
        try:
            if self._outcome is not None:
                if cancelled() or not current():
                    return Outcome("retained", self._outcome.result)
                if self._client is None:
                    with closing(generation._connect(self._owner.database)) as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        try:
                            self._owner.check(conn)
                            lineage_publication.publish_in(conn, self._prepared)
                            conn.commit()
                        except BaseException:
                            conn.rollback()
                            raise
                else:
                    with _transaction(self._owner.database) as conn:
                        self._owner.check(conn)
                        lineage_shared_publication.publish_in(
                            conn,
                            self._client,
                            self._sources,
                            self._job._state.candidate,
                            cancelled=cancelled,
                        )
                return self._outcome
            result = self._job.run(cancelled=cancelled, current=current, progress=progress)
            if result.retention_reason is not None or cancelled() or not current():
                return Outcome("retained", result)
            progress("publication")
            candidate = self._job._state.candidate
            if self._client is None:
                prepared = lineage_publication.prepare(candidate, cancelled=cancelled)
                self._prepared = prepared
                with closing(generation._connect(self._owner.database)) as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        self._owner.check(conn)
                        self._job._guard(cancelled, current)
                        lineage_publication.publish_in(conn, prepared)
                        conn.commit()
                    except BaseException:
                        conn.rollback()
                        raise
                self._outcome = Outcome("saved_local", result)
            else:
                with _transaction(self._owner.database) as conn:
                    self._owner.check(conn)
                    self._job._guard(cancelled, current)
                    published = lineage_shared_publication.publish_in(
                        conn,
                        self._client,
                        self._sources,
                        candidate,
                        cancelled=cancelled,
                    )
                self._outcome = Outcome("queued_sync", result, published["operation_id"])
            return self._outcome
        finally:
            self._lock.release()
