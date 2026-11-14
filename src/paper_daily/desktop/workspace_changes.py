"""Observe committed changes only in the database this watcher was created for."""

import sqlite3
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from shiboken6 import isValid

from paper_daily import store, sync_capture


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


def _outbox_clock(conn, previous=None):
    """Journal-owned operations only; receiving/acknowledging never appends here."""
    names = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('paperfact_sync_identity','paperfact_sync_operations',"
        "'paperfact_sync_cursor')"
    )}
    if not {"paperfact_sync_identity", "paperfact_sync_operations"} <= names:
        return None
    identity = conn.execute(
        "SELECT workspace,device FROM paperfact_sync_identity WHERE id=1"
    ).fetchone()
    if identity is None:
        return None
    sequence = conn.execute(
        "SELECT COALESCE(MAX(sequence),0) FROM paperfact_sync_operations"
    ).fetchone()[0]
    needed = False
    if previous is not None and tuple(identity) == previous[:2] and sequence > previous[2]:
        row = (conn.execute("SELECT sequence FROM paperfact_sync_cursor WHERE id=1").fetchone()
               if "paperfact_sync_cursor" in names else None)
        cursor = row[0] if row is not None else 0
        # Inspect only appended rows, not the workspace's entire retained history.
        needed = conn.execute(
            "SELECT 1 FROM paperfact_sync_operations WHERE sequence>? "
            "AND (server_revision IS NULL OR server_revision>?) LIMIT 1",
            (previous[2], cursor),
        ).fetchone() is not None
    return (*identity, sequence, needed)


class WorkspaceChanges(QObject):
    changed = Signal()
    local_operations = Signal()
    research = Signal(object)
    _read = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._database = Path(store.DB_PATH).resolve()
        self._database_identity = _file_identity(self._database)
        # Preserve the maintenance reader: one bounded, persistent worker.
        self._reader = ThreadPoolExecutor(max_workers=1, thread_name_prefix="workspace-revision")
        self._lifetime = _ReaderLifetime(self._reader)
        self.destroyed.connect(self._lifetime.close)
        self._research_request = None
        initial = self._revision()
        self.revision = initial[:3] if initial is not None else None
        self._outbox = initial[4] if initial is not None and len(initial) == 5 else None
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

    def watch_research(self, owner, token=None):
        """Observe only the actual loaded paper; no new worker or schema migration."""
        if owner is None:
            self._research_request = None
            return
        from paper_daily.manual_highlight_ops import HighlightOwner

        if not isinstance(owner, HighlightOwner) or owner.database != self._database:
            raise ValueError("Research observation belongs to another workspace")
        self._research_request = (owner, token)

    def _revision(self):
        if not self._current():
            return None
        database = self._database
        try:
            # Short read-only access; never follow the process-global path.
            request = self._research_request
            conn = sqlite3.connect(
                database.as_uri() + "?mode=ro", uri=True, timeout=0.025,
                factory=(
                    sync_capture.CaptureConnection if request is not None else sqlite3.Connection
                ),
            )
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("BEGIN")
                revision = conn.execute(
                    "SELECT revision,(SELECT COALESCE(MAX(id),0) FROM integration_changes) "
                    "FROM workspace_revision WHERE id=1"
                ).fetchone()
                if revision is None:
                    return None
                result = (str(database), *revision)
                research = None
                if request is not None:
                    from paper_daily.reading_change_inputs import read

                    owner, token = request
                    try:
                        signatures = read(conn, owner)
                        research = (token, owner.paper_id, signatures)
                    except (ValueError, sqlite3.Error):
                        # One stale reader cannot prevent other research from syncing.
                        pass
                outbox = _outbox_clock(conn, getattr(self, "_outbox", None))
                if outbox is not None:
                    return (*result, research, outbox)
                return (*result, research) if research is not None else result
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
        if len(revision) >= 4 and revision[3] is not None and self._research_request is not None:
            token, paper_id, signatures = revision[3]
            owner, current_token = self._research_request
            if token == current_token and paper_id == owner.paper_id:
                self.research.emit(dict(token=token, paper_id=paper_id, signatures=signatures))
        if not self._current():
            return
        if len(revision) == 5:
            marker = revision[4]
            if self._outbox is None:
                self._outbox = marker
            elif marker[:2] == self._outbox[:2] and marker[2] > self._outbox[2]:
                self._outbox = marker
                if marker[3]:
                    self.local_operations.emit()
        if not self._current():
            return
        base = revision[:3]
        if base != self.revision:
            self.revision = base
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
