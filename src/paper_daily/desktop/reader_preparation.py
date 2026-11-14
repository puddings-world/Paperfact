"""Owned, bounded saved reading preparation; no paid work or global database reads.

MainWindow must register busy/request_close/dispose at its launch/close barriers.
"""

from __future__ import annotations

import threading
import weakref
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Slot
from shiboken6 import isValid

from paper_daily import file_change, manual_highlight_ops, store
from paper_daily import reader_saved_inputs as saved
from paper_daily.desktop import pdfselect
from paper_daily.desktop import reader_saved_render as render

_LIVE = set()
# A database observed mid-write is asked again shortly, a few times, before the
# reader reports that its saved content could not be checked.
RETRIES = 3
RETRY_MS = 50


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
    targets: tuple = ("chat",)
    dive_rich: bool = False
    empty_dive: str | None = None
    preview: object = None
    mark_view: object = None
    active_request: str | None = None


@dataclass(frozen=True)
class Publication:
    snapshot: saved.SavedSnapshot
    html: str
    fence: tuple
    recheck: bool
    dive_html: str | None = None
    highlights: object = None
    preview: object = None
    mark_view: object = None
    mark_words: object = None
    # The rows were read again after the file moved and came back identical. The app
    # writes to the same file all the time (reading positions, job progress), so a
    # moved file alone must not blank an explanation or conversation that did not change.
    settled: bool = False


def _prepare(request, cancelled):
    before = _fence(Path(request.scope.database))
    snapshot = saved.read(request.scope, document=request.document)
    if cancelled.is_set():
        return None
    mark_view = mark_words = None
    marks_changed = False
    if request.mark_view is not None:
        original = request.mark_view
        mark_view = manual_highlight_ops.load(
            original.owner, original.path, original.fingerprint, document=request.document
        )
        marks_changed = saved._json(mark_view.records) != saved._json(
            snapshot.data["highlight_records"]
        )
        pages = {
            page for mark in mark_view.marks
            for page in range(mark["anchor"]["p0"], mark["anchor"]["p1"] + 1)
        }
        mark_words = pdfselect.words_in(mark_view.path, pages)
    if cancelled.is_set():
        return None
    preview = saved.PreviewSnapshot((), ())
    if "dive" in request.targets and request.preview is not None:
        preview = saved.read_preview(
            snapshot, request.preview, document=request.document, cancelled=cancelled.is_set
        )
    if cancelled.is_set():
        return None
    rendered = render.render(
        snapshot,
        dict(request.palette),
        rich=request.rich,
        dive_rich=request.dive_rich,
        figures=preview.figures,
        empty_dive=request.empty_dive,
        active_request=request.active_request,
    )
    page = rendered.dive_html
    if preview.notice:
        import html

        page += '<p class="cache-notice">' + html.escape(preview.notice) + "</p>"
    current = saved.current(snapshot, document=request.document) and saved.preview_current(preview)
    after = _fence(Path(request.scope.database))
    settled = request.attempt > 0 and current and not marks_changed
    return Publication(
        snapshot,
        rendered.chat_html,
        after,
        not current or marks_changed or (before != after and not settled),
        page if "dive" in request.targets else None,
        rendered.highlights,
        preview,
        mark_view,
        mark_words,
        settled,
    )


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
        self._published_marks = None
        self._thread = self._pending = self._active_key = None
        self._disposed = False
        self._enabled = self._source_pending = False
        self._want_dive = False
        self._want_marks = False
        self._empty_dive = None
        self._retries = 0
        self._retry_scheduled = False
        reader.destroyed.connect(self.dispose)

    @property
    def busy(self):
        return (
            self._thread is not None
            or self._pending is not None
            or self._source_pending
            or self._retry_scheduled
        )

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
            self._enabled,
            self._want_dive,
            self._empty_dive,
            reader.qa_presentation.state() if hasattr(reader, "qa_presentation") else (None, 0),
            reader.dive_view.rich if self._want_dive else None,
            id(getattr(getattr(reader, "figure_pane", None), "_frame", None))
            if self._want_dive
            else None,
        )

    def request(self, *, dive=False, empty_dive=None, marks=False):
        """GUI metadata capture only. Repeated same-context activations coalesce."""
        try:
            if dive:
                self._want_dive = True
                self._empty_dive = empty_dive
            if marks:
                self._want_marks = True
            if not dive and not marks:
                self._enabled = True
            context = self._context()
            if context is None:
                return False
            reader = self._reader()
            mark_view = getattr(reader, "_highlight_view", None) if self._want_marks else None
            if self._want_marks and (
                not isinstance(mark_view, manual_highlight_ops.HighlightView)
                or reader._active_document is None
                or mark_view.document is not reader._active_document
                or mark_view.owner is not reader._highlight_owner
            ):
                return False
            request = saved.capture(
                reader._highlight_owner,
                document=reader._active_document,
                native_source_version=(
                    reader.pdf.position_source_version() if reader._active_document else None
                ),
            )
            try:
                fence = _fence(self.database)
            except ValueError:
                # Opening a paper writes to the database, and a write that lands while
                # it is being observed is interference, not an answer. This request
                # already changed what is wanted, so a pending one is stale; ask again
                # once the write settles instead of leaving the page blank.
                if self._retry_later():
                    return False
                raise
            key = context, fence, id(mark_view)
            if self.busy and key == (
                self._pending.key if self._pending is not None else self._active_key
            ):
                return False
            preview = None
            if self._want_dive:
                from paper_daily import figures

                preview = saved.capture_preview(
                    figures.FIG_DIR,
                    dict(
                        min_height=figures.MIN_HEIGHT,
                        max_height=figures.MAX_HEIGHT,
                        render_scale=figures.RENDER_SCALE,
                        min_png_bytes=figures.MIN_PNG_BYTES,
                    ),
                    getattr(reader.figure_pane, "_frame", None),
                )
            self._token += 1
            self._pending = Request(
                self._token,
                key,
                request,
                reader._active_document,
                tuple(sorted(reader.win.pal.items())),
                reader.chat_view.rich,
                targets=tuple(
                    name
                    for name, yes in (("chat", self._enabled), ("dive", self._want_dive),
                                      ("marks", self._want_marks))
                    if yes
                ),
                dive_rich=reader.dive_view.rich,
                empty_dive=self._empty_dive,
                preview=preview,
                mark_view=mark_view,
                active_request=(reader.qa_presentation.state()[0]
                                if hasattr(reader, "qa_presentation") else None),
            )
            if self._thread is not None:
                self._thread.cancelled.set()
            else:
                self._start()
            return True
        except (OSError, ValueError, TypeError):
            self._error()
            return False

    def _retry_later(self):
        if self._disposed or self._retries >= RETRIES:
            return False
        if self._retry_scheduled:
            return True
        self._retries += 1
        self._retry_scheduled = True
        epoch = self._epoch
        owner_ref = weakref.ref(self)

        def again():
            owner = owner_ref()
            if owner is None or not isValid(owner):
                return
            owner._retry_scheduled = False
            if owner._disposed or owner._epoch != epoch:
                return
            if owner._enabled or owner._want_dive or owner._want_marks:
                owner.request(dive=owner._want_dive, empty_dive=owner._empty_dive,
                              marks=owner._want_marks)

        QTimer.singleShot(RETRY_MS, self, again)
        return True

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
                and (request.mark_view is None
                     or self._reader()._highlight_view is request.mark_view
                     or (self._published == request.token
                         and self._published_marks is not None
                         and self._published_marks is self._reader()._highlight_view))
            )
        except (OSError, ValueError, TypeError, RuntimeError):
            return False

    def _error(self):
        reader = self._reader()
        if reader is not None and isValid(reader) and not reader.runner.busy:
            reader.ask_status.setText(
                "Saved reading content could not be checked; reopen to retry."
            )

    def _install_current(self, request, publication):
        try:
            return (
                self._published == request.token
                and self._matches(request)
                and (publication.settled or _fence(self.database) == publication.fence)
                and (publication.preview is None or saved.preview_current(publication.preview))
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
            preview_changed = False
            if publication is not None:
                try:
                    preview_changed = publication.preview is not None and not saved.preview_current(
                        publication.preview
                    )
                    changed = publication.recheck or (
                        not publication.settled and _fence(self.database) != publication.fence
                    )
                except (OSError, ValueError):
                    changed = True
            if worker.failed or publication is None:
                self._error()
            elif preview_changed:
                # Preserve the accepted page. A later explicit request can inspect
                # a new cache snapshot; never silently rebase a queued preview.
                self._error()
            elif changed:
                if request.attempt < 1 and self._pending is None:
                    self._pending = replace(request, attempt=1)
                else:
                    self._error()
            else:
                reader = self._reader()
                self._published = request.token
                if publication.mark_view is not None:
                    selection = getattr(reader.pdf, "selection", None)
                    if selection is not None and self._install_current(request, publication):
                        selection.prime(publication.mark_words)
                        reader._highlight_view = self._published_marks = publication.mark_view
                        selection.set_highlights(publication.mark_view.marks)
                        reader._show_highlight_count(publication.mark_view.marks)
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
                        notice = getattr(target, "saved_text_notice", None)
                        if notice is not None:
                            notice.accept_snapshot(publication.snapshot, request.targets)
                        installed = True
                    return allowed

                if "chat" in request.targets:
                    reader.chat_view.setHtml(publication.html, at_end=True, current=current)
                if "dive" in request.targets:

                    def dive_current():
                        if not current():
                            return False
                        reader._dive_highlights = publication.highlights
                        return True

                    reader.dive_view.setHtml(publication.dive_html, current=dive_current)
        # Ownership includes the entire install/discard above.
        self._thread = None
        self._active_key = None
        if self._pending is None:
            self._want_marks = False
        if not self._disposed:
            self._start()

    def invalidate(self, *, clear=False):
        self._epoch += 1
        self._retries = 0
        self._source_pending = False
        if clear:
            self._enabled = self._want_dive = self._want_marks = False
            self._empty_dive = None
        self._token += 1
        self._pending = self._published = self._published_marks = None
        if self._thread:
            self._thread.cancelled.set()
        reader = self._reader()
        if reader is not None and isValid(reader):
            reader._dive_highlights = None
        if clear and reader is not None and isValid(reader):
            reader.dive_view.setHtml("")
            reader._chat_snapshot = None
            reader._qa_pending = {}
            reader.chat_view.setHtml("")

    def source_changed(self):
        enabled = self._enabled or self._want_dive or self._want_marks
        self.invalidate()
        if enabled and not self._disposed:
            self._source_pending = True
            epoch = self._epoch
            owner_ref = weakref.ref(self)

            def ready():
                owner = owner_ref()
                if owner is not None and isValid(owner) and owner._epoch == epoch:
                    owner._source_pending = False
                    reader = owner._reader()
                    if reader is None or getattr(reader, "_active_document", None) is None:
                        owner._want_marks = False
                    if owner._enabled or owner._want_dive or owner._want_marks:
                        owner.request(dive=owner._want_dive, empty_dive=owner._empty_dive,
                                      marks=owner._want_marks)

            QTimer.singleShot(0, self, ready)

    def request_close(self):
        if self.busy:
            self.invalidate()
            return False
        return True

    def dispose(self, *_):
        self.invalidate()
        self._disposed = True
