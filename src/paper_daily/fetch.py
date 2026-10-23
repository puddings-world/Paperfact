"""Fetch a paper's PDF and extract readable text.

PDFs are fetched lazily -- only for papers that actually reach the front of the
queue. The whole corpus is roughly 40k papers and 400-600 GB; the queue will consume
a few thousand of them over several years, so downloading everything up front would
cost hundreds of gigabytes to read a fraction of it.

Extraction keeps the section structure that PyMuPDF can recover and stops at the
references, which are long, low-value for reading, and already covered by the
lineage graph.
"""

from __future__ import annotations

import re
import sqlite3
import tempfile
import threading
from pathlib import Path

from paper_daily.config import PDF_DIR, TEXT_DIR, ensure_dirs
from paper_daily.http import fetch

_REFERENCES_RE = re.compile(r"\n\s*(references|bibliography)\s*\n", re.I)


def _safe_name(paper_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", paper_id)


# Where a conference's own PDF is its clean camera-ready copy.
PROCEEDINGS_HOSTS = (
    "proceedings.mlr.press", "papers.nips.cc", "proceedings.neurips.cc",
    "openaccess.thecvf.com", "aclanthology.org", "openreview.net", "papers.miccai.org",
)


def pdf_candidates(row: sqlite3.Row) -> list[str]:
    """PDF URLs to try, best first.

    Proceedings links come first because they are the camera-ready version. arXiv is
    the fallback for ICLR, whose PDFs live on OpenReview and 403 for anonymous
    clients -- 83% of ICLR papers have an arXiv version.

    Anything else -- a journal or publisher link -- comes after arXiv. What those
    serve is often not the typeset article: Cataract-LMM's nature.com link was the
    accepted manuscript, stamped ARTICLE IN PRESS across 44 pages of sixteen sizes,
    where arXiv had the authors' own copy of the same text.
    """
    out = []
    own = row["pdf_url"]
    arxiv = f"https://arxiv.org/pdf/{row['arxiv_id']}" if row["arxiv_id"] else None
    if own and any(host in own for host in PROCEEDINGS_HOSTS):
        out.append(own)
        own = None
    if arxiv:
        out.append(arxiv)
    if own:
        out.append(own)
    return out


def ensure_pdf(row: sqlite3.Row) -> Path | None:
    """Download the PDF if we do not have it. Returns the local path, or None."""
    from paper_daily.pdf_downloads import paper_lock

    ensure_dirs()
    dest = PDF_DIR / f"{_safe_name(row['id'])}.pdf"
    with paper_lock(dest, threading.Event()):
        return _ensure_pdf_locked(row, dest)


def _ensure_pdf_locked(row, dest):
    if dest.exists() and dest.stat().st_size > 1024:
        return dest

    for url in pdf_candidates(row):
        try:
            blob = fetch(url, cache=False)
        except Exception:
            continue
        if blob[:5] == b"%PDF-":
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=dest.parent,
                                                 suffix=".part", delete=False) as f:
                    temporary = Path(f.name)
                    f.write(blob)
                temporary.replace(dest)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            return dest
    return None


def extract_text(pdf_path: Path, paper_id: str, max_chars: int = 120_000) -> str | None:
    """Plain text of the paper body, truncated and stripped of the reference list."""
    ensure_dirs()
    cached = TEXT_DIR / f"{_safe_name(paper_id)}.txt"
    if cached.exists():
        return cached.read_text(encoding="utf-8")

    try:
        import pymupdf
    except ImportError:  # keep metadata commands usable without the PDF extra
        return None

    try:
        with pymupdf.open(pdf_path) as doc:
            pages = [page.get_text() for page in doc]
    except Exception:
        return None

    text = "\n".join(pages)
    # Cut at the last "References" heading: some papers cite the word in the body.
    matches = list(_REFERENCES_RE.finditer(text))
    if matches:
        text = text[: matches[-1].start()]
    text = re.sub(r"\n{3,}", "\n\n", text).strip()[:max_chars]
    cached.write_text(text, encoding="utf-8")
    return text


def prepare(row: sqlite3.Row) -> tuple[Path | None, str | None]:
    """Download and extract in one step, for the daily brief."""
    pdf = ensure_pdf(row)
    if not pdf:
        return None, None
    return pdf, extract_text(pdf, row["id"])
