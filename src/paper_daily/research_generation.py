"""Workspace-bound observations and durable publication of generated SQL research.

No model calls, network, enrollment or current-workspace lookup during publication.
The registry is intentionally closed; file-backed artifacts use a separate protocol.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import uuid4

from paper_daily import sync_capture

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 2000
MAX_CONTEXT_BYTES = 3 * 1024 * 1024
REGISTRY = {
    "paper_claim_sets": ("paper", "paper_id", "claims", "claims"),
    "paper_highlight_analysis": ("paper", "paper_id", "highlight_analysis", "highlights"),
    "paper_reading_links": ("paper", "paper_id", "reading_links", "reading_links"),
    "paper_research_questions": ("paper", "paper_id", "research_questions", "questions"),
    "dives": ("paper", "paper_id", "dive", "brief"),
    "paper_context": ("paper", "paper_id", "context", "overview"),
    "paper_later_outcomes": ("paper", "paper_id", "later_outcome", "later_outcome"),
    "close_readings": ("paper", "paper_id", "close_reading", "brief"),
    "list_surveys": ("list", "list_id", "list_survey", "survey"),
    "list_reading_goals": ("list", "list_id", "reading_goal", "target"),
}
REQUEST_FIELDS = {"request_id", "context_json", "row_json", "status", "candidate_id", "reason"}


def _json(value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Research generation snapshot exceeds its size limit")
    return text


def _context_json(value):
    encoded = _json(value)
    if len(encoded.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ValueError("Generation inputs exceed the retained-context budget")
    return encoded


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _dict(row):
    return dict(row) if row is not None else None


def _binding(conn):
    if sync_capture.enabled(conn):
        journal = conn._capture_client.journal
        return {"workspace_id": journal.workspace_id, "device_id": journal.device_id}
    return None


def _path(conn):
    path = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), None)
    if not path:
        raise ValueError("Generation requires an explicit on-disk research database")
    return str(Path(path).resolve())


def _identity(path):
    stat = Path(path).stat()
    return [stat.st_dev, stat.st_ino]


def _target(conn, table, owner_id):
    column = REGISTRY[table][1]
    return _dict(
        conn.execute(f'SELECT * FROM "{table}" WHERE "{column}"=?', (owner_id,)).fetchone()
    )


def _inputs(conn, reader, owner_id):
    if reader == "highlights":
        from paper_daily.highlight_publication import inputs

        return inputs(conn, owner_id)
    if reader == "later_outcome":
        from paper_daily.later_outcomes import inputs

        return inputs(conn, owner_id)
    if reader == "target":
        return None
    if reader == "reading_links":
        inputs = {
            name: _dict(
                conn.execute(f"SELECT * FROM {name} WHERE paper_id=?", (owner_id,)).fetchone()
            )
            for name in ("dives", "close_readings", "paper_highlight_analysis")
        }
        inputs["links_known"] = bool(
            conn.execute(
                "SELECT 1 FROM paper_annotation_known WHERE feature='reading_links' AND paper_id=?",
                (owner_id,),
            ).fetchone()
        )
        return inputs
    if reader == "claims":
        values = {
            name: _dict(
                conn.execute(
                    f"SELECT * FROM {name} WHERE paper_id=?",
                    (owner_id,),
                ).fetchone()
            )
            for name in ("dives", "close_readings")
        }
        values["claims_known"] = bool(
            conn.execute(
                "SELECT 1 FROM paper_annotation_known WHERE feature='claims' AND paper_id=?",
                (owner_id,),
            ).fetchone()
        )
        return values
    if reader == "questions":
        inputs = {
            name: _dict(
                conn.execute(f"SELECT * FROM {name} WHERE paper_id=?", (owner_id,)).fetchone()
            )
            for name in ("dives", "close_readings")
        }
        # Observe a canonical deletion even if the content row is absent again.
        inputs["question_known"] = bool(
            conn.execute(
                "SELECT 1 FROM paper_annotation_known "
                "WHERE feature='research_questions' AND paper_id=?",
                (owner_id,),
            ).fetchone()
        )
        return inputs
    if reader == "brief":
        from paper_daily.brief import input_snapshot

        return input_snapshot(conn, owner_id)
    if reader == "overview":
        from paper_daily.followups import overview_inputs

        return overview_inputs(conn, owner_id, limit=MAX_ROWS)
    if reader == "survey":
        rows = conn.execute(
            "SELECT p.*,d.body AS dive,pc.summary AS context,"
            "(SELECT COUNT(*) FROM followups f WHERE f.paper_id=p.id) AS later "
            "FROM list_papers lp JOIN papers p ON p.id=lp.paper_id "
            "LEFT JOIN dives d ON d.paper_id=p.id "
            "LEFT JOIN paper_context pc ON pc.paper_id=p.id "
            "WHERE lp.list_id=? ORDER BY p.year,lp.position,lp.paper_id LIMIT ?",
            (owner_id, MAX_ROWS + 1),
        ).fetchall()
        members = conn.execute(
            "SELECT paper_id,position FROM list_papers WHERE list_id=? "
            "ORDER BY position,paper_id LIMIT ?",
            (owner_id, MAX_ROWS + 1),
        ).fetchall()
        if max(len(rows), len(members)) > MAX_ROWS:
            raise ValueError("Research generation input exceeds its record limit")
        return {
            "list": _dict(conn.execute("SELECT * FROM lists WHERE id=?", (owner_id,)).fetchone()),
            "papers": [dict(row) for row in rows],
            "_members": [dict(row) for row in members],
        }
    raise ValueError("Unknown generation input reader")


@dataclass(frozen=True)
class GenerationContext:
    """JSON storage makes all public snapshots defensive copies, including nested data."""

    _json: str
    _document: object = None

    @property
    def data(self):
        return json.loads(self._json)

    @property
    def started_at(self):
        return self.data["started_at"]

    @property
    def request_id(self):
        return self.data["request_id"]

    @property
    def db_path(self):
        return Path(self.data["db_path"])

    @property
    def database_path(self):
        return self.db_path

    @property
    def table(self):
        return self.data["table"]

    @property
    def owner_id(self):
        return self.data["owner_id"]

    @property
    def target(self):
        return self.data["target"]

    @property
    def inputs(self):
        data = self.data["inputs"]
        if isinstance(data, dict):
            data.pop("_members", None)
        return data


@dataclass(frozen=True)
class Publication:
    status: str
    request_id: str
    candidate_id: str | None = None
    reason: str = "ok"


def begin_generation(conn, *, table, owner_id, key="main", request_id=None, input_reader=None):
    """Observe a target (including absence) and actual bounded inputs in one read snapshot."""
    if table not in REGISTRY or key != "main" or not isinstance(owner_id, str) or not owner_id:
        raise ValueError("Unsupported research generation target")
    from paper_daily.store import now

    request_id = request_id or str(uuid4())
    if not isinstance(request_id, str) or not 0 < len(request_id) <= 128:
        raise ValueError("Invalid generation request identity")
    reader = input_reader or REGISTRY[table][3]
    if reader not in ("target", REGISTRY[table][3]):
        raise ValueError("Input reader does not match the output feature")
    from paper_daily.research_lifecycle import ensure_lifecycle, parent_lifecycle

    # Persist epochs before the read snapshot when we own the connection. In a
    # caller-owned transaction, never commit unrelated work; a rollback also
    # invalidates epochs initialized there, so later publication fails closed.
    owned = not conn.in_transaction
    if owned:
        conn.execute("BEGIN IMMEDIATE")
    try:
        ensure_lifecycle(conn)
        if owned:
            conn.commit()
    except BaseException:
        if owned:
            conn.rollback()
        raise
    if owned:
        conn.execute("BEGIN")
    try:
        kind, _column, feature, _reader = REGISTRY[table]
        parent = _dict(
            conn.execute(
                f"SELECT * FROM {'papers' if kind == 'paper' else 'lists'} WHERE id=?", (owner_id,)
            ).fetchone()
        )
        if parent is None:
            raise ValueError("Research owner no longer exists")
        path = _path(conn)
        data = {
            "version": 1,
            "started_at": now(),
            "request_id": request_id,
            "db_path": path,
            "database_identity": _identity(path),
            "binding": _binding(conn),
            "table": table,
            "owner_id": owner_id,
            "key": key,
            "input_reader": reader,
            "target": _target(conn, table, owner_id),
            "parent_created_at": parent.get("created_at"),
            "parent_lifecycle": parent_lifecycle(conn, kind, owner_id),
            "observation": sync_capture.observe_target(conn, kind, owner_id, feature, key),
            "inputs": _inputs(conn, reader, owner_id),
            "document": None,
        }
        return GenerationContext(_context_json(data))
    finally:
        if owned:
            conn.rollback()


def bind_inputs(context, *, document=None, input_snapshot=None):
    """Attach only inputs actually used by a prepared pack; publication re-reads them."""
    data = context.data
    if input_snapshot is not None:
        # Re-reading at publication, not this supplied snapshot, is the authority.
        data["inputs"] = input_snapshot
    if document is not None:
        if document.local_id != data["owner_id"] or not document.available:
            raise ValueError("Input PDF is not available for this paper")
        if not re.fullmatch(r"[0-9a-f]{64}", document.sha256 or ""):
            raise ValueError("Input PDF has not been verified")
        data["document"] = {
            "sha256": document.sha256,
            "path": str(document.path.resolve()),
            "target": document.target,
            "managed": document.managed,
        }
    return replace(context, _json=_context_json(data), _document=document)


def _connect(path):
    conn = sqlite3.connect(
        Path(path).as_uri() + "?mode=rw",
        uri=True,
        factory=sync_capture.CaptureConnection,
        timeout=30,
    )
    conn.row_factory = sqlite3.Row
    return conn


def _setup(conn):
    with sync_capture.suppress_capture(conn):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_generation_requests("
            "request_id TEXT PRIMARY KEY,context_json TEXT NOT NULL,row_json TEXT NOT NULL,"
            "status TEXT NOT NULL CHECK(status IN ('accepted','candidate')),"
            "candidate_id TEXT,reason TEXT NOT NULL)"
        )


def _document_current(context):
    document = context._document
    expected = context.data["document"]
    if expected is None:
        return True
    # This runs in a worker, outside SQLite's publication lock. Detect same-size
    # replacement even when file metadata has been deliberately preserved.
    try:
        if document is None:
            from paper_daily.document_reader import from_workspace

            reader = from_workspace(context.db_path, legacy_root=Path(expected["path"]).parent)
            document = reader.resolve(context.data["owner_id"])
        from paper_daily.document_reader import document_current

        if not document_current(document):
            return False
        if document.sha256 != expected["sha256"] or document.target != expected["target"]:
            return False
        with document.path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest() == expected["sha256"]
    except (OSError, ValueError, sqlite3.DatabaseError):
        return False


def _is_link(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _recovery_path(context):
    data = context.data
    namespace = _digest({key: data[key] for key in ("db_path", "database_identity", "binding")})
    return (
        context.db_path.parent
        / ".paperfact-generation"
        / namespace
        / (_digest(context.request_id) + ".json")
    )


def _retain_outside_database(context, row, reason):
    """A replaced/rebound database must never receive even an old job's candidate."""
    candidate_id = _digest({"context": context.data, "row": row})
    record = {
        "request_id": context.request_id,
        "context_json": context._json,
        "row_json": _json(row),
        "status": "candidate",
        "candidate_id": candidate_id,
        "reason": reason,
    }
    path = _recovery_path(context)
    for parent in (path, *path.parents):
        if _is_link(parent):
            raise ValueError("Generation recovery location cannot traverse links")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _json(record)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            existing = validate_request_record(json.loads(path.read_text(encoding="utf-8")))
            if (
                existing["context_json"] != context._json
                or existing["row_json"] != record["row_json"]
            ):
                raise ValueError(
                    "Generation request identity was reused for different content"
                ) from None
            return Publication(
                "candidate", context.request_id, existing["candidate_id"], existing["reason"]
            )
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return Publication("candidate", context.request_id, candidate_id, reason)


def _stale(conn, context):
    data = context.data
    if _path(conn) != data["db_path"] or _identity(data["db_path"]) != data["database_identity"]:
        return "Research database was replaced"
    if _binding(conn) != data["binding"]:
        return "Workspace binding changed"
    kind, _, feature, _ = REGISTRY[data["table"]]
    from paper_daily.research_lifecycle import parent_lifecycle

    token = data.get("parent_lifecycle")
    if not token or parent_lifecycle(conn, kind, data["owner_id"]) != token:
        return "Research owner lifecycle changed or requires explicit review"
    owner = conn.execute(
        f"SELECT * FROM {'papers' if kind == 'paper' else 'lists'} WHERE id=?", (data["owner_id"],)
    ).fetchone()
    if owner is None or dict(owner).get("created_at") != data["parent_created_at"]:
        return "Research owner changed"
    if (
        sync_capture.observe_target(conn, kind, data["owner_id"], feature, data["key"])
        != data["observation"]
    ):
        return "Research target or parent changed"
    if _target(conn, data["table"], data["owner_id"]) != data["target"]:
        return "Research content changed"
    if _inputs(conn, data["input_reader"], data["owner_id"]) != data["inputs"]:
        return "Research inputs changed"
    if data["table"] == "paper_later_outcomes":
        from paper_daily.later_outcomes import source_current

        if not source_current(context):
            return "Later outcome source availability changed"
    if data["table"] == "paper_highlight_analysis" and "highlight_plan" in data:
        from paper_daily.highlight_publication import stale

        return stale(conn, context)
    return None


def _validate_row(context, row):
    from paper_daily.sync_content import FEATURES, validate_payload

    data = context.data
    kind, column, feature, _ = REGISTRY[data["table"]]
    fields = FEATURES[feature][2].split()
    if (
        not isinstance(row, dict)
        or set(row) != {column, *fields}
        or row[column] != data["owner_id"]
    ):
        raise ValueError("Output row does not match the captured target")
    values = {key: row[key] for key in fields}
    for key in ("reading_json", "body_json"):
        if key in values and values[key] is not None:
            values[key] = json.loads(values[key])
    validate_payload(
        {
            "scope": {"kind": kind, "id": "11111111-1111-4111-8111-111111111111"},
            "feature": feature,
            "key": "main",
            "data": values,
            "source_document_hash": data["document"]["sha256"] if data["document"] else None,
        }
    )

    if data["table"] == "paper_highlight_analysis":
        from paper_daily.highlight_publication import validate

        validate(context, row)
    if data["table"] == "paper_claim_sets":
        from paper_daily import claim_content, claim_publication

        claim_publication.validate(context)

        body = json.loads(row["body_json"])
        if (
            not isinstance(context.inputs, dict)
            or not context.inputs.get("dives")
            or not context.inputs.get("close_readings")
        ):
            raise ValueError("Claim sets require original observed analysis inputs")
        inputs = {
            "dive": claim_content.input_digest(context.inputs["dives"]),
            "close_reading": claim_content.input_digest(context.inputs["close_readings"]),
        }
        portable = ((data["observation"] or {}).get("parents") or [{}])[0].get("id")
        if (
            not data["document"]
            or body["inputs"] != inputs
            or body["report"]["source"]["paper_id"] != (portable or context.owner_id)
            or row["document_hash"] != data["document"]["sha256"]
            or body["report"]["source"]["document_hash"] != row["document_hash"]
            or row["source_hash"] != claim_content.source_digest(inputs, row["document_hash"])
        ):
            raise ValueError("Claim set does not match its original observed inputs")


def validate_request_record(record):
    """Validate private recovery records; paths remain provenance, never restore targets."""
    if not isinstance(record, dict) or set(record) != REQUEST_FIELDS:
        raise ValueError("Invalid generation receipt fields")
    if record["status"] not in ("accepted", "candidate"):
        raise ValueError("Invalid generation receipt status")
    data = json.loads(record["context_json"])
    fields = {
        "version",
        "started_at",
        "request_id",
        "db_path",
        "database_identity",
        "binding",
        "table",
        "owner_id",
        "key",
        "input_reader",
        "target",
        "parent_created_at",
        "observation",
        "inputs",
        "document",
    }
    allowed = (fields, fields | {"parent_lifecycle"})
    if isinstance(data, dict) and data.get("table") == "paper_later_outcomes":
        from paper_daily.later_outcomes import validate_private

        allowed = (fields | {"parent_lifecycle", "later_source"},)
        validate_private(data.get("later_source"), document=data.get("document"))
    if isinstance(data, dict) and data.get("table") == "paper_highlight_analysis":
        allowed = (fields | {"parent_lifecycle", "highlight_plan"},)
    if (
        isinstance(data, dict)
        and data.get("table") == "paper_claim_sets"
        and "claim_restore" in data
    ):
        allowed = (fields | {"parent_lifecycle", "claim_restore"},)
    if not isinstance(data, dict) or set(data) not in allowed:
        raise ValueError("Invalid generation context fields")
    # Old recovery records remain readable, but cannot automatically publish.
    # They need explicit target selection in the review workflow.
    if "parent_lifecycle" in data and (
        not isinstance(data["parent_lifecycle"], str)
        or not re.fullmatch(r"[0-9a-f]{32}", data["parent_lifecycle"])
    ):
        raise ValueError("Invalid generation parent lifecycle")
    if data.get("version") != 1 or data.get("request_id") != record["request_id"]:
        raise ValueError("Invalid generation receipt identity")
    from paper_daily.sync_content import _stamp

    _stamp(data["started_at"])
    if not isinstance(data["db_path"], str) or not (
        PurePosixPath(data["db_path"]).is_absolute()
        or PureWindowsPath(data["db_path"]).is_absolute()
    ):
        raise ValueError("Invalid generation database provenance")
    if (
        not isinstance(data["database_identity"], list)
        or len(data["database_identity"]) != 2
        or any(type(value) is not int or value < 0 for value in data["database_identity"])
    ):
        raise ValueError("Invalid generation database identity")
    if data["binding"] is not None and (
        not isinstance(data["binding"], dict)
        or set(data["binding"]) != {"workspace_id", "device_id"}
        or any(not isinstance(value, str) or not value for value in data["binding"].values())
    ):
        raise ValueError("Invalid generation workspace provenance")
    if data["table"] not in REGISTRY or data["input_reader"] not in (
        "target",
        REGISTRY[data["table"]][3],
    ):
        raise ValueError("Unknown generation target")
    if data["key"] != "main" or not isinstance(data["owner_id"], str) or not data["owner_id"]:
        raise ValueError("Invalid generation owner")
    if data["target"] is not None and not isinstance(data["target"], dict):
        raise ValueError("Invalid generation target snapshot")
    if data["document"] is not None:
        document = data["document"]
        if not isinstance(document, dict) or set(document) != {
            "sha256",
            "path",
            "target",
            "managed",
        }:
            raise ValueError("Invalid generation document provenance")
        if not isinstance(document["sha256"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", document["sha256"]
        ):
            raise ValueError("Invalid generation document hash")
        if not isinstance(document["path"], str) or type(document["managed"]) is not bool:
            raise ValueError("Invalid generation document source")
    context = GenerationContext(_json(data))
    _validate_row(context, json.loads(record["row_json"]))
    if record["status"] == "candidate":
        if not isinstance(record["candidate_id"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", record["candidate_id"]
        ):
            raise ValueError("Invalid candidate identity")
    elif record["candidate_id"] is not None:
        raise ValueError("Accepted receipt cannot carry a candidate identity")
    if not isinstance(record["reason"], str) or len(record["reason"]) > 1000:
        raise ValueError("Invalid publication reason")
    _json(record)
    return record


def list_recovery_requests(database_path):
    """Read bounded owned sidecars for backup; returned paths are provenance only."""
    database = Path(database_path).resolve()
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_capture_binding'"
        ).fetchone()
        binding = (
            conn.execute(
                "SELECT workspace,device FROM research_capture_binding WHERE id=1"
            ).fetchone()
            if exists
            else None
        )
    binding = {"workspace_id": binding[0], "device_id": binding[1]} if binding else None
    root = database.parent / ".paperfact-generation"
    if not root.exists():
        return []
    for entry in (root, *root.parents):
        if _is_link(entry):
            raise ValueError("Generation recovery location cannot traverse links")
    records, total, count = [], 0, 0
    for namespace in root.iterdir():
        if (
            _is_link(namespace)
            or not namespace.is_dir()
            or not re.fullmatch(r"[0-9a-f]{64}", namespace.name)
        ):
            raise ValueError("Unexpected generation recovery entry")
        for path in namespace.iterdir():
            if (
                _is_link(path)
                or not path.is_file()
                or not re.fullmatch(r"[0-9a-f]{64}\.json", path.name)
            ):
                raise ValueError("Incomplete or invalid generation recovery artifact")
            count += 1
            total += path.stat().st_size
            if count > 10000 or path.stat().st_size > MAX_BYTES or total > 64 * 1024 * 1024:
                raise ValueError("Generation recovery archive exceeds limits")
            record = validate_request_record(json.loads(path.read_text(encoding="utf-8")))
            context = GenerationContext(record["context_json"])
            if _recovery_path(context) != path:
                raise ValueError("Generation recovery identity differs from its location")
            if context.data["db_path"] == str(database) and context.data["binding"] == binding:
                records.append(record)
    return records


def publish_generation(context, *, row):
    """Persist a valid output once, accepting it only against its captured inputs."""
    _validate_row(context, row)
    data = context.data
    row_json = _json(row)
    pdf_current = _document_current(context)
    from paper_daily.sync_source_files import stage_claim_source

    prepared_source = stage_claim_source(context, row)
    if context.table == "paper_later_outcomes":
        from paper_daily.later_outcome_sources import stage
        from paper_daily.later_outcomes import validate_generation

        validate_generation(context, row)
        prepared_source = stage(context, row)
    try:
        if _identity(context.db_path) != data["database_identity"]:
            return _retain_outside_database(context, row, "Research database was replaced")
        conn = _connect(context.db_path)
    except (OSError, sqlite3.DatabaseError):
        return _retain_outside_database(context, row, "Original research database is unavailable")
    try:
        conn.execute("BEGIN IMMEDIATE")
        if (
            _identity(context.db_path) != data["database_identity"]
            or _binding(conn) != data["binding"]
        ):
            conn.rollback()
            return _retain_outside_database(context, row, "Original workspace binding changed")
        _setup(conn)
        prior = conn.execute(
            "SELECT * FROM research_generation_requests WHERE request_id=?", (context.request_id,)
        ).fetchone()
        if prior:
            if prior["context_json"] != context._json or prior["row_json"] != row_json:
                raise ValueError("Generation request identity was reused for different content")
            return Publication(
                prior["status"], context.request_id, prior["candidate_id"], prior["reason"]
            )
        try:
            reason = _stale(conn, context)
        except ValueError:
            reason = "Research inputs or identity are no longer supported"
        except sqlite3.DatabaseError:
            conn.rollback()
            return _retain_outside_database(context, row, "Original research schema is unavailable")
        if not pdf_current:
            reason = "Input PDF changed or is unavailable"
        # Metadata/currentness recheck under the same publication transaction closes
        # the desired-document change window after off-thread byte verification.
        if context._document is not None and not context._document._owner.current(
            context._document
        ):
            reason = "Input PDF changed or is unavailable"
        status = "candidate" if reason else "accepted"
        candidate_id = _digest({"context": data, "row": row}) if reason else None
        if not reason:
            observation = data["observation"]
            sources = (
                {observation["entity_id"]: data["document"]["sha256"] if data["document"] else None}
                if observation and data["input_reader"] != "target"
                else {}
            )
            observations = [observation]
            if data["table"] == "paper_highlight_analysis":
                from paper_daily.highlight_publication import expectations

                observations.extend(expectations(context))
                sources.update(
                    {item["entity_id"]: data["document"]["sha256"] for item in observations if item}
                )
            with sync_capture.expecting(conn, observations, source_hashes=sources):
                from paper_daily.sync_source_files import apply_claim_source_in

                if context.table == "paper_later_outcomes":
                    from paper_daily.later_outcome_sources import apply_in

                    apply_in(conn, context, row, prepared_source)
                else:
                    apply_claim_source_in(conn, context, row, prepared_source)
                if (
                    data["table"] == "paper_claim_sets"
                    and data.get("claim_restore")
                    and sync_capture.enabled(conn)
                ):
                    from paper_daily.claim_publication import apply_restore

                    apply_restore(conn, context, row)
                else:
                    columns = list(row)
                    owner_column = REGISTRY[data["table"]][1]
                    updates = ",".join(
                        f'"{key}"=excluded."{key}"' for key in columns if key != owner_column
                    )
                    quoted = ",".join(f'"{key}"' for key in columns)
                    conn.execute(
                        f'INSERT INTO "{data["table"]}"({quoted}) VALUES('
                        + ",".join("?" for _ in columns)
                        + f') ON CONFLICT("{owner_column}") DO UPDATE SET {updates}',
                        tuple(row.values()),
                    )
                if data["table"] == "paper_highlight_analysis":
                    from paper_daily.highlight_publication import apply

                    apply(conn, context)
                with sync_capture.suppress_capture(conn):
                    conn.execute(
                        "INSERT INTO research_generation_requests VALUES(?,?,?,?,?,?)",
                        (context.request_id, context._json, row_json, status, None, "ok"),
                    )
                if context.table == "paper_later_outcomes":
                    from paper_daily.store import set_kv

                    set_kv(conn, "analyze.failed.later." + context.owner_id, None)
                conn.commit()
        else:
            with sync_capture.suppress_capture(conn):
                conn.execute(
                    "INSERT INTO research_generation_requests VALUES(?,?,?,?,?,?)",
                    (context.request_id, context._json, row_json, status, candidate_id, reason),
                )
            conn.commit()
        return Publication(status, context.request_id, candidate_id, reason or "ok")
    finally:
        conn.close()


def publish_generated(context, *, row):
    """Retain valid completed output even after an unexpected delivery failure."""
    _validate_row(context, row)
    # Validate the sealed inputs before any fallback can use their private paths.
    validate_request_record(
        {
            "request_id": context.request_id,
            "context_json": context._json,
            "row_json": _json(row),
            "status": "accepted",
            "candidate_id": None,
            "reason": "ok",
        }
    )
    try:
        return publish_generation(context, row=row)
    except Exception:
        return retain_failed_generated(context, row)


def retain_failed_generated(context, row):
    """Probe exact committed success; otherwise preserve the original bounded result."""
    _validate_row(context, row)
    validate_request_record(
        {
            "request_id": context.request_id,
            "context_json": context._json,
            "row_json": _json(row),
            "status": "accepted",
            "candidate_id": None,
            "reason": "ok",
        }
    )
    prior = None
    try:
        if _identity(context.db_path) == context.data["database_identity"]:
            with closing(_connect(context.db_path)) as conn:
                if (
                    _identity(context.db_path) == context.data["database_identity"]
                    and _binding(conn) == context.data["binding"]
                ):
                    record = conn.execute(
                        "SELECT * FROM research_generation_requests WHERE request_id=?",
                        (context.request_id,),
                    ).fetchone()
                    if record is not None:
                        prior = validate_request_record(dict(record))
    except Exception:
        # A broken probe cannot authorize a write into today's replacement DB.
        # The record and its private location were validated before this probe.
        prior = None
    if prior is not None:
        if prior["context_json"] != context._json or prior["row_json"] != _json(row):
            raise ValueError("Generation delivery identity was reused for another result")
        return Publication(
            prior["status"], context.request_id, prior["candidate_id"], prior["reason"]
        )
    return _retain_outside_database(
        context, row, "Completed research retained after delivery failed"
    )


def publish_edit(context, *, row):
    """Retry a draft once per exact content while keeping its original observed base."""
    if context.data["input_reader"] != "target":
        raise ValueError("Manual saves require a target-only observation")
    data = context.data
    data["request_id"] = _digest({"request": context.request_id, "edit": row})
    return publish_generation(replace(context, _json=_context_json(data)), row=row)


def retry_publication(database_path, request_id=None):
    """Return an already durable outcome; stale candidates require explicit review."""
    if isinstance(database_path, GenerationContext):
        context = database_path
        path = _recovery_path(context)
        if path.exists():
            record = validate_request_record(json.loads(path.read_text(encoding="utf-8")))
            if record["context_json"] != context._json:
                raise ValueError("Retained generation context differs")
            return Publication(
                record["status"], context.request_id, record["candidate_id"], record["reason"]
            )
        database_path, request_id = context.db_path, context.request_id
    with closing(_connect(Path(database_path))) as conn:
        record = conn.execute(
            "SELECT * FROM research_generation_requests WHERE request_id=?", (request_id,)
        ).fetchone()
        if record is None:
            raise ValueError("Unknown generation request")
        record = validate_request_record(dict(record))
    return Publication(record["status"], request_id, record["candidate_id"], record["reason"])


def input_versions(context):
    """Sanitized portable provenance; completeness never means stale-proof."""
    data = context.data
    documents = []
    document = data["document"]
    if document and document["managed"] and document["target"]:
        target = document["target"]
        documents.append(
            {
                key: target[key]
                for key in (
                    "paper_id",
                    "operation_id",
                    "incarnation",
                    "parent_incarnation",
                    "sha256",
                )
            }
        )
    # SQL prompts can include untracked legacy rows/ranking state. Until each
    # consumed row has its own captured graph reference, do not claim completeness.
    return {
        "schema_version": 1,
        "entities": [],
        "documents": documents,
        "inputs_sha256": _digest(data["inputs"]),
        "complete": False,
    }
