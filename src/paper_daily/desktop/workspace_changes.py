"""Observe committed changes only in the database this watcher was created for."""

import sqlite3
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from shiboken6 import isValid

from paper_daily import store


def _file_identity(path):
    try:
        info = path.stat()
        return (info.st_dev, info.st_ino) if info.st_ino else None
    except OSError:
        return None


class _ReaderLifetime:
    """Own the executor independently of the QObject while an admitted read drains."""

    def __init__(self, reader):
        self.reader = reader
        self.closed = threading.Event()
        self.drained = threading.Event()
        self.drained.set()
        self.lock = threading.Lock()
        self.active = False
        self.future = None

    def begin(self):
        with self.lock:
            if self.closed.is_set() or self.active:
                return False
            self.active = True
            self.future = None
            self.drained.clear()
            return True

    def attach(self, future):
        with self.lock:
            self.future = future
            closed = self.closed.is_set()
        if future.cancelled() or (closed and future.cancel()):
            self.complete()

    def complete(self):
        self.drained.set()
        with self.lock:
            if self.closed.is_set():
                self.active = False
                self.future = None

    def delivered(self):
        with self.lock:
            self.active = False
            self.future = None

    def close(self, *_):
        with self.lock:
            first = not self.closed.is_set()
            self.closed.set()
            future = self.future
        if future is not None and future.cancel():
            self.complete()
        if first:
            self.reader.shutdown(wait=False, cancel_futures=True)
        if self.drained.is_set():
            self.delivered()
        return self.drained.is_set()


class WorkspaceChanges(QObject):
    changed = Signal()
    _read = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._database = Path(store.DB_PATH).resolve()
        self._database_identity = _file_identity(self._database)
        # Preserve the maintenance reader: one bounded, persistent worker.
        self._reader = ThreadPoolExecutor(max_workers=1, thread_name_prefix="workspace-revision")
        self._lifetime = _ReaderLifetime(self._reader)
        self.destroyed.connect(self._lifetime.close)
        self.revision = self._revision()
        self._read.connect(self._apply, Qt.ConnectionType.QueuedConnection)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.poll_in_background)
        self.timer.start()

    @property
    def _reading(self):
        return self._lifetime.active

    @property
    def disposed(self):
        return self._lifetime.closed.is_set()

    def _current(self):
        if self.disposed or self._database_identity is None:
            return False
        try:
            return (
                Path(store.DB_PATH).resolve() == self._database
                and _file_identity(self._database) == self._database_identity
            )
        except (OSError, TypeError, ValueError):
            return False

    def _revision(self):
        if not self._current():
            return None
        database = self._database
        try:
            # Short read-only access; never follow the process-global path.
            conn = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0.025)
            try:
                revision = conn.execute(
                    "SELECT revision,(SELECT COALESCE(MAX(id),0) FROM integration_changes) "
                    "FROM workspace_revision WHERE id=1"
                ).fetchone()
                return (str(database), *revision) if revision else None
            finally:
                conn.close()
        except (sqlite3.Error, OSError):
            return None

    def poll_in_background(self):
        lifetime = self._lifetime
        if not self._current() or not lifetime.begin():
            return
        revision = self._revision  # Keep the existing no-argument testing seam.
        owner = weakref.ref(self)

        def read():
            value = None
            try:
                if not lifetime.closed.is_set():
                    value = revision()
            except Exception:
                # A transient observer failure is retried by a later explicit poll.
                pass
            finally:
                lifetime.complete()
            if lifetime.closed.is_set():
                return
            watcher = owner()
            if watcher is None or not isValid(watcher):
                lifetime.close()
                return
            try:
                watcher._read.emit(value)
            except RuntimeError:
                lifetime.close()

        try:
            future = self._reader.submit(read)
        except Exception:
            lifetime.complete()
            lifetime.delivered()
            return
        lifetime.attach(future)

    @Slot(object)
    def _apply(self, revision):
        self._lifetime.delivered()
        if not self._current() or revision is None:
            return
        if revision[0] != str(self._database):
            return
        if revision != self.revision:
            self.revision = revision
            self.changed.emit()

    def poll(self):
        lifetime = self._lifetime
        if not self._current() or not lifetime.begin():
            return
        revision = None
        try:
            revision = self._revision()
        except Exception:
            pass
        finally:
            lifetime.complete()
        self._apply(revision)

    def close(self):
        drained = self._lifetime.close()
        if isValid(self) and isValid(self.timer):
            self.timer.stop()
        return drained

    dispose = close
