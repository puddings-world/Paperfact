"""arXiv title lookup -- the last route to a PDF.

Needed because the resolution chain has a hole. The newest conference year is not in
Semantic Scholar's venue index, and some of those papers are not in Semantic Scholar
at all yet; OpenReview, where they actually live, returns 403 to anonymous clients on
both `/pdf?id=` and `/attachment?id=`. Without this, such a paper reaches the reader
with an abstract and no original text -- and being newest, it is exactly the kind of
paper at the front of the queue.

Matching is on the normalised title only. arXiv's `ti:` search is fuzzy, so a
candidate is accepted only when its normalised title is identical.
"""

from __future__ import annotations

import re
import urllib.parse

from paper_daily.http import fetch_text
from paper_daily.sources import openalex

API = "http://export.arxiv.org/api/query"

_ENTRY_RE = re.compile(r"<entry>(.*?)</entry>", re.S)
_ID_RE = re.compile(r"<id>https?://arxiv\.org/abs/([^<]+)</id>")
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
_SUMMARY_RE = re.compile(r"<summary>(.*?)</summary>", re.S)
_AUTHOR_RE = re.compile(r"<author>\s*<name>(.*?)</name>", re.S)
_PUBLISHED_RE = re.compile(r"<published>(\d{4})")

# A bare id as people paste it: "2608.17522", "arXiv:2608.17522v2", or the abs URL.
BARE_ID = re.compile(
    r"^\s*(?:arxiv:\s*|https?://arxiv\.org/(?:abs|pdf)/)?(\d{4}\.\d{4,5})(?:v\d+)?\s*$", re.I
)


def _norm(s: str) -> str:
    return "".join(c for c in s.lower() if c.isalnum())


def _entries(search: str) -> list[tuple[str, str]]:
    """(arxiv id, title) for one query, or nothing if arXiv refuses."""
    query = urllib.parse.urlencode({"search_query": search, "max_results": "5"})
    try:
        xml = fetch_text(f"{API}?{query}", max_age=30 * 86400, retries=3)
    except Exception:
        return []
    out = []
    for entry in _ENTRY_RE.findall(xml):
        tm = _TITLE_RE.search(entry)
        im = _ID_RE.search(entry)
        if tm and im:
            # "2505.20435v3" -> "2505.20435"; the bare id always serves the latest.
            out.append((im.group(1).split("v")[0], re.sub(r"\s+", " ", tm.group(1)).strip()))
    return out


def by_id(arxiv_id: str) -> dict | None:
    """{title, authors, abstract, year, arxiv_id} for one arXiv id.

    A paper posted last week is on arXiv before Semantic Scholar has indexed it, so
    adding it by id has to read arXiv itself or the row is titled with the bare id.
    """
    query = urllib.parse.urlencode({"id_list": arxiv_id})
    try:
        xml = fetch_text(f"{API}?{query}", max_age=30 * 86400, retries=3)
    except Exception:
        return None
    entry = _ENTRY_RE.search(xml)
    title = _TITLE_RE.search(entry.group(1)) if entry else None
    if not title:
        return None
    body = entry.group(1)
    summary = _SUMMARY_RE.search(body)
    year = _PUBLISHED_RE.search(body)
    return {
        "title": re.sub(r"\s+", " ", title.group(1)).strip(),
        "authors": [re.sub(r"\s+", " ", a).strip() for a in _AUTHOR_RE.findall(body)],
        "abstract": re.sub(r"\s+", " ", summary.group(1)).strip() if summary else None,
        "year": int(year.group(1)) if year else 0,
        "arxiv_id": arxiv_id,
    }


def match_title(title: str) -> str | None:
    """arXiv id for this paper, or None.

    Exact title first. Then, if the citation named a method -- "RP-SAM2: ..." -- search
    for that name and check the candidates properly, because a bibliography routinely
    paraphrases the subtitle and an exact match then finds nothing at all.
    """
    if not title or not title.strip():
        return None

    want = _norm(title)
    for aid, found in _entries(f'ti:"{title}"'):
        if _norm(found) == want:
            return aid

    acronym = openalex._acronym(title)
    if not acronym or len(acronym) < 3:
        return None
    for aid, found in _entries(f'all:"{title.split(":")[0].strip()}"'):
        if openalex.same_paper(title, found):
            return aid
    return None
