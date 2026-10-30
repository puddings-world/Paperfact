"""Bounded, coalesced analysis-status reads; no AI, research writes or network."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from paper_daily import analyze
from paper_daily import research_generation as generation
from paper_daily.document_reader import from_workspace
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.sync_documents import _identity


def capture(database, paper_id):
    """A cheap read-only scope token, never byte verification or provider access."""
    database = Path(database).resolve()
    before = generation._identity(database)
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.05)) as conn:
        binding = generation._binding(conn)
        lifecycle = parent_lifecycle(conn, "paper", paper_id)
        exists = conn.execute("SELECT 1 FROM papers WHERE id=?", (paper_id,)).fetchone()
    if not exists or generation._identity(database) != before:
        raise ValueError("The analysis workspace changed")
    reader = from_workspace(database, legacy_root=analyze.PDF_DIR)
    document = reader.inspect(paper_id)
    source_path = document.path
    if source_path is None and not document.managed and reader.legacy_root is not None:
        source_path = reader.legacy_root / (analyze._safe_name(paper_id) + ".pdf")
    try:
        file_identity = _identity(source_path) if source_path is not None else None
    except FileNotFoundError:
        file_identity = None
    return (str(database), paper_id, tuple(before), json.dumps(binding, sort_keys=True), lifecycle,
            document.mode, document._target, document._context, file_identity)


def read(scope):
    """Run on a worker: hash current source bytes and return only the captured scope."""
    database, paper_id = Path(scope[0]), scope[1]
    if capture(database, paper_id) != scope:
        return None
    with closing(generation._connect(database)) as conn:
        conn.execute("PRAGMA busy_timeout=250")
        state = analyze.status(conn, paper_id, verify_sources=True)
        failures = {step: analyze.failed(conn, paper_id, step) or "" for step in state}
    return (state, failures) if capture(database, paper_id) == scope else None


class LatestStatus(QObject):
    """At most one running read and one replaceable pending scope per view."""

    _finished = Signal(int, object, object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._guard = threading.Lock()
        self._token = 0
        self._key = None
        self._pending = None
        self._running = False
        self._closed = False
        self._idle = threading.Event()
        self._idle.set()
        self._finished.connect(self._deliver)
        self.destroyed.connect(self.close)

    def run(self, key, work, apply):
        with self._guard:
            if self._closed or self._running and key == self._key:
                return False
            self._token += 1
            self._key = key
            self._pending = (self._token, work, apply)
            self._idle.clear()
            if self._running:
                return True
            self._running = True
        threading.Thread(target=self._run, name="analysis-status", daemon=True).start()
        return True

    def cancel(self):
        with self._guard:
            self._token += 1
            self._pending = None
            self._key = None

    def close(self, *_):
        with self._guard:
            self._closed = True
            self._token += 1
            self._pending = None

    def wait(self, timeout=5):
        return self._idle.wait(timeout)

    def _run(self):
        while True:
            with self._guard:
                job, self._pending = self._pending, None
                if job is None or self._closed:
                    self._running = False
                    self._idle.set()
                    return
            token, work, apply = job
            try:
                packed = (True, work())
            except Exception:
                # Do not move a provider body, file path or research text into UI errors.
                packed = (False, None)
            try:
                self._finished.emit(token, apply, packed)
            except RuntimeError:
                self.close()

    def _deliver(self, token, apply, packed):
        with self._guard:
            current = not self._closed and token == self._token
        if not current:
            return
        success, result = packed
        if success:
            apply(result)
        else:
            self.failed.emit("Saved analysis could not be checked; please retry")
