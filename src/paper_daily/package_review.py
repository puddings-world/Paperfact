"""Worker-owned import review over the maintained enrolled package transaction."""

from __future__ import annotations

import threading
from contextlib import closing
from pathlib import Path

from paper_daily import research_generation, research_job_lock
from paper_daily.package_import import PackageImporter, _hash
from paper_daily.workspace_service import Ticket, WorkspaceChanged

MAX_SEARCH_RESULTS = 50


class PackageReview:
    """One archive and receiver; titles are display data, never matching authority."""

    def __init__(self, database, data_root, archive, *, current_path=None):
        self.importer = PackageImporter(database, data_root, current_path=current_path)
        self.archive = Path(archive).resolve()
        self.fingerprint = None
        self.prepared = None
        self._pending_lineage = None
        self._lineage_decision = None
        self._lineage_options = None
        self.closed = threading.Event()
        self._state_lock = threading.Lock()
        self._ticket = None
        self.owner = _hash(str(self.archive).encode())

    def _admit(self, ticket):
        with self._state_lock:
            if self.closed.is_set():
                raise WorkspaceChanged("The import review is closed")
            self._ticket = ticket
        return ticket

    def check(self):
        if self.closed.is_set():
            raise WorkspaceChanged("The import review is closed")
        self.importer._check()

    def current(self):
        try:
            self.check()
            return True
        except (OSError, ValueError):
            return False

    def inspect(self, ticket=None):
        ticket = self._admit(ticket or Ticket())
        self.check()
        inventory = self.importer._inventory(self.archive, ticket)
        _path, _stamp, fingerprint, manifest, tables, *_rest = inventory
        with closing(research_generation._connect(self.importer.database)) as conn:
            conn.execute("BEGIN")
            self.importer._check(conn)
            graph = self.importer.client._optimistic_graph(conn)[0]
            lists = [
                dict(id=row[0], name=row[1])
                for row in conn.execute("SELECT id,name FROM lists ORDER BY name,id")
                if graph.get(("list", row[0]), {}).get("active")
            ]
        self.check()
        ticket.check()
        self.fingerprint = fingerprint
        return dict(
            name=manifest["list"]["name"],
            lists=lists,
            papers=[
                dict(id=row["id"], title=row["title"])
                for row in tables["papers"] + tables.get("cited_papers", [])
            ],
        )

    def search(self, query):
        self.check()
        if not isinstance(query, str) or len(query) > 200:
            raise ValueError("Use at most 200 characters to find a paper")
        needle = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with closing(research_generation._connect(self.importer.database)) as conn:
            conn.execute("BEGIN")
            self.importer._check(conn)
            graph = self.importer.client._optimistic_graph(conn)[0]
            rows = conn.execute(
                "SELECT p.id,p.title,p.year,i.sync_id FROM papers p "
                "JOIN research_paper_identity i ON i.local_id=p.id "
                "WHERE p.title LIKE ? ESCAPE '\\' OR p.id=? ORDER BY p.title,p.id",
                ("%" + needle + "%", query.strip()),
            )
            selected = []
            for row in rows:
                if graph.get(("paper", row[3]), {}).get("active"):
                    selected.append(dict(id=row[0], title=row[1], year=row[2]))
                    if len(selected) > MAX_SEARCH_RESULTS:
                        break
        self.check()
        return dict(papers=selected[:MAX_SEARCH_RESULTS], more=len(selected) > MAX_SEARCH_RESULTS)

    def discard(self):
        prepared, self.prepared = self.prepared, None
        if prepared is not None and prepared.work != self.importer.root:
            self.importer._cleanup(prepared.work)

    def prepare(
        self, *, target_list_id=None, paper_mapping=None, ticket=None, lineage_choices=None
    ):
        ticket = self._admit(ticket or Ticket())
        self.check()
        if self.fingerprint is None:
            raise ValueError("Inspect the selected package before reviewing changes")
        self.discard()
        mapping = dict(paper_mapping or {})
        if len(set(mapping.values())) != len(mapping):
            raise ValueError("Each incoming paper needs a separate destination")
        options = (target_list_id, tuple(sorted(mapping.items())))
        if options != self._lineage_options:
            self._pending_lineage = self._lineage_decision = None
            self._lineage_options = options
        if lineage_choices is not None:
            if self._pending_lineage is None:
                raise ValueError("Compare the Lineage versions before choosing")
            self._lineage_decision = self._pending_lineage.decide(lineage_choices)
        with research_job_lock.claim(
            self.importer.database, "package-import", self.owner
        ) as acquired:
            if not acquired:
                raise ValueError("This package import is already in progress")
            from paper_daily.lineage_import_review import ReviewRequired

            try:
                prepared = self.importer.prepare(
                    self.archive,
                    ticket=ticket,
                    target_list_id=target_list_id,
                    paper_mapping=mapping,
                    confirmed_mapping=bool(target_list_id or mapping),
                    allow_new_namespace=target_list_id is None,
                    lineage_decision=self._lineage_decision,
                )
            except ReviewRequired as required:
                ticket.check()
                self.check()
                if required.review.archive_hash != self.fingerprint:
                    self._pending_lineage = self._lineage_decision = None
                    raise ValueError("The selected package changed; reopen its review") from None
                self._pending_lineage = required.review
                return dict(state="needs_lineage_review", conflicts=required.review.conflicts)
            except BaseException:
                self._pending_lineage = self._lineage_decision = None
                raise
            self.prepared = prepared
            try:
                if prepared.preview()["package_fingerprint"] != self.fingerprint:
                    raise ValueError("The selected package changed; reopen its review")
                ticket.check()
                self.check()
            except BaseException:
                self.discard()
                raise
            return prepared.preview()

    def apply(self, ticket=None):
        ticket = self._admit(ticket or Ticket())
        self.check()
        if self.prepared is None:
            raise ValueError("Review changes before importing")
        with research_job_lock.claim(
            self.importer.database, "package-import", self.owner
        ) as acquired:
            if not acquired:
                raise ValueError("This package import is already in progress")
            try:
                return self.importer.apply(self.prepared, ticket=ticket)
            finally:
                self.prepared = None

    def close(self):
        with self._state_lock:
            self.closed.set()
            ticket = self._ticket
        if ticket is not None:
            ticket.cancel()
