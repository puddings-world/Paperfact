"""Observe committed workspace changes from all writers without reloading editors."""

import sqlite3

from PySide6.QtCore import QObject, QTimer, Signal

from paper_daily import store


class WorkspaceChanges(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.revision = self._revision()
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.poll)
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

    def poll(self):
        revision = self._revision()
        if revision is None:
            return
        if revision != self.revision:
            self.revision = revision
            self.changed.emit()
