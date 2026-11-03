"""Let a window nobody is using go quiet, and catch up when it is used again.

A window left open all day kept waking for checks nobody was looking at: the
workspace revision, the nightly result, updates, the reading position, the freeze
watcher's heartbeat. After the window has been in the background for a while
those timers stop; bringing it forward starts them again and runs each catch-up
once, so what is on screen is current by the time it is read. Work someone
started (analysis, downloads, a question) is not paused: its own timers are not
handed to this.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer, Signal
from shiboken6 import isValid

IDLE_MINUTES = 5


class Dormancy(QObject):
    slept = Signal()
    woke = Signal()
    activated = Signal()

    def __init__(self, window, idle_ms: int = IDLE_MINUTES * 60 * 1000):
        super().__init__(window)
        self.asleep = False
        self._timers = []
        self._paused = []
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(idle_ms)
        self._idle.timeout.connect(self._sleep)
        window.installEventFilter(self)
        if not window.isActiveWindow():
            self._idle.start()

    def pause_with(self, timer, catch_up=None) -> None:
        """Stop `timer` while asleep; on waking restart it and call `catch_up` once."""
        self._timers.append((timer, catch_up))

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.WindowDeactivate:
            self._idle.start()
        elif kind == QEvent.Type.WindowActivate:
            self._idle.stop()
            self._wake()
            self.activated.emit()
        return False

    def _sleep(self) -> None:
        self.asleep = True
        self._paused = []
        for timer, catch_up in self._timers:
            if isValid(timer) and timer.isActive():
                timer.stop()
                self._paused.append((timer, catch_up))
        self.slept.emit()

    def _wake(self) -> None:
        if not self.asleep:
            return
        self.asleep = False
        paused, self._paused = self._paused, []
        for timer, catch_up in paused:
            if isValid(timer):
                timer.start()
                if catch_up is not None:
                    catch_up()
        self.woke.emit()


def keys_home(window) -> None:
    """Give the keys back to the page on screen when the window returns with them on
    a button, a notice or nowhere: list keys only act while the list has them, so
    after a click on a notice they seemed dead until the list was clicked."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractButton, QApplication

    focus = QApplication.focusWidget()
    if (focus is not None and focus.window() is window
            and not isinstance(focus, QAbstractButton)
            and focus.focusPolicy() != Qt.FocusPolicy.NoFocus
            and not getattr(focus, "_keys_elsewhere", False)):
        return
    page = window.stack.currentWidget()
    target = getattr(page, "view", None) or page
    target.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
