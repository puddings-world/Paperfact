"""Find what freezes the window: sample the GUI thread's stack while it is stuck.

A timer on the GUI thread beats every 50 ms; a watcher thread notices when the beats
stop and records where the GUI thread is meanwhile. Only code locations are written
(module, function, line), never paper text, notes or settings, to a bounded local
file. The common stack across a stall's samples names the slow step.

Qt's own work (layout, text shaping, painting) has no Python frame, so each stall
also records its context from a fixed vocabulary: whether the app was in front, how
long it had been open, how many widgets existed, and which window-system events
came just before (a screen waking up, fonts or colours changing, a resize). That
tells a relayout after waking from an accumulation over a long session.
"""

from __future__ import annotations

import sys
import threading
import time
from collections import Counter, deque
from datetime import datetime
from pathlib import Path

THRESHOLD = 0.25
SAMPLE_EVERY = 0.02
BEAT_EVERY_MS = 50
LIMIT = 512 * 1024
DEPTH = 14
RECENT_SECONDS = 10.0
COUNT_WIDGETS_EVERY_MS = 60_000
EVENTS = frozenset(
    {
        "app-active",
        "app-inactive",
        "app-hidden",
        "app-suspended",
        "screen-added",
        "screen-removed",
        "screen-changed",
        "fonts-changed",
        "colors-changed",
        "window-resized",
        "window-state",
    }
)
STATES = frozenset({"active", "inactive", "hidden", "suspended", "unknown"})


def _where(frame, prefix: str = "paper_daily") -> tuple[str, ...]:
    """Innermost-first locations: the frame actually running, then app frames."""
    found = []
    innermost = True
    while frame is not None and len(found) < DEPTH:
        module = frame.f_globals.get("__name__", "?")
        if innermost or module.startswith(prefix):
            name = getattr(frame.f_code, "co_qualname", frame.f_code.co_name)
            found.append(f"{module}:{name}:{frame.f_lineno}")
        innermost = False
        frame = frame.f_back
    return tuple(found)


class Watchdog:
    def __init__(
        self,
        path: Path,
        *,
        thread_id: int | None = None,
        clock=time.monotonic,
        prefix="paper_daily",
    ):
        self.path = Path(path)
        self.prefix = prefix
        self.thread_id = thread_id or threading.main_thread().ident
        self.clock = clock
        self.beat = clock()
        self.samples: Counter[tuple[str, ...]] = Counter()
        self.stall_started = None
        self.opened = clock()
        self.state = "unknown"
        self.widgets: int | None = None
        self.recent: deque[tuple[float, str]] = deque(maxlen=16)
        self.stopped = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ui-stall-watch", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.stopped.set()

    def heartbeat(self) -> None:
        self.beat = self.clock()

    def note(self, event: str) -> None:
        """Remember a window-system event (one of EVENTS) for the next stall."""
        if event in EVENTS:
            self.recent.append((self.clock(), event))
            if event.startswith("app-"):
                self.state = event[4:]

    def context(self) -> str:
        start = self.stall_started if self.stall_started is not None else self.clock()
        before = [
            f"{event}@-{start - at:.1f}s"
            for at, event in list(self.recent)
            if 0 <= start - at <= RECENT_SECONDS
        ]
        parts = [
            f"state={self.state}",
            f"open={(start - self.opened) / 3600:.1f}h",
            f"widgets={self.widgets if self.widgets is not None else '?'}",
            f"before={','.join(before) or '-'}",
        ]
        return "  context " + " ".join(parts)

    def check(self) -> None:
        """One watcher step; separate from the loop so tests can drive it."""
        now = self.clock()
        if now - self.beat < THRESHOLD:
            if self.samples:
                self._write(self.beat - self.stall_started)
            return
        if self.stall_started is None:
            self.stall_started = self.beat
        frame = sys._current_frames().get(self.thread_id)
        if frame is not None:
            self.samples[_where(frame, self.prefix)] += 1

    def _run(self) -> None:
        while not self.stopped.wait(SAMPLE_EVERY):
            self.check()

    def _write(self, seconds: float) -> None:
        stack, hits = self.samples.most_common(1)[0]
        total = sum(self.samples.values())
        context = self.context()
        self.samples.clear()
        self.stall_started = None
        lines = [
            f"{datetime.now().isoformat(timespec='seconds')} stall {seconds * 1000:.0f} ms "
            f"(stack in {hits}/{total} samples)",
            *(f"  {where}" for where in stack),
            context,
            "",
        ]
        try:
            if self.path.exists() and self.path.stat().st_size > LIMIT:
                self.path.replace(self.path.with_name(self.path.name + ".1"))
            with self.path.open("a", encoding="utf-8") as log:
                log.write("\n".join(lines) + "\n")
        except OSError:
            pass


def _follow_window_system(watchdog: Watchdog, app, parent) -> None:
    from PySide6.QtCore import QEvent, QObject, Qt, QTimer

    states = {
        Qt.ApplicationState.ApplicationActive: "active",
        Qt.ApplicationState.ApplicationInactive: "inactive",
        Qt.ApplicationState.ApplicationHidden: "hidden",
        Qt.ApplicationState.ApplicationSuspended: "suspended",
    }
    watchdog.state = states.get(app.applicationState(), "unknown")
    app.applicationStateChanged.connect(
        lambda state: watchdog.note("app-" + states.get(state, "unknown"))
    )

    def follow(screen) -> None:
        for signal in (screen.geometryChanged, screen.logicalDotsPerInchChanged):
            signal.connect(lambda *_: watchdog.note("screen-changed"))

    for screen in app.screens():
        follow(screen)
    app.screenAdded.connect(lambda screen: (watchdog.note("screen-added"), follow(screen)))
    app.screenRemoved.connect(lambda _screen: watchdog.note("screen-removed"))
    app.primaryScreenChanged.connect(lambda _screen: watchdog.note("screen-changed"))
    app.fontDatabaseChanged.connect(lambda: watchdog.note("fonts-changed"))
    app.styleHints().colorSchemeChanged.connect(lambda _scheme: watchdog.note("colors-changed"))

    def count() -> None:
        watchdog.widgets = len(app.allWidgets())

    count()
    counter = QTimer(parent)
    counter.setInterval(COUNT_WIDGETS_EVERY_MS)
    counter.timeout.connect(count)
    counter.start()
    watchdog.counter = counter
    if parent is None:
        return

    class Resizes(QObject):
        # A drag-resize sends dozens of events a second; one note per second is
        # enough to place it before a stall.
        last = None

        def eventFilter(self, watched, event):  # noqa: N802
            if event.type() == QEvent.Type.Resize:
                now = watchdog.clock()
                if self.last is None or now - self.last >= 1.0:
                    self.last = now
                    watchdog.note("window-resized")
            elif event.type() == QEvent.Type.WindowStateChange:
                watchdog.note("window-state")
            return False

    watchdog.resizes = Resizes(parent)
    parent.installEventFilter(watchdog.resizes)


def install(directory: Path, parent=None) -> Watchdog:
    """Start watching the calling (GUI) thread; the timer lives as long as `parent`."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    watchdog = Watchdog(Path(directory) / "ui-stalls.log")
    timer = QTimer(parent)
    timer.setInterval(BEAT_EVERY_MS)
    timer.timeout.connect(watchdog.heartbeat)
    timer.start()
    watchdog.timer = timer
    app = QApplication.instance()
    if app is not None:
        _follow_window_system(watchdog, app, parent)
    watchdog.start()
    return watchdog
