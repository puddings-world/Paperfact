"""Find what freezes the window: sample the GUI thread's stack while it is stuck.

A timer on the GUI thread beats every 50 ms; a watcher thread notices when the beats
stop and records where the GUI thread is meanwhile. Only code locations are written
(module, function, line), never paper text, notes or settings, to a bounded local
file. The common stack across a stall's samples names the slow step.
"""

from __future__ import annotations

import sys
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

THRESHOLD = 0.25
SAMPLE_EVERY = 0.02
BEAT_EVERY_MS = 50
LIMIT = 512 * 1024
DEPTH = 14


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
        self.stopped = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ui-stall-watch", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.stopped.set()

    def heartbeat(self) -> None:
        self.beat = self.clock()

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
        self.samples.clear()
        self.stall_started = None
        lines = [
            f"{datetime.now().isoformat(timespec='seconds')} stall {seconds * 1000:.0f} ms "
            f"(stack in {hits}/{total} samples)",
            *(f"  {where}" for where in stack),
            "",
        ]
        try:
            if self.path.exists() and self.path.stat().st_size > LIMIT:
                self.path.replace(self.path.with_name(self.path.name + ".1"))
            with self.path.open("a", encoding="utf-8") as log:
                log.write("\n".join(lines) + "\n")
        except OSError:
            pass


def install(directory: Path, parent=None) -> Watchdog:
    """Start watching the calling (GUI) thread; the timer lives as long as `parent`."""
    from PySide6.QtCore import QTimer

    watchdog = Watchdog(Path(directory) / "ui-stalls.log")
    timer = QTimer(parent)
    timer.setInterval(BEAT_EVERY_MS)
    timer.timeout.connect(watchdog.heartbeat)
    timer.start()
    watchdog.timer = timer
    watchdog.start()
    return watchdog
