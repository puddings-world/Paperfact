"""Poll a small revision counter; never reload a reader or steal focus."""

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
                return conn.execute(
                    "SELECT COALESCE(MAX(id),0) FROM integration_changes"
                ).fetchone()[0]
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
