"""Owned, bounded saved-chat preparation; no paid work or global database reads.

MainWindow must register busy/request_close/dispose at its launch/close barriers.
"""

from __future__ import annotations

import threading
import weakref
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Slot
from shiboken6 import isValid

from paper_daily import file_change, store
from paper_daily import reader_saved_inputs as saved
from paper_daily.desktop import reader_saved_render as render

_LIVE = set()


def _identity(path):
    info = path.stat()
    return info.st_dev, info.st_ino


def _fence(path):
    """Interference only, never a research revision or replacement classification."""
    before = file_change.version(path)
    wal = Path(str(path) + "-wal")
    observed = file_change.version(wal) if wal.exists() else None
    if observed is not None and observed[2] == 0:
        observed = None
    if file_change.version(path) != before:
        raise ValueError("Database changed during observation")
    return before, observed


@dataclass(frozen=True)
class Request:
    token: int
    key: tuple
    scope: saved.SavedRequest
    document: object
    palette: tuple
    rich: bool
    attempt: int = 0


@dataclass(frozen=True)
class Publication:
    snapshot: saved.SavedSnapshot
    html: str
    fence: tuple
    recheck: bool


def _prepare(request, cancelled):
    before = _fence(Path(request.scope.database))
    snapshot = saved.read(request.scope, document=request.document)
    if cancelled.is_set():
        return None
    data = snapshot.data
    pal = dict(request.palette)
    pending = {item["user_key"]: item for item in data["pending"]}
    rows = [item["row"] for item in data["chat"]["rows"]]
    page = (
        "<h3>問答紀錄</h3>"
        + "".join(
            render._exchange(q, a, pending, pal, request.rich)
            for q, a in render.pair_exchanges(rows)
        )
        if rows
        else f'<div style="color:{pal["faint"]};font-size:12px;">'
        "問答紀錄 · 尚無對話。可在底部自行輸入，或先選擇提問建議。</div>"
    )
    if len(page.encode()) > saved.MAX_BYTES * 8:
        raise ValueError("Saved chat HTML exceeds its budget")
    current = saved.current(snapshot, document=request.document)
    after = _fence(Path(request.scope.database))
    return Publication(snapshot, page, after, not current or before != after)


class _Worker(QThread):
    def __init__(self, request):
        super().__init__()
        self.request = request
        self.cancelled = threading.Event()
        self.result = None
        self.failed = False

    def run(self):
        try:
            self.result = _prepare(self.request, self.cancelled)
        except Exception:
            self.failed = True


def _release(worker, owner_ref):
    worker.wait()
    owner = owner_ref()
    if owner is not None and not isValid(owner):
        owner._thread = owner._pending = None
    _LIVE.discard(worker)
    worker.deleteLater()


class ReaderPreparation(QObject):
    """One running thread plus one latest pending request, owned through delivery."""

    def __init__(self, reader):
        super().__init__(reader)
        self._reader = weakref.ref(reader)
        outer = getattr(reader.win, "_workspace_owner", None)
        self.database = outer.database if outer is not None else Path(store.DB_PATH).resolve()
        try:
            self.identity = _identity(self.database)
        except OSError:
            self.identity = None
        self._epoch = self._token = 0
        self._published = None
        self._thread = self._pending = self._active_key = None
        self._disposed = False
        self._enabled = self._source_pending = False
        reader.destroyed.connect(self.dispose)

    @property
    def busy(self):
        return self._thread is not None or self._pending is not None or self._source_pending

    def _outer(self, reader):
        outer = getattr(reader.win, "_workspace_owner", None)
        return bool(
            self.identity is not None
            and self.identity[1]
            and Path(store.DB_PATH).resolve() == self.database
            and _identity(self.database) == self.identity
            and (outer is None or outer.current())
        )

    def _context(self):
        reader = self._reader()
        if self._disposed or reader is None or not isValid(reader) or not self._outer(reader):
            return None
        paper = getattr(reader, "paper", None)
        owner = getattr(reader, "_highlight_owner", None)
        if (
            paper is None
            or owner is None
            or owner.database != self.database
            or owner.paper_id != paper.id
            or reader._qa_view_database != self.database
        ):
            return None
        document = getattr(reader, "_active_document", None)
        native = reader.pdf.position_identity()
        witness = reader.pdf.position_source_version()
        if (
            native[1] is not None
            and witness is not None
            and file_change.version(native[1]) != witness
        ):
            return None
        return (
            self._epoch,
            id(paper),
            paper.id,
            reader._qa_epoch,
            id(owner),
            owner._json,
            id(document),
            id(getattr(document, "_owner", None)),
            getattr(getattr(document, "_owner", None), "_generation", None),
            getattr(getattr(document, "_owner", None), "_closed", False),
            native[0],
            str(native[1]),
            id(native[2]),
            witness,
            reader.chat_view.rich,
            tuple(sorted(reader.win.pal.items())),
            id(getattr(reader, "_qa_job", None)),
        )

    def request(self):
        """GUI metadata capture only. Repeated same-context activations coalesce."""
        try:
            context = self._context()
            if context is None:
                return False
            reader = self._reader()
            self._enabled = True
            request = saved.capture(
                reader._highlight_owner,
                document=reader._active_document,
                native_source_version=(
                    reader.pdf.position_source_version() if reader._active_document else None
                ),
            )
            key = context, _fence(self.database)
            if self.busy and key == (
                self._pending.key if self._pending is not None else self._active_key
            ):
                return False
            self._token += 1
            self._pending = Request(
                self._token,
                key,
                request,
                reader._active_document,
                tuple(sorted(reader.win.pal.items())),
                reader.chat_view.rich,
            )
            if self._thread is not None:
                self._thread.cancelled.set()
            else:
                self._start()
            return True
        except (OSError, ValueError, TypeError):
            self._error()
            return False

    def _start(self):
        if self._disposed or self._pending is None or self._thread is not None:
            return
        request, self._pending = self._pending, None
        worker = _Worker(request)
        self._thread = worker
        self._active_key = request.key
        _LIVE.add(worker)
        worker.finished.connect(self._finished)
        owner_ref = weakref.ref(self)
        worker.finished.connect(lambda: _release(worker, owner_ref))
        worker.start()

    def _matches(self, request):
        try:
            return (
                not self._disposed
                and request.token == self._token
                and (self._context() == request.key[0])
            )
        except (OSError, ValueError, TypeError, RuntimeError):
            return False

    def _error(self):
        reader = self._reader()
        if reader is not None and isValid(reader) and not reader.runner.busy:
            reader.ask_status.setText("Saved conversation could not be checked; reopen to retry.")

    def _install_current(self, request, publication):
        try:
            return (
                self._published == request.token
                and self._matches(request)
                and (_fence(self.database) == publication.fence)
            )
        except (OSError, ValueError):
            return False

    @Slot()
    def _finished(self):
        worker = self._thread
        if worker is None:
            return
        worker.wait()  # finished was emitted: join native cleanup, not outstanding I/O.
        request = worker.request
        if self._matches(request) and not worker.cancelled.is_set():
            publication = worker.result
            changed = False
            if publication is not None:
                try:
                    changed = publication.recheck or _fence(self.database) != publication.fence
                except (OSError, ValueError):
                    changed = True
            if worker.failed or publication is None:
                self._error()
            elif changed:
                if request.attempt < 1 and self._pending is None:
                    self._pending = replace(request, attempt=1)
                else:
                    self._error()
            else:
                reader = self._reader()
                self._published = request.token
                self_ref = weakref.ref(self)

                installed = False

                def current():
                    nonlocal installed
                    owner = self_ref()
                    allowed = (
                        owner is not None
                        and isValid(owner)
                        and owner._install_current(request, publication)
                    )
                    if allowed and not installed:
                        target = owner._reader()
                        target._chat_snapshot = publication.snapshot.chat_snapshot
                        target._qa_pending = {
                            item["user_key"]: item for item in publication.snapshot.data["pending"]
                        }
                        installed = True
                    return allowed

                reader.chat_view.setHtml(publication.html, at_end=True, current=current)
        # Ownership includes the entire install/discard above.
        self._thread = None
        self._active_key = None
        if not self._disposed:
            self._start()

    def invalidate(self, *, clear=False):
        self._epoch += 1
        self._source_pending = False
        if clear:
            self._enabled = False
        self._token += 1
        self._pending = self._published = None
        if self._thread:
            self._thread.cancelled.set()
        reader = self._reader()
        if clear and reader is not None and isValid(reader):
            reader._chat_snapshot = None
            reader._qa_pending = {}
            reader.chat_view.setHtml("")

    def source_changed(self):
        enabled = self._enabled
        self.invalidate()
        if enabled and not self._disposed:
            self._source_pending = True
            epoch = self._epoch
            owner_ref = weakref.ref(self)

            def ready():
                owner = owner_ref()
                if owner is not None and isValid(owner) and owner._epoch == epoch:
                    owner._source_pending = False
                    owner.request()

            QTimer.singleShot(0, self, ready)

    def request_close(self):
        if self.busy:
            self.invalidate()
            return False
        return True

    def dispose(self, *_):
        self.invalidate()
        self._disposed = True
