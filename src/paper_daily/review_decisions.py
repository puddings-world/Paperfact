"""Local decision metadata, independent of application or synchronization authority."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import file_change, sync_capture
from paper_daily.sync_legacy_sources import path as safe_path

_SEAL = object()


def _keys(origin, identity):
    from paper_daily.research_review import TABLES

    if (
        not isinstance(origin, str)
        or origin not in {*TABLES, "sidecar", "compound_sidecar", "archived_draft"}
        or not isinstance(identity, str)
        or not 1 <= len(identity) <= 4096
        or "\0" in identity
    ):
        raise ValueError("Use a bounded original review item identity")
    keys = [(origin, identity)]
    if origin in {"generation", "sidecar", "remote"}:
        keys.extend(
            (kind, origin + ":" + identity) for kind in ("claim_resume", "highlight_resume")
        )
    elif origin == "archived_draft":
        keys.extend(
            (kind, identity)
            for kind in (
                "claim_resume",
                "highlight_resume",
                "archived_resume",
                "archived_note_resume",
            )
        )
    return keys


def latest_in(conn, origin, identity):
    """Last local decision for the original item, including its typed continuation."""
    keys = _keys(origin, identity)
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='research_review_receipts'"
    ).fetchone():
        return None
    conditions = " OR ".join("(origin=? AND origin_id=?)" for _ in keys)
    row = conn.execute(
        "SELECT decision FROM research_review_receipts WHERE "
        + conditions
        + " ORDER BY rowid DESC LIMIT 1",
        tuple(value for key in keys for value in key),
    ).fetchone()
    return row[0] if row is not None and row[0] in {"applied", "kept"} else None


def _fence(path):
    result = []
    for entry in (path, Path(str(path) + "-wal")):
        safe_path(entry)
        observed = file_change.version(entry) if entry.exists() else None
        # SQLite may create/touch a zero-byte WAL while opening/closing a read.
        # It contains no frames. Keep the database's full native version, and
        # every nonempty WAL's full version; either committed-data change revokes.
        if entry != path and observed is not None and observed[2] == 0:
            observed = None
        result.append((str(entry), observed))
    return tuple(result)


@dataclass(frozen=True, init=False)
class DecisionSnapshot:
    service: object = field(repr=False)
    key: tuple[str, str]
    decision: str | None
    fence: tuple = field(repr=False)
    binding: tuple | None = field(repr=False)
    session: str = field(repr=False)
    _seal: object = field(repr=False)

    def __reduce__(self):
        raise TypeError("Decision snapshots are process-only display metadata")


def capture(service, origin, identity):
    """Worker read; never initialize schema, inspect PDFs, write, or grant Apply."""
    _keys(origin, identity)
    binding = None if service.binding is None else tuple(sorted(service.binding.items()))
    session = service.session
    with closing(
        sqlite3.connect(
            service.path.as_uri() + "?mode=ro",
            uri=True,
            factory=sync_capture.CaptureConnection,
            timeout=0.025,
        )
    ) as conn:
        conn.row_factory = sqlite3.Row
        service._check(conn)
        # Opening a read-only SQLite connection can create an empty WAL. Observe
        # after that setup, before reading decision rows; retain the full native
        # database/WAL fence through close and GUI delivery.
        fence = _fence(service.path)
        conn.execute("BEGIN")
        service._check(conn)
        service._record(conn, origin, identity)
        decision = latest_in(conn, origin, identity)
        service._check(conn)
    if fence != _fence(service.path):
        raise ValueError("Decision metadata changed during inspection")
    result = object.__new__(DecisionSnapshot)
    for key, value in dict(
        service=service,
        key=(origin, identity),
        decision=decision,
        fence=fence,
        binding=binding,
        session=session,
        _seal=_SEAL,
    ).items():
        object.__setattr__(result, key, value)
    if not current(result):
        raise ValueError("Decision workspace changed before display")
    return result


def current(snapshot):
    """GUI admission uses native observations only; no SQL or hashing."""
    if (
        not isinstance(snapshot, DecisionSnapshot)
        or getattr(snapshot, "_seal", None) is not _SEAL
        or snapshot.service.closed
        or snapshot.session != snapshot.service.session
        or snapshot.binding
        != (
            None
            if snapshot.service.binding is None
            else tuple(sorted(snapshot.service.binding.items()))
        )
    ):
        return False
    try:
        from paper_daily.research_generation import _identity

        return (
            _identity(snapshot.service.path) == snapshot.service.identity
            and _fence(snapshot.service.path) == snapshot.fence
        )
    except (OSError, ValueError):
        return False
