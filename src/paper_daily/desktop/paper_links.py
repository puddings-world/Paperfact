"""A paper's pages on the web, named for what they are, for the reader and the list."""

from __future__ import annotations

from urllib.parse import quote, urlsplit

CONFERENCE_SITES = ("iclr.cc", "icml.cc", "neurips.cc", "papers.miccai.org", "miccai.org")
SITE_NAMES = (
    ("doi.org", "出版頁面（DOI）"),
    ("openreview.net", "OpenReview"),
    ("arxiv.org", "arXiv"),
    ("semanticscholar.org", "Semantic Scholar"),
    ("openalex.org", "OpenAlex"),
    ("thecvf.com", "CVF 開放取用"),
    ("springer.com", "出版頁面"),
    ("ieeexplore.ieee.org", "IEEE Xplore"),
    ("acm.org", "ACM 數位圖書館"),
)


def web_url(value) -> str | None:
    """Only ordinary web addresses are offered; anything else stays unlinked."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    parts = urlsplit(value)
    return value if parts.scheme in ("http", "https") and parts.netloc else None


def site_name(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    for site, name in SITE_NAMES:
        if host == site or host.endswith("." + site):
            return name
    if any(host == site or host.endswith("." + site) for site in CONFERENCE_SITES):
        return "會議頁面"
    return "論文網頁"


def links(paper, *, search=True) -> list[tuple[str, str]]:
    """(label, url), most useful first: the paper's page, arXiv, where its PDF came from,
    then a Google Scholar search by title for anything not found."""
    out: list[tuple[str, str]] = []

    def add(label, url):
        if url and all(url != seen for _label, seen in out):
            out.append((label, url))

    page = web_url(getattr(paper, "page_url", None))
    if page:
        add(site_name(page), page)
    arxiv = getattr(paper, "arxiv_id", None)
    if isinstance(arxiv, str) and arxiv.strip():
        add(f"arXiv {arxiv.strip()}", f"https://arxiv.org/abs/{quote(arxiv.strip(), safe='./')}")
    pdf = web_url(getattr(paper, "pdf_url", None))
    if pdf:
        add("原文 PDF 來源", pdf)
    title = getattr(paper, "title", None)
    if search and isinstance(title, str) and title.strip():
        add("Google Scholar 搜尋",
            "https://scholar.google.com/scholar?q=" + quote(title.strip(), safe=""))
    return out


def main_link(paper) -> tuple[str, str] | None:
    """The page a click on the row's venue opens: its own page, never a search."""
    found = links(paper, search=False)
    return found[0] if found else None
