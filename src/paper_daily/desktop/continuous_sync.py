"""Explicit, process-local continuous sync; never remembers credentials or consent."""

import time

from PySide6.QtCore import QEvent, QObject, QTimer, Signal, Slot

COPY = {
    "en": {
        "off": "Automatic sync off", "waiting": "Waiting to sync",
        "working": "Syncing", "idle": "Automatic sync on",
        "offline": "Offline; local changes retained", "paused": "Sync paused; reconnect or retry",
        "changed": "Connection changed; enable sync again", "closing": "Stopping sync",
    },
    "zh-TW": {
        "off": "自動同步已關閉", "waiting": "等待同步", "working": "同步中",
        "idle": "自動同步已開啟", "offline": "離線；本機變更已保留",
        "paused": "同步已暫停；請重新連線或重試", "changed": "連線已變更；請重新開啟同步",
        "closing": "正在停止同步",
    },
}


class ContinuousSync(QObject):
    changed = Signal(object)
    settled = Signal()

    def __init__(self, session, parent=None, *, blocked=lambda: False,
                 clock=time.monotonic, poll_seconds=30, debounce_seconds=2):
        super().__init__(parent)
        if not 1 <= poll_seconds <= 300 or not 0 < debounce_seconds <= poll_seconds:
            raise ValueError("Invalid continuous sync intervals")
        self.session, self.blocked, self.clock = session, blocked, clock
        self.poll_seconds, self.debounce_seconds = poll_seconds, debounce_seconds
        self.enabled, self.state = False, "off"
        self.worker = None
        self._epoch = None
        self._next = 0
        self._failures = 0
        self._dirty = False
        self._closing = False
        self._result = None
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        if parent is not None:
            parent.installEventFilter(self)

    @property
    def busy(self):
        return self.worker is not None

    def summary(self):
        return {"enabled": self.enabled, "state": self.state, "busy": self.busy,
                "retry_in": max(0, int(self._next - self.clock())) if self.enabled else None,
                "result": dict(self._result) if self._result else None}

    def _report(self, state):
        self.state = state
        self.changed.emit(self.summary())

    def enable(self):
        """Called only for the user's explicit toggle, after connection verification."""
        if self._closing or not self.session.summary()["authenticated"]:
            return False
        if self.enabled:
            return True
        if self.busy:
            return False
        self.enabled, self._epoch = True, self.session.generation
        self._result = None
        self.timer.start()
        self._next, self._failures = self.clock(), 0
        self._report("waiting")
        return True

    def stop(self):
        self.enabled = False
        self._epoch = None
        if self.worker is not None:
            self.worker.ticket.cancel()
        self._report("off")

    @Slot()
    def local_changed(self):
        if not self.enabled:
            return
        self._dirty = True
        # Never postpone an existing due poll, or defeat an offline retry backoff.
        if not self._failures:
            self._next = min(self._next, self.clock() + self.debounce_seconds)
            if not self.busy:
                self._report("waiting")

    @Slot()
    def tick(self):
        if not self.enabled or self._closing:
            return
        if (self.session.generation != self._epoch
                or not self.session.summary()["authenticated"]):
            self.stop()
            self._report("changed")
            return
        if self.busy or self.session.busy or self.clock() < self._next or self.blocked():
            return
        from paper_daily.desktop.sync_connection_dialog import SyncWorker

        self._dirty = False
        self.worker = SyncWorker(self.session.sync, self)
        self.worker.finished.connect(self._finished)
        self._report("working")
        self.worker.start()

    @Slot()
    def _finished(self):
        worker, self.worker = self.worker, None
        if worker is None:
            return
        current = (self.enabled and self._epoch == self.session.generation
                   and self.session.summary()["authenticated"] and not worker.ticket.cancelled)
        if self.enabled and worker.error == "authorization" and not worker.ticket.cancelled:
            self.enabled = False
            self._report("paused")
        elif current:
            if worker.error == "offline":
                self._failures += 1
                self._next = self.clock() + min(300, 10 * 2 ** min(self._failures - 1, 5))
                self._report("offline")
            elif worker.error:
                self.enabled = False
                self._report("paused")
            else:
                self._failures = 0
                result = worker.result
                self._result = {key: result[key] for key in (
                    "pushed", "received", "pending", "awaiting_receipts", "conflicts")}
                more = (not result["caught_up"] or bool(result["pending"])
                        or bool(result["awaiting_receipts"]))
                self._next = self.clock() + (
                    self.debounce_seconds if self._dirty or more else self.poll_seconds)
                self._report("waiting" if more else "idle")
        elif self.enabled:
            self.stop()
            self._report("changed")
        worker.deleteLater()
        self.settled.emit()
        if self._closing and self.parent() is not None:
            QTimer.singleShot(0, self.parent().close)

    def eventFilter(self, obj, event):
        if obj is self.parent() and event.type() == QEvent.Type.Close:
            self._closing = self.busy
            self.stop()
            self.timer.stop()
            if self.busy:
                self._report("closing")
                event.ignore()
                return True
        return False


def controller_for(owner, session, *, blocked=lambda: False):
    """Reuse the owner window's single controller; a new session needs new consent."""
    existing = getattr(owner, "_continuous_sync", None)
    if existing is not None and existing.session is session:
        return existing
    if existing is not None:
        existing.stop()
        if existing.busy:
            raise RuntimeError("Previous workspace sync is stopping")
        existing.timer.stop()
        owner.removeEventFilter(existing)
        existing.deleteLater()
    controller = ContinuousSync(session, owner, blocked=blocked)
    owner._continuous_sync = controller
    changes = getattr(owner, "workspace_changes", None)
    if changes is not None:
        changes.changed.connect(controller.local_changed)
    button = getattr(owner, "sync_status_btn", None)
    if button is not None:
        def display(value):
            copy = COPY["zh-TW"]
            button.setText(copy[value["state"]])
            result = value["result"]
            text = copy[value["state"]]
            if result:
                text += (f"；上次同步：待送 {result['pending']}，"
                         f"待確認 {result['awaiting_receipts']}，衝突 {result['conflicts']}")
            button.setToolTip(text)
        controller.changed.connect(display)
        display(controller.summary())
    return controller
