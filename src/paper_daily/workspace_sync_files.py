"""Bounded attachment steps for an explicitly authenticated manual sync job."""

import time

from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_files import file_id
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
        from paper_daily import lineage_dependencies

        if lineage_dependencies.requires_readiness(operation):
            with self.client.journal.transaction() as conn:
                return lineage_dependencies.ready_to_push_in(conn, self.client, operation)
        if operation["action"] == "delete":
            return True
        kind = operation["entity_type"]
        if kind == "paper_document":
            return self._step(self.pdf, operation, upload=True)
        if kind == "research_file":
            return self._step(self.artifact, operation, upload=True)
        return True

    @staticmethod
    def _selection(paper_ids):
        if paper_ids is None:
            return None
        if not isinstance(paper_ids, (list, tuple)) or len(paper_ids) > 100:
            raise ValueError("Select at most 100 portable papers")
        if any(not isinstance(identity, str) for identity in paper_ids):
            raise ValueError("Expected portable paper UUIDs")
        selected = list(dict.fromkeys(paper_ids))
        for identity in selected:
            file_id(identity, "deck", "notes")  # Canonical portable UUID validation.
        return selected

    @classmethod
    def _scope(cls, paper_ids, *, artifacts=False):
        selected = cls._selection(paper_ids)
        if selected is None:
            return "", []
        values = selected
        if not values:
            return " AND 0", []
        column = "json_extract(d.operation,'$.payload.paper_id')" if artifacts else "d.paper_id"
        return f" AND {column} IN ({','.join('?' for _ in values)})", values

    def download_selected(self, paper_ids):
        """Explicitly recheck/download selected targets, including previously applied files."""
        return self.download_pending(paper_ids=paper_ids, include_applied=True)

    def download_pending(self, *, paper_ids=None, include_applied=False):
        # Exact target comparisons skip already applied objects, so the first
        # page cannot permanently starve later papers/assets on repeated clicks.
        if type(include_applied) is not bool:
            raise ValueError("Applied-file selection must be boolean")
        pdf_scope, pdf_args = self._scope(paper_ids)
        file_scope, file_args = self._scope(paper_ids, artifacts=True)
        pdf_pending = "" if include_applied else " AND (a.target IS NULL OR a.target!=d.target)"
        file_pending = ("" if include_applied
                        else " AND (a.operation IS NULL OR a.operation!=d.operation)")
        pdf_limit, file_limit = (64, 64) if paper_ids is None else (100, 200)
        with self.client.journal.transaction() as conn:
            pdfs = conn.execute(
                "SELECT d.paper_id FROM research_document_desired d LEFT JOIN "
                "research_document_applied a USING(paper_id) WHERE d.active=1"
                + pdf_pending + pdf_scope + f" ORDER BY d.paper_id LIMIT {pdf_limit}", pdf_args,
            ).fetchall()
            files = conn.execute(
                "SELECT d.entity_id FROM research_file_desired d LEFT JOIN "
                "research_file_applied a USING(entity_id) WHERE d.active=1"
                + file_pending + file_scope + f" ORDER BY d.entity_id LIMIT {file_limit}",
                file_args,
            ).fetchall()
        targets = [(coordinator, row[0])
                   for coordinator, rows in ((self.pdf, pdfs), (self.artifact, files))
                   for row in rows]
        completed, attempted = 0, 0
        for coordinator, identity in targets:
            if (not self.remaining
                    or (self.deadline is not None and time.monotonic() >= self.deadline)):
                break
            attempted += 1
            completed += self._step(coordinator, identity, upload=False)
        return {"transfer_targets": len(targets), "completed_targets": completed,
                "attempted_targets": attempted, "remaining_targets": len(targets) - completed}

    def status(self, *, paper_ids=None):
        pdf_scope, pdf_args = self._scope(paper_ids)
        file_scope, file_args = self._scope(paper_ids, artifacts=True)
        with self.client.journal.transaction() as conn:
            pending = conn.execute(
                "SELECT COUNT(*) FROM research_document_desired d LEFT JOIN "
                "research_document_applied a USING(paper_id) WHERE d.active=1 "
                "AND (a.target IS NULL OR a.target!=d.target)" + pdf_scope, pdf_args,
            ).fetchone()[0]
            pending += conn.execute(
                "SELECT COUNT(*) FROM research_file_desired d LEFT JOIN "
                "research_file_applied a USING(entity_id) WHERE d.active=1 "
                "AND (a.operation IS NULL OR a.operation!=d.operation)" + file_scope, file_args,
            ).fetchone()[0]
        return {
            "steps": self.steps,
            "failed": self.failed,
            "pending": pending,
            "storage_registered": self.pdf is not None or self.artifact is not None,
            "complete_offline_verified": False,
        }
