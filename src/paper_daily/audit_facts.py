"""Closed source-bound fact proposals, not scholarly or semantic certification.

No model, persistence, global source lookup or UI activation lives here. Call on
a worker: the existing source verifier performs bounded PDF extraction/hashing.
"""

from __future__ import annotations

import hmac
import json
import re
import secrets
from dataclasses import dataclass, field
from decimal import Decimal, localcontext

from paper_daily import audit_inputs, claim_content, research_audit
from paper_daily import research_evidence as evidence
from paper_daily.document_reader import document_current

FORMAT = "paperfact.source-facts.proposals.v1"
REPORT = "paperfact.source-facts.v1"
MAX_BYTES = 256 * 1024
MAX_FACTS = 32
MAX_PASSAGES = 64
STUDY_TYPES = {"empirical", "theoretical", "qualitative", "review", "mixed", "unknown"}
CATEGORIES = {
    "design",
    "assumptions",
    "sample",
    "materials",
    "method",
    "outcome",
    "comparator",
    "units",
    "uncertainty",
    "limitations",
}
ORIGINS = {"author_stated", "reviewer_inferred", "not_reported", "not_applicable", "unknown"}
SCOPE = {
    "construct",
    "outcome",
    "comparator",
    "population",
    "time",
    "unit",
    "statistic",
    "conditions",
}
_KEY = secrets.token_bytes(32)


def _fail(code):
    raise research_audit.AuditError(code) from None


def _json(value):
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("invalid_fact_batch")


def _copy(value):
    try:
        encoded = _json(value).encode("utf-8")
    except UnicodeError:
        _fail("invalid_fact_batch")
    if len(encoded) > MAX_BYTES:
        _fail("fact_batch_limit")
    return json.loads(encoded)


def _closed(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        _fail("invalid_fact_batch")


def _text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        _fail("invalid_fact_batch")
    return value


def _member(value, choices):
    if not isinstance(value, str) or value not in choices:
        _fail("invalid_fact_batch")


def _value(value):
    if value is None:
        return
    if not isinstance(value, dict):
        _fail("invalid_fact_batch")
    if value.get("kind") == "text":
        _closed(value, {"kind", "text"})
        _text(value["text"], 2000)
        return
    _closed(value, {"kind", "decimal", "rounded_places", "derived"})
    if value["kind"] != "number" or type(value["derived"]) is not bool:
        _fail("invalid_fact_batch")
    number = value["decimal"]
    if not isinstance(number, str) or not re.fullmatch(r"-?\d{1,18}(?:\.\d{1,12})?", number):
        _fail("invalid_fact_batch")
    places = value["rounded_places"]
    if places is not None:
        if type(places) is not int or not 0 <= places <= 12:
            _fail("invalid_fact_batch")
        # The supplied point must actually be representable at the declared precision.
        with localcontext() as context:
            context.prec = 64
            if Decimal(number) != Decimal(number).quantize(Decimal(1).scaleb(-places)):
                _fail("invalid_fact_batch")


def validate(proposals):
    """Return an independent, complete closed batch; never truncate or fill fields."""
    value = _copy(proposals)
    _closed(value, {"format", "source", "study_type", "facts"})
    if value["format"] != FORMAT:
        _fail("invalid_fact_batch")
    _closed(value["source"], {"paper_id", "document_hash"})
    _text(value["source"]["paper_id"], 512)
    digest = value["source"]["document_hash"]
    if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
        _fail("invalid_fact_batch")
    _member(value["study_type"], STUDY_TYPES)
    facts = value["facts"]
    if not isinstance(facts, list) or len(facts) > MAX_FACTS:
        _fail("fact_count_limit")
    identities, count = set(), 0
    for fact in facts:
        _closed(
            fact,
            {"id", "category", "statement", "origin", "scope", "value", "location", "passages"},
        )
        identity = _text(fact["id"], 64)
        if identity in identities:
            _fail("duplicate_fact")
        identities.add(identity)
        _text(fact["statement"], 2000)
        _member(fact["category"], CATEGORIES)
        _member(fact["origin"], ORIGINS)
        _closed(fact["scope"], SCOPE)
        for text in fact["scope"].values():
            if text is not None:
                _text(text, 256)
        _value(fact["value"])
        if fact["origin"] in {"not_reported", "not_applicable", "unknown"}:
            if fact["value"] is not None:
                _fail("invalid_fact_batch")
        elif fact["value"] is None:
            _fail("invalid_fact_batch")
        location = fact["location"]
        if not isinstance(location, dict):
            _fail("invalid_fact_batch")
        if location.get("kind") == "source":
            _closed(location, {"kind"})
        else:
            _closed(location, {"kind", "item_id", "start", "end"})
            if location["kind"] != "output":
                _fail("invalid_fact_batch")
            _text(location["item_id"], 512)
            if (
                type(location["start"]) is not int
                or type(location["end"]) is not int
                or not 0 <= location["start"] < location["end"] <= research_audit.MAX_TEXT
            ):
                _fail("invalid_fact_batch")
        passages = fact["passages"]
        if not isinstance(passages, list) or len(passages) > 4:
            _fail("invalid_fact_batch")
        count += len(passages)
        if count > MAX_PASSAGES:
            _fail("fact_passage_limit")
        for passage in passages:
            _closed(passage, {"quote", "page", "anchor"})
            _text(passage["quote"], evidence.MAX_QUOTE_CHARS)
            page, anchor = passage["page"], passage["anchor"]
            if page is not None and (type(page) is not int or not 1 <= page <= evidence.MAX_PAGES):
                _fail("invalid_fact_batch")
            if anchor is not None:
                _closed(anchor, evidence.ANCHOR_KEYS)
                if (
                    any(type(v) is not int or v < 0 for v in anchor.values())
                    or not anchor["p0"] <= anchor["p1"] < evidence.MAX_PAGES
                    or anchor["o0"] >= evidence.MAX_WORDS_PER_PAGE
                    or anchor["o1"] >= evidence.MAX_WORDS_PER_PAGE
                    or (anchor["p0"] == anchor["p1"] and anchor["o0"] > anchor["o1"])
                ):
                    _fail("invalid_fact_batch")
    return value


def _guard(capture, cancelled, current):
    if cancelled():
        _fail("cancelled")
    if not current():
        _fail("stale_context")
    if (
        not isinstance(capture, audit_inputs.AuditCapture)
        or capture._seal is not audit_inputs._SEAL
    ):
        _fail("invalid_capture")
    if not capture.current() or not document_current(capture.snapshot._origin):
        _fail("saved_content_changed")


def _seal(report, capture):
    raw = _json([report, id(capture)]).encode("utf-8")
    return hmac.new(_KEY, raw, "sha256").hexdigest()


@dataclass(frozen=True, slots=True)
class FactSheet:
    """Process-sealed derived proposal; serialized JSON is never source authority."""

    _report_json: str = field(repr=False)
    _capture: audit_inputs.AuditCapture = field(repr=False)
    _proof: str = field(repr=False)

    @property
    def report(self):
        return json.loads(self._report_json)

    def current(self):
        try:
            _guard(self._capture, lambda: False, lambda: True)
            return hmac.compare_digest(self._proof, _seal(self.report, self._capture))
        except (ValueError, OSError, TypeError, AttributeError):
            return False


def _checked(sheet, cancelled, current):
    if not isinstance(sheet, FactSheet) or not sheet.current():
        _fail("invalid_or_stale_fact_sheet")
    _guard(sheet._capture, cancelled, current)
    return sheet.report


def prepare(capture, proposals, *, cancelled=lambda: False, current=lambda: True):
    """Validate explicit proposals and locate quotes in the captured exact original.

    No extraction call occurs. Statement/category/value/scope and author-vs-reviewer
    attribution are supplied proposals, even when a quotation is located.
    """
    _guard(capture, cancelled, current)
    batch = validate(proposals)
    if batch["source"] != capture.snapshot.source:
        _fail("source_identity_mismatch")
    items = {item["id"]: item for item in research_audit.validate(json.loads(capture._items_json))}
    bindings = []
    for fact in batch["facts"]:
        location = fact["location"]
        binding = "exact"
        if location["kind"] == "output":
            item = items.get(location["item_id"])
            if (
                item is None
                or item["text"][location["start"] : location["end"]] != fact["statement"]
            ):
                _fail("output_location_mismatch")
            digest = item["document_hash"]
            binding = (
                "unknown"
                if digest is None
                else "exact"
                if digest == batch["source"]["document_hash"]
                else "different_original"
            )
        bindings.append(binding)
    verified = evidence.verify_snapshot(
        capture.snapshot,
        dict(
            format=evidence.FORMAT,
            source=batch["source"],
            claims=[
                dict(
                    text=fact["id"],
                    judgment=dict(status="unresolved", reason="Researcher review"),
                    passages=fact["passages"],
                )
                for fact in batch["facts"]
            ],
        ),
        cancelled=cancelled,
    )
    facts = []
    for fact, binding, checked in zip(batch["facts"], bindings, verified["claims"], strict=True):
        result = {key: val for key, val in fact.items() if key != "passages"}
        result["source_binding"] = binding
        result["evidence"] = [
            dict(
                quote=passage["quote"],
                requested_locator=dict(page=raw["page"], anchor=raw["anchor"]),
                location=passage["location"],
            )
            for raw, passage in zip(fact["passages"], checked["passages"], strict=True)
        ]
        facts.append(result)
    _guard(capture, cancelled, current)
    report = dict(
        format=REPORT,
        source=batch["source"],
        study_type=batch["study_type"],
        owner_observation=claim_content.hashed([capture.paper_id, json.loads(capture._state_json)]),
        input_hash=claim_content.hashed(json.loads(capture._items_json)),
        proposal_hash=claim_content.hashed(batch),
        facts=facts,
        semantic_validation="researcher_review_proposal",
        verification_scope="original_snapshot",
        persistence="none",
        omissions="not_evidence_of_absence",
    )
    report["id"] = claim_content.hashed(report)
    return FactSheet(_json(report), capture, _seal(report, capture))
