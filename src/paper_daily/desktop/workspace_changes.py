"""Observe committed workspace changes from all writers without reloading editors."""

import sqlite3
import threading
from contextlib import suppress

from PySide6.QtCore import QObject, QTimer, Signal

from paper_daily import store


class WorkspaceChanges(QObject):
    changed = Signal()
    _read = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.revision = self._revision()
        self._reading = False
        self._read.connect(self._apply)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.poll_in_background)
        self.timer.start()

    def _revision(self):
        try:
            # Short read-only access: no 30-second write-lock wait on the GUI thread.
            conn = sqlite3.connect(
                store.DB_PATH.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.025
            )
            try:
                revision = conn.execute(
                    "SELECT revision,(SELECT COALESCE(MAX(id),0) FROM integration_changes) "
                    "FROM workspace_revision WHERE id=1"
                ).fetchone()
                return (str(store.DB_PATH.resolve()), *revision) if revision else None
            finally:
                conn.close()
        except (sqlite3.Error, OSError):
            return None

    def poll_in_background(self):
        # Opening a large database can wait on the disk; done on the GUI thread
        # every two seconds it froze the window for up to half a second.
        if self._reading:
            return
        self._reading = True

        def read():
            revision = self._revision()
            # The window may close while this read runs; then there is no one to tell.
            with suppress(RuntimeError):
                self._read.emit(revision)

        threading.Thread(target=read, name="workspace-revision", daemon=True).start()

    def _apply(self, revision):
        self._reading = False
        if revision is None:
            return
        if revision != self.revision:
            self.revision = revision
            self.changed.emit()

    def poll(self):
        self._apply(self._revision())
