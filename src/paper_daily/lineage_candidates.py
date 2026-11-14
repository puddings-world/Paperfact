"""Durable private Lineage proposals; no canonical row or reusable write authority."""

from __future__ import annotations

import hmac
import json
import os
import secrets
import sqlite3
from contextlib import closing, suppress
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

from paper_daily import claim_content, lineage_sets, research_lineage, source_snapshots
from paper_daily import research_generation as generation
from paper_daily.sync_files import read_json

FORMAT = "paperfact.lineage-proposal-context.v1"
REASONS = {
    "pending_lineage_publication",
    "lineage_target_changed",
    "caller_context_changed",
    "route_changed",
    "source_or_owner_changed",
    "cancelled_after_completion",
}
CONTEXT = {
    "format",
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
    "parent_lifecycle",
    "observation",
    "inputs",
    "document",
}
_KEY = secrets.token_bytes(32)


def _read(encoded):
    if not isinstance(encoded, str) or len(encoded.encode()) > generation.MAX_CONTEXT_BYTES:
        raise ValueError("Lineage proposal JSON exceeds its bound")
    return read_json(encoded.encode())


def validate(record):
    """Closed archive data, deliberately ineligible for generic publication/review."""
    claim_content.closed(record, generation.REQUEST_FIELDS)
    context, row = _read(record["context_json"]), _read(record["row_json"])
    has_base = isinstance(context, dict) and "publication_base" in context
    extra = {"publication_base"} if has_base else set()
    claim_content.closed(context, CONTEXT | extra)
    if "publication_base" in context:
        base = context["publication_base"]
        claim_content.closed(
            base, {"format", "request_id", "corpus_id", "target_hash", "observation_hash"}
        )
        if (base["format"] != "paperfact.lineage-target-base.v1"
                or base["request_id"] != context["request_id"]
                or base["corpus_id"] != context["key"]):
            raise ValueError("Lineage publication base identity changed")
        claim_content.digest(base["observation_hash"])
        if base["target_hash"] is not None:
            claim_content.digest(base["target_hash"])
    if (
        context["format"] != FORMAT
        or type(context["version"]) is not int
        or context["version"] != 1
        or context["table"] != lineage_sets.TABLE
        or context["input_reader"] != "lineage_proposal"
        or any(
            context[k] is not None
            for k in ("target", "parent_created_at", "observation", "document")
        )
    ):
        raise ValueError("Invalid archive-only Lineage context")
    lineage_sets.uuid(context["request_id"])
    lineage_sets.uuid(context["key"])
    if record["request_id"] != context["request_id"]:
        raise ValueError("Lineage proposal request identity changed")
    from paper_daily.sync_content import _stamp

    _stamp(context["started_at"])
    lineage_sets.validate_row(row)
    body = lineage_sets.decode(row["body_json"])
    if (
        row["paper_id"] != context["owner_id"]
        or row["corpus_key"] != context["key"]
        or body["inputs"] != dict(dive=None, close_reading=None)
    ):
        raise ValueError("Lineage proposal differs from its original-only corpus")
    path = context["db_path"]
    if not isinstance(path, str) or not (
        PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()
    ):
        raise ValueError("Invalid Lineage database provenance")
    identity = context["database_identity"]
    if (
        not isinstance(identity, list)
        or len(identity) != 2
        or any(type(i) is not int or i < 0 for i in identity)
    ):
        raise ValueError("Invalid Lineage database identity")
    inputs = context["inputs"]
    claim_content.closed(inputs, {"parents", "originals"})
    parents, originals = inputs["parents"], inputs["originals"]
    if (
        not isinstance(parents, list)
        or len(parents) != len(body["bindings"])
        or not isinstance(originals, list)
        or len(originals) > 4
    ):
        raise ValueError("Incomplete bounded Lineage provenance")
    by_source = {}
    for receipt in originals:
        source_snapshots.validate(receipt)
        owner = _read(receipt["owner_json"])
        if owner["format"] != source_snapshots.LINEAGE_FORMAT or owner["source_id"] in by_source:
            raise ValueError("Lineage proposal requires distinct typed original observations")
        by_source[owner["source_id"]] = (owner, receipt)
    expected = set()
    for parent, binding, source in zip(
        parents, body["bindings"], body["report"]["sources"], strict=True
    ):
        claim_content.closed(parent, {"paper_id", "parent_lifecycle"})
        if parent["paper_id"] != binding["paper_id"]:
            raise ValueError("Lineage proposal parent order changed")
        # Reuse the closed source-receipt lifecycle validator for available sources.
        token = parent["parent_lifecycle"]
        if (
            not isinstance(token, str)
            or len(token) != 32
            or any(c not in "0123456789abcdef" for c in token)
        ):
            raise ValueError("Invalid Lineage parent lifecycle")
        if source["availability"] == "unavailable":
            continue
        expected.add(source["id"])
        if source["id"] not in by_source:
            raise ValueError("Lineage proposal is missing an exact original")
        owner, receipt = by_source[source["id"]]
        if (
            owner["database_identity"] != identity
            or owner["binding"] != context["binding"]
            or owner["paper_id"] != parent["paper_id"]
            or owner["parent_lifecycle"] != token
            or owner["focal_paper_id"] != context["owner_id"]
            or owner["focal_lifecycle"] != context["parent_lifecycle"]
            or owner["corpus_id"] != context["key"]
            or owner["generation_request_id"] != context["request_id"]
            or owner["source_identity"] != source["identity"]
            or receipt["sha256"] != source["document_hash"]
        ):
            raise ValueError("Lineage proposal original belongs to another captured owner")
    if set(by_source) != expected or parents[0]["parent_lifecycle"] != context["parent_lifecycle"]:
        raise ValueError("Lineage proposal original closure changed")
    if (
        record["status"] != "candidate"
        or not isinstance(record["reason"], str)
        or record["reason"] not in REASONS
        or record["candidate_id"] != generation._digest({"context": context, "row": row})
    ):
        raise ValueError("Lineage proposal cannot grant accepted publication authority")
    return record


def originals(record):
    validate(record)
    context = _read(record["context_json"])
    return [{"sha256": r["sha256"], "size": r["size"]} for r in context["inputs"]["originals"]]


def _seal(encoded, target=None):
    proof = None
    if target is not None:
        from paper_daily.lineage_observation import lease_data

        lease_data(target)
        proof = [id(target), target._seal]
    data = generation._json([os.getpid(), encoded, proof])
    return hmac.new(_KEY, data.encode(), "sha256").hexdigest()


@dataclass(frozen=True, slots=True)
class PreparedCandidate:
    _json: str = field(repr=False)
    _seal: str = field(repr=False)
    _target: object = field(default=None, repr=False)

    @property
    def record(self):
        return json.loads(self._json)


def prepare(corpus, report, execution, receipts, *, started_at, reason=None, target=None):
    """Capture a native immutable candidate from the actual process-owned corpus."""
    from paper_daily.lineage_jobs import _worker
    from paper_daily.store import now

    _worker()
    captured = research_lineage._checked(corpus)
    if report["sources"] != corpus.sources or execution["task"] != "lineage":
        raise ValueError("Lineage report differs from its captured sources")
    body = dict(
        format=lineage_sets.FORMAT,
        corpus_id=execution["corpus_id"],
        inputs=dict(dive=None, close_reading=None),
        generation={
            k: execution[k] for k in ("task", "backend", "requested_model", "returned_model")
        },
        report=report,
        bindings=[
            dict(source_id=s["id"], paper_id=p["local_id"])
            for s, p in zip(corpus.sources, captured["observed"], strict=True)
        ],
    )
    row = dict(
        paper_id=body["bindings"][0]["paper_id"],
        corpus_key=body["corpus_id"],
        body_json=lineage_sets.canonical(body),
        source_hash=lineage_sets.source_hash(body),
        document_hash=corpus.sources[0]["document_hash"],
        written_at=now(),
    )
    context = dict(
        format=FORMAT,
        version=1,
        started_at=started_at,
        request_id=execution["request_id"],
        db_path=captured["database"],
        database_identity=captured["database_identity"],
        binding=captured["binding"],
        table=lineage_sets.TABLE,
        owner_id=row["paper_id"],
        key=row["corpus_key"],
        input_reader="lineage_proposal",
        target=None,
        parent_created_at=None,
        parent_lifecycle=captured["observed"][0]["lifecycle"],
        observation=None,
        document=None,
        inputs=dict(
            parents=[
                dict(paper_id=p["local_id"], parent_lifecycle=p["lifecycle"])
                for p in captured["observed"]
            ],
            originals=receipts,
        ),
    )
    if target is not None:
        from paper_daily.lineage_observation import lease_data

        base = lease_data(target)
        if (target._observation._corpus is not corpus
                or base["corpus_id"] != execution["corpus_id"]
                or base["request_id"] != execution["request_id"]):
            raise ValueError("Lineage candidate target differs from its original request")
        context["publication_base"] = dict(
            format="paperfact.lineage-target-base.v1",
            request_id=base["request_id"], corpus_id=base["corpus_id"],
            target_hash=generation._digest(base["target"]) if base["target"] is not None else None,
            observation_hash=generation._digest(base),
        )
    record = validate(
        dict(
            request_id=execution["request_id"],
            context_json=generation._context_json(context),
            row_json=generation._json(row),
            status="candidate",
            candidate_id=generation._digest({"context": context, "row": row}),
            reason=reason or "pending_lineage_publication",
        )
    )
    encoded = generation._json(record)
    return PreparedCandidate(encoded, _seal(encoded, target), target)


def checked(prepared):
    """Validate native retention proof; this alone never authorizes publication."""
    if not isinstance(prepared, PreparedCandidate) or not hmac.compare_digest(
        prepared._seal, _seal(prepared._json, prepared._target)
    ):
        raise ValueError("Lineage retention requires its native prepared candidate")
    return validate(prepared.record)


def persist(prepared):
    """SQL candidate or owned recovery sidecar, never write into a replacement DB."""
    from paper_daily import sync_capture
    from paper_daily.lineage_jobs import _worker

    _worker()
    record = checked(prepared)
    context = generation.GenerationContext(record["context_json"])
    expected = context.data

    def outside():
        return generation._retain_outside_database(
            context, json.loads(record["row_json"]), record["reason"]
        )

    try:
        if generation._identity(context.db_path) != expected["database_identity"]:
            return outside()
        conn = generation._connect(context.db_path)
    except (OSError, sqlite3.Error):
        return outside()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if (
            generation._identity(context.db_path) != expected["database_identity"]
            or generation._binding(conn) != expected["binding"]
        ):
            conn.rollback()
            return outside()
        generation._setup(conn)
        prior = conn.execute(
            "SELECT * FROM research_generation_requests WHERE request_id=?", (record["request_id"],)
        ).fetchone()
        if prior is not None:
            if dict(prior) != record:
                raise ValueError("Lineage request identity was reused for another result")
            return generation.Publication(
                "candidate", record["request_id"], record["candidate_id"], record["reason"]
            )
        with sync_capture.suppress_capture(conn):
            conn.execute(
                "INSERT INTO research_generation_requests VALUES(?,?,?,?,?,?)",
                tuple(
                    record[k]
                    for k in (
                        "request_id",
                        "context_json",
                        "row_json",
                        "status",
                        "candidate_id",
                        "reason",
                    )
                ),
            )
        conn.commit()
        return generation.Publication(
            "candidate", record["request_id"], record["candidate_id"], record["reason"]
        )
    except (OSError, sqlite3.Error):
        with suppress(sqlite3.Error):
            conn.rollback()
        # A lost acknowledgement must not turn one committed request into two copies.
        try:
            if generation._identity(context.db_path) == expected["database_identity"]:
                with closing(generation._connect(context.db_path)) as probe:
                    if (
                        generation._identity(context.db_path) == expected["database_identity"]
                        and generation._binding(probe) == expected["binding"]
                    ):
                        prior = probe.execute(
                            "SELECT * FROM research_generation_requests WHERE request_id=?",
                            (record["request_id"],),
                        ).fetchone()
                        if prior is not None:
                            if dict(prior) != record:
                                raise ValueError("Lineage request identity was reused")
                            return generation.Publication(
                                "candidate",
                                record["request_id"],
                                record["candidate_id"],
                                record["reason"],
                            )
        except (OSError, sqlite3.Error):
            pass
        return outside()
    finally:
        conn.close()


def saved(database, paper_id):
    """Bounded saved-only proposals, including owned sidecars; no model or writes."""
    from paper_daily.lineage_jobs import _worker

    _worker()
    database = Path(database).resolve(strict=True)
    claim_content.text(paper_id, 4096)
    records = {}
    total = 0

    def add(record):
        nonlocal total
        validate(record)
        context = _read(record["context_json"])
        if context["owner_id"] != paper_id:
            return
        prior = records.get(record["request_id"])
        if prior is not None:
            if prior != record:
                raise ValueError("Lineage request has inconsistent retained copies")
            return
        total += len(generation._json(record).encode())
        if len(records) >= lineage_sets.MAX_SETS or total > 64 * 1024**2:
            raise ValueError("Lineage proposals require bounded explicit selection")
        records[record["request_id"]] = record

    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_generation_requests'"
        ).fetchone():
            rows = conn.execute(
                "SELECT request_id,CASE WHEN length(CAST(context_json AS BLOB))<=? "
                "THEN context_json END AS context_json,"
                "CASE WHEN length(CAST(row_json AS BLOB))<=? THEN row_json END AS row_json,"
                "status,candidate_id,reason FROM research_generation_requests "
                "WHERE CASE WHEN json_valid(context_json) "
                "THEN json_extract(context_json,'$.format') "
                "END=? AND json_extract(context_json,'$.owner_id')=? LIMIT ?",
                (
                    generation.MAX_CONTEXT_BYTES,
                    generation.MAX_CONTEXT_BYTES,
                    FORMAT,
                    paper_id,
                    lineage_sets.MAX_SETS + 1,
                ),
            )
            for row in rows:
                add(dict(row))
    for record in generation.list_recovery_requests(database):
        if _read(record["context_json"]).get("format") == FORMAT:
            add(record)
    return sorted(
        records.values(),
        key=lambda r: (_read(r["row_json"])["written_at"], r["request_id"]),
        reverse=True,
    )


def export_content(row):
    """Readable scientific proposal only; no private contexts, routes or owner IDs."""
    lineage_sets.validate_row(row)
    report = lineage_sets.decode(row["body_json"])["report"]
    names = {s["id"]: s["identity"]["title"] for s in report["sources"]}
    return dict(
        sources=[s["identity"] for s in report["sources"]],
        statements=[
            dict(
                stage=s["stage"],
                text=s["text"],
                function=s["function"],
                judgment={k: s["judgment"][k] for k in ("status", "reason")},
                semantic_validation=s["requirements"]["semantic_validation"],
                passages=[
                    dict(
                        source_title=names[p["source_id"]],
                        quote=p["quote"],
                        location=p["location"]["state"],
                    )
                    for p in s["passages"]
                ],
            )
            for s in report["statements"]
        ],
    )


def source_receipts(database, conn):
    """Archive original observations for retained SQL/sidecar proposals, not owners."""
    records = []
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='research_generation_requests'"
    ).fetchone():
        columns = ["request_id", "context_json", "row_json", "status", "candidate_id", "reason"]
        raw = conn.execute(
            "SELECT request_id,CASE WHEN length(CAST(context_json AS BLOB))<=? "
            "THEN context_json END,CASE WHEN length(CAST(row_json AS BLOB))<=? "
            "THEN row_json END,status,candidate_id,reason FROM research_generation_requests "
            "WHERE CASE WHEN json_valid(context_json) "
            "THEN json_extract(context_json,'$.format') END=? LIMIT 10001",
            (generation.MAX_CONTEXT_BYTES, generation.MAX_CONTEXT_BYTES, FORMAT),
        ).fetchall()
        if len(raw) > 10000:
            raise ValueError("Lineage proposal source inventory exceeds its bound")
        records = [dict(zip(columns, r, strict=True)) for r in raw]
    records.extend(generation.list_recovery_requests(database))
    receipts, total = {}, 0
    for record in records:
        context = _read(record["context_json"])
        if context.get("format") != FORMAT:
            continue
        validate(record)
        for receipt in context["inputs"]["originals"]:
            key = receipt["request_id"]
            if key in receipts:
                if receipts[key] != receipt:
                    raise ValueError("Lineage original observation identity was reused")
                continue
            receipts[key] = receipt
            total += len(generation._json(receipt).encode())
            if len(receipts) > source_snapshots.MAX_RECEIPTS or total > 64 * 1024**2:
                raise ValueError("Lineage original observation inventory exceeds its bound")
    return sorted(receipts.values(), key=lambda r: r["request_id"])
