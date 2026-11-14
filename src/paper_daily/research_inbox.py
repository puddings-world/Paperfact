"Shared bounded Inbox operations; reads never initialize, fetch or invoke providers."

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from paper_daily import inbox_content as content
from paper_daily.workspace_activity import _versions
from paper_daily.workspace_service import (
    Ticket,
    WorkspaceChanged,
    _binding,
    _read,
    _safe_path,
    _tables,
)

MAX_ROWS = 100_000
MAX_METADATA = 64 * 1024**2
_SEAL = object()


@dataclass(frozen=True)
class InboxView:
    _json: str
    _binding_json: str
    _owner: str | None
    _versions: tuple
    _reader: object
    _seal: object

    @property
    def data(self):
        return content.decode(self._json)


def _owner(conn, tables):
    if content.OWNER not in tables:
        return None
    rows = conn.execute(
        "SELECT id,CASE WHEN length(CAST(token AS BLOB))<=64 THEN token END "
        f"FROM {content.OWNER} LIMIT 2"
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise ValueError("Inbox workspace ownership is invalid")
    content.validate_row(content.OWNER, dict(zip(("id", "token"), rows[0], strict=True)))
    return rows[0][1]


def _preflight(conn, tables):
    total = size = 0
    for table, columns in content.COLUMNS.items():
        if table not in tables:
            continue
        lengths = "+".join(f'COALESCE(length(CAST("{key}" AS BLOB)),0)' for key in columns.split())
        row = conn.execute(
            f"SELECT count(*),COALESCE(sum({lengths}),0),COALESCE(max({lengths}),0) FROM {table}"
        ).fetchone()
        total += row[0]
        size += row[1]
        if total > MAX_ROWS or size > MAX_METADATA or row[2] > 16 * 1024:
            raise ValueError("Inbox stored metadata exceeds its bounded limits")


def _verify_current(conn, row):
    retained = conn.execute(
        f"SELECT item_id,body_json,incarnation,active FROM {content.HISTORY} WHERE version=?",
        (row["version"],),
    ).fetchone()
    if retained is None or tuple(retained) != (
        row["id"],
        row["body_json"],
        row["incarnation"],
        row["active"],
    ):
        raise ValueError("Inbox current row has no exact owned saved version")


def _item(conn, identity):
    row = conn.execute(f"SELECT * FROM {content.ITEMS} WHERE id=?", (identity,)).fetchone()
    if row is None:
        return None
    value = dict(zip(content.COLUMNS[content.ITEMS].split(), row, strict=True))
    content.validate_row(content.ITEMS, value)
    _verify_current(conn, value)
    return value


def _observation(row):
    return {key: row[key] if row else None for key in ("version", "incarnation", "active")}


def _connect(path):
    conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=0.25)
    conn.row_factory = sqlite3.Row
    from paper_daily.sync_capture import trusted_connection

    trusted_connection(conn)  # Closed helper, not an externally callable SQL operation.
    return conn


def retained_count(conn, tables):
    count = (
        conn.execute(
            f"SELECT count(*) FROM {content.CANDIDATES} WHERE resolved_by IS NULL"
        ).fetchone()[0]
        if content.CANDIDATES in tables
        else 0
    )
    if {"paperfact_sync_conflicts", "paperfact_sync_inbox"} <= tables:
        count += conn.execute(
            "SELECT count(*) FROM paperfact_sync_conflicts"
            " c JOIN paperfact_sync_inbox i ON i.sequence="
            "c.sequence WHERE c.resolved_by IS NULL AND js"
            "on_extract(i.event,'$.operation.entity_type')"
            "='inbox_item'"
        ).fetchone()[0]
    return count


def root_status(conn, tables, identity, cursor):
    from paper_daily.sync_projection import _sync_state

    if {"paperfact_sync_conflicts", "paperfact_sync_inbox"} <= tables and conn.execute(
        (
            "SELECT 1 FROM paperfact_sync_conflicts c JOIN"
            " paperfact_sync_inbox i ON i.sequence=c.seque"
            "nce WHERE c.resolved_by IS NULL AND json_extr"
            "act(i.event,'$.operation.entity_type')='inbox"
            "_item' AND json_extract(i.event,'$.operation."
            "entity_id')=? LIMIT 1"
        ),
        (identity,),
    ).fetchone():
        return "conflict"
    return _sync_state(conn, tables, "inbox_item", identity, cursor)["sync_state"]


def _retry_result(conn, request_id, prior, fingerprint, owner, item_id):
    row = dict(
        request_id=request_id, fingerprint=prior[0], owner_token=prior[1], result_json=prior[2]
    )
    content.validate_row(content.REQUESTS, row)
    if prior[0] != fingerprint or prior[1] != owner:
        raise ValueError("Inbox retry changed content or workspace ownership")
    result = content.decode(prior[2])
    if result["item_id"] != item_id:
        raise ValueError("Inbox retry receipt targets another capture")
    if result["status"] == "saved":
        found = conn.execute(
            f"SELECT item_id FROM {content.HISTORY} WHERE version=?", (result["version"],)
        ).fetchone()
        if found is None or found[0] != item_id or result["candidate_id"] is not None:
            raise ValueError("Inbox retry receipt has no matching saved history")
    else:
        found = conn.execute(
            f"SELECT item_id,resolved_by FROM {content.CANDIDATES} WHERE id=?",
            (result["candidate_id"],),
        ).fetchone()
        if (
            found is None
            or found[0] != item_id
            or (result["status"] == "resolved" and found[1] != result["version"])
        ):
            raise ValueError("Inbox retry receipt has no matching retained proposal")
    return result


class Inbox:
    def __init__(self, database, *, current_path=None):
        self.needs_reopen = False
        self.path = _safe_path(database)
        info = self.path.stat()
        self.identity = info.st_dev, info.st_ino
        self.current_path = current_path or (lambda: self.path)
        self._token = object()
        self._initial = _versions(self.path)
        self._binding_json = None
        self._owner = None

    def _path_check(self):
        if Path(self.current_path()).resolve() != self.path:
            self.needs_reopen = True
            raise WorkspaceChanged("The selected Inbox workspace changed")
        info = _safe_path(self.path).stat()
        if not info.st_ino or (info.st_dev, info.st_ino) != self.identity:
            self.needs_reopen = True
            raise WorkspaceChanged("The Inbox workspace was replaced")

    def _view_check(self, view):
        if (
            not isinstance(view, InboxView)
            or view._seal is not _SEAL
            or view._reader is not self._token
        ):
            raise WorkspaceChanged("Unrecognized Inbox workspace proof")
        self._path_check()

    def current(self, view):
        try:
            self._view_check(view)
            return _versions(self.path) == view._versions
        except (OSError, ValueError):
            return False

    def read(self, ticket=None, *, offset=0, include_deleted=False):
        ticket = ticket or Ticket()
        if (
            type(offset) is not int
            or not 0 <= offset <= MAX_ROWS
            or type(include_deleted) is not bool
        ):
            raise ValueError("Invalid Inbox page")
        self._path_check()
        versions = _versions(self.path)
        if self._binding_json is None and versions != self._initial:
            self.needs_reopen = True
            raise WorkspaceChanged("Workspace changed before the initial Inbox read; reopen it")
        with _read(self.path) as conn:
            tables = _tables(conn)
            _preflight(conn, tables)
            binding = content.encode(_binding(conn, tables))
            owner = _owner(conn, tables)
            if self._binding_json is not None and (
                binding != self._binding_json or owner != self._owner
            ):
                self.needs_reopen = True
                raise WorkspaceChanged("Inbox workspace ownership changed; reopen it")
            rows = []
            total = conflicts = 0
            cursor = (
                conn.execute("SELECT sequence FROM paperfact_sync_cursor WHERE id=1").fetchone()[0]
                if "paperfact_sync_cursor" in tables
                else 0
            )
            if content.ITEMS in tables:
                total = conn.execute(f"SELECT count(*) FROM {content.ITEMS}").fetchone()[0]
                if total > MAX_ROWS:
                    raise ValueError("Inbox exceeds its record limit")
                where = "" if include_deleted else "WHERE active=1"
                for row in conn.execute(
                    f"SELECT * FROM {content.ITEMS} {where} ORDER BY id LIMIT ? OFFSET ?",
                    (content.PAGE_SIZE + 1, offset),
                ):
                    ticket.check()
                    value = dict(zip(content.COLUMNS[content.ITEMS].split(), row, strict=True))
                    content.validate_row(content.ITEMS, value)
                    _verify_current(conn, value)
                    rows.append(
                        {
                            **{key: item for key, item in value.items() if key != "body_json"},
                            "payload": content.decode(value["body_json"])
                            if value["body_json"]
                            else None,
                            "sync_state": root_status(conn, tables, value["id"], cursor),
                        }
                    )
                if len(content.encode(rows).encode()) > 3 * 1024**2:
                    raise ValueError("Inbox page exceeds its byte limit")
            conflicts = retained_count(conn, tables)
            data = dict(
                items=rows[: content.PAGE_SIZE],
                offset=offset,
                has_more=len(rows) > content.PAGE_SIZE,
                total=total,
                conflicts=conflicts,
            )
        ticket.check()
        self._path_check()
        if _versions(self.path) != versions:
            raise WorkspaceChanged("Inbox changed during the read")
        self._binding_json, self._owner = binding, owner
        return InboxView(content.encode(data), binding, owner, versions, self._token, _SEAL)

    def _scope(self, conn, view):
        self._view_check(view)
        tables = _tables(conn)
        binding = content.encode(_binding(conn, tables))
        owner = _owner(conn, tables)
        if binding != view._binding_json or owner != view._owner:
            self.needs_reopen = True
            raise WorkspaceChanged("Captured Inbox workspace ownership changed")
        return tables, binding, owner

    @staticmethod
    def _limits(conn):
        _preflight(conn, _tables(conn))

    def save(
        self,
        view,
        *,
        request_id,
        item_id,
        payload,
        observed=None,
        action="put",
        restore=False,
        candidate_id=None,
        ticket=None,
    ):
        "Worker operation: exact retries and stale candidates commit atomically."
        content.uuid(request_id)
        content.uuid(item_id)
        if action not in {"put", "delete"} or type(restore) is not bool:
            raise ValueError("Unsupported Inbox mutation")
        if action == "put":
            payload = content.decode(content.encode(payload))
            content.validate(payload)
        elif payload is not None:
            raise ValueError("Inbox deletion contains no replacement text")
        observed = (
            dict(version=None, incarnation=None, active=None) if observed is None else observed
        )
        observed = content.decode(content.encode(observed))
        content.validate_observation(observed)
        if candidate_id is not None:
            content.uuid(candidate_id)
        request = dict(
            action=action,
            item_id=item_id,
            payload=payload,
            observed=observed,
            restore=restore,
            candidate_id=candidate_id,
        )
        fingerprint = hashlib.sha256(content.encode(request).encode()).hexdigest()
        operation_id = str(uuid5(UUID(request_id), "inbox-operation:" + item_id))
        ticket = ticket or Ticket()
        self._view_check(view)
        with closing(_connect(self.path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                tables = _tables(conn)
                _preflight(conn, tables)
                binding = content.encode(_binding(conn, tables))
                owner = _owner(conn, tables)
                if binding != view._binding_json:
                    raise WorkspaceChanged("Inbox workspace binding changed")
                if content.REQUESTS in tables:
                    prior = conn.execute(
                        f"SELECT fingerprint,owner_token,result_json FROM {content.REQUESTS} "
                        "WHERE request_id=?",
                        (request_id,),
                    ).fetchone()
                    if prior:
                        ticket.check()
                        return _retry_result(conn, request_id, prior, fingerprint, owner, item_id)
                self._scope(conn, view)
                ticket.check()
                content.initialize(conn)
                if owner is None:
                    owner = str(uuid4())
                    conn.execute(f"INSERT INTO {content.OWNER} VALUES(1,?)", (owner,))
                self._limits(conn)
                current = _item(conn, item_id)
                if _observation(current) != observed:
                    candidate = str(uuid5(UUID(request_id), "inbox-conflict:" + item_id))
                    conn.execute(
                        f"INSERT INTO {content.CANDIDATES} VALUES(?,?,?,?,?,NULL)",
                        (
                            candidate,
                            item_id,
                            content.encode(payload) if payload is not None else None,
                            content.encode(observed),
                            action,
                        ),
                    )
                    result = dict(
                        status="conflict",
                        item_id=item_id,
                        version=current["version"] if current else operation_id,
                        candidate_id=candidate,
                    )
                else:
                    if candidate_id is not None:
                        selected = conn.execute(
                            f"SELECT item_id,resolved_by FROM {content.CANDIDATES} WHERE id=?",
                            (candidate_id,),
                        ).fetchone()
                        if selected is None or selected[0] != item_id or selected[1] is not None:
                            raise ValueError("Inbox retained proposal changed; review it again")
                    if current and not current["active"]:
                        if action == "put" and not restore:
                            raise ValueError(
                                "Restoring deleted Inbox research requires an explicit choice"
                            )
                        if action == "delete":
                            raise ValueError("This Inbox item is already deleted")
                    elif restore:
                        raise ValueError("An active or absent Inbox item cannot be restored")
                    if action == "delete" and current is None:
                        raise ValueError("Choose an existing Inbox item to delete")
                    if (
                        current
                        and current["active"]
                        and payload is not None
                        and content.decode(current["body_json"])["created_at"]
                        != payload["created_at"]
                    ):
                        raise ValueError("Inbox captured-at metadata is immutable")
                    enrolled = next(
                        (
                            value
                            for name, value in content.decode(binding)
                            if name == "paperfact_sync_identity"
                        ),
                        None,
                    )
                    if not enrolled and content.decode(binding):
                        raise WorkspaceChanged(
                            "Finish explicit workspace enrollment before Inbox editing"
                        )
                    if enrolled:
                        from paper_daily.sync_client import SyncClient
                        from paper_daily.sync_journal import Journal
                        from paper_daily.sync_research import (
                            research_order_writer,
                            research_projection_writer,
                            research_writer,
                        )

                        journal = Journal.attach_existing(
                            self.path, workspace_id=enrolled[0], device_id=enrolled[1]
                        )
                        client = SyncClient.attach_existing(
                            journal,
                            research_writer,
                            order_writer=research_order_writer,
                            projection_writer=research_projection_writer,
                        )
                        operation = client.new_graph_operation_in(
                            conn,
                            "inbox_item",
                            item_id,
                            payload if payload is not None else {},
                            action=action,
                            operation_id=operation_id,
                            restore=restore,
                        )
                        journal.apply_in(conn, operation, research_writer)
                    else:
                        incarnation = (
                            current["incarnation"] if current and not restore else operation_id
                        )
                        # Same closed root writer; the local outer identity is authenticated here,
                        # never accepted from the captured text or an imported payload field.
                        operation = dict(
                            version=2,
                            operation_id=operation_id,
                            workspace_id=owner,
                            device_id="local-inbox",
                            entity_type="inbox_item",
                            entity_id=item_id,
                            action=action,
                            base_revision=0,
                            depends_on=None,
                            payload=payload if payload is not None else {},
                            incarnation=incarnation,
                            parents=[],
                            structure_revision=0,
                        )
                        content.write(conn, operation)
                    result = dict(
                        status="saved", item_id=item_id, version=operation_id, candidate_id=None
                    )
                    if candidate_id is not None:
                        conn.execute(
                            f"UPDATE {content.CANDIDATES} SET resolved_by=? "
                            "WHERE id=? AND resolved_by IS NULL",
                            (operation_id, candidate_id),
                        )
                conn.execute(
                    f"INSERT INTO {content.REQUESTS} VALUES(?,?,?,?)",
                    (request_id, fingerprint, owner, content.encode(result)),
                )
                self._limits(conn)
                self._path_check()
                if content.encode(_binding(conn, _tables(conn))) != view._binding_json:
                    raise WorkspaceChanged("Inbox binding changed before commit")
                ticket.publish(conn.commit)
                self._owner = owner
                return result
            except BaseException:
                conn.rollback()
                raise

    def _client(self, conn, binding):
        enrolled = next(
            (value for name, value in content.decode(binding) if name == "paperfact_sync_identity"),
            None,
        )
        if enrolled is None:
            return None
        from paper_daily.sync_client import SyncClient
        from paper_daily.sync_journal import Journal
        from paper_daily.sync_research import (
            research_order_writer,
            research_projection_writer,
            research_writer,
        )

        journal = Journal.attach_existing(
            self.path, workspace_id=enrolled[0], device_id=enrolled[1]
        )
        journal._binding(conn)
        return SyncClient.attach_existing(
            journal,
            research_writer,
            order_writer=research_order_writer,
            projection_writer=research_projection_writer,
        )

    def retained(self, view, ticket=None, *, item_id=None):
        ticket = ticket or Ticket()
        self._view_check(view)
        if not self.current(view):
            raise WorkspaceChanged("Refresh Inbox before reviewing retained versions")
        if item_id is not None:
            content.uuid(item_id)
        versions = _versions(self.path)
        with _read(self.path) as conn:
            conn.row_factory = sqlite3.Row
            tables, binding, owner = self._scope(conn, view)
            _preflight(conn, tables)
            records = []
            if content.CANDIDATES in tables:
                conn.row_factory = sqlite3.Row
                for raw in conn.execute(
                    f"SELECT * FROM {content.CANDIDATES} "
                    "WHERE resolved_by IS NULL ORDER BY id LIMIT ?",
                    (content.PAGE_SIZE,),
                ):
                    ticket.check()
                    row = dict(raw)
                    content.validate_row(content.CANDIDATES, row)
                    records.append(
                        dict(
                            id=row["id"],
                            source="local",
                            item_id=row["item_id"],
                            action=row["action"],
                            payload=content.decode(row["body_json"]) if row["body_json"] else None,
                            observed_current=_observation(_item(conn, row["item_id"])),
                        )
                    )
            client = self._client(conn, binding)
            if client is not None:
                for raw in conn.execute(
                    (
                        "SELECT i.sequence,i.event FROM paperfact_sync"
                        "_conflicts c JOIN paperfact_sync_inbox i ON i"
                        ".sequence=c.sequence WHERE c.resolved_by IS N"
                        "ULL AND json_extract(i.event,'$.operation.ent"
                        "ity_type')='inbox_item' ORDER BY i.sequence D"
                        "ESC LIMIT ?"
                    ),
                    (content.PAGE_SIZE,),
                ):
                    ticket.check()
                    event = content.decode(raw["event"])
                    if event["operation"]["entity_type"] != "inbox_item":
                        continue
                    from paper_daily.sync_client import validate_event

                    validate_event(event, client.journal.workspace_id)
                    operation = event["operation"]
                    if len(records) >= content.PAGE_SIZE:
                        break
                    records.append(
                        dict(
                            id=operation["operation_id"],
                            source="server",
                            item_id=operation["entity_id"],
                            action=operation["action"],
                            payload=operation["payload"] if operation["action"] == "put" else None,
                            sequence=raw["sequence"],
                            expected=client.conflict_observation_in(conn, raw["sequence"]),
                        )
                    )
            history = []
            if item_id is not None:
                for raw in conn.execute(
                    f"SELECT * FROM {content.HISTORY} WHERE item_id=? ORDER BY rowid DESC LIMIT ?",
                    (item_id, content.PAGE_SIZE),
                ):
                    ticket.check()
                    row = dict(raw)
                    content.validate_row(content.HISTORY, row)
                    history.append(
                        {
                            **row,
                            "payload": content.decode(row["body_json"])
                            if row["body_json"]
                            else None,
                        }
                    )
        ticket.check()
        self._path_check()
        if _versions(self.path) != versions:
            raise WorkspaceChanged("Inbox changed during retained-version review")
        return InboxView(
            content.encode(dict(retained=records, history=history)),
            binding,
            owner,
            versions,
            self._token,
            _SEAL,
        )

    def resolve(
        self, view, record_id, *, choice, request_id, payload=None, restore=False, ticket=None
    ):
        "Explicit retained-version decision; never recapture a newer displayed base."
        content.uuid(request_id)
        if choice not in {"incoming", "canonical"} or type(restore) is not bool:
            raise ValueError("Unsupported Inbox resolution choice")
        self._view_check(view)
        selected = next(
            (row for row in view.data.get("retained", []) if row["id"] == record_id), None
        )
        if selected is None:
            raise ValueError("Choose a displayed Inbox retained proposal")
        if payload is not None:
            payload = content.decode(content.encode(payload))
            content.validate(payload)
        if selected["source"] == "local" and choice == "incoming":
            return self.save(
                view,
                request_id=request_id,
                item_id=selected["item_id"],
                payload=payload if payload is not None else selected["payload"],
                observed=selected["observed_current"],
                action=selected["action"],
                restore=restore,
                candidate_id=record_id,
                ticket=ticket,
            )
        ticket = ticket or Ticket()
        fingerprint = hashlib.sha256(
            content.encode(
                dict(record=selected, choice=choice, payload=payload, restore=restore)
            ).encode()
        ).hexdigest()
        operation_id = str(uuid5(UUID(request_id), "inbox-resolution:" + record_id))
        with closing(_connect(self.path)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                tables = _tables(conn)
                _preflight(conn, tables)
                binding, owner = content.encode(_binding(conn, tables)), _owner(conn, tables)
                if binding != view._binding_json:
                    raise WorkspaceChanged("Inbox resolution workspace binding changed")
                previous = conn.execute(
                    f"SELECT fingerprint,owner_token,result_json FROM {content.REQUESTS} "
                    "WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if previous:
                    ticket.check()
                    return _retry_result(
                        conn, request_id, previous, fingerprint, owner, selected["item_id"]
                    )
                self._scope(conn, view)
                ticket.check()
                content.initialize(conn)
                if owner is None:
                    owner = str(uuid4())
                    conn.execute(f"INSERT INTO {content.OWNER} VALUES(1,?)", (owner,))
                if selected["source"] == "local":
                    if payload is not None or restore:
                        raise ValueError("Keeping current Inbox research cannot replace its text")
                    current = _item(conn, selected["item_id"])
                    if _observation(current) != selected["observed_current"]:
                        raise WorkspaceChanged(
                            "Inbox changed since the retained proposal was displayed"
                        )
                    changed = conn.execute(
                        f"UPDATE {content.CANDIDATES} SET resolved_by=? "
                        "WHERE id=? AND item_id=? AND resolved_by IS NULL",
                        (operation_id, record_id, selected["item_id"]),
                    ).rowcount
                    if changed != 1:
                        raise ValueError("Inbox retained proposal was already decided")
                    result = dict(
                        status="resolved",
                        item_id=selected["item_id"],
                        version=operation_id,
                        candidate_id=record_id,
                    )
                else:
                    client = self._client(conn, binding)
                    if (
                        client is None
                        or selected["expected"]["event"]["operation"]["entity_type"] != "inbox_item"
                    ):
                        raise WorkspaceChanged("Inbox conflict has no current enrolled workspace")
                    result_op = client.resolve_conflict_in(
                        conn,
                        selected["sequence"],
                        expected=selected["expected"],
                        choice=choice,
                        payload=payload,
                        restore=restore,
                        operation_id=operation_id,
                    )
                    result = dict(
                        status="saved",
                        item_id=selected["item_id"],
                        version=result_op["operation_id"],
                        candidate_id=None,
                    )
                conn.execute(
                    f"INSERT INTO {content.REQUESTS} VALUES(?,?,?,?)",
                    (request_id, fingerprint, owner, content.encode(result)),
                )
                self._limits(conn)
                self._path_check()
                if content.encode(_binding(conn, _tables(conn))) != view._binding_json:
                    raise WorkspaceChanged("Inbox resolution binding changed before commit")
                ticket.publish(conn.commit)
                self._owner = owner
                return result
            except BaseException:
                conn.rollback()
                raise

    def export_entry(self, view, item_id):
        self._view_check(view)
        if not self.current(view):
            raise WorkspaceChanged("Refresh Inbox before exporting an entry")
        item = next((row for row in view.data["items"] if row["id"] == item_id), None)
        if item is None or item["payload"] is None:
            raise ValueError("Choose a captured Inbox entry")
        return content.encode(dict(format="paperfact-inbox-entry.v1", item=item["payload"]))

    def import_entry(self, view, raw, *, request_id, ticket=None):
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > 12 * 1024:
            raise ValueError("Inbox entry import exceeds its bound")
        value = content.decode(raw)
        if (
            not isinstance(value, dict)
            or set(value) != {"format", "item"}
            or value["format"] != "paperfact-inbox-entry.v1"
        ):
            raise ValueError("Unsupported Inbox entry import")
        content.validate(value["item"])
        content.uuid(request_id)
        identity = str(uuid5(UUID(request_id), "inbox-import-item"))
        return self.save(
            view, request_id=request_id, item_id=identity, payload=value["item"], ticket=ticket
        )

    @staticmethod
    def observe(item):
        return _observation(item)
