"""Local control checkpoint, separate from SQLite; not an independent remote anchor."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager

from paper_daily import research_job_lock
from paper_daily.sync_device_management import PAIRING_COLUMNS
from paper_daily.sync_journal import SyncHistoryUnavailable

COLUMNS = {
    "sync_devices": ("token_hash", "workspace", "device", "revoked", "label"),
    "sync_pairings": PAIRING_COLUMNS,
}


def fingerprint(conn):
    """Stream every supported device/pairing field in a deterministic order."""
    digest = hashlib.sha256(b"paperfact.authority-control.v1")
    try:
        for table, columns in COLUMNS.items():
            actual = tuple(row[1] for row in conn.execute(f"PRAGMA table_info({table})"))
            if actual != columns:
                raise ValueError("Unsupported control schema")
            digest.update(json.dumps([table, columns], separators=(",", ":")).encode())
            query = f"SELECT {','.join(columns)} FROM {table} ORDER BY {columns[0]}"
            for row in conn.execute(query):
                raw = json.dumps(tuple(row), ensure_ascii=False, allow_nan=False,
                                 separators=(",", ":")).encode("utf-8")
                digest.update(len(raw).to_bytes(8, "big"))
                digest.update(raw)
    except (ValueError, TypeError, UnicodeError, sqlite3.Error) as error:
        raise SyncHistoryUnavailable("Authority control state needs recovery review") from error
    return digest.hexdigest()


@contextmanager
def transaction_lock(database):
    """Serialize cooperating control readers/writers without a SQLite write read-lock."""
    deadline = time.monotonic() + 10
    while True:
        with research_job_lock.claim(database, "authority-control", "authority") as owned:
            if owned:
                yield
                return
        if time.monotonic() >= deadline:
            raise TimeoutError("Authority control transaction is busy; retry")
        time.sleep(0.01)


def observe(conn, marker, database, identity):
    from paper_daily.sync_admin import marker_record

    record, pinned = marker_record(marker, database)
    if pinned != identity or record["control_sha256"] != fingerprint(conn):
        raise SyncHistoryUnavailable(
            "Authority control checkpoint differs; preserve state and review recovery")
    return record


def publish(marker, database, before, after):
    """Publish before SQLite commit; an interrupted mismatch must remain fail-closed."""
    from paper_daily.sync_admin import marker_record
    from paper_daily.sync_authority_backup import _sync_directory

    if marker_record(marker, database)[0] != before:
        raise SyncHistoryUnavailable("Authority control checkpoint changed during transaction")
    target = marker.with_name(marker.name + "." + secrets.token_hex(12) + ".pending")
    record = {**before, "control_sha256": after}
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(json.dumps(record, separators=(",", ":")).encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
    if marker_record(marker, database)[0] != before:
        raise SyncHistoryUnavailable("Authority control checkpoint changed before publication")
    os.replace(target, marker)
    _sync_directory(marker.parent)
