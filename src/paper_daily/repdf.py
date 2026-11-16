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
import os
import shutil
import sqlite3
import tempfile
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


def replace(
    paper_id: str, url: str | None = None, log=print, file: str | None = None,
    *, first_only: bool = False,
) -> bool:
    """Read `paper_id` from `url` (default: its arXiv copy), or from a PDF on this
    machine, from now on. The local file is how a paywalled paper gets in: download
    it through the library, then hand it over. first_only is the list-intake
    admission: it refuses managed history or a file appearing before publication."""
    # Observe before external I/O, not after a slow download has completed.
    from paper_daily import native_primary_publication as native

    if type(first_only) is not bool:
        raise ValueError("First-original attachment must be an explicit boolean")
    database = Path(store.DB_PATH).resolve()
    safe = fetch._safe_name(paper_id)
    dest = PDF_DIR / f"{safe}.pdf"
    try:
        info = database.stat()
        identity = info.st_dev, info.st_ino

        def current():
            if Path(store.DB_PATH).resolve() != database:
                return False
            now = database.stat()
            return (now.st_dev, now.st_ino) == identity and not (first_only and dest.exists())

        observed = native.observe(
            database, paper_id, current=current, first_only=first_only,
        )
        if not current():
            raise ValueError("Original or workspace changed before attachment")
    except (ValueError, OSError, sqlite3.Error) as exc:
        log(f"PDF replacement refused: {exc}")
        return False
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
    if row is None:
        log(f"no paper {paper_id}")
        return False
    if file:
        if observed is not None:
            try:
                result = native.run(native.prepare(observed, Path(file)))
            except (ValueError, OSError, sqlite3.Error) as exc:
                log(f"PDF replacement refused: {exc}")
                return False
            log(f"Versioned PDF saved ({result['size'] // 1024} KB); prior originals retained")
            return True
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

    if observed is not None:
        from paper_daily.sync_documents import MAX_PDF_BYTES

        if len(blob) > MAX_PDF_BYTES:
            log("PDF replacement refused: original exceeds 150 MiB")
            return False
        try:
            with tempfile.TemporaryDirectory(prefix="paperfact-repdf-") as temporary:
                selected = Path(temporary) / "selected.pdf"
                selected.write_bytes(blob)
                result = native.run(native.prepare(observed, selected))
        except (ValueError, OSError, sqlite3.Error) as exc:
            log(f"PDF replacement refused: {exc}")
            return False
        log(f"Versioned PDF saved ({result['size'] // 1024} KB); prior originals retained")
        return True

    # A legacy request must not adopt enrollment that began during file/network
    # work, or overwrite an independently supplied first original.
    if not current() or native.has_workspace_markers(database):
        log("PDF replacement refused: original or workspace changed; retry the action")
        return False
    if first_only:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=dest.parent, suffix=".part", delete=False,
            ) as output:
                temporary = Path(output.name)
                output.write(blob)
            if not current() or native.has_workspace_markers(database):
                log("PDF attachment refused: original or workspace changed")
                return False
            try:
                os.link(temporary, dest)
            except FileExistsError:
                log("PDF attachment refused: an original appeared; kept it")
                return False
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    else:
        if dest.exists():
            # Explicit legacy replacement keeps the previous file aside.
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
