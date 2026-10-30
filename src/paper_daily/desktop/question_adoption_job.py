"""Local verification/publication without provider capture or Qt worker objects."""

import queue
import threading

from PySide6.QtCore import QObject, QTimer


class AdoptionRunner(QObject):
    """Poll plain-thread results on the owner thread; destruction detaches delivery.

    Publication threads are non-daemon so an accepted transaction is not abandoned
    on interpreter shutdown. The app also checks busy before close/restart. No Qt
    object or UI callback is held by the worker thread itself.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self._results = queue.Queue()
        self._done = self._failed = None
        self._poll = QTimer(self)
        self._poll.setInterval(25)
        self._poll.timeout.connect(self._receive)

    def start(self, call, done, failed):
        if self.busy:
            return False
        self.busy = True
        self._done, self._failed = done, failed
        results = self._results

        def run():
            try:
                value = call()
            except Exception as exc:
                results.put((False, str(exc)[:500] or type(exc).__name__))
            else:
                results.put((True, value))

        try:
            threading.Thread(target=run, name="question-source", daemon=False).start()
        except Exception as exc:
            self.busy = False
            self._done = self._failed = None
            failed(str(exc)[:500] or type(exc).__name__)
            return False
        self._poll.start()
        return True

    def _receive(self):
        try:
            success, value = self._results.get_nowait()
        except queue.Empty:
            return
        self._poll.stop()
        done, failed = self._done, self._failed
        self._done = self._failed = None
        self.busy = False
        (done if success else failed)(value)
