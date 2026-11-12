"""Bounded PATH discovery for display, never account/login or execution authority.

Adapted from maintenance: old answers return while a bounded worker refreshes.
Lookup implementation, PATH, PATHEXT and working directory all scope an answer;
late refreshes cannot replace an answer for a different environment. Callers that
actually execute a program must still resolve/validate their execution boundary.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from collections import OrderedDict

RECHECK = 30.0
MAX_CACHED = 64
MAX_REFRESHES = 4
_found: OrderedDict[tuple, tuple[float, str | None]] = OrderedDict()
_rechecking: set[tuple] = set()
_lock = threading.Lock()


def _key(name):
    return (name, shutil.which, os.environ.get("PATH"), os.environ.get("PATHEXT"), os.getcwd())


def _remember(key, answer):
    for old in [value for value in _found if value[0] == key[0] and value != key]:
        del _found[old]
    _found[key] = (time.monotonic(), answer)
    _found.move_to_end(key)
    while len(_found) > MAX_CACHED:
        _found.popitem(last=False)


def which(name: str, recheck: float | None = None) -> str | None:
    """Display discovery: first lookup is synchronous; expired answers stay usable.

    This does not cache login state or promise a later invocation will succeed.
    Concurrent cold callers may each perform the same harmless filesystem lookup.
    Refreshes are single-flight per context and capped across all names.
    """
    key = _key(name)
    refresh = False
    with _lock:
        found = _found.get(key)
        if found is not None:
            _found.move_to_end(key)
            if (
                time.monotonic() - found[0] > (RECHECK if recheck is None else recheck)
                and key not in _rechecking
                and len(_rechecking) < MAX_REFRESHES
            ):
                _rechecking.add(key)
                refresh = True
    if found is None:
        answer = key[1](name)
        with _lock:
            if _key(name) == key:
                _remember(key, answer)
        return answer
    if refresh:
        try:
            threading.Thread(
                target=_ask_again, args=(key,), name="executable-refresh", daemon=True
            ).start()
        except RuntimeError:
            with _lock:
                _rechecking.discard(key)
    return found[1]


def _ask_again(key):
    try:
        answer = key[1](key[0])
        with _lock:
            if key in _found and _key(key[0]) == key:
                _remember(key, answer)
    except OSError:
        pass  # Discovery failure keeps the last observation; it never authorizes execution.
    finally:
        with _lock:
            _rechecking.discard(key)

def refresh(name: str) -> str | None:
    """Ask again now, on the caller's thread, and keep the answer for this context.

    For an explicit "look again" (settings opened, a start that failed); display
    callers keep using `which`, which never waits on a stale entry."""
    key = _key(name)
    answer = key[1](name)
    with _lock:
        if _key(name) == key:
            _remember(key, answer)
    return answer
