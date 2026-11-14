"""Bounded local reindex of already accepted native history; no transport or AI."""

from __future__ import annotations

import json
import threading
import time
from contextlib import closing

from paper_daily import lineage_dependencies, lineage_projection
from paper_daily import research_generation as generation
from paper_daily.sync_client import validate_event
from paper_daily.sync_journal import MAX_BYTES
from paper_daily.workspace_service import (
    Ticket,
    WorkspaceChanged,
    _binding,
    _read,
    _safe_path,
    _tables,
)

TABLE = "paperfact_sync_lineage_history_scan"
COLUMNS = "id workspace device database_identity sequence"
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS " + TABLE + "(id INTEGER PRIMARY KEY CHECK(id=1),"
    "workspace TEXT NOT NULL,device TEXT NOT NULL,database_identity TEXT NOT NULL,"
    "sequence INTEGER NOT NULL CHECK(sequence>=0))"
)
MAX_EVENTS = 128
MAX_EVENT_BYTES = 2 * MAX_BYTES + 8192
MAX_BATCH_BYTES = 4 * 1024**2


class _BatchTicket(Ticket):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    def check(self):
        self.parent.check()
        super().check()

    def publish(self, action):
        # Keep cancellation available after previous durable batches.
        with self.parent._lock:
            self.parent.check()
            super().publish(action)


def _state_in(conn, workspace, device, identity):
    cursor = conn.execute("SELECT sequence FROM paperfact_sync_cursor WHERE id=1").fetchone()
    if cursor is None:
        raise ValueError("Received history cursor is unavailable")
    target = cursor[0]
    kind = conn.execute("SELECT type FROM sqlite_master WHERE name=?", (TABLE,)).fetchone()
    through = 0
    if kind is not None:
        if (
            kind[0] != "table"
            or [r[1] for r in conn.execute("PRAGMA table_info(" + TABLE + ")")] != COLUMNS.split()
        ):
            raise ValueError("History scan metadata has an unsupported schema")
        rows = conn.execute("SELECT * FROM " + TABLE + " LIMIT 2").fetchall()
        if len(rows) > 1:
            raise ValueError("History scan metadata has multiple owners")
        if rows:
            row = rows[0]
            if row[0] != 1 or type(row[4]) is not int or row[4] < 0:
                raise ValueError("History scan checkpoint is invalid")
            if tuple(row[1:4]) == (
                workspace,
                device,
                json.dumps(identity),
            ):
                through = row[4]
    if type(target) is not int or not 0 <= through <= target:
        raise ValueError("History scan checkpoint is ahead of received history")
    return dict(
        through=through,
        target=target,
        remaining=target - through,
        more=through < target,
        restored=0,
        scanned=0,
    )


def _pending_in(conn):
    journal = conn.execute(
        "SELECT workspace,device FROM paperfact_sync_identity WHERE id=1"
    ).fetchone()
    bound = conn.execute("SELECT workspace,origin FROM research_sync_binding WHERE id=1").fetchone()
    if journal is None or bound is None or tuple(journal) != tuple(bound):
        raise ValueError("History scan bindings disagree")
    return _state_in(conn, *journal, generation._identity(generation._path(conn)))["more"]


class HistoryRepair:
    def __init__(self, client, *, current_path=None, expected_identity=None, current=lambda: True):
        self.client = client
        self.path = _safe_path(client.journal.path)
        self.identity = generation._identity(self.path)
        if expected_identity is not None and list(expected_identity) != self.identity:
            raise WorkspaceChanged("The history repair database was replaced")
        self.current_path = current_path or (lambda: self.path)
        self.current = current
        self._running = threading.Lock()
        with _read(self.path) as conn:
            client.journal._binding(conn)
            self.binding = _binding(conn, _tables(conn))
            expected = (client.journal.workspace_id, client.journal.device_id)
            if any(value != expected for _table, value in self.binding):
                raise WorkspaceChanged("History repair bindings disagree")
            bound = conn.execute(
                "SELECT workspace,origin FROM research_sync_binding WHERE id=1"
            ).fetchone()
            if (
                client.projection_writer is None
                or bound is None
                or tuple(bound)
                != (
                    client.journal.workspace_id,
                    client.journal.device_id,
                )
            ):
                raise ValueError("History repair requires its explicit native research projector")
            self._check(conn)

    def _check(self, conn):
        live = getattr(self.client.journal, "live", None)
        if live is not None:
            live()
        if (
            not self.current()
            or _safe_path(self.current_path()) != self.path
            or generation._identity(self.path) != self.identity
        ):
            raise WorkspaceChanged("The history repair workspace changed")
        self.client.journal._binding(conn)
        if _binding(conn, _tables(conn)) != self.binding:
            raise WorkspaceChanged("The history repair research binding changed")

    def _state(self, conn):
        self._check(conn)
        return _state_in(
            conn, self.client.journal.workspace_id, self.client.journal.device_id, self.identity
        )

    def status(self):
        with _read(self.path) as conn:
            return self._state(conn)

    def step(self, ticket=None, *, limit=64):
        if type(limit) is not int or not 1 <= limit <= MAX_EVENTS:
            raise ValueError("History repair scans 1 to 128 events per step")
        if not self._running.acquire(blocking=False):
            raise ValueError("This history repair is already running")
        ticket = ticket or Ticket()
        try:
            with closing(self.client.journal._connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    ticket.check()
                    state = self._state(conn)
                    through, size, restored, scanned = state["through"], 0, 0, 0
                    with closing(
                        conn.execute(
                            "SELECT sequence,CASE WHEN length(CAST(event AS BLOB))<=? "
                            "THEN event END,"
                            "outcome FROM paperfact_sync_inbox WHERE sequence>? AND sequence<=? "
                            "ORDER BY sequence LIMIT ?",
                            (MAX_EVENT_BYTES, through, state["target"], limit),
                        )
                    ) as rows:
                        for sequence, encoded, outcome in rows:
                            ticket.check()
                            self._check(conn)
                            if encoded is None:
                                raise ValueError("A received history event exceeds its byte budget")
                            count = len(encoded.encode("utf-8"))
                            if scanned and size + count > MAX_BATCH_BYTES:
                                break
                            if sequence != through + 1:
                                raise ValueError("Received history has a sequence gap")
                            event = json.loads(encoded)
                            validate_event(event, self.client.journal.workspace_id)
                            if event["sequence"] != sequence or event["outcome"] != outcome:
                                raise ValueError(
                                    "Received history columns disagree with their event"
                                )
                            receipt = conn.execute(
                                "SELECT event FROM paperfact_sync_graph_receipts "
                                "WHERE operation_id=?",
                                (event["operation"]["operation_id"],),
                            ).fetchone()
                            if receipt is None or json.loads(receipt[0]) != event:
                                raise ValueError("Received history lacks its exact graph receipt")
                            if outcome == "accepted" and lineage_dependencies.requires_readiness(
                                event["operation"]
                            ):
                                restored += int(
                                    lineage_projection._retain_received_in(conn, self.client, event)
                                )
                            through, scanned, size = sequence, scanned + 1, size + count
                    if not scanned and through < state["target"]:
                        raise ValueError("Received history is missing its next event")
                    if scanned:
                        conn.execute(SCHEMA)
                        conn.execute(
                            "INSERT INTO " + TABLE + " VALUES(1,?,?,?,?) "
                            "ON CONFLICT(id) DO UPDATE SET workspace=excluded.workspace,"
                            "device=excluded.device,database_identity=excluded.database_identity,"
                            "sequence=excluded.sequence",
                            (
                                self.client.journal.workspace_id,
                                self.client.journal.device_id,
                                json.dumps(self.identity),
                                through,
                            ),
                        )
                    ticket.check()
                    self._check(conn)
                    ticket.publish(conn.commit)
                    return dict(
                        through=through,
                        target=state["target"],
                        remaining=state["target"] - through,
                        more=through < state["target"],
                        scanned=scanned,
                        restored=restored,
                    )
                except BaseException:
                    conn.rollback()
                    raise
        finally:
            self._running.release()

    def drain(
        self, ticket=None, progress=lambda _value: None, *, max_steps=16, seconds=3, limit=64
    ):
        if (
            type(max_steps) is not int
            or not 1 <= max_steps <= 100
            or isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not 0 < seconds <= 20
        ):
            raise ValueError("Invalid history repair work budget")
        ticket = ticket or Ticket()
        started, scanned, restored = time.monotonic(), 0, 0
        for _ in range(max_steps):
            # Each durable batch has its own publication/cancellation arbitration.
            # A caller's canceled ticket still stops subsequent batches.
            ticket.check()
            batch = _BatchTicket(ticket)
            result = self.step(batch, limit=limit)
            scanned += result["scanned"]
            restored += result["restored"]
            progress(
                {**result, "stage": "history_reindex", "scanned": scanned, "restored": restored}
            )
            if not result["more"] or time.monotonic() - started >= seconds:
                break
        return {**result, "scanned": scanned, "restored": restored}
