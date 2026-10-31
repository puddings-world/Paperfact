"""Read-only deterministic analysis checks; occurrence never proves semantic support.

Callers supply a bounded, explicit saved-output corpus and a sealed owned PDF.
No provider, filesystem destination, database writer or network client lives here.
"""

from __future__ import annotations

import copy
import json
import re

from paper_daily import claim_content as content
from paper_daily import research_evidence as evidence

FORMAT = "paperfact.analysis-audit.v1"
RULE = "source-checks.v2"
MAX_ITEMS = 256
MAX_BYTES = 1024 * 1024
MAX_TEXT = 120_000
MAX_PASSAGES = 512
MAX_QUANTITIES = 512
FEATURES = {
    "dive",
    "close_reading",
    "answer",
    "note",
    "slides",
    "highlights",
    "claims",
    "citations",
    "followups",
    "lineage",
    "list_survey",
    "reading_links",
    "research_questions",
    "paper_context",
}
A1_SQL_FEATURES = {"reading_links", "research_questions", "paper_context"}
LINK_FINDINGS = {
    "analysis_missing": "linked_analysis_missing",
    "analysis_changed": "linked_analysis_changed",
    "source_changed": "linked_source_mismatch",
    "quote_missing": "linked_quote_unavailable",
}
CHECKS = (
    "quote_location", "anchor", "quantity_occurrence", "reference_identity", "evidence_basis",
    "link_provenance",
)


class AuditError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__("Analysis audit: " + code)


def _fail(code):
    raise AuditError(code) from None


def _closed(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        _fail("invalid_input")


def _text(value, limit, *, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        _fail("invalid_input")
    return value


def _digest(value, *, nullable=False):
    if nullable and value is None:
        return
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        _fail("invalid_input")


def _provenance(item):
    if not isinstance(item["feature"], str) or item["feature"] not in A1_SQL_FEATURES:
        _fail("invalid_input")
    value = item["provenance"]
    _closed(value, {"record_hash", "input_hash", "related_record_hash", "link_state"})
    _digest(value["record_hash"])
    _digest(value["input_hash"], nullable=item["feature"] == "paper_context")
    _digest(value["related_record_hash"], nullable=True)
    if item["feature"] == "reading_links":
        if not isinstance(value["link_state"], str) or value["link_state"] not in {
            "matched", *LINK_FINDINGS
        }:
            _fail("invalid_input")
        if (value["link_state"] == "analysis_missing") != (value["related_record_hash"] is None):
            _fail("invalid_input")
        if value["link_state"] != "matched" and item["passages"]:
            _fail("invalid_input")
    elif value["link_state"] is not None or value["related_record_hash"] is not None:
        _fail("invalid_input")
    if item["feature"] == "paper_context" and (
        value["input_hash"] is not None or item["document_hash"] is not None or item["passages"]
    ):
        _fail("invalid_input")


def validate(items):
    try:
        encoded = json.dumps(items, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_BYTES:
            _fail("input_limit")
        items = json.loads(encoded)
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, AuditError):
            raise
        _fail("invalid_input")
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        _fail("item_limit")
    identities, passages = set(), 0
    for item in items:
        if not isinstance(item, dict):
            _fail("invalid_input")
        fields = {"id", "feature", "text", "document_hash", "passages", "reference"}
        if "provenance" in item:
            fields.add("provenance")
        _closed(item, fields)
        if "provenance" in item:
            _provenance(item)
        identity = _text(item["id"], 512)
        if identity in identities:
            _fail("duplicate_item")
        identities.add(identity)
        if not isinstance(item["feature"], str) or item["feature"] not in FEATURES:
            _fail("invalid_input")
        _text(item["text"], MAX_TEXT, empty=True)
        _digest(item["document_hash"], nullable=True)
        if not isinstance(item["passages"], list):
            _fail("invalid_input")
        passages += len(item["passages"])
        if passages > MAX_PASSAGES:
            _fail("passage_limit")
        for passage in item["passages"]:
            _closed(passage, {"quote", "page", "anchor", "document_hash"})
            _text(passage["quote"], evidence.MAX_QUOTE_CHARS)
            _digest(passage["document_hash"], nullable=True)
            if passage["page"] is not None and type(passage["page"]) is not int:
                _fail("invalid_input")
            anchor = passage["anchor"]
            if anchor is not None and (
                not isinstance(anchor, dict)
                or set(anchor) != evidence.ANCHOR_KEYS
                or any(type(value) is not int for value in anchor.values())
            ):
                _fail("invalid_input")
        reference = item["reference"]
        if reference is not None:
            _closed(
                reference,
                {
                    "basis",
                    "contexts",
                    "proposed_title",
                    "resolved_title",
                    "proposed_doi",
                    "resolved_doi",
                    "relation",
                },
            )
            if reference["basis"] not in ("context", "title", "unknown"):
                _fail("invalid_input")
            if not isinstance(reference["contexts"], list) or len(reference["contexts"]) > 32:
                _fail("invalid_input")
            for value in reference["contexts"]:
                _text(value, 4000)
            for key in (
                "proposed_title",
                "resolved_title",
                "proposed_doi",
                "resolved_doi",
                "relation",
            ):
                if reference[key] is not None:
                    _text(reference[key], 4000)
    return items


# Lexical candidates only. Values are never added, converted, rounded or interpreted.
_NUMBER = re.compile(r"(?<![\w.])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w]|\.\d)")
_UNIT = re.compile(
    r"\s*(%|ms|s|mm|cm|km|mg|kg|mL|mA|Hz|kHz|MHz|GHz|MB|GB|TB|Pa|kPa|MPa|K|C|F)(?!\w)"
)
_URL = re.compile(r"(?:https?://|doi:|10\.\d{4,9}/)\S+", re.I)


def quantities(text):
    """Bounded lexical number/unit occurrences, retaining original output offsets."""
    text = content.normalize(text)
    # Preserve offsets while excluding URLs, code and list-number prefixes.
    clean = _URL.sub(lambda match: " " * len(match[0]), text)
    result, seen = [], set()
    for match in _NUMBER.finditer(clean):
        unit = _UNIT.match(clean, match.end())
        end = unit.end() if unit else match.end()
        token = (match[0], unit[1] if unit else "")
        if token in seen:
            continue
        seen.add(token)
        result.append({"value": token[0], "unit": token[1], "start": match.start(), "end": end})
        if len(result) > MAX_QUANTITIES:
            _fail("quantity_limit")
    return result


def _doi(value):
    if value is None:
        return None
    return re.sub(
        r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value.strip(), flags=re.I
    ).lower()


def _binding(expected, actual):
    return "unknown" if expected is None else "exact" if expected == actual else "different"


def _reference(reference):
    if reference is None:
        return []
    results = []
    first, second = _doi(reference["proposed_doi"]), _doi(reference["resolved_doi"])
    if first and second and first != second:
        results.append(("reference_identity", "doi_mismatch"))
    elif reference["proposed_title"] and reference["resolved_title"]:
        from paper_daily.sources.openalex import same_paper

        matches = same_paper(reference["proposed_title"], reference["resolved_title"])
        results.append(
            ("reference_identity", "title_similar" if matches else "title_mismatch_candidate")
        )
    else:
        results.append(("reference_identity", "identity_not_checked"))
    # Similar titles are a heuristic, even when DOI strings happen to agree.
    if reference["basis"] == "title":
        results.append(("evidence_basis", "title_only"))
    elif reference["relation"] and not reference["contexts"]:
        results.append(("evidence_basis", "citing_context_missing"))
    else:
        results.append(("evidence_basis", "context_requires_appraisal"))
    return results


def run(snapshot, items, *, cancelled=lambda: False, progress=lambda done, total: None):
    """Report exact bounded checks. A report neither edits nor certifies research."""
    items = validate(items)
    source, data = evidence._checked_snapshot(snapshot)
    if cancelled():
        _fail("cancelled")
    extracted = evidence._extract(data, cancelled)
    return _run_checked_pages(source, items, extracted, cancelled=cancelled, progress=progress)


def _run_checked_pages(source, items, extracted, *, cancelled, progress):
    """Internal deterministic reducer; caller must separately verify owned source bytes."""
    pages, indexes, whole = extracted
    original_quantities = {
        (entry["value"], entry["unit"]) for page in indexes for entry in quantities(page[0])
    }
    checks, quantity_count = [], 0
    for index, item in enumerate(items):
        if cancelled():
            _fail("cancelled")
        binding = _binding(item["document_hash"], source["document_hash"])
        base = {"item_id": item["id"], "feature": item["feature"], "binding": binding}
        provenance = item.get("provenance")
        if provenance and provenance["link_state"] in LINK_FINDINGS:
            checks.append(
                {**base, "rule": "link_provenance",
                 "state": LINK_FINDINGS[provenance["link_state"]]}
            )
        for number, passage in enumerate(item["passages"]):
            bound = _binding(passage["document_hash"], source["document_hash"])
            entry = {
                **base,
                "rule": "quote_location",
                "passage": number,
                "binding": bound,
                "quote": passage["quote"],
                "location": None,
            }
            if bound == "exact":
                location = evidence._locate(passage, pages, indexes, whole)
                entry.update(state=location["state"], location=location)
            else:
                entry["state"] = "source_unknown" if bound == "unknown" else "source_mismatch"
            checks.append(entry)
        for quantity in quantities(item["text"]):
            quantity_count += 1
            if quantity_count > MAX_QUANTITIES:
                _fail("quantity_limit")
            present = (quantity["value"], quantity["unit"]) in original_quantities
            state = (
                ("observed" if present else "not_observed")
                if binding == "exact"
                else ("source_unknown" if binding == "unknown" else "source_mismatch")
            )
            checks.append(
                {**base, "rule": "quantity_occurrence", "state": state, "quantity": quantity}
            )
        for rule, state in _reference(item["reference"]):
            checks.append({**base, "rule": rule, "state": state})
        progress(index + 1, len(items))
    if cancelled():
        _fail("cancelled")
    counts = {}
    for check in checks:
        counts[check["state"]] = counts.get(check["state"], 0) + 1
    report = {
        "format": FORMAT,
        "rule_version": RULE,
        "source": source,
        "input_hash": content.hashed(items),
        "page_count": len(pages),
        "items": copy.deepcopy(items),
        "checks": checks,
        "counts": counts,
        "semantics": "not_checked",
        "scope": list(CHECKS),
        "not_checked": [
            "semantic_support",
            "number_interpretation",
            "image_only_text",
            "causal_influence",
            "author_identity",
            "full_reference_resolution",
        ],
    }
    return {**report, "id": content.hashed(report)}
