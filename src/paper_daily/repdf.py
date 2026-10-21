"""Swap the PDF a paper is read from, and keep the notes pointing at their passages.

The publisher's copy is not always the one to read. Cataract-LMM's link on nature.com
served the accepted manuscript: "ARTICLE IN PRESS" stamped diagonally across 44
pages of sixteen sizes. The same text is on arXiv as the authors typeset it.

Notes and questions are anchored by word position within a page, which means
nothing in another PDF. Each one also keeps the passage it was written about, so it
is found again by its words. One that cannot be found keeps its text and loses only
the link back.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from paper_daily import fetch, figures, pocket, store
from paper_daily.config import PDF_DIR, TEXT_DIR
from paper_daily.figures import FIG_DIR

# How a passage is introduced in a question asked about it (see desktop 問這段).
_MARK = "關於這段原文:"


def passage_of(body: str) -> str:
    """The words a note or question was written about, from how it was stored."""
    head = body.split("\n\n", 1)[0] if body.startswith(">") else body
    if _MARK in head or _MARK in body:
        source = head if _MARK in head else body
        return source.split(_MARK, 1)[1].strip().lstrip(">").strip()
    if body.startswith(">"):
        return " ".join(ln[1:].strip() for ln in body.splitlines() if ln.startswith(">"))
    return ""


def reanchor(conn, paper_id: str) -> tuple[int, list[str]]:
    """Find every anchored note and question again in the current PDF.

    Returns (how many were placed, the passages that could not be found).
    """
    placed, lost = 0, []
    for table in ("notes", "chat"):
        rows = conn.execute(
            f"SELECT id, body FROM {table} WHERE paper_id=? AND anchor IS NOT NULL",
            (paper_id,),
        ).fetchall()
        for row in rows:
            passage = passage_of(row["body"] or "")
            spot = pocket.locate(paper_id, passage) if passage else None
            if spot is None:
                conn.execute(
                    f"UPDATE {table} SET anchor=NULL, page=NULL WHERE id=?", (row["id"],)
                )
                lost.append(passage[:80] or f"{table} {row['id']}")
                continue
            conn.execute(
                f"UPDATE {table} SET anchor=?, page=? WHERE id=?",
                (json.dumps(spot), spot["p0"] + 1, row["id"]),
            )
            placed += 1
    return placed, lost


def replace(paper_id: str, url: str | None = None, log=print, file: str | None = None) -> bool:
    """Read `paper_id` from `url` (default: its arXiv copy), or from a PDF on this
    machine, from now on. The local file is how a paywalled paper gets in: download
    it through the library, then hand it over."""
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
    if row is None:
        log(f"no paper {paper_id}")
        return False
    if file:
        blob = Path(file).read_bytes()
        url = row["pdf_url"]
    else:
        url = url or (f"https://arxiv.org/pdf/{row['arxiv_id']}" if row["arxiv_id"] else None)
        if not url:
            log("no URL given and no arXiv id on record")
            return False
        blob = fetch.fetch(url, cache=False)
    if blob[:5] != b"%PDF-":
        log(f"{file or url} is not a PDF")
        return False

    safe = fetch._safe_name(paper_id)
    dest = PDF_DIR / f"{safe}.pdf"
    if dest.exists():
        # Kept aside rather than deleted: the figures and anchors of the old copy
        # are gone either way, but the file itself may be the version of record.
        (PDF_DIR / "replaced").mkdir(exist_ok=True)
        shutil.move(dest, PDF_DIR / "replaced" / f"{safe}.pdf")
    dest.write_bytes(blob)
    log(f"PDF  {file or url} ({len(blob) // 1024} KB)")

    (TEXT_DIR / f"{safe}.txt").unlink(missing_ok=True)
    fetch.extract_text(dest, paper_id)
    shutil.rmtree(FIG_DIR / figures._safe(paper_id), ignore_errors=True)
    log(f"figures  {len(figures.extract(paper_id, dest, force=True))}")

    with store.connect() as conn:
        conn.execute("UPDATE papers SET pdf_url=? WHERE id=?", (url, paper_id))
        placed, lost = reanchor(conn, paper_id)
    log(f"notes re-anchored  {placed}")
    for passage in lost:
        log(f"  not found, link dropped: {passage}")
    return True
