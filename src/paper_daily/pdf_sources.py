"""Public PDF candidates from retrieved metadata, never model-invented URLs."""

import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlencode, urlsplit

from paper_daily.http import FetchError, fetch
from paper_daily.store import title_key


def web_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme in ("https", "http") and parsed.hostname and not (
            parsed.username or parsed.password
        ):
            return value
    except ValueError:
        pass
    return None


def arxiv_id(value):
    if not isinstance(value, str):
        return None
    value = re.sub(r"^(?:https?://(?:www\.)?arxiv.org/(?:abs|pdf)/|arxiv:)", "", value,
                   flags=re.I)
    value = re.sub(r"^https?://doi.org/", "", value, flags=re.I)
    value = re.sub(r"^10\.48550/arxiv\.", "", value, flags=re.I)
    value = value.removesuffix(".pdf")
    return value if re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?",
                                 value) else None


def direct_link(value):
    value = web_url(value)
    if not value:
        return None
    aid = arxiv_id(value)
    if aid:
        return "https://arxiv.org/pdf/" + aid
    parsed = urlsplit(value)
    if parsed.hostname == "openreview.net" and parsed.path == "/forum" and parsed.query:
        return "https://openreview.net/pdf?" + parsed.query
    return value if parsed.path.lower().endswith(".pdf") else None


def openalex_links(work):
    locations = [work.get("best_oa_location"), work.get("primary_location")]
    locations += work.get("locations") or []
    urls = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        urls += [web_url(location.get("pdf_url")), direct_link(location.get("landing_page_url"))]
    aid = arxiv_id(work.get("doi"))
    if aid:
        urls.append("https://arxiv.org/pdf/" + aid)
    return list(dict.fromkeys(url for url in urls if url))


def known_links(row):
    from paper_daily.fetch import pdf_candidates

    row = dict(row)
    aid = arxiv_id(row.get("arxiv_id")) or arxiv_id(row.get("doi"))
    urls = pdf_candidates(dict(pdf_url=web_url(row.get("pdf_url")), arxiv_id=aid))
    urls.append(direct_link(row.get("page_url")))
    return list(dict.fromkeys(url for url in urls if url))


def _same(row, title, doi=None):
    expected = str(row.get("doi") or "").removeprefix("https://doi.org/").casefold()
    actual = str(doi or "").removeprefix("https://doi.org/").casefold()
    return bool(expected and actual == expected) or (
        bool(title) and title_key(title) == title_key(row["title"]))


def discover(row, check=lambda: None):
    """Yield alternate sources with bounded requests and exact identity checks."""
    row = dict(row)
    title = row["title"]
    from paper_daily.enrich.s2 import API, MATCH_FIELDS

    urls = [
        ("s2", API + "/paper/search/match?" + urlencode(dict(query=title, fields=MATCH_FIELDS))),
        ("oa", "https://api.openalex.org/works?" + urlencode(dict(search=title, per_page=5))),
        ("arxiv", "https://export.arxiv.org/api/query?" + urlencode(
            dict(search_query='ti:"' + title.replace('"', ' ') + '"', max_results=5))),
    ]
    errors = []
    for source, url in urls:
        check()
        try:
            payload = fetch(url, retries=1, timeout=12, max_age=86400)
            check()
            if source == "arxiv":
                root = ET.fromstring(payload)
                ns = {"a": "http://www.w3.org/2005/Atom"}
                for entry in root.findall("a:entry", ns):
                    if _same(row, " ".join((entry.findtext("a:title", "", ns)).split())):
                        link = direct_link(entry.findtext("a:id", "", ns))
                        if link:
                            yield link
            else:
                body = json.loads(payload)
                for result in body.get("data" if source == "s2" else "results") or []:
                    if source == "oa":
                        if _same(row, result.get("display_name"), result.get("doi")):
                            yield from openalex_links(result)
                    else:
                        ext = result.get("externalIds") or {}
                        if _same(row, result.get("title"), ext.get("DOI")):
                            yield from known_links(dict(
                                pdf_url=(result.get("openAccessPdf") or {}).get("url"),
                                arxiv_id=ext.get("ArXiv"), doi=ext.get("DOI")))
        except (FetchError, ValueError, TypeError, AttributeError, ET.ParseError):
            errors.append(source)
    if errors:
        raise FetchError("部分文獻來源暫時無法查詢，請稍後重試。")
