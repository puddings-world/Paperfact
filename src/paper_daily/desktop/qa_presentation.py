"""Ephemeral prepared-question display; never publication or retry authority."""

from __future__ import annotations

import sqlite3
import threading
import weakref
from contextlib import closing, suppress
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal, Slot
from shiboken6 import isValid

from paper_daily import audit_inputs, file_change, research_chat
from paper_daily.desktop.window_workspace import WindowWorkspace


@dataclass(frozen=True)
class _WorkerScope:
    owner: object
    path: object
    version: tuple | None
    stopped: threading.Event

    def verify(self, request):
        if self.stopped.is_set():
            return False
        record = research_chat.validate_request_record(getattr(request, "_receipt", None))
        if (record["context_json"] != request.encoded
                or record["request_id"] != request.request_id
                or request.db_path != self.owner.database
                or request.data["paper_id"] != self.owner.paper_id):
            return False
        with closing(audit_inputs._connect(self.owner.database)) as conn:
            self.owner.check(conn)
        document = request.document
        if self.path is None:
            return document is None
        return (
            document is not None and document.path == self.path
            and self.version is not None and file_change.version(self.path) == self.version
            and document.sha256 == request.data["document"]["sha256"]
            and document._owner.intact(document)
        )


class ChatPresentation(QObject):
    """One weak worker sink and one bounded mailbox; signal carries only UUID."""

    prepared = Signal(str)

    def __init__(self, reader):
        super().__init__(reader)
        self._reader = weakref.ref(reader)
        self._outer = getattr(reader.win, "_workspace_owner", None)
        if self._outer is None:
            self._outer = WindowWorkspace.capture()
        self._lock = threading.Lock()
        self._closed = False
        self._serial = self._revision = 0
        self._mail = None
        self._lease = self._scope = self._run = None
        self._active = None
        self.prepared.connect(self._arrived, Qt.ConnectionType.QueuedConnection)
        reader.pdf.source_changed.connect(self.view_changed)

    def _context(self):
        reader = self._reader()
        if self._closed or reader is None or not isValid(reader) or not self._outer.current():
            return None
        if getattr(reader.win, "_workspace_owner", self._outer) is not self._outer:
            return None
        paper = reader.paper
        owner = getattr(reader, "_highlight_owner", None)
        if paper is None or owner is None or owner.database != reader._qa_view_database:
            return None
        native = reader.pdf.position_identity()
        witness = reader.pdf.position_source_version()
        if native[1] is not None and (
            witness is None or file_change.version(native[1]) != witness
        ):
            return None
        document = getattr(reader, "_active_document", None)
        return (id(paper), paper.id, reader._qa_epoch, id(owner), owner._json,
                id(document), id(getattr(document, "_owner", None)),
                getattr(getattr(document, "_owner", None), "_generation", None),
                getattr(getattr(document, "_owner", None), "_closed", False),
                native[0], native[1], id(native[2]), witness)

    def begin(self, job, paper, epoch):
        self.view_changed()
        reader = self._reader()
        context = self._context()
        if context is None or reader.paper is not paper or reader._qa_epoch != epoch:
            return None
        self._lease = context
        scope = _WorkerScope(reader._highlight_owner, context[10], context[12], threading.Event())
        self._scope = scope
        serial = self._serial
        self._run = (weakref.ref(job), paper.id, reader.ask_status.text())
        owner_ref = weakref.ref(self)

        def offer(request):
            if not scope.verify(request):
                return
            owner = owner_ref()
            if owner is None:
                return
            identity = request.request_id
            with owner._lock:
                if owner._closed or scope.stopped.is_set() or serial != owner._serial:
                    return
                owner._mail = (serial, identity)
            with suppress(RuntimeError):
                owner.prepared.emit(identity)

        return offer

    @Slot(str)
    def _arrived(self, identity):
        with self._lock:
            if self._mail != (self._serial, identity):
                return
            self._mail = None
        try:
            if self._context() != self._lease or self._lease is None:
                return
            reader = self._reader()
            job = self._run[0]() if self._run else None
            if job is None or reader._qa_job is not job or not reader.runner.busy:
                return
            if job.answer is not None or self._active == identity:
                return
            self._active = identity
            self._revision += 1
            reader.preparation.request()
        except (OSError, ValueError, RuntimeError):
            return

    def state(self):
        try:
            active = (self._active
                      if self._lease is not None and self._context() == self._lease else None)
        except (OSError, ValueError, RuntimeError):
            active = None
        return active, self._revision

    def view_changed(self, *_args):
        with self._lock:
            self._serial += 1
            self._mail = None
            if self._scope is not None:
                self._scope.stopped.set()
            self._scope = self._lease = None
            self._active = None
            self._revision += 1

    def finished(self, job, *, failed=False):
        run = self._run
        if run is None or run[0]() is not job:
            return
        reader = self._reader()
        try:
            same = self._lease is not None and self._context() == self._lease
            self.view_changed()
            self._run = None
            if reader is None or not isValid(reader) or not self._outer.current():
                return
            if same and failed:
                reader.preparation.request()
            # Opening another paper clears the line; anything else there is newer news.
            elif (reader.paper is not None and reader.paper.id != run[1]
                  and reader._qa_job is job and reader.ask_status.text() in (run[2], "")):
                reader.ask_status.setText("先前論文的問答已結束；目前論文與草稿保留。")
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            self.view_changed()

    def dispose(self):
        self.view_changed()
        with self._lock:
            self._closed = True
        self._run = None
