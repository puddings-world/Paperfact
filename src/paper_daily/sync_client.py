"""Explicit-path sync client experiment; no automatic app or network integration."""

from __future__ import annotations

import json
import threading
from uuid import uuid4

from paper_daily.sync_journal import ID, Journal, canonical_operation


def validate_event(event, workspace_id):
    if not isinstance(event, dict) or set(event) != {"sequence", "outcome", "operation", "head"}:
        raise ValueError("Invalid sync event")
    sequence = event["sequence"]
    if type(sequence) is not int or sequence < 1:
        raise ValueError("Invalid event sequence")
    if event["outcome"] not in ("accepted", "conflict"):
        raise ValueError("Invalid event outcome")
    operation = json.loads(canonical_operation(event["operation"]))
    if operation["workspace_id"] != workspace_id:
        raise ValueError("Event belongs to another workspace")
    head = event["head"]
    if not isinstance(head, dict) or set(head) != {"revision", "operation"}:
        raise ValueError("Invalid entity head")
    revision = head["revision"]
    if type(revision) is not int or not 0 <= revision <= sequence:
        raise ValueError("Invalid entity revision")
    if revision == 0:
        if head["operation"] is not None:
            raise ValueError("An absent head cannot contain an operation")
    else:
        canonical_operation(head["operation"])
        for key in ("workspace_id", "entity_type", "entity_id"):
            if head["operation"][key] != operation[key]:
                raise ValueError("Head belongs to another research entity")
    if event["outcome"] == "accepted":
        if revision != sequence or head["operation"] != operation:
            raise ValueError("Accepted event must identify its new head")
    elif revision >= sequence:
        raise ValueError("A conflict cannot replace its canonical head")
    return json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class SyncClient:
    """Transactional receive/cursor and retryable push through a supplied transport.

    The transport owns authentication. Research writers are trusted local callbacks.
    Neither credentials nor model calls are stored or executed by this client.
    """

    def __init__(self, journal: Journal, writer):
        self.journal = journal
        self.writer = writer
        self._running = threading.Lock()
        conn = journal._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            journal._binding(conn)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS paperfact_sync_cursor "
                "(id INTEGER PRIMARY KEY CHECK(id=1), sequence INTEGER NOT NULL)"
            )
            conn.execute("INSERT OR IGNORE INTO paperfact_sync_cursor VALUES(1,0)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS paperfact_sync_inbox "
                "(sequence INTEGER PRIMARY KEY, event TEXT NOT NULL, outcome TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS paperfact_sync_heads "
                "(entity_type TEXT,entity_id TEXT,revision INTEGER NOT NULL,operation TEXT,"
                "applied_revision INTEGER NOT NULL DEFAULT -1,"
                "PRIMARY KEY(entity_type,entity_id))"
            )
            has_conflict_index = (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='paperfact_sync_conflicts'"
                ).fetchone()
                is not None
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS paperfact_sync_conflicts "
                "(operation_id TEXT PRIMARY KEY,sequence INTEGER NOT NULL UNIQUE,resolved_by TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS research_resolution_intents "
                "(operation_id TEXT PRIMARY KEY,conflict_sequence INTEGER NOT NULL,"
                "request TEXT NOT NULL,operation TEXT NOT NULL)"
            )
            if not has_conflict_index:
                # Upgrade the private prototype once; receive maintains this index in
                # its cursor transaction. Ordinary restart must not scan full history.
                for row in conn.execute("SELECT event FROM paperfact_sync_inbox ORDER BY sequence"):
                    self._record_conflict_state(conn, json.loads(row[0]))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def new_operation(self, kind, entity_id, payload, *, action="put", operation_id=None):
        """Build once and retain the returned envelope when retrying a local action."""
        conn = self.journal._connect()
        try:
            conn.execute("BEGIN")
            self.journal._binding(conn)
            head = conn.execute(
                "SELECT revision FROM paperfact_sync_heads WHERE entity_type=? AND entity_id=?",
                (kind, entity_id),
            ).fetchone()
            previous = conn.execute(
                "SELECT operation_id FROM paperfact_sync_operations "
                "WHERE entity_type=? AND entity_id=? AND (server_revision IS NULL "
                "OR server_revision>(SELECT sequence FROM paperfact_sync_cursor WHERE id=1)) "
                "ORDER BY sequence DESC LIMIT 1",
                (kind, entity_id),
            ).fetchone()
            value = {
                "version": 1,
                "operation_id": operation_id or str(uuid4()),
                "workspace_id": self.journal.workspace_id,
                "device_id": self.journal.device_id,
                "entity_type": kind,
                "entity_id": entity_id,
                "action": action,
                "base_revision": head[0] if head else 0,
                "depends_on": previous[0] if previous else None,
                "payload": payload,
            }
            return json.loads(canonical_operation(value))
        finally:
            conn.close()

    def save(self, operation):
        return self.journal.apply(operation, self.writer)

    def resolve_conflict(self, sequence, *, choice="incoming", payload=None, operation_id=None):
        """Save an explicit resolution; acceptance in the event stream closes the conflict.

        Retain operation_id for caller retries. Repeated pending requests without an ID
        reuse their existing intent. Outstanding edits must sync before resolution.
        """
        if type(sequence) is not int or sequence < 1:
            raise ValueError("Invalid conflict sequence")
        if choice not in ("incoming", "canonical"):
            raise ValueError("Invalid resolution choice")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("Resolution payload must be an object")
        if operation_id is not None and (
            not isinstance(operation_id, str) or not ID.fullmatch(operation_id)
        ):
            raise ValueError("Invalid resolution operation ID")
        try:
            request = json.dumps(
                {"sequence": sequence, "choice": choice, "payload": payload},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid resolution payload") from exc
        conn = self.journal._connect()
        try:
            conn.execute("BEGIN")
            self.journal._binding(conn)
            previous = None
            if operation_id is not None:
                previous = conn.execute(
                    "SELECT request,operation FROM research_resolution_intents "
                    "WHERE operation_id=?",
                    (operation_id,),
                ).fetchone()
            if previous is None:
                previous = conn.execute(
                    "SELECT i.request,i.operation FROM research_resolution_intents i "
                    "JOIN paperfact_sync_operations o ON o.operation_id=i.operation_id "
                    "WHERE i.conflict_sequence=? AND (o.server_revision IS NULL OR "
                    "o.server_revision>(SELECT sequence FROM paperfact_sync_cursor WHERE id=1)) "
                    "ORDER BY o.sequence DESC LIMIT 1",
                    (sequence,),
                ).fetchone()
                if previous and operation_id is not None:
                    raise ValueError("A resolution is already pending for this conflict")
            if previous:
                if previous["request"] != request:
                    raise ValueError("Resolution retry changed its choice or payload")
                operation = json.loads(previous["operation"])
            else:
                target = conn.execute(
                    "SELECT i.event,c.resolved_by FROM paperfact_sync_inbox i "
                    "JOIN paperfact_sync_conflicts c ON c.sequence=i.sequence WHERE i.sequence=?",
                    (sequence,),
                ).fetchone()
                if target is None:
                    raise ValueError("Unknown conflict sequence")
                if target["resolved_by"] is not None:
                    raise ValueError("Conflict is already resolved")
                conflict = json.loads(target["event"])["operation"]
                key = (conflict["entity_type"], conflict["entity_id"])
                head = conn.execute(
                    "SELECT revision,operation FROM paperfact_sync_heads "
                    "WHERE entity_type=? AND entity_id=?",
                    key,
                ).fetchone()
                if self._outstanding(conn, key):
                    raise ValueError("Synchronize outstanding edits before resolving this conflict")
                source = (
                    conflict
                    if choice == "incoming"
                    else (json.loads(head["operation"]) if head["operation"] else None)
                )
                operation = {
                    "version": 1,
                    "operation_id": operation_id if operation_id is not None else str(uuid4()),
                    "workspace_id": self.journal.workspace_id,
                    "device_id": self.journal.device_id,
                    "entity_type": key[0],
                    "entity_id": key[1],
                    "action": source["action"] if source else "delete",
                    "base_revision": head["revision"],
                    "depends_on": None,
                    "payload": payload
                    if payload is not None
                    else (source["payload"] if source else {}),
                    "resolution_of": conflict["operation_id"],
                }
                operation = json.loads(canonical_operation(operation))
        finally:
            conn.close()

        def write_resolution(conn, value):
            row = conn.execute(
                "SELECT resolved_by FROM paperfact_sync_conflicts WHERE operation_id=?",
                (value["resolution_of"],),
            ).fetchone()
            if row is None or row["resolved_by"] is not None:
                raise ValueError("Conflict changed before resolution was saved")
            key = (value["entity_type"], value["entity_id"])
            current = conn.execute(
                "SELECT revision FROM paperfact_sync_heads WHERE entity_type=? AND entity_id=?",
                key,
            ).fetchone()
            if current is None or current[0] != value["base_revision"]:
                raise ValueError("Canonical content changed; review the conflict again")
            if self._outstanding(conn, key):
                raise ValueError("Synchronize outstanding edits before resolving this conflict")
            self.writer(conn, value)
            conn.execute(
                "INSERT INTO research_resolution_intents VALUES(?,?,?,?)",
                (value["operation_id"], sequence, request, canonical_operation(value)),
            )

        result = self.journal.apply(operation, write_resolution)
        return {"operation_id": operation["operation_id"], **result}

    @staticmethod
    def _outstanding(conn, key):
        return (
            conn.execute(
                "SELECT 1 FROM paperfact_sync_operations WHERE entity_type=? AND entity_id=? "
                "AND (server_revision IS NULL OR server_revision>"
                "(SELECT sequence FROM paperfact_sync_cursor WHERE id=1)) LIMIT 1",
                key,
            ).fetchone()
            is not None
        )

    @staticmethod
    def _record_conflict_state(conn, event):
        operation = event["operation"]
        target_id = operation.get("resolution_of")
        if target_id is not None:
            target = conn.execute(
                "SELECT i.event FROM paperfact_sync_conflicts c "
                "JOIN paperfact_sync_inbox i ON i.sequence=c.sequence WHERE c.operation_id=?",
                (target_id,),
            ).fetchone()
            if target is None:
                raise ValueError("Resolution refers to an unknown conflict")
            original = json.loads(target["event"])["operation"]
            if (original["entity_type"], original["entity_id"]) != (
                operation["entity_type"],
                operation["entity_id"],
            ):
                raise ValueError("Resolution refers to another research entity")
            if event["outcome"] == "accepted":
                conn.execute(
                    "UPDATE paperfact_sync_conflicts SET resolved_by=? "
                    "WHERE operation_id=? AND resolved_by IS NULL",
                    (operation["operation_id"], target_id),
                )
        if event["outcome"] == "conflict":
            conn.execute(
                "INSERT OR IGNORE INTO paperfact_sync_conflicts VALUES(?,?,NULL)",
                (operation["operation_id"], event["sequence"]),
            )

    def status(self):
        conn = self.journal._connect()
        try:
            conn.execute("BEGIN")
            self.journal._binding(conn)
            return {
                "cursor": conn.execute("SELECT sequence FROM paperfact_sync_cursor").fetchone()[0],
                "pending": conn.execute(
                    "SELECT COUNT(*) FROM paperfact_sync_operations WHERE server_revision IS NULL"
                ).fetchone()[0],
                "awaiting_receipts": conn.execute(
                    "SELECT COUNT(*) FROM paperfact_sync_operations WHERE server_revision>"
                    "(SELECT sequence FROM paperfact_sync_cursor WHERE id=1)"
                ).fetchone()[0],
                "conflicts": conn.execute(
                    "SELECT COUNT(*) FROM paperfact_sync_conflicts WHERE resolved_by IS NULL"
                ).fetchone()[0],
                "deferred": conn.execute(
                    "SELECT COUNT(*) FROM paperfact_sync_heads WHERE applied_revision<revision"
                ).fetchone()[0],
            }
        finally:
            conn.close()

    def history(self, *, conflicts_only=False, after=0, limit=100):
        if type(after) is not int or after < 0:
            raise ValueError("Invalid history cursor")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Invalid history limit")
        conn = self.journal._connect()
        try:
            self.journal._binding(conn)
            rows = conn.execute(
                "SELECT event FROM paperfact_sync_inbox WHERE sequence>? "
                "AND (?=0 OR outcome='conflict') ORDER BY sequence LIMIT ?",
                (after, int(conflicts_only), limit),
            )
            return [json.loads(row[0]) for row in rows]
        finally:
            conn.close()

    def receive(self, events):
        """Persist a bounded contiguous batch and resulting research in one transaction.

        Local edits defer materialization until their acknowledgment is received in the
        contiguous inbox, including when upload succeeded but pull failed. All versions
        remain in history. UI draft/selection handling belongs to the desktop adapter.
        """
        if not isinstance(events, list) or len(events) > 1000:
            raise ValueError("Invalid event batch")
        encoded = [validate_event(event, self.journal.workspace_id) for event in events]
        conn = self.journal._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self.journal._binding(conn)
            cursor = conn.execute("SELECT sequence FROM paperfact_sync_cursor").fetchone()[0]
            received = 0
            for data in encoded:
                event = json.loads(data)
                sequence = event["sequence"]
                if sequence <= cursor:
                    receipt = conn.execute(
                        "SELECT event FROM paperfact_sync_inbox WHERE sequence=?", (sequence,)
                    ).fetchone()
                    if receipt is None or receipt[0] != data:
                        raise ValueError("Event replay changed content")
                    continue
                if sequence != cursor + 1:
                    raise ValueError("Event stream has a gap")
                op, head = event["operation"], event["head"]
                key = (op["entity_type"], op["entity_id"])
                existing = conn.execute(
                    "SELECT revision,operation FROM paperfact_sync_heads "
                    "WHERE entity_type=? AND entity_id=?",
                    key,
                ).fetchone()
                head_data = canonical_operation(head["operation"]) if head["operation"] else None
                if event["outcome"] == "conflict":
                    expected = tuple(existing) if existing else (0, None)
                    if (head["revision"], head_data) != expected:
                        raise ValueError("Conflict head differs from the accepted event stream")
                if existing and (
                    head["revision"] < existing[0]
                    or (head["revision"] == existing[0] and head_data != existing[1])
                ):
                    raise ValueError("Entity head moved backwards or changed content")
                conn.execute(
                    "INSERT INTO paperfact_sync_heads "
                    "(entity_type,entity_id,revision,operation,applied_revision) "
                    "VALUES(?,?,?,?,-1) "
                    "ON CONFLICT(entity_type,entity_id) DO UPDATE SET "
                    "revision=excluded.revision,operation=excluded.operation,"
                    "applied_revision=-1",
                    (*key, head["revision"], head_data),
                )
                conn.execute(
                    "INSERT INTO paperfact_sync_inbox VALUES(?,?,?)",
                    (sequence, data, event["outcome"]),
                )
                self._record_conflict_state(conn, event)
                cursor = sequence
                received += 1
            applied = self._materialize(conn, cursor)
            conn.execute("UPDATE paperfact_sync_cursor SET sequence=? WHERE id=1", (cursor,))
            conn.commit()
            return {"received": received, "applied": applied, "cursor": cursor}
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _materialize(self, conn, cursor):
        heads = conn.execute(
            "SELECT * FROM paperfact_sync_heads WHERE applied_revision<revision ORDER BY revision"
        ).fetchall()
        applied = 0
        for head in heads:
            key = (head["entity_type"], head["entity_id"])
            pending = conn.execute(
                "SELECT 1 FROM paperfact_sync_operations "
                "WHERE entity_type=? AND entity_id=? "
                "AND (server_revision IS NULL OR server_revision>?) LIMIT 1",
                (*key, cursor),
            ).fetchone()
            if pending:
                continue
            if head["operation"] is None:
                # Canonical absence still needs materialization when a local stale-base
                # create was rejected. Keep that content in conflict history, and invoke
                # only the research writer; this synthetic delete is never queued/pushed.
                operation = {
                    "version": 1,
                    "operation_id": str(uuid4()),
                    "workspace_id": self.journal.workspace_id,
                    "device_id": self.journal.device_id,
                    "entity_type": head["entity_type"],
                    "entity_id": head["entity_id"],
                    "action": "delete",
                    "base_revision": 0,
                    "depends_on": None,
                    "payload": {},
                }
            else:
                operation = json.loads(head["operation"])
            conn.set_authorizer(self.journal._authorize_writer)
            try:
                self.writer(conn, operation)
            finally:
                conn.set_authorizer(None)
            conn.execute(
                "UPDATE paperfact_sync_heads SET applied_revision=revision "
                "WHERE entity_type=? AND entity_id=?",
                key,
            )
            applied += 1
        return applied

    def sync_once(self, transport, token, *, limit=100):
        """One bounded pass, with no timer, hidden retries, login or network policy."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Invalid sync batch limit")
        if not self._running.acquire(blocking=False):
            return {"busy": True}
        try:
            pushed = 0
            for operation in self.journal.pending(limit):
                event = transport.push(token, operation)
                validate_event(event, self.journal.workspace_id)
                if event["operation"] != operation:
                    raise ValueError("Acknowledgment belongs to another operation")
                self.journal.acknowledge(operation["operation_id"], event["sequence"])
                pushed += 1
            events = transport.pull(token, after=self.status()["cursor"], limit=limit)
            received = self.receive(events)
            return {"busy": False, "pushed": pushed, **received, **self.status()}
        finally:
            self._running.release()
