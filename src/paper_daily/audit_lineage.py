"""Explicit saved-corpus audit using independently verified original readers.

This is a worker operation, not a source grant, download or scientific verdict.
"""

from __future__ import annotations

import copy
import hmac
import json
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field

from paper_daily import (
    audit_inputs,
    claim_content,
    lineage_sets,
    lineage_source_reader,
    research_audit,
)
from paper_daily import research_evidence as evidence
from paper_daily.lineage_jobs import _worker
from paper_daily.manual_highlight_ops import HighlightOwner, _readonly_connection
from paper_daily.workspace_activity import _versions

MAX_ORIGINALS = 4
MAX_PDF_BYTES = 32 * 1024**2
MAX_PAGES = 96
MAX_WORDS = 50_000
_KEY = secrets.token_bytes(32)


def _fail(code):
    raise research_audit.AuditError(code) from None


def _seal(owner, row_json, versions, report_json, reader, proofs):
    value = repr(
        (
            id(owner),
            row_json,
            versions,
            report_json,
            id(reader),
            tuple((sid, id(proof)) for sid, proof in proofs),
        )
    ).encode()
    return hmac.digest(_KEY, value, "sha256")


@dataclass(frozen=True, slots=True)
class PreparedLineageAudit:
    """Delivery witness; a copied report never grants original access."""

    _owner: HighlightOwner = field(repr=False)
    _row_json: str = field(repr=False)
    _versions: tuple = field(repr=False)
    _json: str = field(repr=False)
    _reader: object = field(repr=False)
    _proofs: tuple = field(repr=False)
    _seal: bytes = field(repr=False)

    def current(self):
        try:
            if (
                not hmac.compare_digest(
                    self._seal,
                    _seal(
                        self._owner,
                        self._row_json,
                        self._versions,
                        self._json,
                        self._reader,
                        self._proofs,
                    ),
                )
                or _versions(self._owner.database) != self._versions
            ):
                return False
            with closing(_readonly_connection(self._owner.database)) as conn:
                self._owner.check(conn)
            return all(self._reader.metadata_current(proof) for _, proof in self._proofs) and (
                _versions(self._owner.database) == self._versions
            )
        except (ValueError, TypeError, OSError, sqlite3.Error):
            return False

    def for_delivery(self, owner, row):
        if owner is not self._owner or row != json.loads(self._row_json) or not self.current():
            _fail("saved_content_changed")
        return json.loads(self._json)


def _partition(items, statements, source_id):
    """Check subject prose only on its owner; preserve original passage indices."""
    selected, indices = [], {}
    for item, statement in zip(items, statements, strict=True):
        positions = [
            i
            for i, passage in enumerate(statement["passages"])
            if passage["source_id"] == source_id
        ]
        subject = statement["subject"] == source_id
        if not positions and not subject:
            continue
        value = copy.deepcopy(item)
        if not subject:
            value["text"] = ""
        value["passages"] = [value["passages"][i] for i in positions]
        if not subject:
            value["source_paper_id"] = value["passages"][0]["source_paper_id"]
            value["document_hash"] = value["passages"][0]["document_hash"]
        selected.append(value)
        indices[item["id"]] = positions
    return research_audit.validate(selected), indices


def prepare(owner, expected, *, cancelled=lambda: False, progress=lambda _a, _b: None):
    """Check an explicitly selected current corpus without adoption, edits or AI.

    Cancellation returns no partial result. Missing originals remain explicit;
    changed provenance refuses the whole result. The actual owner is required
    again at delivery, including after a queued desktop completion.
    """
    _worker()
    if not isinstance(owner, HighlightOwner):
        _fail("invalid_owner")
    lineage_sets.validate_row(expected)
    expected = copy.deepcopy(expected)
    versions = _versions(owner.database)
    if cancelled():
        _fail("cancelled")
    with closing(_readonly_connection(owner.database)) as conn:
        conn.execute("BEGIN")
        reader = lineage_source_reader.reader_in(conn, owner, expected)
        items = research_audit.validate(audit_inputs._lineage_items(conn, expected))
        body = lineage_sets.decode(expected["body_json"])
        bindings = {b["source_id"]: b["paper_id"] for b in body["bindings"]}
    sources = body["report"]["sources"]
    if sum(len(research_audit.quantities(item["text"])) for item in items) > (
        research_audit.MAX_QUANTITIES
    ):
        _fail("quantity_limit")
    if len(sources) > MAX_ORIGINALS:
        _fail("input_limit")
    results, proofs = [], []
    byte_count = page_count = word_count = 0
    for index, source in enumerate(sources):
        if cancelled():
            _fail("cancelled")
        sid = source["id"]
        progress(index, len(sources))
        proof = reader.prepare(owner, expected, sid, cancelled=cancelled)
        if cancelled():
            _fail("cancelled")
        selected, positions = _partition(items, body["report"]["statements"], sid)
        report, state = None, "original_unavailable"
        if proof is not None:
            data = reader.for_delivery(proof, owner, expected, sid)
            byte_count += len(data)
            if byte_count > MAX_PDF_BYTES:
                _fail("input_limit")
            import pymupdf

            with pymupdf.open(stream=data, filetype="pdf") as pdf:
                page_count += len(pdf)
                if page_count > MAX_PAGES:
                    _fail("input_limit")
            extracted = evidence._extract(data, cancelled)
            word_count += sum(len(words) for words in extracted[0])
            if word_count > MAX_WORDS:
                _fail("input_limit")
            # These owners come from the same validated native alias mapping as
            # the audit items, independently of byte equality across sources.
            owners = {p["source_paper_id"] for item in selected for p in item["passages"]}
            owners.update(item["source_paper_id"] for item in selected if item["text"])
            if len(owners) > 1:
                _fail("invalid_saved_content")
            paper_id = next(iter(owners), bindings[sid])
            report = research_audit._run_checked_pages(
                dict(paper_id=paper_id, document_hash=source["document_hash"]),
                selected,
                extracted,
                cancelled=cancelled,
                progress=lambda _a, _b: None,
            )
            # The reducer numbers its partition; expose stable original indices.
            for check in report["checks"]:
                if "passage" in check:
                    check["original_passage"] = positions[check["item_id"]][check["passage"]]
            report.pop("id")
            report["id"] = claim_content.hashed(report)
            proofs.append((sid, proof))
            state = "available"
        results.append(
            dict(
                source_id=sid,
                local_paper_id=bindings[sid],
                recorded_document_hash=source["document_hash"],
                state=state,
                passage_indices=positions,
                report=report,
            )
        )
    if cancelled():
        _fail("cancelled")
    value = dict(
        format="paperfact.lineage-audit.v1",
        rule_version=research_audit.RULE,
        paper_id=owner.paper_id,
        corpus_key=expected["corpus_key"],
        source_hash=expected["source_hash"],
        sources=results,
        originals_checked=len(proofs),
        originals_total=len(sources),
        semantics="not_checked",
        not_checked=["semantic_support", "causal_influence"],
    )
    row_json = json.dumps(expected, sort_keys=True)
    report_json = json.dumps(value, ensure_ascii=False, allow_nan=False)
    proofs = tuple(proofs)
    result = PreparedLineageAudit(
        owner,
        row_json,
        versions,
        report_json,
        reader,
        proofs,
        _seal(owner, row_json, versions, report_json, reader, proofs),
    )
    if not result.current():
        _fail("saved_content_changed")
    progress(len(sources), len(sources))
    return result
