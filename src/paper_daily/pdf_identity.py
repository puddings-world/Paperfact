"""Work out which paper a PDF on this machine is, from the file alone.

A dropped PDF has no citation attached, only what the file says about itself. The
DOI and arXiv id printed on the first page are exact; the title is a guess from the
largest type at the top of that page, and the person confirms it before anything is
looked up.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>{}]+)", re.I)
ARXIV = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
# Producers stamp these into the metadata title of papers that never had one.
_PLACEHOLDER = re.compile(
    r"^(untitled|microsoft word\b|document\d*|paper\d*|main|manuscript)|\.(docx?|tex|pdf|dvi)$",
    re.I,
)


def from_parts(metadata_title: str, first_page: str, spans: list[tuple[float, float, str]]) -> dict:
    """`spans` are lines of (font size, top y as a fraction of the page height, text)."""
    doi = DOI.search(first_page)
    arxiv = ARXIV.search(first_page)
    return {
        "doi": doi.group(1).rstrip(".,;)") if doi else None,
        "arxiv": arxiv.group(1) if arxiv else None,
        "title": _title(metadata_title, spans),
    }


def _title(metadata_title: str, spans: list[tuple[float, float, str]]) -> str:
    meta = " ".join((metadata_title or "").split())
    if len(meta.split()) >= 3 and not _PLACEHOLDER.search(meta):
        return meta
    # The arXiv stamp down the margin and running heads are large or high up too,
    # so only the top half counts, and only lines that read like words.
    top = [
        (size, text.strip())
        for size, y, text in spans
        if y < 0.5 and len(text.strip()) > 2 and not ARXIV.search(text)
    ]
    if not top:
        return meta
    biggest = max(size for size, _ in top)
    words = [text for size, text in top if size >= biggest - 0.5]
    return " ".join(unicodedata.normalize("NFKC", " ".join(words)).split())[:300]


def guess(path: str | Path) -> dict:
    import pymupdf

    with pymupdf.open(path) as doc:
        if not doc.page_count:
            return {"doi": None, "arxiv": None, "title": ""}
        page = doc[0]
        height = page.rect.height or 1
        # Whole lines, sized by their largest span: a small-caps title sets each
        # capital larger than the rest of its word, and spans would split the word.
        lines = [
            (
                max(span["size"] for span in line["spans"]),
                line["bbox"][1] / height,
                "".join(span["text"] for span in line["spans"]),
            )
            for block in page.get_text("dict")["blocks"]
            for line in block.get("lines", [])
            if line["spans"]
        ]
        return from_parts((doc.metadata or {}).get("title", ""), page.get_text(), lines)
