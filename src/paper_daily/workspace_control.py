"""Small device-local authority knowledge, separate from replicated research."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing

from paper_daily.sync_authority_history import validate_checkpoint
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_journal import SyncHistoryUnavailable, _identifier
from paper_daily.workspace_service import _read, _tables

FORMAT = "paperfact.device-control-knowledge.v1"
MAX_BYTES = 2048


class ControlKnowledge:
    """Retain an authenticated prefix with compare-and-swap, never credentials."""

    def __init__(self, path, identity, live):
        self.path, self.live = path, live
        _identifier(identity["workspace_id"])
        _identifier(identity["device_id"])
        self.workspace, self.device = identity["workspace_id"], identity["device_id"]
        scope = json.dumps([self.workspace, self.device], separators=(",", ":"))
        self.key = "ui.sync.control." + hashlib.sha256(scope.encode()).hexdigest()

    def _read(self, conn):
        if "kv" not in _tables(conn):
            return None
        row = conn.execute(
            "SELECT CASE WHEN length(CAST(value AS BLOB))<=? THEN value END "
            "FROM kv WHERE key=?", (MAX_BYTES, self.key),
        ).fetchone()
        if row is None:
            return None
        try:
            from paper_daily.sync_http import _decode

            if not isinstance(row[0], str):
                raise ValueError("Invalid control metadata")
            value = _decode(row[0].encode("utf-8"))
            if (not isinstance(value, dict)
                    or set(value) != {"format", "workspace", "device", "checkpoint"}
                    or value["format"] != FORMAT or value["workspace"] != self.workspace
                    or value["device"] != self.device):
                raise ValueError("Wrong control scope")
            return validate_checkpoint(value["checkpoint"])
        except (TypeError, ValueError, UnicodeError) as error:
            raise SyncHistoryUnavailable("Local authority control knowledge is invalid") from error

    def load(self):
        self.live()
        with _read(self.path) as conn:
            point = self._read(conn)
        self.live()
        return point

    def remember(self, point, previous):
        point = validate_checkpoint(point)
        if previous is not None:
            previous = validate_checkpoint(previous)
        self.live()
        with closing(sqlite3.connect(
            self.path.resolve().as_uri() + "?mode=rw", uri=True,
            timeout=2, factory=CaptureConnection,
        )) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                self.live()
                current = self._read(conn)
                if current not in (previous, point):
                    raise SyncHistoryUnavailable("Local authority control knowledge advanced")
                if current is not None and (
                    point["authority_id"] != current["authority_id"]
                    or point["sequence"] < current["sequence"]
                    or point["sequence"] == current["sequence"] and point != current
                ):
                    raise SyncHistoryUnavailable("Local authority control history moved backwards")
                value = json.dumps(dict(format=FORMAT, workspace=self.workspace,
                                       device=self.device, checkpoint=point), separators=(",", ":"))
                conn.execute(
                    "INSERT INTO kv(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (self.key, value),
                )
                self.live()
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        self.live()


def bind_control(transport, path, identity, live):
    """Use explicit type capabilities; dynamic proxy fallbacks are not support."""
    knowledge = ControlKnowledge(path, identity, live)
    binder = getattr(type(transport), "bind_control_checkpoint", None)
    if binder is None:
        if knowledge.load() is not None:
            raise SyncHistoryUnavailable("Transport removed authority control continuity")
        return
    binder(transport, knowledge.load, knowledge.remember, identity)
