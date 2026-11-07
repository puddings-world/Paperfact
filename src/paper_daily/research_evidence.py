"""Bounded, source-bound quote verification, independent of UI, agents and storage.

A located quote is not proof that a claim is supported. Caller judgments and
external citation identities remain explicitly unverified semantic proposals.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, field
from itertools import islice

from paper_daily.document_reader import DocumentReader, ResolvedDocument
from paper_daily.fetch import _safe_name

FORMAT = "paperfact.claim-evidence.proposals.v1"
REPORT = "paperfact.claim-evidence.report.v1"
RULE = "nfkc-whitespace-soft-hyphen-wrap.v1"
MAX_REQUEST_BYTES = 256 * 1024
MAX_PDF_BYTES = 32 * 1024 * 1024
MAX_PAGES = 500
MAX_WORDS = 200_000
MAX_WORDS_PER_PAGE = 20_000
MAX_TEXT_CHARS = 2_000_000
MAX_CLAIMS = 64
MAX_PASSAGES = 128
MAX_QUOTE_CHARS = 4000
MAX_MATCHES = 8
ANCHOR_KEYS = {"p0", "o0", "p1", "o1"}


class EvidenceError(ValueError):
    """A content-free machine-readable failure; no partial verified report exists."""

    def __init__(self, code):
        self.code = code
        super().__init__("Claim evidence verification: " + code)


def _fail(code):
    raise EvidenceError(code) from None


def _json(value):
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("invalid_schema")


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _normalize(text):
    text = unicodedata.normalize("NFKC", text).replace("\u00ad", "")
    return " ".join(re.sub(r"-\s*\n\s*(?=[a-z])", "", text).split())


def _text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        _fail("invalid_schema")
    return value


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) <= set(required) | set(
        optional
    ):
        _fail("invalid_schema")


def _validate(payload):
    # Copy JSON data once so a caller cannot alter authority while PDF IO runs.
    try:
        encoded = _json(payload).encode("utf-8")
    except UnicodeError:
        _fail("invalid_schema")
    if len(encoded) > MAX_REQUEST_BYTES:
        _fail("request_limit")
    payload = json.loads(encoded)
    _keys(payload, {"format", "source", "claims"})
    if payload["format"] != FORMAT:
        _fail("invalid_schema")
    _keys(payload["source"], {"paper_id", "document_hash"})
    _text(payload["source"]["paper_id"], 512)
    fingerprint = payload["source"]["document_hash"]
    if not isinstance(fingerprint, str) or not re.fullmatch("[0-9a-f]{64}", fingerprint):
        _fail("invalid_schema")
    claims = payload["claims"]
    if not isinstance(claims, list):
        _fail("invalid_schema")
    if len(claims) > MAX_CLAIMS:
        _fail("claim_limit")
    texts, total = set(), 0
    for claim in claims:
        _keys(claim, {"text", "judgment", "passages"})
        text = _normalize(_text(claim["text"], 2000))
        if not text:
            _fail("invalid_schema")
        if text in texts:
            _fail("duplicate_claim")
        texts.add(text)
        judgment = claim["judgment"]
        _keys(judgment, {"status", "reason"})
        if not isinstance(judgment["status"], str) or judgment["status"] not in {
            "supported",
            "inferred",
            "unresolved",
        }:
            _fail("invalid_schema")
        _text(judgment["reason"], 2000)
        if not isinstance(claim["passages"], list):
            _fail("invalid_schema")
        total += len(claim["passages"])
        if total > MAX_PASSAGES:
            _fail("passage_limit")
        passages = set()
        for passage in claim["passages"]:
            _keys(passage, {"quote", "page", "anchor"}, {"citation"})
            quote = _normalize(_text(passage["quote"], MAX_QUOTE_CHARS))
            if not quote:
                _fail("invalid_schema")
            if passage["page"] is not None and type(passage["page"]) is not int:
                _fail("invalid_schema")
            anchor = passage["anchor"]
            if anchor is not None:
                _keys(anchor, ANCHOR_KEYS)
                if any(type(anchor[key]) is not int for key in ANCHOR_KEYS):
                    _fail("invalid_schema")
            citation = passage.get("citation")
            if citation is not None:
                _keys(citation, {"paper_id", "doi", "title"})
                if not any(citation.values()):
                    _fail("invalid_schema")
                for value in citation.values():
                    if value is not None:
                        _text(value, 1000)
            key = _json([quote, passage["page"], anchor])
            if key in passages:
                _fail("duplicate_passage")
            passages.add(key)
    return payload


def _check_source(document):
    if (
        not isinstance(document, ResolvedDocument)
        or not document.available
        or not isinstance(document._owner, DocumentReader)
    ):
        _fail("source_unavailable")
    if not document._owner.intact(document):
        _fail("source_changed")
    try:
        if document.managed:
            target = document.target
            if (
                not target
                or target["paper_id"] != document.paper_id
                or target["sha256"] != document.sha256
            ):
                _fail("source_identity_mismatch")
        else:
            root = document._owner.legacy_root
            if (
                root is None
                or document.path.resolve()
                != (root / (_safe_name(document.local_id) + ".pdf")).resolve()
            ):
                _fail("source_identity_mismatch")
        if document.path.stat().st_size > MAX_PDF_BYTES:
            _fail("pdf_limit")
        with document.path.open("rb") as stream:
            data = stream.read(MAX_PDF_BYTES + 1)
    except OSError:
        _fail("source_unavailable")
    if len(data) > MAX_PDF_BYTES:
        _fail("pdf_limit")
    if hashlib.sha256(data).hexdigest() != document.sha256:
        _fail("source_changed")
    if not document._owner.intact(document):
        _fail("source_changed")
    return data


def _page_words(page, number):
    words = page.get_text("words")
    if len(words) > MAX_WORDS_PER_PAGE:
        _fail("text_limit")
    return [(number, index, item[4], tuple(item[5:7])) for index, item in enumerate(words)]


def _index(words):
    parts, starts, ends, refs, size = [], [], [], [], 0
    prior = None
    for page, order, raw, line in words:
        piece = _normalize(raw)
        if not piece:
            continue
        wrap = bool(
            prior
            and prior[0] == page
            and prior[1] != line
            and parts[-1].endswith("-")
            and piece[:1].islower()
        )
        if wrap:
            parts[-1] = parts[-1][:-1]
            size -= 1
            ends[-1] -= 1
        elif parts:
            parts.append(" ")
            size += 1
        starts.append(size)
        size += len(piece)
        ends.append(size)
        refs.append((page, order))
        parts.append(piece)
        prior = (page, line)
    return "".join(parts), starts, ends, refs


def _ascii_word(char):
    return bool(char and char.isascii() and (char.isalnum() or char == "_"))


def _matches(index, quote):
    text, starts, ends, refs = index
    offset = 0
    while True:
        start = text.find(quote, offset)
        if start < 0:
            return
        end = start + len(quote)
        offset = start + 1
        # Preserve lexical boundaries: treatment must not match pretreatment.
        if (start and _ascii_word(text[start - 1]) and _ascii_word(quote[0])) or (
            end < len(text) and _ascii_word(text[end]) and _ascii_word(quote[-1])
        ):
            continue
        first, last = bisect_right(starts, start) - 1, bisect_right(starts, end - 1) - 1
        if first < 0 or end > ends[last]:
            continue
        p0, o0 = refs[first]
        p1, o1 = refs[last]
        yield {"p0": p0, "o0": o0, "p1": p1, "o1": o1}


def _location(state, reason=None, anchor=None, candidates=(), truncated=False):
    return {
        "state": state,
        "reason": reason,
        "anchor": anchor,
        "page": anchor["p0"] + 1 if anchor else None,
        "candidates": list(candidates),
        "truncated": truncated,
    }


def _locate(passage, pages, indexes, whole):
    page, anchor = passage["page"], passage["anchor"]
    quote = _normalize(passage["quote"])
    if page is not None and not 1 <= page <= len(pages):
        return _location("invalid_page", "page_out_of_range")
    if anchor is not None:
        p0, o0, p1, o1 = (anchor[key] for key in ("p0", "o0", "p1", "o1"))
        if (
            not 0 <= p0 <= p1 < len(pages)
            or not 0 <= o0 < len(pages[p0])
            or not 0 <= o1 < len(pages[p1])
            or (p1, o1) < (p0, o0)
            or (page is not None and page != p0 + 1)
        ):
            return _location("invalid_anchor", "anchor_out_of_range_or_page_mismatch")
        selected = [
            word
            for number in range(p0, p1 + 1)
            for word in pages[number]
            if (p0, o0) <= word[:2] <= (p1, o1)
        ]
        matches = list(islice(_matches(_index(selected), quote), 2))
        if len(matches) != 1 or matches[0] != anchor:
            return _location("invalid_anchor", "anchor_does_not_bound_unique_quote")
        return _location("located", anchor=anchor)
    matches = []
    for index in [indexes[page - 1]] if page is not None else [whole]:
        for found in _matches(index, quote):
            matches.append(found)
            if len(matches) > MAX_MATCHES:
                return _location(
                    "ambiguous",
                    "multiple_quote_locations",
                    candidates=matches[:MAX_MATCHES],
                    truncated=True,
                )
    if not matches:
        return _location("missing", "quote_not_found")
    if len(matches) > 1:
        return _location("ambiguous", "multiple_quote_locations", candidates=matches)
    return _location("located", anchor=matches[0])


_SNAPSHOT_KEY = secrets.token_bytes(32)


@dataclass(frozen=True, slots=True)
class EvidenceSnapshot:
    """Process-sealed original bytes; never deserialize these as wire authority."""

    _source_json: str = field(repr=False)
    _bytes: bytes = field(repr=False)
    _origin: object = field(repr=False)
    _seal: str = field(repr=False)

    @property
    def source(self):
        return json.loads(self._source_json)


def _snapshot_seal(source, data, origin):
    message = _json([source, hashlib.sha256(data).hexdigest(), id(origin), os.getpid()]).encode()
    return hmac.new(_SNAPSHOT_KEY, message, "sha256").hexdigest()


def capture(document):
    """Capture owner-verified immutable bytes before a bounded remote operation."""
    data = _check_source(document)
    source = {"paper_id": document.paper_id or document.local_id, "document_hash": document.sha256}
    return EvidenceSnapshot(_json(source), data, document, _snapshot_seal(source, data, document))


def capture_original(proof, *, cancelled=lambda: False):
    """Worker: reuse an actual receiver-owned retained-original read capability.

    This grants content verification only, never research publication. Old paths,
    hashes or hand-built current-document objects are not accepted authority.
    """
    from paper_daily import resumed_draft_originals

    fresh = resumed_draft_originals.revalidate(proof, cancelled=cancelled)
    payload = json.loads(fresh.prepared.payload)
    source = {"paper_id": payload["paper_id"], "document_hash": fresh.document_hash}
    data = fresh.data
    if not isinstance(data, bytes) or len(data) > MAX_PDF_BYTES:
        _fail("pdf_limit")
    if hashlib.sha256(data).hexdigest() != source["document_hash"]:
        _fail("source_changed")
    return EvidenceSnapshot(_json(source), data, fresh, _snapshot_seal(source, data, fresh))


def _checked_snapshot(snapshot):
    if (
        not isinstance(snapshot, EvidenceSnapshot)
        or not isinstance(snapshot._source_json, str)
        or len(snapshot._source_json) > 2048
        or not isinstance(snapshot._seal, str)
        or not re.fullmatch("[0-9a-f]{64}", snapshot._seal)
        or not isinstance(snapshot._bytes, bytes)
        or len(snapshot._bytes) > MAX_PDF_BYTES
    ):
        _fail("invalid_snapshot")
    try:
        source = snapshot.source
    except (ValueError, TypeError):
        _fail("invalid_snapshot")
    if (
        not isinstance(snapshot._bytes, bytes)
        or not hmac.compare_digest(
            snapshot._seal, _snapshot_seal(source, snapshot._bytes, snapshot._origin)
        )
        or hashlib.sha256(snapshot._bytes).hexdigest() != source["document_hash"]
    ):
        _fail("invalid_snapshot")
    return source, snapshot._bytes


def _cancel(cancelled):
    if cancelled is not None and cancelled():
        _fail("cancelled")


def _extract(data, cancelled=None):
    import pymupdf

    pages, indexes, words, chars = [], [], 0, 0
    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            if pdf.needs_pass:
                _fail("encrypted_document")
            if not 1 <= len(pdf) <= MAX_PAGES:
                _fail("page_limit")
            for number, page in enumerate(pdf):
                _cancel(cancelled)
                page_words = _page_words(page, number)
                index = _index(page_words)
                words += len(page_words)
                chars += len(index[0])
                if words > MAX_WORDS or chars > MAX_TEXT_CHARS:
                    _fail("text_limit")
                pages.append(page_words)
                indexes.append(index)
    except EvidenceError:
        raise
    except (RuntimeError, ValueError, OSError):
        raise EvidenceError("invalid_document") from None
    whole = _index(word for page in pages for word in page)
    return pages, indexes, whole


def snapshot_pages(snapshot, *, cancelled=None):
    """Bounded normalized original pages for explicit AI input, without recapture."""
    _source, data = _checked_snapshot(snapshot)
    _cancel(cancelled)
    _pages, indexes, _whole = _extract(data, cancelled)
    return [{"page": index + 1, "text": value[0]} for index, value in enumerate(indexes)]


def _verify_bytes(data, expected, payload, cancelled):
    _cancel(cancelled)
    pages, indexes, whole = _extract(data, cancelled)
    results = []
    for claim in payload["claims"]:
        _cancel(cancelled)
        claim_id = _hash(["claim", expected, _normalize(claim["text"])])
        passages, located = [], set()
        for passage in claim["passages"]:
            _cancel(cancelled)
            location = _locate(passage, pages, indexes, whole)
            if location["state"] == "located":
                key = _json(location["anchor"])
                if key in located:
                    _fail("duplicate_passage")
                located.add(key)
            citation = passage.get("citation")
            proposal_id = _hash(
                [
                    "passage-proposal",
                    expected,
                    _normalize(passage["quote"]),
                    passage["page"],
                    passage["anchor"],
                ]
            )
            passage_id = (
                _hash(
                    [
                        "located-passage",
                        expected,
                        _normalize(passage["quote"]),
                        location["anchor"],
                    ]
                )
                if location["state"] == "located"
                else proposal_id
            )
            passages.append(
                {
                    "id": passage_id,
                    "proposal_id": proposal_id,
                    "quote": passage["quote"],
                    "location": location,
                    "citation_identity": {
                        "state": "unresolved" if citation is not None else "not_requested",
                        "reason": "no_trusted_citation_mapping" if citation is not None else None,
                        "proposed": citation,
                    },
                }
            )
        results.append(
            {
                "id": claim_id,
                "text": claim["text"],
                "atomicity": "caller_supplied",
                "judgment": {**claim["judgment"], "authority": "caller"},
                "semantic_validation": "not_performed",
                "passages": passages,
            }
        )
    _cancel(cancelled)
    report = {
        "format": REPORT,
        "source": expected,
        "normalization": RULE,
        "page_count": len(pages),
        "claims": results,
    }
    return {**report, "id": _hash(report)}


def _bound_payload(source, proposals):
    payload = _validate(proposals)
    if payload["source"]["paper_id"] != source["paper_id"]:
        _fail("source_identity_mismatch")
    if payload["source"]["document_hash"] != source["document_hash"]:
        _fail("source_hash_mismatch")
    return payload


def verify_snapshot(snapshot, proposals, *, cancelled=None):
    """Verify only captured original bytes, not today's active/current source.

    The caller must publish through observed generation. A changed source retains
    this completed original-source result as a candidate rather than adopting it.
    """
    source, data = _checked_snapshot(snapshot)
    report = _verify_bytes(data, source, _bound_payload(source, proposals), cancelled)
    report.pop("id")
    report["verification_scope"] = "original_snapshot"
    return {**report, "id": _hash(report)}


def verify(document, proposals, *, cancelled=None):
    """Verify proposals against an explicit source still intact at both boundaries."""
    if not isinstance(document, ResolvedDocument):
        _fail("source_unavailable")
    source = {"paper_id": document.paper_id or document.local_id, "document_hash": document.sha256}
    payload = _bound_payload(source, proposals)
    _cancel(cancelled)
    data = _check_source(document)
    report = _verify_bytes(data, source, payload, cancelled)
    _check_source(document)
    return report


QUOTE_FORMAT = "paperfact.quote-locations.proposals.v1"
QUOTE_REPORT = "paperfact.quote-locations.report.v1"


def locate_quotes_snapshot(snapshot, proposals, *, cancelled=None):
    """Locate bounded quotes without creating assertions or semantic judgments.

    This reuses the same normalization/anchor engine as claim verification.
    Results describe captured bytes only, never permission to publish research.
    """
    _cancel(cancelled)
    source, data = _checked_snapshot(snapshot)
    try:
        encoded = _json(proposals).encode("utf-8")
    except UnicodeError:
        _fail("invalid_schema")
    if len(encoded) > MAX_REQUEST_BYTES:
        _fail("request_limit")
    payload = json.loads(encoded)
    _keys(payload, {"format", "source", "passages"})
    if payload["format"] != QUOTE_FORMAT:
        _fail("invalid_schema")
    _keys(payload["source"], {"paper_id", "document_hash"})
    _text(payload["source"]["paper_id"], 4096)
    fingerprint = payload["source"]["document_hash"]
    if not isinstance(fingerprint, str) or not re.fullmatch("[0-9a-f]{64}", fingerprint):
        _fail("invalid_schema")
    if payload["source"]["paper_id"] != source["paper_id"]:
        _fail("source_identity_mismatch")
    if fingerprint != source["document_hash"]:
        _fail("source_hash_mismatch")
    passages = payload["passages"]
    if not isinstance(passages, list) or not 1 <= len(passages) <= MAX_PASSAGES:
        _fail("passage_limit")
    used = set()
    for passage in passages:
        _keys(passage, {"quote", "page", "anchor"})
        quote = _normalize(_text(passage["quote"], MAX_QUOTE_CHARS))
        if not quote or (passage["page"] is not None and type(passage["page"]) is not int):
            _fail("invalid_schema")
        anchor = passage["anchor"]
        if anchor is not None:
            _keys(anchor, ANCHOR_KEYS)
            if any(type(anchor[key]) is not int for key in ANCHOR_KEYS):
                _fail("invalid_schema")
        key = _json([quote, passage["page"], anchor])
        if key in used:
            _fail("duplicate_passage")
        used.add(key)
    pages, indexes, whole = _extract(data, cancelled)
    results = []
    for passage in passages:
        _cancel(cancelled)
        results.append(
            dict(
                quote=passage["quote"],
                page_hint=passage["page"],
                location=_locate(passage, pages, indexes, whole),
            )
        )
    _cancel(cancelled)
    _checked_snapshot(snapshot)
    report = dict(
        format=QUOTE_REPORT,
        source=source,
        normalization=RULE,
        page_count=len(pages),
        empty_pages=[i + 1 for i, page in enumerate(pages) if not page],
        passages=results,
        verification_scope="original_snapshot",
        semantic_validation="not_performed",
    )
    return {**report, "id": _hash(report)}
