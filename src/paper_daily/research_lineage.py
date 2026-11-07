"""One explicit bounded corpus; exact-source quote checks, no AI or retrieval."""

from __future__ import annotations

import hmac
import json
import os
import secrets
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import lineage_content as content
from paper_daily import research_evidence as evidence
from paper_daily import research_generation as generation
from paper_daily.document_reader import DocumentReader, ResolvedDocument, from_workspace
from paper_daily.research_lifecycle import parent_lifecycle

PROPOSALS = "paperfact.lineage-proposals.v1"
MAX_BYTES = 64 * 1024**2
MAX_INPUT_BYTES = 240 * 1024
MAX_RESPONSE_BYTES = 200 * 1024
_KEY = secrets.token_bytes(32)


class LineageError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__("Lineage evidence: " + code)


def _fail(code):
    raise LineageError(code) from None


def _json(value):
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _fail("invalid_schema")


def _seal(encoded, snapshots, documents):
    value = [
        encoded,
        [s._seal if s else None for s in snapshots],
        [id(document) for document in documents],
        os.getpid(),
    ]
    return hmac.new(_KEY, _json(value).encode(), "sha256").hexdigest()


@dataclass(frozen=True, slots=True)
class CorpusSnapshot:
    """Process-bound capture, never deserialize a report as source authority."""

    _json: str = field(repr=False)
    _snapshots: tuple = field(repr=False)
    _documents: tuple = field(repr=False)
    _seal: str = field(repr=False)

    @property
    def focal(self):
        return json.loads(self._json)["sources"][0]["id"]

    @property
    def sources(self):
        return json.loads(self._json)["sources"]


def _checked(corpus):
    if (
        not isinstance(corpus, CorpusSnapshot)
        or not isinstance(corpus._json, str)
        or not isinstance(corpus._snapshots, tuple)
        or not isinstance(corpus._documents, tuple)
        or not isinstance(corpus._seal, str)
    ):
        _fail("invalid_capture")
    if not hmac.compare_digest(
        corpus._seal, _seal(corpus._json, corpus._snapshots, corpus._documents)
    ):
        _fail("invalid_capture")
    data = json.loads(corpus._json)
    if not 1 <= len(data["sources"]) <= content.MAX_SOURCES:
        _fail("invalid_capture")
    for source, snapshot, origin in zip(
        data["sources"], corpus._snapshots, corpus._documents, strict=True
    ):
        if snapshot:
            if snapshot._origin is not origin:
                _fail("invalid_capture")
            verified, _bytes = evidence._checked_snapshot(snapshot)
            if verified["document_hash"] != source["document_hash"]:
                _fail("invalid_capture")
    return data


def _paper(conn, paper_id):
    row = conn.execute(
        "SELECT title,doi,arxiv_id,s2_id FROM papers WHERE id=?", (paper_id,)
    ).fetchone()
    if row is None:
        _fail("paper_unavailable")
    value = dict(zip(("title", "doi", "arxiv_id", "s2_id"), row, strict=True))
    try:
        content.text(value["title"], 2000)
        for field in content.IDENTITY_FIELDS - {"title"}:
            content.text(value[field], 1000, nullable=True)
    except (ValueError, TypeError):
        _fail("paper_identity_invalid")
    return value


def capture(database, focal_id, related_ids=(), *, legacy_root, documents=None, cancelled=None):
    """Read selected records and exact PDFs after caller established local epochs.

    Missing related originals remain explicit unavailable sources. The focal
    original is required. No directory scan, search, download or provider access.
    """
    if (
        not isinstance(focal_id, str)
        or not focal_id
        or not isinstance(related_ids, (list, tuple))
        or len(related_ids) > content.MAX_SOURCES - 1
        or any(not isinstance(x, str) or not x for x in related_ids)
    ):
        _fail("invalid_corpus")
    ids = [focal_id, *related_ids]
    if len(set(ids)) != len(ids):
        _fail("duplicate_paper")
    if documents is not None and (not isinstance(documents, dict) or set(documents) - set(ids)):
        _fail("invalid_documents")
    evidence._cancel(cancelled)
    try:
        database = Path(database).resolve(strict=True)
        identity = generation._identity(database)
        if not identity[1]:
            _fail("database_unavailable")
    except (OSError, TypeError, ValueError):
        _fail("database_unavailable")
    with closing(generation._connect(database)) as conn:
        if generation._identity(database) != identity:
            _fail("database_changed")
        conn.execute("BEGIN")
        binding = generation._binding(conn)
        observed = []
        for local in ids:
            token = parent_lifecycle(conn, "paper", local)
            if token is None:
                _fail("paper_lifecycle_uninitialized")
            observed.append(
                {"local_id": local, "identity": _paper(conn, local), "lifecycle": token}
            )
    reader = from_workspace(database, legacy_root=legacy_root)
    sources, snapshots, origins, total, pages = [], [], [], 0, 0
    for index, row in enumerate(observed):
        evidence._cancel(cancelled)
        document = documents.get(row["local_id"]) if documents else None
        document = document if document is not None else reader.resolve(row["local_id"])
        if (
            not isinstance(document, ResolvedDocument)
            or not isinstance(document._owner, DocumentReader)
            or document.local_id != row["local_id"]
            or document._owner.db_path.resolve() != database
        ):
            _fail("source_owner_mismatch")
        snapshot = evidence.capture(document) if document.available else None
        if not snapshot and index == 0:
            _fail("focal_source_unavailable")
        if snapshot:
            _source, raw = evidence._checked_snapshot(snapshot)
            total += len(raw)
            if total > MAX_BYTES:
                _fail("corpus_byte_limit")
            import pymupdf

            try:
                with pymupdf.open(stream=raw, filetype="pdf") as pdf:
                    if pdf.needs_pass:
                        _fail("encrypted_document")
                    count = len(pdf)
            except (RuntimeError, ValueError):
                _fail("invalid_document")
            pages += count
            if count < 1 or pages > 96:
                _fail("corpus_page_limit")
            sha = snapshot.source["document_hash"]
        else:
            count, sha = None, None
        sources.append(
            {
                "id": content.source_id(row["identity"], sha),
                "identity": row["identity"],
                "identity_authority": "selected_workspace_record",
                "document_hash": sha,
                "availability": "available" if snapshot else "unavailable",
                "page_count": count,
            }
        )
        snapshots.append(snapshot)
        origins.append(document)
    if len({s["id"] for s in sources}) != len(sources):
        _fail("duplicate_source")
    data = {
        "database": str(database),
        "database_identity": identity,
        "binding": binding,
        "observed": observed,
        "sources": sources,
    }
    encoded = _json(data)
    result = CorpusSnapshot(
        encoded, tuple(snapshots), tuple(origins), _seal(encoded, tuple(snapshots), tuple(origins))
    )
    current(result)
    evidence._cancel(cancelled)
    return result


def current(corpus):
    """Recheck actual selected owners and each current original, never an AI title."""
    data = _checked(corpus)
    database = Path(data["database"])
    try:
        if generation._identity(database) != data["database_identity"]:
            _fail("database_changed")
        with closing(generation._connect(database)) as conn:
            if generation._identity(database) != data["database_identity"]:
                _fail("database_changed")
            conn.execute("BEGIN")
            if generation._binding(conn) != data["binding"]:
                _fail("workspace_changed")
            for row in data["observed"]:
                if (
                    parent_lifecycle(conn, "paper", row["local_id"]) != row["lifecycle"]
                    or _paper(conn, row["local_id"]) != row["identity"]
                ):
                    _fail("paper_changed")
        for document, snapshot in zip(corpus._documents, corpus._snapshots, strict=True):
            if snapshot:
                evidence._check_source(document)
            elif document._owner.resolve(document.local_id).available:
                _fail("source_changed")
        if generation._identity(database) != data["database_identity"]:
            _fail("database_changed")
    except LineageError:
        raise
    except (OSError, ValueError):
        _fail("source_changed")
    return True


def pages(corpus, *, cancelled=None):
    """Explicit producer input, bounded independently of model response limits."""
    _checked(corpus)
    result = []
    for source, snapshot in zip(corpus.sources, corpus._snapshots, strict=True):
        evidence._cancel(cancelled)
        result.append(
            {
                **source,
                "pages": evidence.snapshot_pages(snapshot, cancelled=cancelled) if snapshot else [],
            }
        )
    if len(_json(result).encode()) > MAX_INPUT_BYTES:
        _fail("corpus_text_limit")
    return result


def _proposals(value, corpus):
    encoded = _json(value)
    if len(encoded.encode()) > MAX_RESPONSE_BYTES:
        _fail("proposal_byte_limit")
    value = json.loads(encoded)
    content.closed(value, {"format", "focal", "statements"})
    if value["format"] != PROPOSALS or value["focal"] != corpus.focal:
        _fail("focal_identity_mismatch")
    if (
        not isinstance(value["statements"], list)
        or len(value["statements"]) > content.MAX_STATEMENTS
    ):
        _fail("statement_limit")
    sources = {s["id"] for s in corpus.sources}
    texts, passages = set(), 0
    for item in value["statements"]:
        content.closed(item, {"stage", "subject", "text", "function", "judgment", "passages"})
        if (
            not isinstance(item["stage"], str)
            or item["stage"] not in content.STAGES
            or not isinstance(item["subject"], str)
            or item["subject"] not in sources
        ):
            _fail("unselected_paper")
        if (item["stage"] == "current_change") != (item["subject"] == corpus.focal):
            _fail("stage_source_mismatch")
        content.text(item["text"], 2000)
        key = content.hashed([item["stage"], item["subject"], content.normalize(item["text"])])
        if key in texts:
            _fail("duplicate_statement")
        texts.add(key)
        if not isinstance(item["function"], str) or item["function"] not in content.FUNCTIONS:
            _fail("invalid_function")
        content.closed(item["judgment"], {"status", "reason"})
        if not isinstance(item["judgment"]["status"], str) or item["judgment"]["status"] not in {
            "supported",
            "inferred",
            "unresolved",
        }:
            _fail("invalid_judgment")
        content.text(item["judgment"]["reason"], 2000)
        if not isinstance(item["passages"], list):
            _fail("invalid_passages")
        passages += len(item["passages"])
        if passages > content.MAX_PASSAGES:
            _fail("passage_limit")
        seen = set()
        for p in item["passages"]:
            content.closed(p, {"source_id", "role", "cites", "quote", "page", "anchor"})
            if (
                not isinstance(p["source_id"], str)
                or p["source_id"] not in sources
                or not isinstance(p["role"], str)
                or p["role"] not in content.ROLES
                or (
                    p["cites"] is not None
                    and (not isinstance(p["cites"], str) or p["cites"] not in sources)
                )
            ):
                _fail("unselected_passage_source")
            if (p["role"] == "citing_context") != (p["cites"] is not None):
                _fail("invalid_citation_proposal")
            content.text(p["quote"], 4000)
            if p["page"] is not None and type(p["page"]) is not int:
                _fail("invalid_page")
            if p["anchor"] is not None:
                content.closed(p["anchor"], {"p0", "o0", "p1", "o1"})
                if any(type(value) is not int for value in p["anchor"].values()):
                    _fail("invalid_anchor")
            key = content.hashed(p)
            if key in seen:
                _fail("duplicate_passage")
            seen.add(key)
    return value


def verify_snapshot(corpus, proposals, *, cancelled=None):
    """Quote-location report for the immutable captures, not today's current PDFs."""
    _checked(corpus)
    values = _proposals(proposals, corpus)
    by_id = {s["id"]: (s, snap) for s, snap in zip(corpus.sources, corpus._snapshots, strict=True)}
    locations = {}
    for source_id, (_source, snapshot) in by_id.items():
        unique = {}
        for item in values["statements"]:
            for passage in item["passages"]:
                if passage["source_id"] == source_id:
                    key = content.hashed(
                        [content.normalize(passage["quote"]), passage["page"], passage["anchor"]]
                    )
                    unique.setdefault(key, {k: passage[k] for k in ("quote", "page", "anchor")})
        if snapshot and unique:
            verified = evidence.verify_snapshot(
                snapshot,
                {
                    "format": evidence.FORMAT,
                    "source": snapshot.source,
                    "claims": [
                        {
                            "text": "Selected exact source passages for bounded lineage.",
                            "judgment": {"status": "unresolved", "reason": "Quote location only."},
                            "passages": list(unique.values()),
                        }
                    ],
                },
                cancelled=cancelled,
            )["claims"][0]["passages"]
            for key, passage in zip(unique, verified, strict=True):
                locations[(source_id, key)] = passage["location"]
    statements = []
    for item in values["statements"]:
        evidence._cancel(cancelled)
        passages = []
        for p in item["passages"]:
            _source, snapshot = by_id[p["source_id"]]
            if snapshot:
                key = content.hashed([content.normalize(p["quote"]), p["page"], p["anchor"]])
                located = locations[(p["source_id"], key)]
            else:
                located = {
                    "state": "source_unavailable",
                    "reason": "original_unavailable",
                    "anchor": None,
                    "page": None,
                    "candidates": [],
                    "truncated": False,
                }
            result = {k: p[k] for k in ("source_id", "role", "cites", "quote")}
            result["location"] = located
            passages.append({"id": content.passage_id(result), **result})
        output = {
            "id": content.statement_id(corpus.focal, item),
            **item,
            "judgment": {**item["judgment"], "authority": "caller_proposal"},
            "passages": passages,
        }
        output["requirements"] = content.requirements(corpus.focal, output)
        statements.append(output)
    evidence._cancel(cancelled)
    report = {
        "format": content.FORMAT,
        "recipe": content.RECIPE,
        "verification_scope": "original_snapshots",
        "normalization": evidence.RULE,
        "focal": corpus.focal,
        "sources": corpus.sources,
        "statements": statements,
        "coverage": {
            stage: ("proposed" if any(s["stage"] == stage for s in statements) else "no_statement")
            for stage in sorted(content.STAGES)
        },
    }
    return content.validate({**report, "id": content.hashed(report)})


def verify(corpus, proposals, *, cancelled=None):
    """Verify current sources twice; a mutation never becomes a current-source report."""
    current(corpus)
    report = verify_snapshot(corpus, proposals, cancelled=cancelled)
    current(corpus)
    report["verification_scope"] = "current_sources"
    report["id"] = content.hashed({k: v for k, v in report.items() if k != "id"})
    return content.validate(report)


def parse_proposals(raw, corpus):
    """Decode a bounded model response without accepting duplicate keys or NaN."""
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_RESPONSE_BYTES:
        _fail("proposal_byte_limit")

    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value:
                _fail("duplicate_json_key")
            value[key] = item
        return value

    def invalid(_value):
        _fail("nonfinite_json")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except LineageError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _fail("invalid_json")
    return _proposals(value, corpus)
