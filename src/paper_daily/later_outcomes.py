"""Typed, input-bound queried-empty later-work outcome; never an overview."""

from __future__ import annotations

import json
import re
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path

from paper_daily import config
from paper_daily import research_evidence as evidence
from paper_daily import research_generation as generation
from paper_daily.document_reader import from_workspace
from paper_daily.research_lifecycle import parent_lifecycle

TABLE = "paper_later_outcomes"
FEATURE = "later_outcome"
FORMAT = "paperfact.later-outcome.v1"
POLICY = "followups.empty-query.v1"
MAX_BODY = 32 * 1024
FIELDS = "body_json document_hash written_at"
_SEAL = object()
PAPER_FIELDS = ["title", "venue", "year", "abstract", "doi", "s2_id", "arxiv_id"]


def initialize(conn):
    if not conn.in_transaction:
        raise ValueError("Later outcome initialization requires a transaction")
    schema = (
        "CREATE TABLE IF NOT EXISTS paper_later_outcomes("
        "paper_id TEXT PRIMARY KEY,body_json TEXT NOT NULL,document_hash TEXT,"
        "written_at TEXT NOT NULL)"
    )
    triggers = {
        "paperfact_later_outcome_delete": (
            "CREATE TRIGGER IF NOT EXISTS paperfact_later_outcome_delete AFTER DELETE ON papers "
            "BEGIN DELETE FROM paper_later_outcomes WHERE paper_id=OLD.id; END"
        ),
        "paperfact_later_outcome_identity": (
            "CREATE TRIGGER IF NOT EXISTS paperfact_later_outcome_identity "
            "AFTER UPDATE OF id ON papers WHEN OLD.id IS NOT NEW.id "
            "BEGIN DELETE FROM paper_later_outcomes WHERE paper_id=OLD.id; END"
        ),
    }
    exists = _exists(conn)
    if exists:
        info = [tuple(row) for row in conn.execute("PRAGMA table_info(paper_later_outcomes)")]
        expected = [
            ("paper_id", "TEXT", 0, None, 1),
            ("body_json", "TEXT", 1, None, 0),
            ("document_hash", "TEXT", 0, None, 0),
            ("written_at", "TEXT", 1, None, 0),
        ]
        if [row[1:] for row in info] != expected:
            raise ValueError("Later outcome schema requires explicit repair")

    def normalized(sql):
        return " ".join(re.sub(r"\bif not exists\b", "", sql.casefold()).split()).rstrip(";")

    missing_triggers = []
    for name, sql in triggers.items():
        found = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,)
        ).fetchone()
        if found and normalized(found[0]) != normalized(sql):
            raise ValueError("Later outcome parent cleanup requires explicit repair")
        if not found:
            missing_triggers.append(sql)
    if not exists:
        conn.execute(schema)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='papers'").fetchone():
        for sql in missing_triggers:
            conn.execute(sql)


def _exists(conn):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone())


def inputs(conn, paper_id):
    row = conn.execute(
        "SELECT " + ",".join(PAPER_FIELDS) + " FROM papers WHERE id=?", (paper_id,)
    ).fetchone()
    paper = dict(zip(PAPER_FIELDS, row, strict=True)) if row else None
    from paper_daily import followups

    result = {
        "paper": paper,
        "lookup_policy": {
            "version": POLICY,
            "most_cited": followups.MOST_CITED,
            "newest": followups.NEWEST,
        },
    }
    for table in ("cites", "followups"):
        rows = conn.execute(
            'SELECT * FROM "' + table + '" WHERE paper_id=? LIMIT ?',
            (paper_id, generation.MAX_ROWS + 1),
        ).fetchall()
        if len(rows) > generation.MAX_ROWS:
            raise ValueError("Later outcome inventory exceeds its bound")
        # Full inventories, including unjudged rows; aliases never enter the digest.
        result[table] = [{k: v for k, v in dict(row).items() if k != "paper_id"} for row in rows]
    for table, key in (("dives", "dive"), ("paper_context", "overview")):
        value = conn.execute(
            'SELECT * FROM "' + table + '" WHERE paper_id=?', (paper_id,)
        ).fetchone()
        result[key] = (
            generation._digest({k: v for k, v in dict(value).items() if k != "paper_id"})
            if value
            else None
        )
    return result


def _empty(value):
    return (
        value["paper"] is not None
        and not value["cites"]
        and not value["followups"]
        and value["overview"] is None
    )


def decode(value):
    from paper_daily.sync_content import _stamp, _text
    from paper_daily.sync_files import closed, digest

    if not isinstance(value, str) and len(generation._json(value).encode("utf-8")) > MAX_BODY:
        raise ValueError("Later outcome exceeds its bound")
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_BODY:
            raise ValueError("Later outcome exceeds its bound")

        def pairs(rows):
            result = {}
            for key, item in rows:
                if key in result:
                    raise ValueError("Duplicate later-outcome field")
                result[key] = item
            return result

        def invalid(_value):
            raise ValueError("Nonfinite later-outcome value")

        try:
            value = json.loads(value, object_pairs_hook=pairs, parse_constant=invalid)
        except (RecursionError, UnicodeError) as exc:
            raise ValueError("Invalid bounded later-outcome JSON") from exc
    closed(value, {"format", "state", "policy", "input_hash", "query", "source"})
    if (value["format"], value["state"], value["policy"]) != (
        FORMAT,
        "queried_no_judged_inputs",
        POLICY,
    ):
        raise ValueError("Unsupported later outcome")
    digest(value["input_hash"])
    query = value["query"]
    closed(query, {"request_id", "queried_at", "lookup", "providers"})
    from uuid import UUID

    if (
        not isinstance(query["request_id"], str)
        or str(UUID(query["request_id"])) != query["request_id"]
    ):
        raise ValueError("Invalid later query request")
    _stamp(query["queried_at"])
    closed(query["lookup"], {"title", "doi", "s2_id", "arxiv_id"})
    for text in query["lookup"].values():
        _text(text, 8192)
    providers = query["providers"]
    closed(providers, {"openalex", "semantic_scholar"})
    if any(v not in ("queried_empty", "unknown") for v in providers.values()) or not any(
        v == "queried_empty" for v in providers.values()
    ):
        raise ValueError("An unknown query cannot establish empty completion")
    source = value["source"]
    closed(source, {"availability", "document_hash", "desired_hash"})
    if source["availability"] not in ("available", "unavailable"):
        raise ValueError("Unsupported later source state")
    for key in ("document_hash", "desired_hash"):
        if source[key] is not None:
            digest(source[key])
    if (source["document_hash"] is not None) != (source["availability"] == "available"):
        raise ValueError("Later outcome source identity differs from availability")
    if source["availability"] == "available" and source["desired_hash"] is not None:
        raise ValueError("Available original identity must be transport independent")
    return value


def validate_row(row):
    from paper_daily.sync_content import _stamp, _text
    from paper_daily.sync_files import closed

    closed(row, {"paper_id", "body_json", "document_hash", "written_at"})
    _text(row["paper_id"], 4096, nullable=False, nonempty=True)
    body = decode(row["body_json"])
    if body["source"]["document_hash"] != row["document_hash"]:
        raise ValueError("Later outcome has contradictory source hashes")
    _stamp(row["written_at"])
    return row


def validate_wire(payload):
    from paper_daily.sync_files import closed

    closed(payload["data"], {"body_json", "document_hash", "written_at"})
    if not isinstance(payload["data"]["body_json"], dict):
        raise ValueError("Later outcome wire body must be an object")
    body = decode(payload["data"]["body_json"])
    validate_row({"paper_id": payload["scope"]["id"], **payload["data"]})
    if body["source"]["document_hash"] != payload["source_document_hash"]:
        raise ValueError("Later outcome source differs from its envelope")


def _source(document):
    return {
        "availability": "available" if document.available else "unavailable",
        "document_hash": document.sha256 if document.available else None,
        "desired_hash": None if document.available else (document.target or {}).get("sha256"),
    }


@dataclass(frozen=True)
class PreparedEmpty:
    context: object
    source: object
    marker: tuple
    snapshot: object
    seal: object


def _reader(database, paper_id):
    """Use recorded workspace paths; current global legacy root is only a local fallback."""
    reader = from_workspace(database)
    if reader.legacy_root is not None:
        return reader
    from paper_daily import store

    if Path(store.DB_PATH).resolve() == Path(database).resolve():
        return from_workspace(database, legacy_root=config.PDF_DIR)
    # A managed binding can resolve its exact owned bytes without a legacy folder.
    return reader if reader.inspect(paper_id).managed else None


def prepare(fetch_context):
    """Explicit producer admission before remote work; no reads activate this path."""
    database = fetch_context.database_path
    if database is None:
        return None
    with closing(generation._connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        initialize(conn)
        conn.commit()
        context = generation.begin_generation(conn, table=TABLE, owner_id=fetch_context.owner_id)
    if not _empty(context.inputs):
        return None
    reader = _reader(database, context.owner_id)
    if reader is None:
        return None
    document = reader.resolve(context.owner_id)
    marker = (document.mode, document._target, document._context)
    try:
        snapshot = evidence.capture(document) if document.available else None
    except ValueError:
        return None  # Ordinary retrieval continues; no empty-completion claim.
    if snapshot:
        context = generation.bind_inputs(context, document=document)
    data = context.data
    data["later_source"] = {
        "availability": "available" if snapshot else "unavailable",
        "legacy_root": str(document._owner.legacy_root),
        "marker": generation._json(marker),
    }
    context = replace(context, _json=generation._context_json(data))
    return PreparedEmpty(context, document, marker, snapshot, _SEAL)


def _source_current(prepared):
    doc = prepared.source
    if doc.available:
        try:
            return doc._owner.current(doc) and bool(evidence._check_source(doc))
        except (ValueError, OSError):
            return False
    if doc._owner._closed:
        return False
    now = doc._owner.resolve(doc.local_id)
    return not now.available and (now.mode, now._target, now._context) == prepared.marker


def validate_generation(context, row):
    """The producer must refer to an actual accepted successful empty fetch."""
    from paper_daily import research_compound as compound

    body = decode(row["body_json"])
    if (
        not _empty(context.inputs)
        or generation._digest(context.inputs) != body["input_hash"]
        or row["document_hash"] != (context.data["document"] or {}).get("sha256")
    ):
        raise ValueError("Later outcome differs from captured inputs")
    with closing(generation._connect(context.db_path)) as conn:
        raw = conn.execute(
            "SELECT * FROM research_compound_requests WHERE request_id=?",
            (body["query"]["request_id"],),
        ).fetchone()
    if raw is None:
        raise ValueError("Later outcome has no accepted query")
    record = dict(raw)
    compound.validate_request_record(record)
    data, mutations = json.loads(record["context_json"]), json.loads(record["mutations_json"])
    lookup = {key: context.inputs["paper"][key] for key in ("title", "doi", "s2_id", "arxiv_id")}
    if (
        record["status"] != "accepted"
        or data["phase"] != "fetch"
        or data["owner_id"] != context.owner_id
        or data["database_identity"] != context.data["database_identity"]
        or data["binding"] != context.data["binding"]
        or data["parent_lifecycle"] != context.data["parent_lifecycle"]
        or mutations["puts"]
        or mutations["deletes"]
        or not mutations["completion"]
        or data["rows"]
        or body["query"]["queried_at"] != data["started_at"]
        or body["query"]["lookup"] != lookup
        or {k: data["paper"][k] for k in lookup} != lookup
    ):
        raise ValueError("Later outcome query/owner/input closure is invalid")


def complete(prepared, fetch_context, providers):
    if prepared is None:
        return None
    if not isinstance(prepared, PreparedEmpty) or prepared.seal is not _SEAL:
        raise ValueError("Later outcome requires its captured producer")
    if not _source_current(prepared):
        return None
    context = prepared.context
    body = {
        "format": FORMAT,
        "state": "queried_no_judged_inputs",
        "policy": context.inputs["lookup_policy"]["version"],
        "input_hash": generation._digest(context.inputs),
        "query": {
            "request_id": fetch_context.request_id,
            "queried_at": fetch_context.started_at,
            "lookup": {
                key: context.inputs["paper"][key] for key in ("title", "doi", "s2_id", "arxiv_id")
            },
            "providers": providers,
        },
        "source": _source(prepared.source),
    }
    row = {
        "paper_id": context.owner_id,
        "body_json": generation._json(body),
        "document_hash": body["source"]["document_hash"],
        "written_at": fetch_context.started_at,
    }
    validate_row(row)
    if prepared.snapshot:
        from paper_daily.source_snapshots import retain

        retain(context, prepared.snapshot)
    return generation.publish_generated(context, row=row)


def coverage(conn, paper_id, *, verify_source=True):
    """Read only; old KV/private receipts alone never establish completion."""
    unknown = {"state": "unknown", "reason": ""}
    if not _exists(conn):
        return unknown
    raw = conn.execute(
        "SELECT * FROM paper_later_outcomes WHERE paper_id=?", (paper_id,)
    ).fetchone()
    if raw is None:
        return unknown
    row = dict(raw)
    body = decode(row["body_json"])
    validate_row(row)
    actual = inputs(conn, paper_id)
    if (
        not parent_lifecycle(conn, "paper", paper_id)
        or generation._digest(actual) != body["input_hash"]
        or body["query"]["lookup"]
        != {key: actual["paper"][key] for key in ("title", "doi", "s2_id", "arxiv_id")}
    ):
        return unknown
    from paper_daily.store import get_kv

    failure = get_kv(conn, "analyze.failed.later." + paper_id)
    if failure:
        return {"state": "failed", "reason": failure}
    database = next(r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main")
    reader = _reader(Path(database), paper_id)
    if reader is None:
        return unknown
    if verify_source:
        document = reader.resolve(paper_id)
        if _source(document) != body["source"]:
            return unknown
        if document.available:
            try:
                evidence._check_source(document)
            except (ValueError, OSError):
                return unknown
    else:
        document = reader.inspect(paper_id)
        if body["source"]["availability"] == "available":
            return {"state": "unverified", "reason": "Checking the original for queried-empty work"}
        from paper_daily.fetch import _safe_name

        appeared = (
            not document.managed
            and reader.legacy_root is not None
            and (reader.legacy_root / (_safe_name(paper_id) + ".pdf")).exists()
        )
        if (
            appeared
            or document.available
            or (document.target or {}).get("sha256") != body["source"]["desired_hash"]
        ):
            return unknown
    return {
        "state": "queried_no_judged_inputs",
        "query": {
            "queried_at": body["query"]["queried_at"],
            "providers": dict(body["query"]["providers"]),
        },
        "reason": (
            "Queried successfully; no judged references or later work are available for an overview"
        ),
    }


def settled(conn, paper_id, *, verify_source=True):
    return (
        coverage(conn, paper_id, verify_source=verify_source)["state"] == "queried_no_judged_inputs"
    )


def validate_private(value, *, document=None):
    from paper_daily.sync_files import closed

    closed(value, {"availability", "legacy_root", "marker"})
    if value["availability"] not in ("available", "unavailable"):
        raise ValueError("Unknown captured later source state")
    if (value["availability"] == "available") != (document is not None):
        raise ValueError("Captured source availability differs from its document observation")
    if not isinstance(value["legacy_root"], str) or not isinstance(value["marker"], str):
        raise ValueError("Invalid captured later source scope")
    if len(value["legacy_root"]) > 4096 or len(value["marker"].encode()) > 16384:
        raise ValueError("Captured later source scope exceeds bounds")


def source_current(context):
    value = context.data["later_source"]
    validate_private(value, document=context.data["document"])
    if value["availability"] == "available":
        return True  # Existing generation document checks own byte/native proof.
    from paper_daily.fetch import _safe_name

    reader = from_workspace(context.db_path, legacy_root=Path(value["legacy_root"]))
    now = reader.inspect(context.owner_id)
    if now.available or generation._json((now.mode, now._target, now._context)) != value["marker"]:
        return False
    return not (
        not now.managed and (reader.legacy_root / (_safe_name(context.owner_id) + ".pdf")).exists()
    )
