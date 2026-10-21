"""CVF Open Access: PDFs for CVPR, ICCV and WACV.

Imported reading lists reach well outside the three conferences, and the vision
venues are the most common thing they reach for. Semantic Scholar often holds those
papers with no arXiv id and no open-access link at all -- a CVPR 2026 paper in the
first imported list had `externalIds: {CorpusId: ...}` and nothing else -- while CVF
publishes every one of them for free.

The proceedings index is one large page per conference-year, so it is fetched once
and cached; a lookup is then a title match against it.
"""

from __future__ import annotations

import re
from html import unescape

from paper_daily.http import fetch_text
from paper_daily.store import title_key

BASE = "https://openaccess.thecvf.com"

# Venue strings as Semantic Scholar and bibliographies write them. ICCV is tested
# first because CVPR's loose pattern would otherwise claim it: only the word
# "International" separates the two long forms, and a venue string truncated
# mid-name still has to land on the right conference.
VENUE_PATTERNS = (
    (
        "ICCV",
        re.compile(
            r"\bICCV\b|International Conference on Computer Vision"
            # A venue string cut mid-name still has to resolve, and "IEEE/CVF
            # International" belongs to ICCV alone.
            r"|IEEE/CVF International",
            re.I,
        ),
    ),
    ("WACV", re.compile(r"\bWACV\b|Winter Conference on Applications", re.I)),
    (
        "CVPR",
        re.compile(
            r"\bCVPR\b|Computer Vision and Pattern Recognition"
            r"|IEEE/CVF Conference on Computer Vision",
            re.I,
        ),
    ),
)

_ANCHOR_RE = re.compile(r'<a href="(/content/[^"]+/html/[^"]+\.html)">([^<]+)</a>')


def venue_code(venue: str | None) -> str | None:
    """CVPR/ICCV/WACV if this venue string is one of them, else None."""
    if not venue:
        return None
    for code, pattern in VENUE_PATTERNS:
        if pattern.search(venue):
            return code
    return None


def _index(code: str, year: int) -> dict[str, str]:
    """title_key -> paper page path, for one conference-year."""
    # `day=all` is what returns the whole programme; without it recent years serve a
    # landing page with no papers on it at all.
    for url in (f"{BASE}/{code}{year}?day=all", f"{BASE}/{code}{year}"):
        try:
            html = fetch_text(url, max_age=30 * 86400, timeout=120)
        except Exception:
            continue
        found = {
            title_key(unescape(text)): href
            for href, text in _ANCHOR_RE.findall(html)
            if text.strip()
        }
        if found:
            return found
    return {}


def pdf_url(title: str, venue: str | None, year: int | None) -> str | None:
    """The open-access PDF for this paper, if CVF has it."""
    code = venue_code(venue)
    if not code or not year:
        return None
    key = title_key(title)
    if not key:
        return None

    # A paper can be indexed under the year beside it or the one before: CVF files by
    # conference year, and a citation sometimes carries the preprint's.
    for candidate in (year, year - 1):
        page = _index(code, candidate).get(key)
        if page:
            return BASE + page.replace("/html/", "/papers/").replace(".html", ".pdf")
    return None
