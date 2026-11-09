"""MICCAI open access pages: the PDF, abstract and authors of a MICCAI paper.

papers.miccai.org publishes every accepted paper on its own page, before the indexes
catch up: for a MICCAI 2026 paper the title searches through Semantic Scholar, OpenAlex
and arXiv found no PDF, while its page already linked the open access copy. The page carries no
`citation_pdf_url` meta tag, so the links are read from its own sections.
"""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin, urlsplit

HOST = "papers.miccai.org"

_PAGE_PATH = re.compile(r"^/miccai-\d{4}/[^/]+\.html$")
_SECTION = re.compile(r'<h1 id="{}"[^>]*>.*?</h1>(.*?)(?=<h1[\s>]|$)', re.S)
_HREF = re.compile(r'<a\s[^>]*href="([^"]+)"', re.I)
_AUTHOR_META = re.compile(r'<meta name="author" content="([^"]*)"', re.I)
_PARAGRAPH = re.compile(r"<p>(.*?)</p>", re.S)


def is_page(url) -> bool:
    if not isinstance(url, str):
        return False
    parts = urlsplit(url)
    return parts.hostname == HOST and bool(_PAGE_PATH.match(parts.path))


def _section(html: str, anchor: str) -> str:
    found = re.search(_SECTION.pattern.format(re.escape(anchor)), html, re.S)
    return found.group(1) if found else ""


def _text(fragment: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _author(name: str) -> str:
    last, sep, first = name.partition(",")
    return f"{first.strip()} {last.strip()}" if sep and first.strip() else name.strip()


def parse(html: str, page_url: str) -> dict:
    """What the page states about its paper; a field the page lacks is None or empty."""
    links = _section(html, "link-id")
    pdf = next(
        (
            urljoin(page_url, href)
            for href in _HREF.findall(links)
            if urlsplit(href).path.lower().endswith(".pdf")
        ),
        None,
    )
    doi = next(
        (href for href in _HREF.findall(links) if urlsplit(href).hostname == "doi.org"),
        None,
    )
    code = next(iter(_HREF.findall(_section(html, "code-id"))), None)
    paragraphs = [_text(p) for p in _PARAGRAPH.findall(_section(html, "abstract-id"))]
    abstract = "\n\n".join(p for p in paragraphs if p) or None
    meta = _AUTHOR_META.search(html)
    names = unescape(meta.group(1)).split(" AND ") if meta else []
    return dict(
        pdf_url=pdf,
        doi=doi,
        code_url=code,
        abstract=abstract,
        authors=[_author(n) for n in names if n.strip()],
    )
