"""A paper read from another PDF keeps its notes pointing at their passages."""

from __future__ import annotations

import json
import sqlite3

import pytest

from paper_daily import pocket, repdf, store

pymupdf = pytest.importorskip("pymupdf")
PID = "ref:lmm"


def test_the_passage_is_read_back_from_how_it_was_stored():
    note = "> 有標組織嗎 關於這段原文: two ocular structures (Pupil, Cornea)\n\n沒有。"
    assert repdf.passage_of(note) == "two ocular structures (Pupil, Cornea)"
    asked = "有標組織嗎\n\n關於這段原文:\ntwo ocular structures"
    assert repdf.passage_of(asked) == "two ocular structures"
    assert repdf.passage_of("> a plain quote\n\nmy note") == "a plain quote"
    assert repdf.passage_of("no passage at all") == ""


def test_notes_are_found_again_in_the_new_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(pocket, "PDF_DIR", tmp_path)
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "Background only on the first page.")
    doc.new_page().insert_text((72, 100), "Frames show two ocular structures here.")
    doc.save(tmp_path / "ref_lmm.pdf")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    store._migrate(conn)
    old = json.dumps({"p0": 3, "o0": 1, "p1": 3, "o1": 2})
    conn.execute(
        "INSERT INTO notes(paper_id, body, created_at, kind, page, anchor) VALUES (?,?,?,?,?,?)",
        (PID, "> 問 關於這段原文: two ocular structures\n\n答", "now", "ask", 4, old),
    )
    conn.execute(
        "INSERT INTO chat(paper_id, role, body, created_at, page, anchor) VALUES (?,?,?,?,?,?)",
        (PID, "user", "問\n\n關於這段原文:\nIN PRESS", "now", 4, old),
    )
    placed, lost = repdf.reanchor(conn, PID)
    assert (placed, lost) == (1, ["IN PRESS"])
    note = conn.execute("SELECT page, anchor FROM notes").fetchone()
    assert note["page"] == 2 and json.loads(note["anchor"])["o0"] == 2
    # A passage that is not in the new copy keeps its text and loses only the link.
    assert conn.execute("SELECT anchor FROM chat").fetchone()["anchor"] is None
