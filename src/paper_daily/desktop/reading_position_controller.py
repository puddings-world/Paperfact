"""Bounded native reading positions; all source/storage verification runs off Qt.

The browser/native PDF load is never a reading event. Only sealed native page
input or Remember starts a save. Resume targets an already-loaded verified source
and is never queued for a later load. No account or AI operation lives here.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QLabel, QPushButton
from shiboken6 import isValid

from paper_daily import reading_position_ops as operations
from paper_daily.desktop.position_observer import NativePositionObserver

MESSAGES = {
    "remember": ("記住此頁", "Remember page"),
    "resume": ("前往記錄頁", "Resume page"),
    "check": ("檢查頁碼記錄", "Check page record"),
    "stop": ("停止", "Stop"),
    "checking": ("正在核對原文與頁碼…", "Checking original and page…"),
    "saving": ("正在記錄閱讀頁碼…", "Recording reading page…"),
    "resuming": ("正在核對記錄頁…", "Checking recorded page…"),
    "empty": ("本原文尚無頁碼記錄。", "No recorded page for this original."),
    "recorded": ("已記錄第 {page} 頁 · 僅此原文", "Recorded page {page} · this original only"),
    "retained": (
        "頁碼有衝突；第 {page} 頁已保留。按「記住此頁」選用。",
        "Captured page {page} was retained after a conflict. Remember page to choose it.",
    ),
    "failed": ("頁碼核對／記錄失敗；請重試檢查。", "Page check/save failed; check again to retry."),
    "migration": (
        "此工作區需明確更新頁碼記錄格式；閱讀原文與草稿仍保留。",
        "This workspace needs an explicit reading-page schema update; "
        "reading and drafts remain available.",
    ),
    "witness": (
        "已載入的原文版本無法核對；請明確重新開啟此 PDF，再記錄頁碼。",
        "The loaded original version could not be verified. "
        "Reopen this PDF before recording a page.",
    ),
    "cancelled": ("已停止；請檢查目前記錄。", "Stopped; check the current recorded page."),
    "draft": (
        "請先處理未送出的問題或筆記，再前往記錄頁。",
        "Finish the question or note draft before resuming.",
    ),
    "unavailable": (
        "原文開啟並核對後才可記錄頁碼。",
        "Open and verify the original to record a page.",
    ),
    "coverage": (
        "只記錄本機實際翻頁或明確選用的頁碼；不會在開啟時自動跳頁。",
        "Records actual local page navigation or an explicit choice; "
        "never jumps automatically on open.",
    ),
}


def message(key, locale="zh-TW", **values):
    return MESSAGES[key][0 if locale == "zh-TW" else 1].format(**values)


_LIVE_WORKERS = set()


class _Worker(QThread):
    visit = Signal(object)

    def __init__(self, kind, data):
        super().__init__()
        self.kind, self.data = kind, data
        self.cancelled = Event()
        selected = data if kind in ("capture", "check") else data[0]
        self.database = (
            selected[0].owner.database if kind == "capture" else selected.highlight.owner.database
        )
        self.result, self.error = None, False
        self.exception = None

    def _cancelled(self):
        from paper_daily import store

        return self.cancelled.is_set() or Path(store.DB_PATH).absolute() != self.database

    def run(self):
        try:
            if self._cancelled():
                return
            if self.kind == "capture":
                highlight, witness = self.data
                view = operations.capture(highlight, cancelled=self._cancelled)
                if view is not None and (witness is None or view.original_version != witness):
                    raise operations.LoadedSourceChanged("The native loaded source changed")
                self.result = (view, operations.current(view)) if view else None
            elif self.kind == "check":
                view = operations.refresh(self.data)
                self.result = (view, json.loads(view.base_json))
            elif self.kind in ("remember", "observed"):
                view, page, evidence, previous = self.data
                if self.kind == "remember":
                    view = operations.refresh(view)
                    prepared = operations.prepare(view, page, method="entered")
                else:
                    if previous is not None:
                        evidence, satisfied = operations.follow_native(
                            evidence,
                            previous,
                            view,
                            with_status=True,
                        )
                        if satisfied:
                            # This exact current head already committed this
                            # source-bound page. Return its visible result/proof
                            # without creating another intent or retry receipt.
                            self.result = (view, previous.result, previous)
                            return
                    prepared = operations.prepare(
                        evidence.view,
                        page,
                        method="observed",
                        observation=evidence,
                    )
                committed = operations.save(prepared, cancelled=self._cancelled, with_proof=True)
                if committed is not None:
                    self.result = (operations.refresh(prepared.view), committed.result, committed)
            elif self.kind == "resume":
                view, expected = self.data

                def visit(page):
                    decision = {
                        "page": page,
                        "accepted": False,
                        "source_version": view.original_version,
                    }
                    self.visit.emit(decision)
                    return decision["accepted"]

                self.result = operations.navigate(
                    view,
                    expected,
                    visit,
                    cancelled=self._cancelled,
                )
        except Exception as exc:
            self.error = True
            self.exception = exc


def _release(worker):
    _LIVE_WORKERS.discard(worker)
    worker.deleteLater()


class ReadingPositionController(QObject):
    """One worker, one latest observation, one view epoch; no delayed auto-resume."""

    def __init__(self, reader, bar, *, locale="zh-TW", debounce_ms=500):
        super().__init__(reader)
        self.reader, self.locale = reader, locale
        self.view = self.suggestion = self._key = None
        self._epoch = 0
        self._thread = self._pending = self._previous = None
        self._paused = self._disposed = self._quiet = False
        self._schema_required = False
        self.observer = NativePositionObserver(reader.pdf)
        self.observer.observed.connect(self._observed)
        reader.pdf.source_changed.connect(self._source_changed)
        reader.destroyed.connect(self._destroyed)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(debounce_ms)
        self.timer.timeout.connect(self._flush)
        self.poll = QTimer(self)
        self.poll.setInterval(5000)
        self.poll.timeout.connect(
            lambda: self.check(quiet=True)
            if not self._paused and not self._schema_required
            else None
        )
        self.poll.start()
        self.remember_button = QPushButton(message("remember", locale))
        self.resume_button = QPushButton(message("resume", locale))
        self.check_button = QPushButton(message("check", locale))
        self.stop_button = QPushButton(message("stop", locale))
        self.status = QLabel(message("unavailable", locale))
        self.status.setWordWrap(True)
        self.status.setMaximumWidth(200)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setMinimumWidth(0)
        for button, callback in (
            (self.remember_button, self.remember),
            (self.resume_button, self.resume),
            (self.check_button, self.check),
            (self.stop_button, self.cancel),
        ):
            button.clicked.connect(callback)
            button.setToolTip(message("coverage", locale))
            bar.addWidget(button)
        bar.addWidget(self.status)
        self.remember_button.setShortcut("Alt+Shift+M")
        self.resume_button.setShortcut("Alt+Shift+R")
        self._update()

    @property
    def busy(self):
        return self._thread is not None

    def _context(self):
        """Pure GUI comparison; no SQL, filesystem reads, PDF hashing or parsing."""
        from paper_daily import store

        reader = self.reader
        if self._disposed or not isValid(reader):
            return None
        paper = getattr(reader, "paper", None)
        high = getattr(reader, "_highlight_view", None)
        if (
            paper is None
            or high is None
            or high.owner.paper_id != paper.id
            or high.fingerprint != getattr(reader, "_pdf_fingerprint", None)
            or high.document is not getattr(reader, "_active_document", None)
            or high.owner.database != Path(store.DB_PATH).absolute()
            or reader.pdf.position_identity()[1] != high.path
        ):
            return None
        return (
            id(paper),
            reader._qa_epoch,
            reader.pdf.position_identity(),
            high.owner._json,
            high.path,
            high.fingerprint,
            Path(store.DB_PATH).absolute(),
            reader.pdf.position_source_version(),
        )

    def _valid(self):
        return self._key is not None and self._context() == self._key

    def _draft(self):
        return bool(
            self.reader.ask_box.text().strip() or self.reader.note_edit.toPlainText().strip()
        )

    def _text(self, key, **values):
        self.status.setText(message(key, self.locale, **values))

    def _update(self):
        ready = self.view is not None and self._valid() and self.reader.pdf.isVisible()
        self.remember_button.setEnabled(ready and not self.busy)
        self.resume_button.setEnabled(ready and self.suggestion is not None and not self.busy)
        self.check_button.setEnabled(not self.busy and self._context() is not None)
        self.stop_button.setVisible(self.busy and not self._quiet)

    def invalidate(self):
        self._epoch += 1
        if self._thread:
            self._thread.cancelled.set()
        self.timer.stop()
        self.observer.clear()
        self.view = self.suggestion = self._key = self._pending = self._previous = None
        self._paused = False
        self._schema_required = False
        self._text("unavailable")
        self._update()

    def _source_changed(self):
        if self._disposed:
            return
        self.invalidate()
        QTimer.singleShot(0, self.bind)

    def bind(self):
        if self._disposed or self.busy:
            return False
        key = self._context()
        if key is None:
            self.invalidate()
            return False
        if key == self._key and self.view is not None:
            return True
        self._key = key
        if self.reader.pdf.position_source_version() is None:
            self._text("witness")
            return False
        return self._start(
            "capture", (self.reader._highlight_view, self.reader.pdf.position_source_version())
        )

    def _start(self, kind, data, *, quiet=False):
        if self.busy or not self._valid():
            return False
        self._quiet = quiet
        self._started_epoch = self._epoch
        self._started_key = self._key
        self._resume_draft = (self.reader.ask_box.text(), self.reader.note_edit.toPlainText())
        self._resume_page = self.reader.pdf.current_page()
        worker = _Worker(kind, data)
        self._thread = worker
        worker.visit.connect(self._visit, Qt.ConnectionType.BlockingQueuedConnection)
        worker.finished.connect(self._finished)
        worker.finished.connect(lambda: _release(worker))
        _LIVE_WORKERS.add(worker)
        if quiet:
            # The five-second background check must not touch the toolbar: a status
            # line that rewraps and a stop button that appears and vanishes resize
            # the row above the PDF, and the page visibly jumps every few seconds.
            worker.start()
            return True
        self._text(
            "resuming"
            if kind == "resume"
            else "saving"
            if kind in ("remember", "observed")
            else "checking"
        )
        self._update()
        worker.start()
        return True

    @Slot()
    def _finished(self):
        worker, self._thread = self._thread, None
        self._quiet = False
        if worker is None or self._disposed:
            return
        if self._epoch != self._started_epoch or self._context() != self._started_key:
            self.invalidate()
            QTimer.singleShot(0, self.bind)
            return
        if worker.cancelled.is_set():
            self._text("cancelled")
        elif worker.error:
            self._schema_required = isinstance(worker.exception, operations.PositionSchemaRequired)
            if isinstance(
                worker.exception,
                (operations.LoadedSourceChanged, operations.PositionSchemaRequired),
            ):
                self.view = self.suggestion = self._pending = None
                self.observer.clear()
            self._text(
                "migration"
                if self._schema_required
                else "witness"
                if isinstance(worker.exception, operations.LoadedSourceChanged)
                else "failed"
            )
        elif worker.kind in ("capture", "check") and worker.result:
            self._schema_required = False
            self.view, self.suggestion = worker.result
            self.observer.bind(self.view, self._key)
            self._show_suggestion()
        elif worker.kind in ("remember", "observed") and worker.result:
            self.view, result, self._previous = worker.result
            self.suggestion = json.loads(self.view.base_json)
            self.observer.bind(self.view, self._key)
            self._paused = result["status"] == "retained"
            if self._paused:
                self._text("retained", page=result["position"]["page"])
            else:
                self._show_suggestion()
        elif worker.kind == "resume":
            self._show_suggestion() if worker.result else self._text("cancelled")
        self._update()
        if self._pending is not None:
            self.timer.start()

    def _show_suggestion(self):
        self._text("recorded", page=self.suggestion["page"]) if self.suggestion else self._text(
            "empty"
        )

    def _observed(self, observation):
        if (
            self._paused
            or not self._valid()
            or observation.epoch != self._key
            or not self.reader.pdf.isVisible()
        ):
            return
        self._pending = observation
        self.timer.start()

    def _flush(self):
        if self.busy or self._pending is None:
            return
        observation, self._pending = self._pending, None
        if self.view is None or not self._valid():
            return
        self._start("observed", (self.view, observation.page, observation.evidence, self._previous))

    def remember(self):
        if self.busy or self.view is None or not self._valid() or not self.reader.pdf.isVisible():
            return False
        self.timer.stop()
        self._pending = None
        page = self.reader.pdf.current_page() + 1
        if self.suggestion and self.suggestion["page"] == page and not self._paused:
            self._show_suggestion()
            return False
        return self._start("remember", (self.view, page, None, None))

    def check(self, *, quiet=False):
        if self.busy or self._pending is not None or self.observer.pending_input:
            return False
        if self.view is None or not self._valid():
            return self.bind()
        return self._start("check", self.view, quiet=quiet)

    def resume(self):
        if self.busy or self._pending is not None or self.view is None or not self._valid():
            return False
        if self._draft():
            self._text("draft")
            return False
        if self.suggestion is None:
            return False
        return self._start("resume", (self.view, dict(self.suggestion)))

    @Slot(object)
    def _visit(self, decision):
        if (
            self._disposed
            or self._thread is None
            or self._thread.cancelled.is_set()
            or self._epoch != self._started_epoch
            or not self._valid()
            or self._draft()
            or not self.reader.pdf.isVisible()
            or self.reader.pdf.current_page() != self._resume_page
            or (self.reader.ask_box.text(), self.reader.note_edit.toPlainText())
            != self._resume_draft
        ):
            return
        self.observer.suppress()
        if decision.get("source_version") is not None:
            decision["accepted"] = self.reader.pdf.go_to_position(
                decision["page"],
                source_version=decision["source_version"],
            )
        self.observer.suppress()

    def cancel(self):
        self.timer.stop()
        self._pending = None
        if self._thread:
            self._thread.cancelled.set()
        self._text("cancelled")

    def request_close(self):
        if self.busy:
            self.cancel()
            return False
        return True

    def close(self):
        self.invalidate()
        self.poll.stop()
        self._disposed = True

    def _destroyed(self):
        self._disposed = True
        if self._thread:
            self._thread.cancelled.set()
