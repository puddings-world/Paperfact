"""Private transaction history for authority controls; not an external rollback anchor."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import UTC, datetime
from uuid import UUID, uuid4

from paper_daily.sync_journal import ID, SyncHistoryUnavailable

TABLE = "sync_control_history"
FORMAT = "paperfact.authority-control-event.v1"
MAX_RECORDS = 10_000
MAX_RECORD_BYTES = 8 * 1024**2
MAX_HISTORY_BYTES = 64 * 1024**2
MAX_STATE_ROWS = 10_000
MAX_STATE_BYTES = 8 * 1024**2
ZERO = "0" * 64
FIELDS = {"format", "authority_id", "sequence", "previous", "before", "after",
          "changes", "recorded_at"}


def _fail():
    raise SyncHistoryUnavailable("Authority control history needs recovery review")


def _encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


def _hash(value):
    return hashlib.sha256(_encode(value).encode("utf-8")).hexdigest()


def _columns():
    from paper_daily.sync_authority_control import COLUMNS

    return COLUMNS


def _empty():
    return {name: {} for name in _columns()}


def _hex(value):
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def _row(table, key, row):
    if (not _hex(key) or not isinstance(row, list) or len(row) != len(_columns()[table])
            or row[0] != key or not isinstance(row[1], str) or not ID.fullmatch(row[1])):
        _fail()
    if any(type(value) not in (str, int, float, type(None)) for value in row):
        _fail()
    if any(type(value) is float and not math.isfinite(value) for value in row):
        _fail()
    if table == "sync_devices":
        from paper_daily.sync_device_management import device_label

        if (not isinstance(row[2], str) or not ID.fullmatch(row[2])
                or type(row[3]) is not int or row[3] not in (0, 1)):
            _fail()
        device_label(row[4])
    else:
        if (row[2] is not None and not _hex(row[2])
                or type(row[3]) not in (int, float) or row[3] < 0
                or row[4] is not None and (not isinstance(row[4], str) or not ID.fullmatch(row[4]))
                or row[5] is not None and not _hex(row[5])
                or row[7] is not None and not isinstance(row[7], str)):
            _fail()
        from paper_daily.sync_device_management import device_label

        device_label(row[6])


def snapshot(conn):
    """Bounded actual control state, with no plaintext tokens or pairing codes."""
    state, count, used = _empty(), 0, 0
    try:
        for table, columns in _columns().items():
            if tuple(row[1] for row in conn.execute(f"PRAGMA table_info({table})")) != columns:
                _fail()
            size = "+".join(f"coalesce(length(CAST({column} AS BLOB)),0)" for column in columns)
            amount = conn.execute(f"SELECT count(*) FROM (SELECT 1 FROM {table} LIMIT ?)",
                                  (MAX_STATE_ROWS + 1,)).fetchone()[0]
            if amount + count > MAX_STATE_ROWS or conn.execute(
                    f"SELECT 1 FROM {table} WHERE ({size})>? LIMIT 1",
                    (MAX_STATE_BYTES,)).fetchone():
                _fail()
            query = f"SELECT {','.join(columns)} FROM {table} ORDER BY {columns[0]} LIMIT ?"
            for raw in conn.execute(query, (MAX_STATE_ROWS + 1,)):
                row = list(raw)
                _row(table, row[0], row)
                count += 1
                used += len(_encode(row).encode("utf-8"))
                if count > MAX_STATE_ROWS or used > MAX_STATE_BYTES or row[0] in state[table]:
                    _fail()
                state[table][row[0]] = row
    except (TypeError, ValueError, UnicodeError, sqlite3.Error) as error:
        raise SyncHistoryUnavailable("Authority control state needs recovery review") from error
    return state


def _changes(before, after):
    return [dict(table=table, key=key, before=before[table].get(key), after=after[table].get(key))
            for table in sorted(before)
            for key in sorted(before[table].keys() | after[table].keys())
            if before[table].get(key) != after[table].get(key)]


def _schema(conn):
    columns = tuple((row[1], row[5]) for row in conn.execute(f"PRAGMA table_info({TABLE})"))
    if columns != (("sequence", 1), ("record", 0), ("sha256", 0)):
        _fail()
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
                    (TABLE,)).fetchone():
        _fail()


def read(conn, *, check=lambda: None):
    """Verify the complete bounded chain and return its replayed private control state."""
    state, head, authority, sequence, used = _empty(), ZERO, None, 0, 0
    checking = False
    try:
        _schema(conn)
        query = (f"SELECT sequence,CASE WHEN length(CAST(record AS BLOB))<=? THEN record END,"
                 f"sha256 FROM {TABLE} ORDER BY sequence LIMIT ?")
        for number, raw, saved in conn.execute(query, (MAX_RECORD_BYTES, MAX_RECORDS + 1)):
            checking = True
            check()
            checking = False
            if type(number) is not int or number != sequence + 1 or number > MAX_RECORDS:
                _fail()
            if not isinstance(raw, str) or not _hex(saved):
                _fail()
            used += len(raw.encode("utf-8"))
            if used > MAX_HISTORY_BYTES:
                _fail()
            value = json.loads(raw)
            if (not isinstance(value, dict) or set(value) != FIELDS or _encode(value) != raw
                    or value["format"] != FORMAT or type(value["sequence"]) is not int
                    or value["sequence"] != number or value["previous"] != head
                    or value["before"] != _hash(state) or _hash(value) != saved):
                _fail()
            identity = value["authority_id"]
            if not isinstance(identity, str) or str(UUID(identity)) != identity:
                _fail()
            if authority is not None and identity != authority:
                _fail()
            stamp = datetime.fromisoformat(value["recorded_at"])
            if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
                _fail()
            changes = value["changes"]
            if not isinstance(changes, list) or (number > 1 and not changes):
                _fail()
            previous = None
            for item in changes:
                if not isinstance(item, dict) or set(item) != {"table", "key", "before", "after"}:
                    _fail()
                table, key = item["table"], item["key"]
                if table not in state or not _hex(key):
                    _fail()
                position = (table, key)
                if previous is not None and position <= previous:
                    _fail()
                previous = position
                if item["before"] is not None:
                    _row(table, key, item["before"])
                if item["before"] != state[table].get(key) or item["before"] == item["after"]:
                    _fail()
                if item["after"] is None:
                    del state[table][key]
                else:
                    _row(table, key, item["after"])
                    state[table][key] = item["after"]
            if _hash(state) != value["after"]:
                _fail()
            if sum(len(rows) for rows in state.values()) > MAX_STATE_ROWS:
                _fail()
            if len(_encode(state).encode("utf-8")) > MAX_STATE_BYTES:
                _fail()
            head, authority, sequence = saved, identity, number
        if sequence == 0:
            _fail()
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError,
            RecursionError, sqlite3.Error) as error:
        if checking:
            raise  # Preserve the caller's cancellation/deadline signal.
        if isinstance(error, sqlite3.Error):
            check()  # SQLite progress cancellation may surface as an interrupted query.
        raise SyncHistoryUnavailable("Authority control history needs recovery review") from error
    return dict(authority_id=authority, sequence=sequence, sha256=head, state=state)


def _append(conn, before, after, authority, sequence, previous):
    if not conn.in_transaction or sequence > MAX_RECORDS:
        _fail()
    value = dict(format=FORMAT, authority_id=authority, sequence=sequence, previous=previous,
                 before=_hash(before), after=_hash(after), changes=_changes(before, after),
                 recorded_at=datetime.now(UTC).isoformat(timespec="microseconds"))
    raw = _encode(value)
    if len(raw.encode("utf-8")) > MAX_RECORD_BYTES:
        _fail()
    # The transaction's final fingerprint validates total bytes and the full chain.
    conn.execute(f"INSERT INTO {TABLE}(sequence,record,sha256) VALUES(?,?,?)",
                 (sequence, raw, _hash(value)))


def initialize(conn):
    """Explicit fresh-authority baseline; never migrate or replace an existing journal."""
    if not conn.in_transaction:
        _fail()
    current = snapshot(conn)
    conn.execute(f"CREATE TABLE {TABLE}(sequence INTEGER PRIMARY KEY,"
                 "record TEXT NOT NULL,sha256 TEXT NOT NULL)")
    _append(conn, _empty(), current, str(uuid4()), 1, ZERO)
    read(conn)


def append(conn, before):
    """Record actual control deltas in the caller's same mutation transaction."""
    history = read(conn)
    if history != before:
        _fail()  # A writer cannot replace the prefix it observed at transaction entry.
    after = snapshot(conn)
    if before["state"] != after:
        _append(conn, before["state"], after, history["authority_id"], history["sequence"] + 1,
                history["sha256"])


def validate_checkpoint(value):
    if (not isinstance(value, dict) or set(value) != {"authority_id", "sequence", "sha256"}
            or not isinstance(value["authority_id"], str)
            or type(value["sequence"]) is not int or not 1 <= value["sequence"] <= MAX_RECORDS
            or not _hex(value["sha256"])):
        _fail()
    try:
        if str(UUID(value["authority_id"])) != value["authority_id"]:
            _fail()
    except (ValueError, AttributeError):
        _fail()
    return dict(value)


def checkpoint(conn, expected=None):
    checked = read(conn)
    point = {key: checked[key] for key in ("authority_id", "sequence", "sha256")}
    if expected is not None:
        expected = validate_checkpoint(expected)
        row = conn.execute(f"SELECT sha256 FROM {TABLE} WHERE sequence=?",
                           (expected["sequence"],)).fetchone()
        if (point["authority_id"] != expected["authority_id"] or row is None
                or row[0] != expected["sha256"]):
            raise SyncHistoryUnavailable("Observed authority control history is unavailable")
    return point
