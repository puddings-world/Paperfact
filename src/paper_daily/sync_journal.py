"""Experimental local sync journal; opt-in by explicit path, never on app startup.

Private v1 list/plain-note and v2 paper/membership graph contracts are supported.
No network, credentials, research migration, or desktop integration is provided.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

MAX_BYTES = 256 * 1024
PREFIX = "paperfact_sync_"
ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
FIELDS = {
    "version",
    "operation_id",
    "workspace_id",
    "device_id",
    "entity_type",
    "entity_id",
    "action",
    "base_revision",
    "depends_on",
    "payload",
}


def _identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("Invalid sync identifier")


def canonical_operation(value: dict) -> str:
    """Validate a closed payload shape before opening a transaction or calling a writer."""
    if isinstance(value, dict) and type(value.get("version")) is int and value["version"] == 2:
        from paper_daily.sync_schema_v2 import canonical_operation as canonical_v2

        return canonical_v2(value)
    if not isinstance(value, dict) or set(value) not in (FIELDS, FIELDS | {"resolution_of"}):
        raise ValueError("Unexpected or missing operation fields")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Unsupported sync protocol version")
    for key in ("operation_id", "workspace_id", "device_id", "entity_id"):
        _identifier(value[key])
    if "resolution_of" in value:
        _identifier(value["resolution_of"])
        if value["resolution_of"] == value["operation_id"]:
            raise ValueError("An operation cannot resolve itself")
    dependency = value["depends_on"]
    if dependency is not None:
        _identifier(dependency)
        if dependency == value["operation_id"]:
            raise ValueError("An operation cannot depend on itself")
    if type(value["base_revision"]) is not int or value["base_revision"] < 0:
        raise ValueError("Invalid base revision")
    kind, action, payload = value["entity_type"], value["action"], value["payload"]
    if kind not in ("list", "note") or action not in ("put", "delete"):
        raise ValueError("Unsupported research operation")
    if not isinstance(payload, dict):
        raise ValueError("Payload must be an object")
    if action == "delete":
        if payload:
            raise ValueError("Delete must have an empty payload")
    elif kind == "list":
        if set(payload) != {"name", "note"}:
            raise ValueError("List payload requires name and note only")
        if not isinstance(payload["name"], str) or not payload["name"].strip():
            raise ValueError("List name must not be empty")
        if len(payload["name"]) > 200 or not isinstance(payload["note"], str):
            raise ValueError("Invalid list content")
    else:
        if set(payload) != {"paper_id", "body"}:
            raise ValueError("Text note payload requires paper_id and body only")
        paper = payload["paper_id"]
        if not isinstance(paper, str) or not paper.strip() or len(paper) > 512:
            raise ValueError("Invalid paper identity")
        if not isinstance(payload["body"], str):
            raise ValueError("Note body must be text")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Sync operation exceeds 256 KiB")
    return encoded


class Journal:
    """Own short-lived connections to one explicitly selected local database.

    Writers are trusted application callbacks, not supplied SQL or remote code.
    The callback may issue research DML but cannot commit, alter schema, attach
    another database, or modify journal tables. An exception rolls back both writes.
    """

    def __init__(self, path: Path, *, workspace_id: str, device_id: str):
        _identifier(workspace_id)
        _identifier(device_id)
        self.path = Path(path)
        self.workspace_id, self.device_id = workspace_id, device_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS paperfact_sync_identity "
                "(id INTEGER PRIMARY KEY CHECK(id=1), workspace TEXT, device TEXT)"
            )
            conn.execute(
                "INSERT OR IGNORE INTO paperfact_sync_identity VALUES(1,?,?)",
                (workspace_id, device_id),
            )
            self._binding(conn)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS paperfact_sync_operations ("
                "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
                "operation_id TEXT NOT NULL UNIQUE, fingerprint TEXT NOT NULL, "
                "entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, "
                "envelope TEXT NOT NULL, server_revision INTEGER)"
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def _binding(self, conn):
        row = conn.execute(
            "SELECT workspace,device FROM paperfact_sync_identity WHERE id=1"
        ).fetchone()
        if row is None or tuple(row) != (self.workspace_id, self.device_id):
            raise ValueError("Workspace/device binding differs; explicit enrollment is required")

    @staticmethod
    def _authorize_writer(action, first, second, database, trigger):
        if database not in (None, "main"):
            return sqlite3.SQLITE_DENY
        allowed = {
            sqlite3.SQLITE_SELECT,
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_FUNCTION,
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_UPDATE,
            sqlite3.SQLITE_DELETE,
            sqlite3.SQLITE_RECURSIVE,
        }
        if action not in allowed:
            return sqlite3.SQLITE_DENY
        if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE) and (
            first or ""
        ).startswith(PREFIX):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    @contextmanager
    def transaction(self):
        """Own one connection/commit for a compound research action.

        Network work must finish before entering. Call apply_in repeatedly inside
        this scope; any propagated failure rolls back the entire compound action.
        """
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._binding(conn)
            boundary = "paperfact_action_" + uuid4().hex
            conn.execute(f"SAVEPOINT {boundary}")
            yield conn
            if not conn.in_transaction:
                raise RuntimeError("Research transaction ended before the action completed")
            try:
                # SQLite ON CONFLICT ROLLBACK can abort the whole transaction.
                # Even if a caller catches that error and starts another write,
                # loss of this marker prevents reporting a partial action as saved.
                conn.execute(f"RELEASE SAVEPOINT {boundary}")
            except sqlite3.DatabaseError as exc:
                raise RuntimeError(
                    "Research transaction was interrupted; retry the action"
                ) from exc
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def apply(self, operation: dict, write) -> dict:
        """Commit once; an exact replay never calls the research writer again."""
        with self.transaction() as conn:
            return self.apply_in(conn, operation, write)

    def apply_in(self, conn: sqlite3.Connection, operation: dict, write) -> dict:
        """Save inside a caller-owned transaction without committing that transaction.

        The connection must target this journal's database and must not have a
        caller-installed SQLite authorizer: this method temporarily owns it while
        invoking the trusted application writer. It restores the default afterward.
        An ordinary failed operation rolls back to its savepoint. SQLite failures
        that abort the entire transaction cannot retain earlier writes; external
        transaction owners must abort/retry if conn.in_transaction becomes false.
        Propagate the failure to
        transaction() to roll back an entire compound action; catch it only when
        intentionally retaining earlier unrelated work in the outer transaction.
        """
        encoded = canonical_operation(operation)
        value = json.loads(encoded)
        if (value["workspace_id"], value["device_id"]) != (self.workspace_id, self.device_id):
            raise ValueError("Operation belongs to another workspace/device")
        if not conn.in_transaction:
            raise ValueError("A caller-owned write transaction is required")
        databases = conn.execute("PRAGMA database_list").fetchall()
        main = next((row[2] for row in databases if row[1] == "main"), None)
        if not main or Path(main).resolve() != self.path.resolve():
            raise ValueError("Connection belongs to another research database")
        fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        savepoint = "paperfact_write_" + uuid4().hex
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            self._binding(conn)
            previous = conn.execute(
                "SELECT sequence,fingerprint FROM paperfact_sync_operations WHERE operation_id=?",
                (value["operation_id"],),
            ).fetchone()
            if previous:
                if previous[1] != fingerprint:
                    raise ValueError("Operation ID was reused with different content")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                return {"applied": False, "sequence": previous[0]}
            predecessor = value["depends_on"]
            if predecessor:
                parent = conn.execute(
                    "SELECT entity_type,entity_id FROM paperfact_sync_operations "
                    "WHERE operation_id=?",
                    (predecessor,),
                ).fetchone()
                if parent is None or tuple(parent) != (value["entity_type"], value["entity_id"]):
                    raise ValueError("Missing or unrelated predecessor")
            pending = conn.execute(
                "SELECT operation_id FROM paperfact_sync_operations "
                "WHERE entity_type=? AND entity_id=? AND server_revision IS NULL "
                "ORDER BY sequence DESC LIMIT 1",
                (value["entity_type"], value["entity_id"]),
            ).fetchone()
            if pending and pending[0] != predecessor:
                raise ValueError("An offline edit must depend on the latest pending edit")
            conn.set_authorizer(self._authorize_writer)
            try:
                write(conn, json.loads(encoded))
            finally:
                conn.set_authorizer(None)
            cursor = conn.execute(
                "INSERT INTO paperfact_sync_operations "
                "(operation_id,fingerprint,entity_type,entity_id,envelope) VALUES(?,?,?,?,?)",
                (
                    value["operation_id"],
                    fingerprint,
                    value["entity_type"],
                    value["entity_id"],
                    encoded,
                ),
            )
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            return {"applied": True, "sequence": cursor.lastrowid}
        except BaseException:
            # Some SQLite failures already roll back the entire transaction.
            # Preserve that original failure instead of masking it with a missing
            # savepoint error. The transaction owner must then abort/retry the action.
            if conn.in_transaction:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise

    def pending(self, limit: int = 100) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Batch size must be between 1 and 1000")
        conn = self._connect()
        try:
            self._binding(conn)
            rows = conn.execute(
                "SELECT envelope FROM paperfact_sync_operations "
                "WHERE server_revision IS NULL ORDER BY sequence LIMIT ?",
                (limit,),
            )
            return [json.loads(row[0]) for row in rows]
        finally:
            conn.close()

    def acknowledge(self, operation_id: str, server_revision: int) -> None:
        """Persist a trusted transport acknowledgment; retain the replay receipt."""
        if type(server_revision) is not int or server_revision <= 0:
            raise ValueError("Invalid server revision")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._binding(conn)
            row = conn.execute(
                "SELECT envelope,server_revision FROM paperfact_sync_operations "
                "WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Unknown operation")
            if row["server_revision"] not in (None, server_revision):
                raise ValueError("Acknowledgment revision changed")
            predecessor = json.loads(row["envelope"])["depends_on"]
            if predecessor:
                parent = conn.execute(
                    "SELECT server_revision FROM paperfact_sync_operations WHERE operation_id=?",
                    (predecessor,),
                ).fetchone()
                if parent is None or parent[0] is None or parent[0] >= server_revision:
                    raise ValueError("Acknowledge the predecessor before this edit")
            conn.execute(
                "UPDATE paperfact_sync_operations SET server_revision=? WHERE operation_id=?",
                (server_revision, operation_id),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
