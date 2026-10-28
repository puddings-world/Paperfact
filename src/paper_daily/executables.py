"""Where a command-line program lives, without walking PATH on every question.

`shutil.which` stats every PATH folder for every PATHEXT suffix; on a Windows PATH
with forty folders that is 50-100 ms, and the window asks whenever a tab changes or
a settings dialog opens. An answer is kept for a while and, once old, still given
while a thread asks again, so only the first question for a program ever waits.
"""

from __future__ import annotations

import os
import shutil
import threading
import time

RECHECK = 30.0
_found: dict = {}
_rechecking: set = set()


def which(name: str, recheck: float | None = None) -> str | None:
    # The lookup itself and PATH are part of the key: a changed PATH, or a test's
    # stand-in for which, is asked again at once.
    key = (name, shutil.which, os.environ.get("PATH"))
    found = _found.get(key)
    if found is None:
        found = (time.monotonic(), shutil.which(name))
        for old in [k for k in _found if k[0] == name]:
            del _found[old]
        _found[key] = found
    elif (
        time.monotonic() - found[0] > (RECHECK if recheck is None else recheck)
        and key not in _rechecking
    ):
        _rechecking.add(key)
        threading.Thread(target=_ask_again, args=(key,), daemon=True).start()
    return found[1]


def _ask_again(key) -> None:
    name, lookup, _path = key
    try:
        answer = lookup(name)
        if key in _found:
            _found[key] = (time.monotonic(), answer)
    finally:
        _rechecking.discard(key)
