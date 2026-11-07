"""Remember window and view state without making the window wait for the database.

A write from the GUI thread waits for any other writer -- a PDF download, an
analysis -- to commit first, and that froze the window for over a second. View
state (the open list, a sort, a splitter) is queued here instead and written by
one background thread; the latest value per key wins. Reads see queued values,
and closing or restarting flushes the queue first.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from paper_daily import store

RETRY_SECONDS = 0.5
_lock = threading.Lock()
_write_lock = threading.Lock()
_wake = threading.Event()
_pending: dict[tuple[Path, str], object] = {}
_thread: threading.Thread | None = None


def save(key: str, value) -> None:
    global _thread
    # Bound to the database open now, so a later switch of workspace cannot
    # receive this one's view state.
    with _lock:
        _pending[(Path(store.DB_PATH), key)] = value
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_run, name="ui-state", daemon=True)
            _thread.start()
    _wake.set()


def read(conn, key: str, default=None):
    with _lock:
        queued = _pending.get((Path(store.DB_PATH), key), _pending)
    return store.get_kv(conn, key, default) if queued is _pending else queued


def flush() -> bool:
    """Write everything queued now, on the calling thread; whether all of it landed."""
    return _write()


def _run() -> None:
    while True:
        _wake.wait()
        _wake.clear()
        while not _write():
            if _wake.wait(RETRY_SECONDS):
                _wake.clear()


def _write() -> bool:
    # The worker and a close/restart flush must snapshot and commit in order.
    # Otherwise an older worker batch can commit AFTER flush's newer values.
    # Keep save/read on the separate lightweight lock so UI input stays responsive.
    with _write_lock:
        return _write_batch()


def _write_batch() -> bool:
    with _lock:
        batch = dict(_pending)
    ok = True
    for path in {path for path, _key in batch}:
        items = {key: value for (where, key), value in batch.items() if where == path}
        try:
            with store.connect(path=path, timeout=5) as conn:
                for key, value in items.items():
                    store.set_kv(conn, key, value)
        except (sqlite3.Error, OSError):
            ok = False
            continue
        with _lock:
            for key, value in items.items():
                if _pending.get((path, key), _pending) is value:
                    del _pending[(path, key)]
    return ok


def prefixed(conn, prefix: str) -> dict[str, object]:
    """Every stored and queued value whose key starts with `prefix`, by the rest."""
    found = {
        row[0][len(prefix) :]: json.loads(row[1])
        for row in conn.execute(
            "SELECT key, value FROM kv WHERE key >= ? AND key < ?", (prefix, prefix + "\U0010ffff")
        )
    }
    here = Path(store.DB_PATH)
    with _lock:
        queued = {
            key[len(prefix) :]: value
            for (path, key), value in _pending.items()
            if path == here and key.startswith(prefix)
        }
    return found | queued
