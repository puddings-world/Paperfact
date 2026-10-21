"""OpenAlex: the route to everything that is not a conference paper or a preprint.

The resolution chain was Semantic Scholar, then CVF, then arXiv. That covers ML
conferences and preprints and little else, so a list of medical-imaging work came
back with entries marked "unknown 0" and no PDF -- including a Nature Scientific Data
paper whose open-access PDF is one search away.

OpenAlex indexes ~250M works across every publisher, is free with no key, and carries
the field the others do not: `best_oa_location.pdf_url`, a direct link to a legally
free copy. It also fills in venue, year and authors, which is what turns "unknown 0"
back into a real citation.

Matching is by normalised title, like every other matcher here: the search is fuzzy
and would otherwise hand back a different paper with confidence.
"""

from __future__ import annotations

import json
import re
import urllib.parse

from paper_daily.http import fetch_text

API = "https://api.openalex.org/works"

# OpenAlex asks for a contact address and gives the "polite pool" -- faster and more
# reliably served -- in return. It is sent as a query parameter, not a header, so it
# also lands in the disk cache key, which is fine: it never changes.
MAILTO = "paper-daily@users.noreply.github.com"


def _norm(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum())


# Words that carry no identity: two unrelated surgical papers share all of them.
_STOP = {
    "a", "an", "and", "for", "from", "in", "of", "on", "the", "to", "via", "with",
    "using", "based", "towards", "toward",
}


def _tokens(title: str) -> set[str]:
    words = re.split(r"[^A-Za-z0-9]+", (title or "").lower())
    return {w for w in words if w and w not in _STOP and len(w) > 1}


def _acronym(title: str) -> str | None:
    """The name before the colon, when it looks like a method name rather than prose.

    "CSMAE: Cataract Surgical Masked Autoencoder" -> "csmae". This is the part of a
    title that people never paraphrase, which makes it the reliable half.
    """
    head = (title or "").split(":")[0].strip()
    if not head or len(head.split()) > 2 or len(head) > 24:
        return None
    if not any(c.isdigit() or c.isupper() for c in head):
        return None
    return _norm(head)


def same_paper(wanted: str, candidate: str) -> bool:
    """Is this the paper someone meant, written under its real title?

    A bibliography shortens and paraphrases. "CSMAE: Cataract Surgery Masked
    Autoencoder" is filed as "CSMAE: Cataract Surgical Masked Autoencoder (MAE) Based
    Pre-Training", and an exact-title match will never find it, which is how papers
    that are one web search away came to be marked unavailable.

    So: identical after normalising, or the method name matches and the rest overlaps,
    or almost every significant word of the shorter title appears in the longer. The
    thresholds are deliberately high -- returning the wrong paper is worse than
    returning none, because the reader would be given an explanation of something else.
    """
    if _norm(wanted) == _norm(candidate):
        return True
    a, b = _tokens(wanted), _tokens(candidate)
    if not a or not b:
        return False

    acronym = _acronym(wanted)
    if acronym and len(acronym) >= 3 and acronym == _acronym(candidate):
        return len(a & b) / min(len(a), len(b)) >= 0.4

    # Without a shared method name, a short title carries too little to be sure.
    # "llama.cpp" is two words, and both of them appear in "llama-roofline: a
    # portable memory-bandwidth roofline for llama.cpp" -- a different work entirely,
    # which the relaxed rule accepted and retitled the row to.
    if min(len(a), len(b)) < 4:
        return False
    return len(a & b) / len(a | b) >= 0.6


def _abstract(work: dict) -> str | None:
    """OpenAlex stores abstracts as a word -> positions index, for copyright reasons."""
    index = work.get("abstract_inverted_index")
    if not index:
        return None
    positions: list[tuple[int, str]] = []
    for word, spots in index.items():
        positions.extend((spot, word) for spot in spots)
    if not positions:
        return None
    positions.sort()
    return " ".join(word for _spot, word in positions)[:4000]


def _pdf_url(work: dict) -> str | None:
    for key in ("best_oa_location", "primary_location"):
        location = work.get(key) or {}
        url = location.get("pdf_url")
        if url:
            return url
    return None


def _venue(work: dict) -> str | None:
    for key in ("primary_location", "best_oa_location"):
        source = (work.get(key) or {}).get("source") or {}
        if source.get("display_name"):
            return source["display_name"]
    return None


SELECT = (
    "id,doi,display_name,publication_year,authorships,"
    "primary_location,best_oa_location,cited_by_count,abstract_inverted_index"
)


def _query(params: dict) -> list[dict]:
    query = urllib.parse.urlencode({**params, "per-page": 5, "select": SELECT, "mailto": MAILTO})
    try:
        payload = json.loads(fetch_text(f"{API}?{query}", max_age=30 * 86400, retries=3))
    except Exception:
        return []
    return payload.get("results") or []


def match_title(title: str) -> dict | None:
    """Look a paper up by title. Returns the fields a papers row needs, or None."""
    if not title or not title.strip():
        return None

    # The title filter is precise and cheap; relevance search is the fallback for a
    # citation that paraphrased the title, which is most of the ones that fail.
    candidates = _query({"filter": f"title.search:{title}"})
    if not any(same_paper(title, w.get("display_name", "")) for w in candidates):
        candidates += _query({"search": title})

    for work in candidates:
        if not same_paper(title, work.get("display_name", "")):
            continue
        doi = (work.get("doi") or "").replace("https://doi.org/", "") or None
        return {
            "title": work.get("display_name"),
            "year": work.get("publication_year"),
            "venue": _venue(work),
            "doi": doi,
            "pdf_url": _pdf_url(work),
            "page_url": work.get("doi"),
            "authors": [
                a.get("author", {}).get("display_name")
                for a in (work.get("authorships") or [])
                if a.get("author", {}).get("display_name")
            ],
            "abstract": _abstract(work),
            "citation_count": work.get("cited_by_count"),
        }
    return None
