"""Bounded lexical source retrieval for explicit appraisal, never evidence of completeness."""

from __future__ import annotations

import re
from collections import Counter

from paper_daily import claim_content
from paper_daily import research_evidence as evidence

MAX_SPANS = 96
SPANS_PER_ITEM = 6
WORDS_PER_SPAN = 100
MAX_SPAN_CHARS = 2400
_TOKEN = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{1,}|[\u3400-\u9fff]|\d+(?:\.\d+)?")
_STOP = {
    "the",
    "and",
    "that",
    "this",
    "with",
    "from",
    "were",
    "was",
    "for",
    "are",
    "not",
    "but",
    "has",
    "have",
}


def tokens(value):
    return Counter(
        token
        for token in _TOKEN.findall(claim_content.normalize(value).lower())
        if token not in _STOP
    )


def retrieve(snapshot, items, *, cancelled=lambda: False):
    source, data = evidence._checked_snapshot(snapshot)
    pages, indexes, whole = evidence._extract(data, cancelled)
    spans = []
    for page, words in enumerate(pages):
        if cancelled():
            raise evidence.EvidenceError("cancelled")
        for start in range(0, len(words), WORDS_PER_SPAN):
            chunk = words[start : start + WORDS_PER_SPAN]
            text = evidence._index(chunk)[0]
            if not text.strip() or len(text) > MAX_SPAN_CHARS:
                continue
            anchor = dict(p0=page, o0=chunk[0][1], p1=page, o1=chunk[-1][1])
            spans.append(
                dict(
                    id=claim_content.hashed([source, anchor, text]),
                    text=text,
                    page=page + 1,
                    anchor=anchor,
                    _tokens=tokens(text),
                )
            )
    selected = {}
    total = set()
    for item in items:
        if item.get("source_paper_id", source["paper_id"]) != source["paper_id"]:
            selected[item["id"]] = []
            continue
        query = tokens(item["text"])
        ranked = []
        for position, span in enumerate(spans):
            # Lexical overlap is a retrieval order, never a confidence/quality score.
            overlap = sum(min(n, span["_tokens"].get(t, 0)) for t, n in query.items())
            if overlap:
                ranked.append((-overlap, position, span))
        chosen = []
        for _score, _position, span in sorted(ranked)[:SPANS_PER_ITEM]:
            chosen.append({key: value for key, value in span.items() if key != "_tokens"})
            total.add(span["id"])
        if len(total) > MAX_SPANS:
            raise ValueError("Appraisal retrieval exceeds its span budget")
        selected[item["id"]] = chosen
    return selected, (pages, indexes, whole)
