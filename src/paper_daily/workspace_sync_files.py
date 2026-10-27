"""Bounded attachment steps for an explicitly authenticated manual sync job."""

import time

from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_transfers import DocumentTransfers
from paper_daily.workspace_service import Cancelled, _binding, _paths, _tables
from paper_daily.workspace_sync import SyncStopped


class AttachmentSteps:
    def __init__(self, client, transport, token, live, progress, *, budget=64, deadline=None):
        self.client, self.live, self.progress = client, live, progress
        self.remaining, self.steps, self.failed = budget, 0, 0
        self.deadline = deadline
        self.pdf = self.artifact = None
        with client.journal.transaction() as conn:
            tables = _tables(conn)
            root, _, registrations = _paths(conn, tables, _binding(conn, tables))
        if root is None or not root.is_dir() or not (root / "index.sqlite").is_file():
            return
        rows = dict(registrations)
        store = BlobStore(root)
        if "document_reader_paths" in rows:
            self.pdf = DocumentTransfers(
                client, store, transport, origin=transport.base_url, token=token
            )
        if "research_file_paths" in rows:
            self.artifact = FileTransfers(
                client,
                store,
                transport,
                origin=transport.base_url,
                token=token,
                version_root=rows["research_file_paths"][2],
            )

    def close(self):
        for coordinator in (self.pdf, self.artifact):
            if coordinator:
                coordinator.close()

    def _step(self, coordinator, operation, *, upload):
        if coordinator is None:
            return False
        while self.remaining and (self.deadline is None or time.monotonic() < self.deadline):
            self.live()
            self.remaining -= 1
            self.steps += 1
            try:
                result = (
                    coordinator.upload(operation, retry=True)
                    if upload
                    else coordinator.download(operation, retry=True)
                )
            except (PermissionError, SyncStopped, Cancelled):
                raise
            except (OSError, ValueError, RuntimeError):
                self.failed += 1
                return False
            self.live()
            self.progress(
                {
                    "stage": "attachments",
                    "steps": self.steps,
                    **{
                        key: result[key]
                        for key in ("offset", "size", "completed", "total")
                        if key in result
                    },
                }
            )
            state = result["state"]
            if state in {"uploaded", "bound"}:
                return True
            if state not in {"uploading", "downloading"}:
                if state == "failed":
                    self.failed += 1
                return False
        return False

    def prepare(self, operation):
        if operation["action"] == "delete":
            return True
        kind = operation["entity_type"]
        if kind == "paper_document":
            return self._step(self.pdf, operation, upload=True)
        if kind == "research_file":
            return self._step(self.artifact, operation, upload=True)
        return True

    def download_pending(self):
        # Exact target comparisons skip already applied objects, so the first
        # page cannot permanently starve later papers/assets on repeated clicks.
        with self.client.journal.transaction() as conn:
            pdfs = conn.execute(
                "SELECT d.paper_id FROM research_document_desired d LEFT JOIN "
                "research_document_applied a USING(paper_id) WHERE d.active=1 AND "
                "(a.target IS NULL OR a.target!=d.target) ORDER BY d.paper_id LIMIT 64"
            ).fetchall()
            files = conn.execute(
                "SELECT d.entity_id FROM research_file_desired d LEFT JOIN "
                "research_file_applied a USING(entity_id) WHERE d.active=1 AND "
                "(a.operation IS NULL OR a.operation!=d.operation) ORDER BY d.entity_id LIMIT 64"
            ).fetchall()
        for coordinator, rows in ((self.pdf, pdfs), (self.artifact, files)):
            for row in rows:
                if not self.remaining:
                    return
                self._step(coordinator, row[0], upload=False)

    def status(self):
        with self.client.journal.transaction() as conn:
            pending = conn.execute(
                "SELECT COUNT(*) FROM research_document_desired d LEFT JOIN "
                "research_document_applied a USING(paper_id) WHERE d.active=1 "
                "AND (a.target IS NULL OR a.target!=d.target)"
            ).fetchone()[0]
            pending += conn.execute(
                "SELECT COUNT(*) FROM research_file_desired d LEFT JOIN "
                "research_file_applied a USING(entity_id) WHERE d.active=1 "
                "AND (a.operation IS NULL OR a.operation!=d.operation)"
            ).fetchone()[0]
        return {
            "steps": self.steps,
            "failed": self.failed,
            "pending": pending,
            "storage_registered": self.pdf is not None or self.artifact is not None,
            "complete_offline_verified": False,
        }
