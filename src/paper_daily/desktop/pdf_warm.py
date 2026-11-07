"""Read a paper's PDF before it is opened, so opening it does not wait on the disk.

QPdfDocument.load reads the whole file on the window's thread: two thirds of a second
for a few-megabyte paper still on a cold disk, a twentieth once the system has it
cached. Pointing at a paper in the list reads its file on a worker, so by the click
it is in the cache. Only the paper pointed at last waits its turn: sweeping the
pointer down the list does not queue up every row it crossed.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path

CHUNK = 1 << 20
REMEMBERED = 64

_lock = threading.Lock()
_next: Path | None = None
_reading = False
_done: OrderedDict[Path, None] = OrderedDict()


def warm(path: Path) -> None:
    global _next, _reading
    with _lock:
        if path in _done:
            return
        _next = path
        if _reading:
            return
        _reading = True
    threading.Thread(target=_drain, name="pdf-warm", daemon=True).start()


def _drain() -> None:
    global _next, _reading
    while True:
        with _lock:
            path, _next = _next, None
            if path is None:
                _reading = False
                return
        try:
            with open(path, "rb") as pdf:
                while pdf.read(CHUNK):
                    pass
        except OSError:
            continue
        with _lock:
            _done[path] = None
            while len(_done) > REMEMBERED:
                _done.popitem(last=False)


def idle(timeout: float = 5.0) -> bool:
    """Whether the reads asked for have finished (for tests)."""
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        with _lock:
            if not _reading:
                return True
        time.sleep(0.005)
    return False
