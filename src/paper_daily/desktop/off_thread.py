"""The slow part of filling the reader, done on a worker thread.

Opening a paper read its PDF's text, typeset its deep dive and its conversation and
matched its highlights to words, one after another on the window's thread: a third
of a second to a second and a half with the window frozen. The page now switches at
once and each part is filled in when it is ready.

Only the newest request of each kind is applied, so a paper left before its dive
was typeset never overwrites the next one. Every OffThread shares one worker, which
keeps the requests in order and never has two of them reading PDFs at once.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal

_POOL: ThreadPoolExecutor | None = None


def _pool() -> ThreadPoolExecutor:
    global _POOL
    if _POOL is None:
        _POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reader-prepare")
    return _POOL


class _Failed:
    def __init__(self, error: BaseException) -> None:
        self.error = error


class OffThread(QObject):
    _finished = Signal(str, int, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._latest: dict[str, int] = {}
        self._idle = threading.Event()
        self._idle.set()
        self._pending = 0
        self._lock = threading.Lock()
        self._finished.connect(self._deliver)

    def run(self, kind: str, work: Callable[[], object], apply: Callable[[object], None]) -> None:
        """Do `work()` on the worker, then `apply(result)` here, unless a newer
        request of the same kind came in meanwhile."""
        token = self.cancel(kind)
        with self._lock:
            self._pending += 1
            self._idle.clear()

        def job() -> None:
            try:
                if self._latest.get(kind) != token:
                    return
                try:
                    result = work()
                except Exception as exc:
                    # Raised again on the window's thread, where it would have been.
                    result = _Failed(exc)
                self._finished.emit(kind, token, (apply, result))
            finally:
                with self._lock:
                    self._pending -= 1
                    if not self._pending:
                        self._idle.set()

        _pool().submit(job)

    def cancel(self, kind: str) -> int:
        """Forget any request of this kind still under way; returns the new token."""
        token = self._latest.get(kind, 0) + 1
        self._latest[kind] = token
        return token

    def wait(self, timeout: float = 10.0) -> bool:
        """Block until the worker has finished everything asked of it (for tests and
        scripts); the results still arrive through the event loop."""
        return self._idle.wait(timeout)

    def _deliver(self, kind: str, token: int, packed) -> None:
        if self._latest.get(kind) != token:
            return
        apply, result = packed
        if isinstance(result, _Failed):
            raise result.error
        apply(result)


def warm_up() -> None:
    """Import, on a spare thread, what the first paper opened would otherwise wait
    for: PyMuPDF alone took a quarter to half a second."""

    def load() -> None:
        import pymupdf  # noqa: F401

        from paper_daily.desktop import rich_html

        rich_html.markdown("**warm**")

    threading.Thread(target=load, name="warm-up", daemon=True).start()
