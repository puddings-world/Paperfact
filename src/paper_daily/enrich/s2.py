"""Semantic Scholar: citation counts, author strength, lineage, and the ICLR roster.

S2 plays three roles:
  1. roster for ICLR, which has no open proceedings site (OpenReview's /notes API is
     behind an anti-bot challenge and its PDFs 403 for anonymous clients);
  2. stand-in roster for a venue whose proceedings are not posted yet -- NeurIPS
     publishes months after the conference, so the newest year is S2-only for a while;
  3. enrichment for every paper, matched back onto the authoritative roster by title.

One bulk query returns 1000 papers, so the whole decade costs ~60 paginated requests
rather than one request per paper.
"""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Iterator
from typing import Any

from paper_daily.http import fetch, post_json

API = "https://api.semanticscholar.org/graph/v1"

# Fields the bulk endpoint actually accepts (verified -- authors.hIndex and tldr do not).
BULK_FIELDS = (
    "paperId,title,year,venue,abstract,citationCount,influentialCitationCount,"
    "referenceCount,externalIds,openAccessPdf,publicationTypes,fieldsOfStudy,"
    "s2FieldsOfStudy,authors"
)

# One query string per venue is enough: Semantic Scholar normalises venue names, so
# "NeurIPS" and "Neural Information Processing Systems" return identical result sets
# (13608 each for 2023-2025), and querying both would simply triple the request count.
VENUE_QUERY = {"ICLR": "ICLR", "ICML": "ICML", "NeurIPS": "NeurIPS"}


def bulk_venue_year(venue: str, year: int, window: int = 1) -> Iterator[dict[str, Any]]:
    """Every S2 record for one venue-year, searched over a +/- `window` year range.

    The window is not optional padding. Semantic Scholar records a paper under the
    year of its first public version, so an ICLR 2024 paper first posted to arXiv in
    2023 is filed as 2023. Matching an ICLR 2024 roster against year=2024 alone hits
    42% of the roster; widening to 2023-2025 hits 94%. Since results are matched back
    by exact normalised title against one venue-year roster, the wider net cannot
    pull in papers from a neighbouring year of the same conference.
    """
    alias = VENUE_QUERY.get(venue, venue)
    yearspec = f"{year - window}-{year + window}" if window else str(year)
    seen: set[str] = set()
    token = None
    while True:
        q = {"venue": alias, "year": yearspec, "fields": BULK_FIELDS}
        if token:
            q["token"] = token
        url = f"{API}/paper/search/bulk?{urllib.parse.urlencode(q)}"
        # Results shift as S2 reindexes; a week-old page is fine and saves a lot.
        payload = json.loads(fetch(url, max_age=7 * 86400))
        for p in payload.get("data") or []:
            pid = p.get("paperId")
            if pid and pid not in seen:
                seen.add(pid)
                yield p
        token = payload.get("token")
        if not token:
            break


MATCH_FIELDS = (
    "paperId,title,year,venue,abstract,citationCount,influentialCitationCount,"
    "referenceCount,externalIds,openAccessPdf,authors"
)


def match_title(title: str) -> dict[str, Any] | None:
    """Resolve one paper by exact-ish title.

    The bulk venue search misses the newest conference year almost entirely -- an
    ICLR 2026 venue query matched 18 of 5468 papers, because Semantic Scholar has not
    filed them under the venue yet. This endpoint finds them anyway, and crucially
    returns the arXiv id, which is the only route to a PDF for a year whose papers
    live on OpenReview behind a 403.

    One request per paper, so it is only ever used on papers already in the queue.
    """
    query = urllib.parse.urlencode({"query": title, "fields": MATCH_FIELDS})
    url = f"{API}/paper/search/match?{query}"
    try:
        # Deliberately impatient, unlike the bulk crawl. These are many cheap,
        # independent lookups: losing one costs a single paper's metadata, while
        # the bulk endpoint's long backoff would cost minutes per 429 and drag a
        # 200-paper pass out to half an hour.
        payload = json.loads(fetch(url, max_age=30 * 86400, retries=3))
    except Exception:
        return None
    data = payload.get("data") or []
    return data[0] if data else None


def by_doi(doi: str) -> dict[str, Any] | None:
    """Resolve one paper by DOI, which is exact where a title match is a guess.

    The publisher's reference list gives a DOI for most entries, and a citation
    string from it ("Zhou, Z., Siddiquee, M. M. R. ... Unet++ ...") is a poor search
    query: the author block outweighs the title. With the DOI there is nothing to
    match.
    """
    if not doi:
        return None
    url = f"{API}/paper/DOI:{urllib.parse.quote(doi)}?fields={MATCH_FIELDS}"
    try:
        payload = json.loads(fetch(url, max_age=30 * 86400, retries=3))
    except Exception:
        return None
    return payload or None


def papers_by_doi(dois: list[str]) -> dict[str, dict[str, Any]]:
    """DOI -> record, for a whole reference list in one request.

    One lookup per reference would be 40 requests for a single paper's bibliography,
    which is where the 429s come from. The batch endpoint takes up to 500 ids and
    answers positionally, with null for the ones it cannot resolve.
    """
    wanted = [d for d in dict.fromkeys(dois) if d]
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(wanted), 500):
        chunk = wanted[i : i + 500]
        res = post_json(
            f"{API}/paper/batch?fields={MATCH_FIELDS}",
            {"ids": [f"DOI:{d}" for d in chunk]},
        )
        for doi, record in zip(chunk, res or [], strict=False):
            if record:
                out[doi] = record
    return out


def author_batch(author_ids: list[str]) -> list[dict[str, Any]]:
    """h-index and citation totals for up to 1000 authors per request."""
    out: list[dict[str, Any]] = []
    for i in range(0, len(author_ids), 1000):
        chunk = author_ids[i : i + 1000]
        res = post_json(
            f"{API}/author/batch?fields=name,hIndex,citationCount,paperCount",
            {"ids": chunk},
        )
        out.extend(a for a in (res or []) if a)
    return out


def references(s2_paper_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Works this paper builds on -- the edges that drive lineage expansion."""
    url = (
        f"{API}/paper/{s2_paper_id}/references"
        f"?fields=paperId,title,year,venue,citationCount,isInfluential&limit={limit}"
    )
    payload = json.loads(fetch(url, max_age=30 * 86400))
    out = []
    for e in payload.get("data") or []:
        cited = e.get("citedPaper") or {}
        if cited.get("paperId"):
            cited["isInfluential"] = bool(e.get("isInfluential"))
            out.append(cited)
    return out
