"""Notes other people write on the shared page, coming back to the desktop.

They arrive knowing only their words and page: pdf.js and PyMuPDF split text into
different runs, so the page cannot record the desktop's word numbers. The desktop
has to find the words again, or the card cannot lead back to the passage.
"""

from __future__ import annotations

import json
import sqlite3

import pymupdf
import pytest

from paper_daily import pocket, store
from paper_daily.figures import _safe

PID = "ref:sharedtest"


@pytest.fixture
def paper(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(pocket, "PDF_DIR", tmp_path)
    conn = sqlite3.connect(tmp_path / "papers.db")
    conn.executescript(store.SCHEMA)
    store.upsert_papers(
        conn, [{"id": PID, "title": "A paper", "venue": "X", "year": 2025, "source": "test"}]
    )
    conn.commit()
    conn.close()

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "The first page says nothing much at all.")
    page = doc.new_page()
    page.insert_text((72, 72), "Domain shift between centres is the open")
    page.insert_text((72, 90), "problem, and the average dice coefficient")
    page.insert_text((72, 108), "equals 77% in domain.")
    doc.save(tmp_path / f"{_safe(PID)}.pdf")
    return tmp_path


def test_a_quote_split_across_lines_is_found_again(paper):
    # pdf.js hands the selection back with its own spacing; a line break became a space.
    anchor = pocket.anchor_for(PID, 2, "the open problem, and the average dice")
    assert anchor is not None
    assert anchor["p0"] == anchor["p1"] == 1
    with pymupdf.open(paper / f"{_safe(PID)}.pdf") as doc:
        words = [w[4] for w in doc[1].get_text("words")]
    assert words[anchor["o0"]] == "the"
    assert words[anchor["o1"]] == "dice"


def test_a_quote_not_on_that_page_has_no_anchor(paper):
    assert pocket.anchor_for(PID, 1, "the average dice coefficient") is None


def test_pulling_twice_files_each_note_once(paper):
    notes = [
        {
            "paper": PID,
            "section": "第 2 頁",
            "anchor": 2,
            "quote": "the average dice coefficient equals 77%",
            "question": "這一段在說什麼?",
            "body": "77% 是五折平均。",
            "kind": "ask",
            "created": "2026-10-05T10:00:00Z",
        },
        # Written before the PDF viewer: the anchor is a paragraph number.
        {"paper": PID, "section": "摘要", "anchor": 3, "quote": "x", "body": "舊筆記"},
    ]
    assert pocket.file_notes(notes) == (2, 0)
    assert pocket.file_notes(notes) == (0, 2)

    with store.connect() as conn:
        rows = {r["kind"]: r for r in conn.execute("SELECT * FROM notes")}
    ask, old = rows["ask"], rows["note"]
    assert ask["kind"] == "ask" and ask["page"] == 2
    assert ask["body"].startswith("> the average dice")
    assert json.loads(ask["anchor"])["p0"] == 1
    assert old["page"] is None and old["anchor"] is None
