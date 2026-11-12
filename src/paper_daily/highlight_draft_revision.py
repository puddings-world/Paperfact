"""Closed human highlight proposals; exact selectable original quotes, no write grant."""

from __future__ import annotations

import hashlib
import json
from itertools import islice

from paper_daily import annotation_content as annotations
from paper_daily import research_evidence as evidence

FORMAT = "paperfact.highlight-review-draft.v1"
MAX_BYTES = annotations.MAX_BYTES


def _encoded(value):
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("Invalid highlight draft JSON") from error


def _load(raw, limit=MAX_BYTES):
    if not isinstance(raw, (str, bytes)):
        raise ValueError("Use a bounded encoded highlight draft")

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("Duplicate highlight draft field")
            value[key] = item
        return value

    def nonfinite(_value):
        raise ValueError("Nonfinite highlight draft value")

    try:
        data = raw.encode("utf-8") if isinstance(raw, str) else raw
        if len(data) > limit:
            raise ValueError("Highlight draft exceeds its byte bound")
        return json.loads(data, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (UnicodeError, TypeError, RecursionError) as error:
        raise ValueError("Invalid bounded highlight draft JSON") from error


def _baseline(row):
    annotations.validate_row("highlight_analysis", row)
    if row["document_hash"] is None:
        raise ValueError("Highlight baseline has no exact original source")
    saved = _load(_encoded(row), 2 * MAX_BYTES + 16384)
    return saved, annotations.decode("highlight_analysis", saved["body_json"])


def _checked(row, body, draft):
    annotations._closed(draft, {"format", "baseline_digest", "source", "items"})
    if draft["format"] != FORMAT:
        raise ValueError("Unsupported highlight draft format")
    if draft["baseline_digest"] != evidence._hash(row):
        raise ValueError("Highlight draft belongs to another complete saved baseline")
    if draft["source"] != dict(paper_id=row["paper_id"], document_hash=row["document_hash"]):
        raise ValueError("Highlight draft cannot change its original source")
    items = draft["items"]
    if not isinstance(items, list) or not 1 <= len(items) <= annotations.MAX_ITEMS:
        raise ValueError("Highlight draft needs a bounded nonempty group")
    # Validate proposed fields without inventing a claim or accepting output flags.
    used = set()
    for item in items:
        annotations._closed(item, {"text", "page", "anchor", "kind", "reason"})
        annotations._text(item["text"], 4000, minimum=20)
        annotations._text(item["reason"], 1600)
        annotations._page(item["page"])
        if not isinstance(item["kind"], str) or item["kind"] not in annotations.KINDS:
            raise ValueError("Invalid proposed highlight role")
        anchor = item["anchor"]
        if anchor is not None:
            annotations._closed(anchor, evidence.ANCHOR_KEYS)
            if any(
                type(value) is not int or not 0 <= value <= 1000000 for value in anchor.values()
            ):
                raise ValueError("Invalid proposed highlight coordinates")
        key = (item["page"], evidence._normalize(item["text"]))
        if key in used:
            raise ValueError("Duplicate proposed highlight")
        used.add(key)
    # A copy prevents concurrent mutation during original-byte verification.
    return _load(_encoded(draft))


def editable(baseline):
    row, body = _baseline(baseline)
    draft = dict(
        format=FORMAT,
        baseline_digest=evidence._hash(row),
        source=dict(paper_id=row["paper_id"], document_hash=row["document_hash"]),
        items=[
            dict(
                text=item["text"],
                page=item["page"],
                anchor=None,
                kind=item["kind"],
                reason=item["reason"],
            )
            for item in body["items"]
        ],
    )
    return _checked(row, body, draft)


def parse(baseline, raw):
    """Closed private proposal validation, no file, SQL, AI or publication."""
    row, body = _baseline(baseline)
    return _checked(row, body, _load(raw))


def _selectable(document, cache, quote, anchor):
    from paper_daily.pdf_selection_text import level_words

    p0, o0, p1, o1 = (anchor[key] for key in ("p0", "o0", "p1", "o1"))
    selected = []
    for number in range(p0, p1 + 1):
        if number not in cache:
            cache[number] = level_words(document[number])
        words = cache[number]
        orders = {index for index, _word in words}
        if (number == p0 and o0 not in orders) or (number == p1 and o1 not in orders):
            return False
        selected.extend(
            (number, index, word[4], tuple(word[5:7]))
            for index, word in words
            if (p0, o0) <= (number, index) <= (p1, o1)
        )
    matches = list(
        islice(evidence._matches(evidence._index(selected), evidence._normalize(quote)), 2)
    )
    return matches == [anchor]


def _revise(snapshot, baseline, raw, *, receiver, cancelled):
    import pymupdf

    evidence._cancel(cancelled)
    row, body = _baseline(baseline)
    draft = _checked(row, body, _load(raw))
    source, data = evidence._checked_snapshot(snapshot)
    if source["document_hash"] != draft["source"]["document_hash"]:
        raise ValueError("Highlight snapshot is not the exact original")
    if not receiver and source["paper_id"] != draft["source"]["paper_id"]:
        raise ValueError("Highlight snapshot belongs to another paper")
    report = evidence.locate_quotes_snapshot(
        snapshot,
        dict(
            format=evidence.QUOTE_FORMAT,
            source=source,
            passages=[
                dict(quote=item["text"], page=item["page"], anchor=item["anchor"])
                for item in draft["items"]
            ],
        ),
        cancelled=cancelled,
    )
    coverage = body["coverage"]
    if coverage["pages"] != report["page_count"] or (
        coverage["has_page_numbers"] and sorted(coverage["empty_pages"]) != report["empty_pages"]
    ):
        raise ValueError("Saved highlight coverage differs from the exact original")
    reviewed, marks, items = [], [], []
    used = set()
    with pymupdf.open(stream=data, filetype="pdf") as document:
        cache = {}
        for index, (item, located) in enumerate(
            zip(draft["items"], report["passages"], strict=True)
        ):
            evidence._cancel(cancelled)
            location = located["location"]
            if location["state"] == "located" and not _selectable(
                document, cache, item["text"], location["anchor"]
            ):
                location = evidence._location("invalid_anchor", "not_selectable_in_reader")
            reviewed.append({**item, "location": location})
            if location["state"] != "located":
                continue
            key = evidence._json(location["anchor"])
            if key in used:
                raise ValueError("Highlight proposals resolve to the same source range")
            used.add(key)
            page = location["page"]
            items.append(
                dict(
                    text=item["text"],
                    page=page,
                    kind=item["kind"],
                    reason=item["reason"],
                    source=f"page:{page}",
                )
            )
            marks.append(
                dict(
                    source_key=hashlib.sha256(f"{page}:{item['text']}".encode()).hexdigest(),
                    anchor=location["anchor"],
                    item_index=index,
                )
            )
    evidence._cancel(cancelled)
    complete = len(marks) == len(draft["items"])
    analysis = (
        annotations.validate("highlight_analysis", dict(items=items, coverage=coverage))
        if complete
        else None
    )
    return dict(
        source=source,
        baseline_digest=draft["baseline_digest"],
        draft_digest=evidence._hash(draft),
        baseline_source_hash=row["source_hash"],
        items=reviewed,
        coverage=coverage,
        analysis=analysis,
        marks=marks if complete else [],
        all_quotes_located=complete,
        generation=dict(
            task="highlight_analysis", backend="manual", requested_model=None, returned_model=None
        ),
        semantic_validation="not_performed",
    )


def revise(snapshot, baseline, raw, *, cancelled=None):
    """Content-only edit against the exact captured original; no Apply authority."""
    return _revise(snapshot, baseline, raw, receiver=False, cancelled=cancelled)


def revise_for_receiver(snapshot, baseline, raw, *, cancelled=None):
    """Explicit content-only receiver mapping; the future operation owns target CAS."""
    return _revise(snapshot, baseline, raw, receiver=True, cancelled=cancelled)
