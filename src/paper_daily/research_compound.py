"""Observed, typed publication of a paper's citation/followup/resource phase.

Feature inventories are local read dependencies, not whole-paper conflict domains.
Publication alone owns its transaction; network/model calls belong to producers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing, nullcontext
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import uuid4

from paper_daily import research_generation as generation
from paper_daily import sync_capture, sync_content

MAX_ROWS = 2000
MAX_BYTES = 8 * 1024 * 1024
TABLES = {
    "cites": ("citation", "ref_key"),
    "followups": ("followup", "work_id"),
    "resources": ("resource", "url"),
}
PHASES = {
    "citations": "cites",
    "fetch": "followups",
    "judge": "followups",
    "resources": "resources",
    "edit_reference": "cites",
    "edit_followup": "followups",
}
REQUEST_FIELDS = {
    "request_id",
    "context_json",
    "mutations_json",
    "status",
    "candidate_id",
    "reason",
}


@dataclass(frozen=True)
class Context:
    _json: str
    _document: object = None
    _connection: object = None

    @property
    def data(self):
        return json.loads(self._json)

    @property
    def database_path(self):
        return Path(self.data["db_path"]) if self.data["db_path"] else None

    db_path = database_path

    @property
    def request_id(self):
        return self.data["request_id"]

    @property
    def owner_id(self):
        return self.data["owner_id"]

    @property
    def table(self):
        return PHASES[self.data["phase"]]

    @property
    def started_at(self):
        return self.data["started_at"]

    @property
    def rows(self):
        return self.data["rows"]

    @property
    def paper(self):
        return self.data["paper"]

    @property
    def target(self):
        return self.rows[0] if self.rows else None


def _inventory(conn, table, owner, key=None):
    column = TABLES[table][1]
    rows = conn.execute(
        f'SELECT * FROM "{table}" WHERE paper_id=?'
        + (f' AND "{column}"=?' if key is not None else "")
        + f' ORDER BY "{column}" LIMIT ?',
        (owner, key, MAX_ROWS + 1) if key is not None else (owner, MAX_ROWS + 1),
    ).fetchall()
    if len(rows) > MAX_ROWS:
        raise ValueError("Research feature exceeds its record limit")
    return [dict(row) for row in rows]


def _paper(conn, owner, phase):
    columns = {
        "citations": "id,title,venue,year,abstract,doi,s2_id",
        "fetch": "id,title,doi,s2_id,arxiv_id",
        "judge": "id,title,venue,year,abstract",
        "resources": "id,title,arxiv_id,authors_json",
    }.get(phase, "id")
    row = conn.execute(f"SELECT {columns} FROM papers WHERE id=?", (owner,)).fetchone()
    return dict(row) if row is not None else None


def begin(conn, *, phase, owner_id, key=None):
    from paper_daily.store import now

    if phase not in PHASES or not isinstance(owner_id, str) or not owner_id:
        raise ValueError("Unsupported compound research scope")
    if phase.startswith("edit_") != (key is not None):
        raise ValueError("Manual edits require one exact row")
    table = PHASES[phase]
    path = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "")
    if path and conn.in_transaction:
        raise ValueError("Commit pending changes before starting research generation")
    from paper_daily.research_lifecycle import ensure_lifecycle, parent_lifecycle

    owned = not conn.in_transaction
    if owned:
        conn.execute("BEGIN IMMEDIATE")
    ensure_lifecycle(conn)
    if owned:
        conn.commit()
    if owned:
        conn.execute("BEGIN")
    try:
        paper = _paper(conn, owner_id, phase)
        if paper is None:
            raise ValueError("Research owner no longer exists")
        tokens, parent, portable = {}, None, None
        if sync_capture.enabled(conn):
            portable = conn.execute(
                "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (owner_id,)
            ).fetchone()[0]
            conn._capture_graph_cache = conn._capture_client._optimistic_graph(conn)
            parent = sync_capture.observe(conn, "paper", portable)
            if not parent["active"] or parent["incarnation"] is None:
                raise ValueError("Research owner is not ready for synchronized writes")
            state, _touches, _own = conn._capture_client._optimistic_graph(conn)
            # Graph state intentionally carries lifecycle only, not payloads.
            # The existing projection inventory retains typed natural identities,
            # including tombstones, so an old target still cannot be revived.
            targets = [row[0] for row in conn.execute(
                "SELECT entity_id FROM research_content_projection "
                "WHERE feature=? AND scope_kind='paper' AND scope_id=? LIMIT ?",
                (TABLES[table][0], portable, MAX_ROWS + 1),
            )]
            if len(targets) > MAX_ROWS:
                raise ValueError("Research observation exceeds its graph limit")
            for identity in targets:
                value = state.get(("research_content", identity))
                if value is None:
                    continue
                parents = value["parents"]
                if len(parents) != 1 or (
                    parents[0]["kind"], parents[0]["id"]
                ) != ("paper", portable):
                    raise ValueError("Research target has another dependency closure")
                tokens[identity] = sync_capture.observe(conn, "research_content", identity)
        data = {
            "version": 1,
            "request_id": str(uuid4()),
            "started_at": now(),
            "db_path": str(Path(path).resolve()) if path else None,
            "database_identity": generation._identity(path) if path else None,
            "binding": generation._binding(conn),
            "owner_id": owner_id,
            "phase": phase,
            "key": key,
            "rows": _inventory(conn, table, owner_id, key),
            "paper": paper,
            "portable": portable,
            "parent": parent,
            "tokens": tokens,
            "document": None,
            "text_source": None,
            "prompts": [],
            "parent_lifecycle": parent_lifecycle(conn, "paper", owner_id),
        }
        return Context(generation._context_json(data), _connection=conn if not path else None)
    finally:
        if owned:
            conn.rollback()


def read_text(context, *, pdf_root, text_root):
    """Read the exact captured PDF, or an explicitly legacy extracted-text file."""
    from paper_daily.document_reader import from_workspace
    from paper_daily.fetch import _safe_name

    data = context.data
    document = None
    if context.database_path is not None:
        reader = from_workspace(context.database_path, legacy_root=pdf_root)
        document = reader.resolve(context.owner_id)
        if (
            document.managed
            and not document.available
            or document.status in ("ambiguous", "invalid", "stale", "quota")
        ):
            raise ValueError("The current research PDF is unavailable")
    first = ""
    if document is not None and document.available:
        import pymupdf

        with pymupdf.open(document.path) as pdf:
            parts, total = [], 0
            for page in pdf:
                text = page.get_text()
                total += len(text.encode("utf-8"))
                if total > 3 * 1024 * 1024:
                    raise ValueError("Research PDF text exceeds its input limit")
                parts.append(text)
            first = parts[0] if parts else ""
            text = "\n".join(parts)
        data["document"] = {
            "sha256": document.sha256,
            "path": str(document.path.resolve()),
            "target": document.target,
            "managed": document.managed,
        }
        context = replace(context, _json=generation._context_json(data), _document=document)
        if not generation._document_current(context):
            raise ValueError("The input PDF changed while reading")
    else:
        path = Path(text_root) / (_safe_name(context.owner_id) + ".txt")
        raw = None
        if path.exists():
            if path.stat().st_size > 3 * 1024 * 1024:
                raise ValueError("Research text exceeds its input limit")
            with path.open("rb") as stream:
                raw = stream.read(3 * 1024 * 1024 + 1)
        if raw is not None and len(raw) > 3 * 1024 * 1024:
            raise ValueError("Research text exceeds its input limit")
        text = raw.decode("utf-8") if raw is not None else ""
        data["text_source"] = {
            "path": str(path.resolve()),
            "sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
        }
        context = replace(context, _json=generation._context_json(data))
    return context, text, first


def with_prompt(context, prompt):
    """Retain the exact bounded model input; local read-set guards remain authoritative."""
    if not isinstance(prompt, str) or len(prompt.encode("utf-8")) > 256 * 1024:
        raise ValueError("Compound model input exceeds its limit")
    data = context.data
    if len(data["prompts"]) >= 64:
        raise ValueError("Compound model batch count exceeds its limit")
    data["prompts"].append(prompt)
    return replace(context, _json=generation._context_json(data))


def _token(context, key):
    data = context.data
    if data["binding"] is None:
        return None
    identity = sync_content.content_id(
        {"kind": "paper", "id": data["portable"]}, TABLES[context.table][0], key
    )
    if identity in data["tokens"]:
        return data["tokens"][identity]
    parent = data["parent"]
    return {
        "workspace_id": data["binding"]["workspace_id"],
        "kind": "research_content",
        "entity_id": identity,
        "revision": 0,
        "predecessor": None,
        "incarnation": None,
        "active": False,
        "parents": [
            {
                "kind": "paper",
                "id": data["portable"],
                "incarnation": parent["incarnation"],
                "active": parent["active"],
            }
        ],
    }


def row(context, key, /, **values):
    """Construct a complete typed row, preserving a captured existing row's fields."""
    feature, column = TABLES[context.table]
    fields = sync_content.FEATURES[feature][2].split()
    existing = next((r for r in context.rows if r[column] == key), None)
    result = dict(existing) if existing else {name: None for name in fields}
    result.update(paper_id=context.owner_id, **{column: key})
    for name in ("edited", "influential", "own"):
        if name in fields and result.get(name) is None:
            result[name] = 0
    result.update(values)
    # Legacy sentinel timestamps are retained in the observation, normalized only
    # in the newly published row with a deterministic time shared by every retry.
    for name in ("written_at", "fetched_at", "checked_at"):
        if name in result:
            try:
                sync_content._stamp(result[name])
            except (ValueError, TypeError):
                result[name] = context.started_at
    return result


def citation_answered(value):
    """A reference key/title alone is not an explanation of its research role."""
    return (
        value.get("verdict") in ("必讀", "值得", "參考", "略過")
        and all(isinstance(value.get(k), str) and value[k].strip()
                for k in ("purpose", "gist", "why"))
    )


def _validate(context, mutations):
    if not isinstance(mutations, dict) or set(mutations) != {"puts", "deletes", "completion"}:
        raise ValueError("Unexpected compound mutation fields")
    puts, deletes = mutations["puts"], mutations["deletes"]
    if (
        not isinstance(puts, list)
        or not isinstance(deletes, list)
        or len(puts) + len(deletes) > MAX_ROWS
    ):
        raise ValueError("Compound mutation exceeds its record limit")
    feature, column = TABLES[context.table]
    fields = set(sync_content.FEATURES[feature][2].split())
    keys = []
    for value in puts:
        if not isinstance(value, dict) or set(value) != fields | {"paper_id", column}:
            raise ValueError("Unexpected compound output columns")
        if value["paper_id"] != context.owner_id:
            raise ValueError("Compound output belongs to another paper")
        key = value[column]
        values = {k: value[k] for k in fields}
        if values.get("contexts_json") is not None:
            values["contexts_json"] = json.loads(values["contexts_json"])
        sync_content.validate_payload(
            {
                "scope": {"kind": "paper", "id": "11111111-1111-4111-8111-111111111111"},
                "feature": feature,
                "key": key,
                "data": values,
                "source_document_hash": (context.data["document"] or {}).get("sha256"),
            }
        )
        keys.append(key)
    if any(not isinstance(k, str) or not k or len(k) > 4096 for k in deletes):
        raise ValueError("Invalid compound deletion key")
    if len(set(keys + deletes)) != len(keys) + len(deletes):
        raise ValueError("Duplicate compound target")
    phase = context.data["phase"]
    completion = mutations["completion"]
    if phase == "fetch":
        if completion is not None:
            sync_content._stamp(completion)
    elif phase == "resources":
        if completion not in ("text", "notext"):
            raise ValueError("Resource completion requires its input mode")
    elif phase == "citations" and completion is not None:
        if not isinstance(completion, dict) or set(completion) != {"kind", "sent", "answered"}:
            raise ValueError("Invalid typed citation coverage")
        if completion["kind"] != "citation_coverage":
            raise ValueError("Unknown citation coverage kind")
        for name in ("sent", "answered"):
            values = completion[name]
            if not isinstance(values, list) or len(values) > MAX_ROWS:
                raise ValueError("Citation coverage exceeds its limit")
            if any(not isinstance(k, str) or not k or len(k) > 4096 for k in values):
                raise ValueError("Invalid citation coverage key")
            if sorted(set(values)) != values:
                raise ValueError("Citation coverage keys must be unique and sorted")
        source = context.data["document"] or context.data["text_source"]
        if not source or not source.get("sha256") or not context.data["prompts"]:
            raise ValueError("Citation coverage requires its captured source and model input")
        sent, answered = set(completion["sent"]), set(completion["answered"])
        edited = {r[column] for r in context.rows if r.get("edited") and citation_answered(r)}
        explained = {r[column] for r in puts if citation_answered(r)}
        if not sent or answered != (explained | edited) & sent or set(keys) - sent:
            raise ValueError("Citation coverage differs from observed and published references")
        if deletes and len(answered) * 5 < len(sent) * 4:
            raise ValueError("Partial citation analysis cannot prune prior research")
    elif completion is not None:
        raise ValueError("Unexpected research completion flag")
    if phase not in ("citations", "resources") and deletes:
        raise ValueError("This phase cannot delete research")
    if phase.startswith("edit_") and (deletes or keys != [context.data["key"]]):
        raise ValueError("Manual edit must retain its exact target")
    originals = {r[column]: r for r in context.rows}
    if not phase.startswith("edit_") and any(
        originals.get(value[column], {}).get("edited") and value != originals[value[column]]
        for value in puts
    ):
        raise ValueError("A generated phase cannot overwrite manual research")
    if context.table == "resources":
        curated = {
            key
            for key, value in originals.items()
            if value["source"] not in ("pdf", "hf", "search")
        }
        if curated.intersection(deletes) or any(
            value[column] in curated and value != originals[value[column]] for value in puts
        ):
            raise ValueError("Resource discovery cannot overwrite curated resources")
    if any(originals.get(k, {}).get("edited") for k in deletes):
        raise ValueError("A generated phase cannot prune manual research")
    generation._json(mutations)


def _setup(conn):
    with sync_capture.suppress_capture(conn):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS research_compound_requests("
            "request_id TEXT PRIMARY KEY,context_json TEXT NOT NULL,"
            "mutations_json TEXT NOT NULL,status TEXT NOT NULL,"
            "candidate_id TEXT,reason TEXT NOT NULL)"
        )


def scope_current(context):
    """Whether a later independent phase still belongs to the original paper lifetime."""
    from paper_daily.research_lifecycle import parent_lifecycle

    data = context.data
    if context.database_path is None:
        return (
            parent_lifecycle(context._connection, "paper", context.owner_id)
            == data["parent_lifecycle"]
        )
    try:
        if generation._identity(context.database_path) != data["database_identity"]:
            return False
        with closing(generation._connect(context.database_path)) as conn:
            if (
                generation._binding(conn) != data["binding"]
                or parent_lifecycle(conn, "paper", context.owner_id) != data["parent_lifecycle"]
            ):
                return False
            if data["parent"] is not None:
                parent = sync_capture.observe(conn, "paper", data["portable"])
                return all(parent[key] == data["parent"][key] for key in ("incarnation", "active"))
            return True
    except (OSError, ValueError, sqlite3.DatabaseError):
        return False


def _stale(conn, context, mutations):
    from paper_daily.research_lifecycle import parent_lifecycle

    data = context.data
    if parent_lifecycle(conn, "paper", context.owner_id) != data["parent_lifecycle"]:
        return "Research owner lifecycle changed"
    if data["parent"] is not None:
        current_parent = sync_capture.observe(conn, "paper", data["portable"])
        if any(current_parent[k] != data["parent"][k] for k in ("incarnation", "active")):
            return "Research owner lifecycle changed"
    if _paper(conn, context.owner_id, data["phase"]) != data["paper"]:
        return "Research inputs or owner changed"
    if _inventory(conn, context.table, context.owner_id, data["key"]) != context.rows:
        return "Research feature inventory changed"
    putting = {r[TABLES[context.table][1]] for r in mutations["puts"]}
    for key in list(putting) + mutations["deletes"]:
        observed = _token(context, key)
        if (
            key in putting and observed is not None and observed["incarnation"] is not None
            and not observed["active"]
        ):
            return "Research target was deleted; explicit restore is required"
        if sync_capture.observe_target(
            conn, "paper", context.owner_id, TABLES[context.table][0], key
        ) != _token(context, key):
            return "Research target or parent changed"
    return None


def _input_current(context):
    if not generation._document_current(context):
        return False
    source = context.data["text_source"]
    if source:
        path = Path(source["path"])
        try:
            if not path.exists():
                return source["sha256"] is None
            if path.stat().st_size > 3 * 1024 * 1024:
                return False
            return hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"]
        except OSError:
            return False
    return True


def _recovery_path(context):
    namespace = generation._digest(
        {k: context.data[k] for k in ("db_path", "database_identity", "binding")}
    )
    return (
        context.database_path.parent
        / ".paperfact-compound"
        / namespace
        / (generation._digest(context.request_id) + ".json")
    )


def _record(context, mutations, status, reason):
    return {
        "request_id": context.request_id,
        "context_json": context._json,
        "mutations_json": generation._json(mutations),
        "status": status,
        "candidate_id": generation._digest({"context": context.data, "mutations": mutations})
        if status == "candidate"
        else None,
        "reason": reason,
    }


def _outcome(record):
    return generation.Publication(
        record["status"], record["request_id"], record["candidate_id"], record["reason"]
    )


def _retain(context, mutations, reason):
    if context.database_path is None:
        raise OSError("In-memory research cannot retain a durable failure candidate")
    path = _recovery_path(context)
    for item in (path, *path.parents):
        if generation._is_link(item):
            raise ValueError("Compound recovery cannot traverse links")
    path.parent.mkdir(parents=True, exist_ok=True)
    record = _record(context, mutations, "candidate", reason)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(generation._json(record).encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
    try:
        try:
            os.link(temporary, path)
        except FileExistsError:
            prior = validate_request_record(json.loads(path.read_text(encoding="utf-8")))
            if (
                prior["context_json"] != context._json
                or prior["mutations_json"] != record["mutations_json"]
            ):
                raise ValueError("Compound request reused for different content") from None
            return _outcome(prior)
    finally:
        temporary.unlink(missing_ok=True)
    return _outcome(record)


def publish(context, *, puts, deletes=(), completion=None, manual=False):
    mutations = {"puts": puts, "deletes": list(deletes), "completion": completion}
    _validate(context, mutations)
    if manual:
        data = context.data
        data["request_id"] = generation._digest({"request": context.request_id, "edit": mutations})
        context = replace(context, _json=generation._context_json(data))
    if context.database_path is not None:
        recovery = _recovery_path(context)
        if recovery.exists():
            prior = validate_request_record(json.loads(recovery.read_text(encoding="utf-8")))
            if prior["context_json"] != context._json or prior[
                "mutations_json"
            ] != generation._json(mutations):
                raise ValueError("Compound request reused for different content")
            return _outcome(prior)
    try:
        return _publish(context, mutations)
    except (OSError, sqlite3.DatabaseError):
        if manual:
            raise
        # A commit reply can fail after the complete transaction was accepted.
        try:
            return retry_publication(context)
        except (OSError, sqlite3.DatabaseError, ValueError):
            return _retain(context, mutations, "Research storage failed")


def _publish(context, mutations):
    data = context.data
    valid_input = _input_current(context)
    if context.database_path is not None:
        try:
            if generation._identity(context.database_path) != data["database_identity"]:
                return _retain(context, mutations, "Original research database changed")
            conn = generation._connect(context.database_path)
        except (OSError, sqlite3.DatabaseError):
            return _retain(context, mutations, "Original research database unavailable")
    else:
        conn = context._connection
    owned = context.database_path is not None
    try:
        conn.execute("BEGIN IMMEDIATE" if owned else "SAVEPOINT compound_publish")
        if generation._binding(conn) != data["binding"] or (
            owned and generation._identity(context.database_path) != data["database_identity"]
        ):
            conn.rollback()
            return _retain(context, mutations, "Original workspace binding changed")
        _setup(conn)
        prior = conn.execute(
            "SELECT * FROM research_compound_requests WHERE request_id=?", (context.request_id,)
        ).fetchone()
        if prior:
            if prior["context_json"] != context._json or prior[
                "mutations_json"
            ] != generation._json(mutations):
                raise ValueError("Compound request reused for different content")
            if not owned:
                conn.execute("RELEASE compound_publish")
            return _outcome(dict(prior))
        if sync_capture.enabled(conn):
            conn._capture_graph_cache = conn._capture_client._optimistic_graph(conn)
        reason = _stale(conn, context, mutations)
        if (
            not valid_input
            or context._document is not None
            and not context._document._owner.current(context._document)
        ):
            reason = "Input document changed or is unavailable"
        record = _record(context, mutations, "candidate" if reason else "accepted", reason or "ok")
        keys = [r[TABLES[context.table][1]] for r in mutations["puts"]] + mutations["deletes"]
        observations = [_token(context, key) for key in keys]
        sources = {
            t["entity_id"]: (data["document"] or {}).get("sha256")
            for t in observations
            if t and not data["phase"].startswith("edit_")
        }
        expectation = (
            sync_capture.expecting(conn, observations, source_hashes=sources)
            if isinstance(conn, sync_capture.CaptureConnection)
            else nullcontext()
        )
        with expectation:
            if not reason:
                _apply(conn, context, mutations)
            graph = getattr(conn, "_capture_graph_cache", None)
            with sync_capture.suppress_capture(conn):
                conn.execute(
                    "INSERT INTO research_compound_requests VALUES(?,?,?,?,?,?)",
                    tuple(
                        record[k]
                        for k in (
                            "request_id",
                            "context_json",
                            "mutations_json",
                            "status",
                            "candidate_id",
                            "reason",
                        )
                    ),
                )
            # The trusted receipt insert changes no graph state. Preserve the
            # transaction-local snapshot for the existing incremental outbox flush.
            if graph is not None:
                conn._capture_graph_cache = graph
            if owned:
                conn.commit()
            else:
                conn.execute("RELEASE compound_publish")
        return _outcome(record)
    except BaseException:
        if not owned:
            conn.execute("ROLLBACK TO compound_publish")
            conn.execute("RELEASE compound_publish")
        raise
    finally:
        if owned:
            conn.close()


def _apply(conn, context, mutations):
    table, column = context.table, TABLES[context.table][1]
    for key in mutations["deletes"]:
        conn.execute(
            f'DELETE FROM "{table}" WHERE paper_id=? AND "{column}"=?', (context.owner_id, key)
        )
    for value in mutations["puts"]:
        columns = list(value)
        names = ",".join('"' + name + '"' for name in columns)
        updates = ",".join(
            f'"{name}"=excluded."{name}"' for name in columns if name not in ("paper_id", column)
        )
        conn.execute(
            f'INSERT INTO "{table}"({names}) VALUES('
            + ",".join("?" for _ in columns)
            + f') ON CONFLICT(paper_id,"{column}") DO UPDATE SET {updates}',
            tuple(value.values()),
        )
    # Citation coverage stays inside the atomic observed receipt. It is derived
    # completion evidence, not a legacy KV writer or a separate shared domain.
    if mutations["completion"] is not None and context.data["phase"] in ("fetch", "resources"):
        from paper_daily.store import set_kv

        prefix = "resources:" if context.data["phase"] == "resources" else "followups.checked."
        set_kv(conn, prefix + context.owner_id, mutations["completion"])


def _validate_context(data):
    def text(value, maximum=4096):
        if not isinstance(value, str) or not value or len(value) > maximum:
            raise ValueError("Invalid compound observation text")

    def absolute(value):
        text(value, 32768)
        if not (PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()):
            raise ValueError("Compound provenance requires an absolute path")

    def token(value):
        fields = {
            "workspace_id",
            "kind",
            "entity_id",
            "revision",
            "predecessor",
            "incarnation",
            "active",
            "parents",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise ValueError("Invalid compound graph observation")
        for key in ("workspace_id", "kind", "entity_id"):
            text(value[key])
        if (
            type(value["revision"]) is not int
            or value["revision"] < 0
            or type(value["active"]) is not bool
        ):
            raise ValueError("Invalid compound observed revision")
        for key in ("predecessor", "incarnation"):
            if value[key] is not None:
                text(value[key])
        if not isinstance(value["parents"], list) or len(value["parents"]) > 1:
            raise ValueError("Invalid compound observed parent")
        for parent in value["parents"]:
            if not isinstance(parent, dict) or set(parent) != {
                "kind",
                "id",
                "incarnation",
                "active",
            }:
                raise ValueError("Invalid compound observed parent fields")
            if parent["kind"] != "paper" or type(parent["active"]) is not bool:
                raise ValueError("Invalid compound observed paper parent")
            text(parent["id"])
            if parent["incarnation"] is not None:
                text(parent["incarnation"])

    if (
        not isinstance(data["prompts"], list)
        or len(data["prompts"]) > 64
        or any(
            not isinstance(prompt, str) or len(prompt.encode("utf-8")) > 256 * 1024
            for prompt in data["prompts"]
        )
    ):
        raise ValueError("Invalid compound model-input snapshot")
    text(data["request_id"], 128)
    text(data["owner_id"], 1024)
    if not isinstance(data["parent_lifecycle"], str) or not re.fullmatch(
        "[a-f0-9]{32}", data["parent_lifecycle"]
    ):
        raise ValueError("Invalid compound local lifecycle")
    if data["db_path"] is not None:
        absolute(data["db_path"])
        if (
            not isinstance(data["database_identity"], list)
            or len(data["database_identity"]) != 2
            or any(type(value) is not int or value < 0 for value in data["database_identity"])
        ):
            raise ValueError("Invalid compound database identity")
    elif data["database_identity"] is not None or data["binding"] is not None:
        raise ValueError("In-memory observations cannot carry workspace ownership")
    if data["binding"] is None:
        if data["parent"] is not None or data["portable"] is not None or data["tokens"]:
            raise ValueError("Unbound observations cannot invent graph ownership")
    else:
        if not isinstance(data["binding"], dict) or set(data["binding"]) != {
            "workspace_id",
            "device_id",
        }:
            raise ValueError("Invalid compound workspace binding")
        for value in data["binding"].values():
            text(value, 128)
        sync_content._uuid(data["portable"])
        token(data["parent"])
        if data["parent"]["kind"] != "paper" or data["parent"]["entity_id"] != data["portable"]:
            raise ValueError("Compound parent differs from owner")
        if len(data["tokens"]) > MAX_ROWS:
            raise ValueError("Compound graph observation exceeds limit")
        for identity, value in data["tokens"].items():
            token(value)
            if (
                value["kind"] != "research_content"
                or value["entity_id"] != identity
                or any(parent["id"] != data["portable"] for parent in value["parents"])
            ):
                raise ValueError("Compound content observation belongs to another owner")
    table = PHASES[data["phase"]]
    feature, column = TABLES[table]
    columns = set(sync_content.FEATURES[feature][2].split()) | {"paper_id", column}
    keys = set()
    for row in data["rows"]:
        if not isinstance(row, dict) or set(row) != columns or row["paper_id"] != data["owner_id"]:
            raise ValueError("Invalid compound captured row")
        text(row[column])
        if row[column] in keys:
            raise ValueError("Duplicate compound captured row")
        keys.add(row[column])
    if data["phase"].startswith("edit_"):
        text(data["key"])
        if len(data["rows"]) > 1 or keys - {data["key"]}:
            raise ValueError("Manual observation belongs to another item")
    elif data["key"] is not None:
        raise ValueError("Generated phase cannot carry an edit key")
    if not isinstance(data["paper"], dict) or data["paper"].get("id") != data["owner_id"]:
        raise ValueError("Invalid captured input owner")
    if data["document"] is not None:
        document = data["document"]
        if not isinstance(document, dict) or set(document) != {
            "sha256",
            "path",
            "target",
            "managed",
        }:
            raise ValueError("Invalid compound document provenance")
        absolute(document["path"])
        sync_content._hash(document["sha256"])
        if (
            type(document["managed"]) is not bool
            or document["target"] is not None
            and not isinstance(document["target"], dict)
        ):
            raise ValueError("Invalid compound document identity")
        if document["managed"]:
            from paper_daily.sync_documents import _validate_target

            _validate_target(document["target"])
            if document["target"]["sha256"] != document["sha256"]:
                raise ValueError("Compound document hashes disagree")
        elif document["target"] is not None:
            raise ValueError("Legacy document cannot claim managed provenance")
    if data["text_source"] is not None:
        source = data["text_source"]
        if (
            not isinstance(source, dict)
            or set(source) != {"path", "sha256"}
            or data["document"] is not None
        ):
            raise ValueError("Invalid compound legacy text provenance")
        absolute(source["path"])
        sync_content._hash(source["sha256"], nullable=True)


def validate_request_record(record):
    if not isinstance(record, dict) or set(record) != REQUEST_FIELDS:
        raise ValueError("Invalid compound receipt fields")
    data = json.loads(record["context_json"])
    fields = {
        "version",
        "request_id",
        "started_at",
        "db_path",
        "database_identity",
        "binding",
        "owner_id",
        "phase",
        "key",
        "rows",
        "paper",
        "portable",
        "parent",
        "tokens",
        "document",
        "text_source",
        "parent_lifecycle",
        "prompts",
    }
    if not isinstance(data, dict) or set(data) != fields or data["version"] != 1:
        raise ValueError("Invalid compound observation")
    if data["phase"] not in PHASES or not isinstance(data["owner_id"], str) or not data["owner_id"]:
        raise ValueError("Invalid compound owner/feature")
    if data["request_id"] != record["request_id"] or not isinstance(record["request_id"], str):
        raise ValueError("Invalid compound receipt identity")
    if (
        not isinstance(data["rows"], list)
        or len(data["rows"]) > MAX_ROWS
        or not isinstance(data["tokens"], dict)
    ):
        raise ValueError("Invalid compound inventory")
    sync_content._stamp(data["started_at"])
    _validate_context(data)
    if (
        record["status"] not in ("accepted", "candidate")
        or not isinstance(record["reason"], str)
        or len(record["reason"]) > 1000
    ):
        raise ValueError("Invalid compound receipt state")
    context = Context(generation._context_json(data))
    mutations = json.loads(record["mutations_json"])
    _validate(context, mutations)
    expected = _record(context, mutations, record["status"], record["reason"])
    if expected["candidate_id"] != record["candidate_id"]:
        raise ValueError("Compound candidate identity differs")
    generation._json(record)
    return record


def retry_publication(context):
    path = _recovery_path(context)
    if path.exists():
        record = validate_request_record(json.loads(path.read_text(encoding="utf-8")))
    else:
        with closing(generation._connect(context.database_path)) as conn:
            found = conn.execute(
                "SELECT * FROM research_compound_requests WHERE request_id=?", (context.request_id,)
            ).fetchone()
            if found is None:
                raise ValueError("Unknown compound publication")
            record = validate_request_record(dict(found))
    if record["context_json"] != context._json:
        raise ValueError("Compound observation differs")
    return _outcome(record)


def list_recovery_requests(database_path):
    database = Path(database_path).resolve()
    root = database.parent / ".paperfact-compound"
    if not root.exists():
        return []
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_capture_binding'"
        ).fetchone()
        row = (
            conn.execute(
                "SELECT workspace,device FROM research_capture_binding WHERE id=1"
            ).fetchone()
            if exists
            else None
        )
        binding = {"workspace_id": row[0], "device_id": row[1]} if row else None
    for path in (root, *root.parents):
        if generation._is_link(path):
            raise ValueError("Compound recovery cannot traverse links")
    records, count, total = [], 0, 0
    for namespace in root.iterdir():
        if (
            generation._is_link(namespace)
            or not namespace.is_dir()
            or not re.fullmatch("[a-f0-9]{64}", namespace.name)
        ):
            raise ValueError("Invalid compound recovery namespace")
        for path in namespace.iterdir():
            if (
                generation._is_link(path)
                or not path.is_file()
                or not re.fullmatch("[a-f0-9]{64}\\.json", path.name)
            ):
                raise ValueError("Invalid compound recovery record")
            count += 1
            size = path.stat().st_size
            total += size
            if count > 10000 or size > MAX_BYTES or total > 64 * 1024 * 1024:
                raise ValueError("Compound recovery exceeds archive limits")
            record = validate_request_record(json.loads(path.read_text(encoding="utf-8")))
            context = Context(record["context_json"])
            if _recovery_path(context) != path:
                raise ValueError("Compound recovery location differs")
            if context.database_path == database and context.data["binding"] == binding:
                records.append(record)
    return records
