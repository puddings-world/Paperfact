"""Fetch a paper's PDF in the background, for the paper being looked at.

`prefetch` walks the queue in order, which is the wrong shape for a reader that
jumps around: following a lineage link or pressing 下一篇 past the buffer lands on a
paper nobody prefetched, and telling someone to go and run a terminal command is not
an answer a desktop app gets to give.

The download is a few seconds of blocking network and PDF parsing, so it runs on a
worker thread and the pane redraws when it lands.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from paper_daily.fetch import prepare
from paper_daily.store import connect


class _FetchWorker(QObject):
    finished = Signal(str, bool)  # paper id, whether a PDF arrived

    def __init__(self, paper_id: str) -> None:
        super().__init__()
        self._paper_id = paper_id

    def run(self) -> None:
        try:
            with connect() as conn:
                row = conn.execute(
                    "SELECT * FROM papers WHERE id = ?", (self._paper_id,)
                ).fetchone()
            path, _text = prepare(row) if row else (None, None)
        except Exception:
            path = None
        self.finished.emit(self._paper_id, path is not None)


class FetchRunner(QObject):
    """One download in flight at a time, owning its thread.

    A QObject for the same reason AskRunner is one: a callback with no thread
    affinity would be delivered on the worker thread, and anything it touches in the
    window would then be drawn from outside the GUI thread.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _FetchWorker | None = None
        self._paper_id: str | None = None
        self._on_done = None

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def fetching(self, paper_id: str) -> bool:
        return self.busy and self._paper_id == paper_id

    def start(self, paper_id: str, on_done) -> bool:
        """Begin fetching, or return False if another fetch is already running."""
        if self.busy:
            return False
        if self._thread is not None:
            self._thread.wait()
        self._paper_id = paper_id
        self._on_done = on_done
        self._thread = QThread()
        self._worker = _FetchWorker(paper_id)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._deliver)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()
        return True

    @Slot(str, bool)
    def _deliver(self, paper_id: str, ok: bool) -> None:
        if self._on_done:
            self._on_done(paper_id, ok)
