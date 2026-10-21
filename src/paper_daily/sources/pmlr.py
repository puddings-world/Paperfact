"""ICML roster from PMLR.

PMLR is the authoritative proceedings for ICML: one volume per year, every accepted
paper listed with a direct PDF on GitHub raw. Abstracts live on the per-paper page,
which we only fetch for papers that survive ranking -- pulling 2600 abstract pages
per year would be 26k requests for text we mostly throw away.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any

from paper_daily.http import fetch_text
from paper_daily.store import now, title_key

INDEX_URL = "https://proceedings.mlr.press/"

# Verified year -> volume for ICML. Auto-discovery handles anything newer.
KNOWN_VOLUMES = {
    2015: "v37",
    2016: "v48",
    2017: "v70",
    2018: "v80",
    2019: "v97",
    2020: "v119",
    2021: "v139",
    2022: "v162",
    2023: "v202",
    2024: "v235",
}

_INDEX_ITEM_RE = re.compile(r'<li><a href="(v\d+)"><b>Volume \d+</b></a>\s*(.*?)</li>', re.S)
# Main-conference volumes are labelled exactly "Proceedings of ICML 2024" or
# "ICML 2015 Proceedings". Workshops co-located with ICML ("GRaM at ICML 2024")
# share the acronym and must not be mistaken for the conference itself.
_ICML_MAIN_RE = re.compile(r"^(?:proceedings of\s+)?icml\s+(20\d{2})(?:\s+proceedings)?$")

_PAPER_RE = re.compile(r'<div class="paper">(.*?)</div>', re.S)
_TITLE_RE = re.compile(r'<p class="title">(.*?)</p>', re.S)
_AUTHORS_RE = re.compile(r'<span class="authors">(.*?)</span>', re.S)
_HREF_RE = re.compile(r'<a href="([^"]+)"[^>]*>([^<]*)</a>')
_ABSTRACT_RE = re.compile(r'<div[^>]*class="abstract"[^>]*>(.*?)</div>', re.S)


def _strip(html: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", html)).strip()


def discover_volumes() -> dict[int, str]:
    """Map year -> PMLR volume for every main ICML volume on the index page."""
    html = fetch_text(INDEX_URL, max_age=86400)
    found: dict[int, str] = {}
    for vol, label in _INDEX_ITEM_RE.findall(html):
        m = _ICML_MAIN_RE.match(re.sub(r"\s+", " ", _strip(label)).strip().lower())
        if m:
            found[int(m.group(1))] = vol
    return {**KNOWN_VOLUMES, **found}


def volume_for_year(year: int) -> str | None:
    try:
        return discover_volumes().get(year)
    except Exception:
        return KNOWN_VOLUMES.get(year)


def crawl_year(year: int) -> list[dict[str, Any]]:
    vol = volume_for_year(year)
    if not vol:
        return []
    html = fetch_text(f"https://proceedings.mlr.press/{vol}/", max_age=86400)
    out: list[dict[str, Any]] = []
    for block in _PAPER_RE.findall(html):
        tm = _TITLE_RE.search(block)
        if not tm:
            continue
        title = _strip(tm.group(1))
        am = _AUTHORS_RE.search(block)
        authors = [a.strip() for a in _strip(am.group(1)).split(",") if a.strip()] if am else []

        page_url = pdf_url = None
        for href, label in _HREF_RE.findall(block):
            label = label.strip().lower()
            if label == "abs":
                page_url = href
            elif "download pdf" in label or href.endswith(".pdf"):
                pdf_url = href
        slug = re.search(r"/([^/]+)\.html$", page_url or "")
        pid = f"ICML:{year}:{slug.group(1) if slug else title_key(title)[:40]}"

        out.append(
            {
                "id": pid,
                "venue": "ICML",
                "year": year,
                "title": title,
                "title_key": title_key(title),
                "authors_json": _json(authors),
                "page_url": page_url,
                "pdf_url": pdf_url,
                "source": "pmlr",
                "crawled_at": now(),
            }
        )
    return out


def fetch_abstract(page_url: str) -> str | None:
    """Fetch one paper's abstract. Called lazily, only for ranked papers."""
    try:
        html = fetch_text(page_url)
    except Exception:
        return None
    m = _ABSTRACT_RE.search(html)
    return _strip(m.group(1)) if m else None


def _json(v: Any) -> str:
    import json

    return json.dumps(v, ensure_ascii=False)
