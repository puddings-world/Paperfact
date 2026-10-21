"""NeurIPS roster from papers.nips.cc.

The year index carries title, authors and the per-paper hash, which is everything we
need -- fetching 4k detail pages per year just for abstracts would be 40k requests
across the decade, so abstracts come from Semantic Scholar during enrichment.

Two details the site does not advertise:
  * the PDF filename mirrors the abstract filename ("-Abstract-Conference.html" ->
    "-Paper-Conference.pdf"), and the suffix changed in 2023;
  * the suffix also encodes the track, which is how we spot Datasets & Benchmarks
    papers without reading them.
"""

from __future__ import annotations

import json
import re
from html import unescape
from typing import Any

from paper_daily.http import fetch_text
from paper_daily.store import now, title_key

BASE = "https://papers.nips.cc"

_ITEM_RE = re.compile(
    r'<li[^>]*>\s*<div class="paper-content">\s*'
    r'<a title="paper title" href="([^"]+)">(.*?)</a>\s*'
    r'<span class="paper-authors">(.*?)</span>',
    re.S,
)
_HASH_RE = re.compile(r"/hash/([0-9a-f]+)-Abstract(.*?)\.html")


def _strip(html: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", html)).strip()


def _track_of(suffix: str) -> str:
    """ "-Conference" -> "main"; "-Datasets_and_Benchmarks" -> that track's name."""
    s = suffix.strip("-")
    if not s or s == "Conference":
        return "main"
    return s


def crawl_year(year: int) -> list[dict[str, Any]]:
    """Every NeurIPS paper posted for `year`. Empty if the proceedings are not up yet."""
    try:
        html = fetch_text(f"{BASE}/paper_files/paper/{year}", max_age=86400)
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for href, title_html, authors_html in _ITEM_RE.findall(html):
        m = _HASH_RE.search(href)
        if not m:
            continue
        digest, suffix = m.group(1), m.group(2)
        title = _strip(title_html)
        authors = [a.strip() for a in _strip(authors_html).split(",") if a.strip()]
        track = _track_of(suffix)
        out.append(
            {
                "id": f"NeurIPS:{year}:{digest[:16]}",
                "venue": "NeurIPS",
                "year": year,
                "title": title,
                "title_key": title_key(title),
                "authors_json": json.dumps(authors, ensure_ascii=False),
                "page_url": BASE + href,
                "pdf_url": f"{BASE}/paper_files/paper/{year}/file/{digest}-Paper{suffix}.pdf",
                "topic": None if track == "main" else track,
                "source": "nips.cc",
                "crawled_at": now(),
            }
        )
    return out


_PDF_META_RE = re.compile(r'name="citation_pdf_url"\s+content="([^"]+)"')


def resolve_pdf_url(page_url: str) -> str | None:
    """Authoritative PDF link from the paper page, for the rare derived-URL miss."""
    try:
        m = _PDF_META_RE.search(fetch_text(page_url))
    except Exception:
        return None
    return m.group(1) if m else None
