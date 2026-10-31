"""Typed optional legacy reading workflow; no list/order inference or AI."""

from __future__ import annotations

import hashlib
import json
import math
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import file_change
from paper_daily.sync_files import canonical_json, closed
from paper_daily.workspace_service import SnapshotChanged, Ticket, _safe_path

QUEUE_FIELDS = "paper_id rank state role parent_id reason queued_at delivered_at read_at"
EVENT_FIELDS = "id paper_id delivered_at brief_path role note"
STATES = {"pending", "delivered", "read", "skipped", "deferred"}
MAX_ROWS = 100000
MAX_METADATA = 64 * 1024**2
MAX_BRIEF = 8 * 1024**2
_SEAL = object()


def _text(value, limit, *, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, str) or len(value.encode("utf-8")) > limit:
        raise ValueError("Invalid bounded legacy workflow text")


def _time(value, *, nullable=False):
    if value is None and nullable:
        return
    from paper_daily.sync_content import _stamp

    _stamp(value)


def validate_queue(row):
    closed(row, QUEUE_FIELDS.split())
    _text(row["paper_id"], 4096)
    if not row["paper_id"]:
        raise ValueError("Legacy queue requires its paper identity")
    rank = row["rank"]
    try:
        valid = type(rank) in (int, float) and math.isfinite(rank)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("Legacy queue rank must be finite numeric data")
    if row["state"] not in STATES:
        raise ValueError("Unknown legacy queue state")
    _text(row["role"], 128)
    _text(row["parent_id"], 4096, nullable=True)
    _text(row["reason"], 200 * 1024, nullable=True)
    for key in ("queued_at", "delivered_at", "read_at"):
        _time(row[key], nullable=True)
    return row


def validate_event(row):
    closed(row, EVENT_FIELDS.split())
    if type(row["id"]) is not int or not 1 <= row["id"] < 2**63:
        raise ValueError("Legacy delivery log requires its positive original identity")
    _text(row["paper_id"], 4096)
    if not row["paper_id"]:
        raise ValueError("Legacy delivery requires its paper identity")
    _time(row["delivered_at"])
    _text(row["brief_path"], 32768, nullable=True)
    if row["brief_path"] == "":
        raise ValueError("An empty legacy brief path is not a declared file")
    _text(row["role"], 128, nullable=True)
    _text(row["note"], 200 * 1024, nullable=True)
    return row


@dataclass(frozen=True, init=False)
class PreparedBrief:
    source: Path = field(repr=False)
    data: bytes = field(repr=False)
    file_version: tuple = field(repr=False)
    sha256: str
    size: int
    legacy_day: str | None
    seal: object = field(repr=False)

    @property
    def descriptor(self):
        return {"sha256": self.sha256, "size": self.size, "media_type": "text/markdown"}


def read_brief(source, *, trusted_root, ticket=None):
    """Explicit declared source only; old history/context paths are never followed."""
    ticket = ticket or Ticket()
    ticket.check()
    root, path = _safe_path(trusted_root), _safe_path(source)
    if (
        not path.is_relative_to(root)
        or not path.is_file()
        or path.suffix.lower() not in {".md", ".markdown"}
    ):
        raise ValueError(
            "Declared legacy brief requires an existing Markdown file in its trusted root"
        )
    data = bytearray()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        version = file_change.version(path, stream=stream)
        if not 0 < version[2] <= MAX_BRIEF:
            raise ValueError("Legacy Markdown brief exceeds its bounded bytes")
        while block := stream.read(min(256 * 1024, MAX_BRIEF + 1 - len(data))):
            ticket.check()
            data.extend(block)
            digest.update(block)
            if len(data) > MAX_BRIEF:
                raise ValueError("Legacy Markdown brief exceeds its bounded bytes")
        if len(data) != version[2] or file_change.version(path, stream=stream) != version:
            raise SnapshotChanged("Legacy brief changed while reading")
    if file_change.version(path) != version:
        raise SnapshotChanged("Legacy brief changed before capture")
    try:
        text = data.decode("utf-8")
    except UnicodeError as error:
        raise ValueError("Legacy brief must contain exact readable UTF-8 Markdown") from error
    if "\x00" in text:
        raise ValueError("Legacy brief contains unsupported binary data")
    from datetime import date

    relative = path.relative_to(root)
    legacy_day = None
    if len(relative.parts) > 1:
        try:
            candidate = relative.parts[0]
            if date.fromisoformat(candidate).isoformat() == candidate:
                legacy_day = candidate
        except ValueError:
            pass
    result = object.__new__(PreparedBrief)
    for key, value in dict(
        source=path,
        data=bytes(data),
        file_version=version,
        sha256=digest.hexdigest(),
        size=len(data),
        legacy_day=legacy_day,
        seal=_SEAL,
    ).items():
        object.__setattr__(result, key, value)
    return result


def brief_current(brief):
    if not isinstance(brief, PreparedBrief) or getattr(brief, "seal", None) is not _SEAL:
        return False
    try:
        return file_change.version(_safe_path(brief.source)) == brief.file_version
    except (OSError, ValueError):
        return False


def inventory(conn, *, source_root, ticket=None):
    """Read closed rows and declared brief bytes; no schema or identities created."""
    ticket = ticket or Ticket()
    papers = {row[0] for row in conn.execute("SELECT id FROM papers")}
    result = {"queue": [], "reading_log": [], "briefs": {}}
    total = 0
    brief_bytes = 0
    for table, columns, validate in (
        ("queue", QUEUE_FIELDS, validate_queue),
        ("reading_log", EVENT_FIELDS, validate_event),
    ):
        actual = [row[1] for row in conn.execute('PRAGMA table_info("' + table + '")')]
        if actual != columns.split():
            raise ValueError("Unknown legacy workflow schema")
        names = columns.split()
        limits = {
            "paper_id": 4096,
            "rank": 128,
            "state": 64,
            "role": 128,
            "parent_id": 4096,
            "reason": 200 * 1024,
            "queued_at": 64,
            "delivered_at": 64,
            "read_at": 64,
            "brief_path": 32768,
            "note": 200 * 1024,
            "id": 128,
        }
        for name in names:
            oversized = (
                'SELECT 1 FROM "'
                + table
                + '" WHERE typeof("'
                + name
                + '") IN (?,?) AND length(CAST("'
                + name
                + '" AS BLOB))>? LIMIT 1'
            )
            if conn.execute(oversized, ("text", "blob", limits[name])).fetchone():
                raise ValueError("Legacy workflow text exceeds its closed field bound")
        selected = ",".join('"' + name + '"' for name in names)
        order = "paper_id" if table == "queue" else "id"
        for count, raw in enumerate(
            conn.execute(
                "SELECT " + selected + ' FROM "' + table + '" ORDER BY "' + order + '" LIMIT ?',
                (MAX_ROWS + 1,),
            ),
            1,
        ):
            ticket.check()
            row = validate(dict(zip(names, raw, strict=True)))
            total += len(canonical_json(row))
            if count > MAX_ROWS or total > MAX_METADATA:
                raise ValueError("Legacy workflow inventory exceeds its bounded scope")
            if row["paper_id"] not in papers:
                raise ValueError("Legacy workflow row requires its existing paper")
            if table == "queue" and row["parent_id"] is not None and row["parent_id"] not in papers:
                raise ValueError("Legacy queue parent requires its existing declared paper")
            if table == "reading_log" and row["brief_path"] is not None:
                declared = Path(row["brief_path"])
                if not declared.is_absolute():
                    declared = Path(source_root) / declared
                result["briefs"][row["id"]] = read_brief(
                    declared, trusted_root=Path(source_root) / "briefs", ticket=ticket
                )
                brief_bytes += result["briefs"][row["id"]].size
                if brief_bytes > 512 * 1024**2:
                    raise ValueError("Legacy briefs exceed the bounded staging inventory")
            result[table].append(row)
    return result


WIRE_FEATURES = {"queue_entry", "reading_event"}
QUEUE_DATA = set(QUEUE_FIELDS.split()) - {"paper_id"}
EVENT_DATA = {"delivered_at", "role", "note", "brief"}


def validate_descriptor(value):
    from paper_daily.sync_files import digest

    closed(value, {"sha256", "size", "media_type"})
    digest(value["sha256"])
    if (
        type(value["size"]) is not int
        or not 0 < value["size"] <= MAX_BRIEF
        or value["media_type"] != "text/markdown"
    ):
        raise ValueError("Invalid exact legacy Markdown descriptor")
    return value


def validate_wire(payload):
    from paper_daily.sync_content import _uuid

    if payload["source_document_hash"] is not None:
        raise ValueError("Legacy workflow metadata does not assert PDF provenance")
    data, feature = payload["data"], payload["feature"]
    if feature == "queue_entry":
        closed(data, QUEUE_DATA)
        validate_queue(dict(data, paper_id=payload["scope"]["id"]))
        if data["parent_id"] is not None:
            _uuid(data["parent_id"])
    elif feature == "reading_event":
        closed(data, EVENT_DATA)
        _time(data["delivered_at"])
        _text(data["role"], 128, nullable=True)
        _text(data["note"], 200 * 1024, nullable=True)
        if data["brief"] is not None:
            validate_descriptor(data["brief"])
    else:
        raise ValueError("Unknown legacy workflow feature")
    if len(canonical_json(payload)) > 240 * 1024:
        raise ValueError("Legacy workflow metadata exceeds its inline bound")


def payload(conn, table, row):
    require_ready(conn)
    from paper_daily.sync_content import _portable_paper, _row_key

    row = dict(row)
    scope = {"kind": "paper", "id": _portable_paper(conn, row["paper_id"])}
    if table == "queue":
        validate_queue(row)
        data = {key: row[key] for key in QUEUE_DATA}
        if data["parent_id"] is not None:
            data["parent_id"] = _portable_paper(conn, data["parent_id"])
        feature, key = "queue_entry", "main"
    elif table == "reading_log":
        validate_event(row)
        key = _row_key(conn, table, row)
        from paper_daily.legacy_briefs import descriptor_for_row

        brief = descriptor_for_row(conn, row, key)
        data = {name: row[name] for name in ("delivered_at", "role", "note")}
        data["brief"] = brief
        feature = "reading_event"
    else:
        raise ValueError("Unknown legacy workflow SQL table")
    result = dict(scope=scope, feature=feature, key=key, data=data, source_document_hash=None)
    validate_wire(result)
    return result


def write_in(conn, operation, *, feature, local, scope, key, data, deleting):
    from paper_daily.sync_content import _local_scope, _record_projection

    require_ready(conn)
    if feature == "queue_entry":
        if deleting:
            conn.execute("DELETE FROM queue WHERE paper_id=?", (local,))
            return
        for parent in operation["parents"]:
            actual = conn.execute(
                "SELECT incarnation FROM research_paper_projection WHERE sync_id=?", (parent["id"],)
            ).fetchone()
            if actual is None or actual[0] != parent["incarnation"]:
                raise ValueError("Legacy queue parent incarnation changed")
        row = {"paper_id": local, **data}
        if row["parent_id"] is not None:
            row["parent_id"] = _local_scope(conn, {"kind": "paper", "id": row["parent_id"]})
        fields = QUEUE_FIELDS.split()
        conn.execute(
            "INSERT INTO queue VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(paper_id) "
            "DO UPDATE SET " + ",".join(name + "=excluded." + name for name in fields[1:]),
            tuple(row[name] for name in fields),
        )
    elif feature == "reading_event":
        mapping = conn.execute(
            "SELECT local_id,paper_id,created_at FROM research_content_identity "
            "WHERE feature='reading_event' AND sync_key=?",
            (key,),
        ).fetchone()
        if mapping is not None and mapping[1] != local:
            raise ValueError("Legacy log identity cannot move to another paper")
        if deleting:
            if mapping is not None and mapping[0] is not None:
                conn.execute(
                    "DELETE FROM reading_log WHERE id=? AND paper_id=?", (mapping[0], local)
                )
                conn.execute(
                    "UPDATE research_content_identity SET local_id=NULL "
                    "WHERE feature='reading_event' AND sync_key=?",
                    (key,),
                )
            from paper_daily.legacy_briefs import clear_in

            clear_in(conn, key)
            return
        if mapping is not None and mapping[2] != data["delivered_at"]:
            raise ValueError("Legacy delivery timestamp is an immutable event identity")
        previous = (
            conn.execute(
                "SELECT brief_path FROM reading_log WHERE id=? AND paper_id=?", (mapping[0], local)
            ).fetchone()
            if mapping and mapping[0] is not None
            else None
        )
        from paper_daily.legacy_briefs import clear_in, target

        old_target = target(conn, key)
        old_descriptor = json.loads(old_target["descriptor_json"]) if old_target else None
        brief_path = previous[0] if previous and data["brief"] == old_descriptor else None
        values = (local, data["delivered_at"], brief_path, data["role"], data["note"])
        if previous is not None:
            conn.execute(
                "UPDATE reading_log SET paper_id=?,delivered_at=?,brief_path=?,role=?,note=? "
                "WHERE id=?",
                (*values, mapping[0]),
            )
        else:
            inserted = conn.execute(
                "INSERT INTO reading_log(paper_id,delivered_at,brief_path,role,note) "
                "VALUES(?,?,?,?,?)",
                values,
            )
            conn.execute(
                "INSERT INTO research_content_identity VALUES('reading_event',?,?,?,?) "
                "ON CONFLICT(feature,sync_key) DO UPDATE SET local_id=excluded.local_id",
                (key, inserted.lastrowid, local, data["delivered_at"]),
            )
        if data["brief"] is not None:
            from paper_daily.legacy_briefs import declare_in

            declare_in(conn, key, local, data["brief"])
        else:
            clear_in(conn, key)
    else:
        raise ValueError("Unknown legacy workflow projection")
    _record_projection(conn, operation, feature, scope, key, None)


_QUEUE_SEAL = object()


@dataclass(frozen=True, init=False)
class _QueueContext:
    connection: object = field(repr=False)
    entity_id: str
    before: dict
    after: dict
    seal: object = field(repr=False)


@contextmanager
def companion_context(conn, *, paper_id, rank, parent_id, reason):
    """Only the actual companion writer seals an observed new context.

    Scalar rank/state edits continue through ordinary capture. A raw SQL parent
    rewrite gets no capability to replace the graph's observed context.
    """
    from paper_daily.sync_capture import (
        _flush,
        enabled,
        expecting,
        observe_content,
        suppress_capture,
    )

    if not enabled(conn):
        yield
        return
    require_ready(conn)
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    with suppress_capture(conn):
        _flush(conn)
    old = conn.execute("SELECT * FROM queue WHERE paper_id=?", (paper_id,)).fetchone()
    if old is None or old["state"] != "pending":
        yield
        return
    old = dict(old)
    new = {**old, "rank": rank, "role": "companion", "parent_id": parent_id, "reason": reason}
    with suppress_capture(conn):
        before, after = payload(conn, "queue", old), payload(conn, "queue", new)
        from paper_daily.sync_content import content_id, parent_identities

        if parent_identities(before) == parent_identities(after):
            observation = None
        else:
            observation = observe_content(conn, "queue", old)
            proof = object.__new__(_QueueContext)
            for key, value in dict(
                connection=conn,
                entity_id=content_id(after["scope"], "queue_entry", "main"),
                before=before,
                after=after,
                seal=_QUEUE_SEAL,
            ).items():
                object.__setattr__(proof, key, value)
            intents = getattr(conn, "_legacy_queue_contexts", {})
            intents[proof.entity_id] = proof
            conn._legacy_queue_contexts = intents
    with expecting(conn, [observation] if observation is not None else []):
        yield


def consume_queue_context(conn, identity, current, after):
    proof = getattr(conn, "_legacy_queue_contexts", {}).get(identity)
    if proof is None:
        return False
    if (
        type(proof) is not _QueueContext
        or getattr(proof, "seal", None) is not _QUEUE_SEAL
        or proof.connection is not conn
        or proof.entity_id != identity
        or current is None
        or current["action"] != "put"
        or proof.before != current["payload"]
        or proof.after != after
    ):
        raise ValueError("Companion context differs from its sealed observed writer")
    state = conn._capture_client._optimistic_graph(conn)[0]
    from paper_daily.sync_graph import _parents_active

    graph = state.get(("research_content", identity))
    if (
        graph is None
        or not graph["active"]
        or not _parents_active(lambda kind, key: state.get((kind, key)), graph["parents"])
    ):
        raise ValueError("Companion context's observed parents are no longer active")
    del conn._legacy_queue_contexts[identity]
    return True


_CAPABILITY_SQL = {
    "capture_queue_delete": (
        'CREATE TRIGGER "capture_queue_delete" AFTER DELETE ON "queue" BEGIN '
        "SELECT paperfact_capture('queue',json_object('paper_id',OLD.\"paper_id\""
        ",'rank',OLD.\"rank\",'state',OLD.\"state\",'role',OLD.\"role\",'parent_id',O"
        'LD."parent_id",\'reason\',OLD."reason",\'queued_at\',OLD."queued_at",\'deli'
        'vered_at\',OLD."delivered_at",\'read_at\',OLD."read_at"),NULL); END'
    ),
    "capture_queue_insert": (
        'CREATE TRIGGER "capture_queue_insert" AFTER INSERT ON "queue" BEGIN '
        "SELECT paperfact_capture('queue',NULL,json_object('paper_id',NEW.\"pape"
        "r_id\",'rank',NEW.\"rank\",'state',NEW.\"state\",'role',NEW.\"role\",'parent_"
        'id\',NEW."parent_id",\'reason\',NEW."reason",\'queued_at\',NEW."queued_at",'
        "'delivered_at',NEW.\"delivered_at\",'read_at',NEW.\"read_at\")); END"
    ),
    "capture_queue_update": (
        'CREATE TRIGGER "capture_queue_update" AFTER UPDATE ON "queue" BEGIN '
        "SELECT paperfact_capture('queue',json_object('paper_id',OLD.\"paper_id\""
        ",'rank',OLD.\"rank\",'state',OLD.\"state\",'role',OLD.\"role\",'parent_id',O"
        'LD."parent_id",\'reason\',OLD."reason",\'queued_at\',OLD."queued_at",\'deli'
        "vered_at',OLD.\"delivered_at\",'read_at',OLD.\"read_at\"),json_object('pap"
        "er_id',NEW.\"paper_id\",'rank',NEW.\"rank\",'state',NEW.\"state\",'role',NEW"
        ".\"role\",'parent_id',NEW.\"parent_id\",'reason',NEW.\"reason\",'queued_at',"
        'NEW."queued_at",\'delivered_at\',NEW."delivered_at",\'read_at\',NEW."read_'
        'at")); END'
    ),
    "capture_reading_log_delete": (
        'CREATE TRIGGER "capture_reading_log_delete" AFTER DELETE ON '
        "\"reading_log\" BEGIN SELECT paperfact_capture('reading_log',json_object"
        "('id',OLD.\"id\",'paper_id',OLD.\"paper_id\",'delivered_at',OLD.\"delivered"
        '_at",\'brief_path\',OLD."brief_path",\'role\',OLD."role",\'note\',OLD."note"'
        "),NULL); END"
    ),
    "capture_reading_log_insert": (
        'CREATE TRIGGER "capture_reading_log_insert" AFTER INSERT ON '
        "\"reading_log\" BEGIN SELECT paperfact_capture('reading_log',NULL,json_o"
        "bject('id',NEW.\"id\",'paper_id',NEW.\"paper_id\",'delivered_at',NEW.\"deli"
        "vered_at\",'brief_path',NEW.\"brief_path\",'role',NEW.\"role\",'note',NEW.\""
        'note")); END'
    ),
    "capture_reading_log_update": (
        'CREATE TRIGGER "capture_reading_log_update" AFTER UPDATE ON '
        "\"reading_log\" BEGIN SELECT paperfact_capture('reading_log',json_object"
        "('id',OLD.\"id\",'paper_id',OLD.\"paper_id\",'delivered_at',OLD.\"delivered"
        '_at",\'brief_path\',OLD."brief_path",\'role\',OLD."role",\'note\',OLD."note"'
        "),json_object('id',NEW.\"id\",'paper_id',NEW.\"paper_id\",'delivered_at',N"
        'EW."delivered_at",\'brief_path\',NEW."brief_path",\'role\',NEW."role",\'not'
        'e\',NEW."note")); END'
    ),
    "research_content_identity": (
        "CREATE TABLE research_content_identity (feature TEXT NOT NULL,sync_key"
        " TEXT NOT NULL,local_id INTEGER,paper_id TEXT NOT NULL,created_at TEXT"
        " NOT NULL,PRIMARY KEY(feature,sync_key),UNIQUE(feature,local_id))"
    ),
    "research_content_projection": (
        "CREATE TABLE research_content_projection (entity_id TEXT PRIMARY "
        "KEY,feature TEXT NOT NULL,scope_kind TEXT NOT NULL,scope_id TEXT NOT "
        "NULL,item_key TEXT NOT NULL,incarnation TEXT NOT "
        "NULL,parent_incarnation TEXT NOT NULL,source_hash TEXT)"
    ),
    "research_file_applied": "CREATE TABLE research_file_applied (entity_id TEXT PRIMARY "
    "KEY,operation TEXT NOT NULL)",
    "research_file_desired": "CREATE TABLE research_file_desired (entity_id TEXT PRIMARY "
    "KEY,operation TEXT NOT NULL,active INTEGER NOT NULL)",
    "research_file_intents": "CREATE TABLE research_file_intents (operation_id TEXT PRIMARY "
    "KEY,entity_id TEXT NOT NULL,state TEXT NOT NULL)",
    "research_file_paths": "CREATE TABLE research_file_paths (id INTEGER PRIMARY KEY "
    "CHECK(id=1),workspace TEXT NOT NULL,blob_root TEXT NOT "
    "NULL,version_root TEXT NOT NULL)",
    "research_file_versions": "CREATE TABLE research_file_versions (operation_id TEXT PRIMARY "
    "KEY,entity_id TEXT NOT NULL,operation TEXT NOT NULL)",
}


def require_ready(conn):
    """Closed metadata capability guard; no DDL, identities or lazy repair."""
    from paper_daily.legacy_briefs import TARGET_SCHEMA, TARGETS

    expected = {**_CAPABILITY_SQL, TARGETS: TARGET_SCHEMA}
    capture = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='research_capture_binding'"
    ).fetchone()
    if not capture:
        expected = {name: sql for name, sql in expected.items() if not name.startswith("capture_")}
    rows = dict(
        conn.execute(
            "SELECT name,CASE WHEN length(CAST(sql AS BLOB))<=8192 THEN sql END "
            "FROM sqlite_master WHERE name IN (" + ",".join("?" for _ in expected) + ")",
            tuple(sorted(expected)),
        )
    )

    def normalized(value):
        return "".join(value.split()).lower().replace("ifnotexists", "")

    if set(rows) != set(expected) or any(
        not isinstance(rows[name], str) or normalized(rows[name]) != normalized(sql)
        for name, sql in expected.items()
    ):
        raise ValueError(
            "Legacy workflow migration required: create a complete backup, "
            "restore detached, then prepare a new editable copy"
        )
