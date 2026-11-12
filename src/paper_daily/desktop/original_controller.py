"""Owned read-only original windows; subclasses provide distinct source authority.

This GUI lifecycle owns cancellation, delivery, reuse and close/drain only.
It cannot select a source or construct a backend permission on its own.
"""
from __future__ import annotations

import weakref

from PySide6.QtCore import QEvent, QObject, QTimer, Slot
from shiboken6 import isValid

from paper_daily.desktop.original_version import OriginalVersionDialog, ViewerWorker
from paper_daily.desktop.window_workspace import WindowWorkspace

_LIVE = set()
TEXT = {
    "en": {
        "checking": "Checking the cited original version…",
        "opened": "Opened the cited original read-only; the current PDF and drafts are preserved.",
        "page": "Opened the cited original at page {page}; passage matching is not verified.",
        "failed": "The cited original could not be verified. Check the saved source, then retry.",
        "changed": "Source context changed; the previous original read was cancelled.",
    },
    "zh-TW": {
        "checking": "正在核對引用的原文版本…",
        "opened": "已另開引用原文（唯讀）；目前 PDF 與編輯草稿保留原樣。",
        "page": "已另開引用原文第 {page} 頁；尚未核對到精確段落。",
        "failed": "無法核對引用的原文；請確認已儲存的來源，再重試。",
        "changed": "來源情境已改變，已取消先前的原文開啟工作。",
    },
}


def _released(worker):
    _LIVE.discard(worker)
    worker.deleteLater()


class OriginalController(QObject):
    def __init__(self, reader):
        super().__init__(reader)
        self._reader = weakref.ref(reader)
        self.owner = getattr(reader.win, "_workspace_owner", None) or WindowWorkspace.capture()
        self._worker = self._context = self.viewer = None
        self._disposed = False
        reader.installEventFilter(self)
        reader.destroyed.connect(self.dispose)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._poll)
        self.timer.start()


    @property
    def busy(self):
        return self._worker is not None or bool(self.viewer is not None and self.viewer.busy)


    def _text(self, key, **values):
        reader = self._reader()
        language = getattr(getattr(reader, "win", None), "language", "zh-TW")
        return TEXT.get(language, TEXT["en"])[key].format(**values)


    def _status(self, key, **values):
        reader = self._reader()
        if reader is not None and isValid(reader):
            reader.presentation_pane.status.setText(self._text(key, **values))


    @Slot()
    def _finished(self):
        self._complete(self.sender())

    def _complete(self, worker):
        # Keep Qt sender lookup in the non-overridden slot; subclass hooks get
        # explicit identities because overridden PySide slots can lose sender().
        if worker is not self._worker:
            return
        self._worker = None
        context = worker.context
        if not self._matches(context):
            return
        if worker.error or not worker.result:
            self._context = None
            self._status("failed")
            return
        snapshot, source = worker.result
        try:
            reader = self._reader()
            viewer = OriginalVersionDialog(
                snapshot,
                reader,
                current=lambda: self._matches(context),
                language=getattr(reader.win, "language", "zh-TW"),
                palette=reader.win.pal,
            )
            viewer.closed.connect(self._view_closed)
            self.viewer = viewer
            page = source.get("page")
            if type(page) is int and 1 <= page <= snapshot.pages:
                viewer.page.setValue(page)
                self._status("page", page=page)
            else:
                self._status("opened")
            viewer.show()
        except (OSError, ValueError, RuntimeError):
            self._context = None
            self._status("failed")


    @Slot()
    def _view_closed(self):
        self._closed_view(self.sender())

    def _closed_view(self, viewer):
        if viewer is self.viewer:
            self.viewer = None
        viewer.deleteLater()


    @Slot()
    def _poll(self):
        if self._context is not None and not self._matches(self._context):
            self.invalidate()
            self._status("changed")


    def invalidate(self):
        if self._context is not None:
            self._context.stop.set()
        self._context = None
        if self._worker is not None:
            self._worker.cancelled.set()
        if self.viewer is not None and not self.viewer.disposed:
            self.viewer.close()


    def request_close(self):
        self.invalidate()
        return not self.busy


    def dispose(self):
        self._disposed = True
        self.invalidate()


    def eventFilter(self, watched, event):
        if (
            watched is self._reader()
            and event.type() == QEvent.Type.Close
            and not self.request_close()
        ):
            event.ignore()
            return True
        return False


    def _matches(self, context):
        raise NotImplementedError("A source adapter must admit its own captured context")

    def _launch(self, context, prepare):
        worker = ViewerWorker(prepare, None)
        worker.context = context
        self._worker = worker
        _LIVE.add(worker)
        worker.finished.connect(self._finished)
        worker.finished.connect(lambda: _released(worker))
        worker.start()
