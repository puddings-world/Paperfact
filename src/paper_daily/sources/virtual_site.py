"""Rosters and oral/spotlight labels from the conference "virtual" sites.

These sites turn out to be the best roster source for all three venues:

  * they are authoritative about what was *accepted* (ICLR 2024 lists 2296 papers;
    a Semantic Scholar venue search returns 2845 because it sweeps in workshop
    papers that were never in the main conference);
  * they go up the moment the programme is set, months before PMLR or
    papers.nips.cc publish -- which is the only way to reach the newest year, and
    the newest year is exactly where a newest-first reading order starts;
  * they carry the programme committee's oral/spotlight verdict, which no
    proceedings site and no citation database exposes.

What they do not carry is abstracts or PDFs, so a roster from here is always paired
with a proceedings crawl or Semantic Scholar enrichment.
"""

from __future__ import annotations

import json
import re
from html import unescape
from typing import Any

from paper_daily.http import fetch_text
from paper_daily.store import now, title_key

HOSTS = {"ICLR": "iclr.cc", "ICML": "icml.cc", "NeurIPS": "neurips.cc"}
EVENT_KINDS = ("oral", "spotlight")

_POSTER_RE = re.compile(r'<a href="/virtual/\d+/poster/(\d+)"[^>]*>\s*(.*?)\s*</a>', re.S)
_EVENT_TITLE_RE = re.compile(r'<h3 class="event-title">\s*<a href="[^"]*">\s*(.*?)\s*</a>', re.S)


def _strip(html: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", html)).strip()


def fetch_roster(venue: str, year: int) -> list[dict[str, Any]]:
    """Accepted papers for one venue-year. Titles only -- enrichment fills the rest."""
    host = HOSTS.get(venue)
    if not host:
        return []
    try:
        html = fetch_text(
            f"https://{host}/virtual/{year}/papers.html?filter=titles", max_age=7 * 86400
        )
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for poster_id, raw in _POSTER_RE.findall(html):
        title = _strip(raw)
        if not title or title.lower() == "view full details":
            continue
        key = title_key(title)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "id": f"{venue}:{year}:v{poster_id}",
                "venue": venue,
                "year": year,
                "title": title,
                "title_key": key,
                "authors_json": "[]",
                "page_url": f"https://{host}/virtual/{year}/poster/{poster_id}",
                "source": "virtual",
                "crawled_at": now(),
            }
        )
    return out


_JSONLD_RE = re.compile(r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', re.S)
_KEYWORDS_RE = re.compile(r'<meta name="keywords" content="([^"]*)"')
_ABSTRACT_RE = re.compile(r'<div class="abstract-text[^"]*"[^>]*>(.*?)</div>', re.S)


def fetch_paper_detail(page_url: str) -> dict[str, Any]:
    """Authors, abstract and the conference's own topic label for one paper.

    Needed for the newest conference year, where Semantic Scholar has not indexed
    anything yet -- ICLR 2026 matched 18 of 5468 papers -- so the roster would
    otherwise reach the reader with no authors and no abstract at all. One request
    per paper, made only when a paper is actually delivered.
    """
    out: dict[str, Any] = {}
    try:
        html = fetch_text(page_url, max_age=30 * 86400)
    except Exception:
        return out

    m = _JSONLD_RE.search(html)
    if m:
        try:
            data = json.loads(m.group(1))
            names = [a.get("name") for a in data.get("author") or [] if a.get("name")]
            if names:
                out["authors"] = names
        except json.JSONDecodeError:
            pass

    m = _ABSTRACT_RE.search(html)
    if m:
        text = _strip(m.group(1))
        if len(text) > 40:
            out["abstract"] = text

    m = _KEYWORDS_RE.search(html)
    if m and m.group(1).strip():
        out["keywords"] = m.group(1).strip()

    return out


def fetch_awards(venue: str, year: int) -> dict[str, str]:
    """title_key -> "oral" | "spotlight".

    Empty for years that predate these sites; ranking then falls back to its other
    signals rather than pretending every paper was a poster.
    """
    host = HOSTS.get(venue)
    if not host:
        return {}
    out: dict[str, str] = {}
    for kind in reversed(EVENT_KINDS):  # weaker first, so "oral" wins a double listing
        try:
            html = fetch_text(f"https://{host}/virtual/{year}/events/{kind}", max_age=30 * 86400)
        except Exception:
            continue
        for raw in _EVENT_TITLE_RE.findall(html):
            title = _strip(raw)
            if title and title.lower() != "view full details":
                key = title_key(title)
                if key:
                    out[key] = kind
    return out


__all__ = ["fetch_roster", "fetch_paper_detail", "fetch_awards", "HOSTS"]
