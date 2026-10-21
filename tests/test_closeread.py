"""逐節精讀: written per paper, counted as half of 講解, shown with the paper's figures."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from paper_daily import analyze, closeread, store
from paper_daily.figures import Figure

PALETTE = {
    k: "#000000" for k in ("ink", "muted", "faint", "sunk", "border", "accent", "surface", "ground")
}


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    c = sqlite3.connect(tmp_path / "papers.db")
    c.row_factory = sqlite3.Row
    c.executescript(store.SCHEMA)
    store._migrate(c)
    store.upsert_papers(
        c, [{"id": "a", "title": "A", "venue": "MICCAI", "year": 2024, "source": "test"}]
    )
    c.commit()
    monkeypatch.setattr(closeread, "init_db", lambda: None)
    return c


def test_a_close_reading_is_stored_and_needs_the_full_text(conn, monkeypatch):
    calls = []
    monkeypatch.setattr(closeread.brief, "pack_text", lambda c, row: ("pack", Path("a.pdf")))

    def complete(prompt, system=None, timeout=0, task=""):
        calls.append((prompt, task))
        return "## 3 Method\n" + "逐段講解。" * 800, "ok"

    monkeypatch.setattr(closeread.llm, "complete", complete)
    body, reason = closeread.write("a")
    assert reason == "ok" and calls == [("pack", "dive")]
    assert closeread.get(conn, "a").startswith("## 3 Method")
    assert closeread.select(conn, ["a"]) == []

    monkeypatch.setattr(closeread.brief, "pack_text", lambda c, row: ("pack", None))
    body, reason = closeread.write("a")
    assert body is None and "no PDF" in reason


def test_a_short_reply_is_not_kept(conn, monkeypatch):
    monkeypatch.setattr(closeread.brief, "pack_text", lambda c, row: ("pack", Path("a.pdf")))
    monkeypatch.setattr(closeread.llm, "complete", lambda *a, **k: ("I can't.", "ok"))
    body, reason = closeread.write("a")
    assert body is None and "too short" in reason
    assert closeread.get(conn, "a") is None


def test_explained_means_both_halves(conn, monkeypatch):
    monkeypatch.setattr(analyze, "has_pdf", lambda pid: True)
    conn.execute("INSERT INTO dives(paper_id, body, written_at) VALUES ('a', 'dive', 'now')")
    assert analyze.status(conn, "a")["dive"] is False
    conn.execute("INSERT INTO close_readings(paper_id, body, written_at) VALUES ('a', 'x', 'now')")
    assert analyze.status(conn, "a")["dive"] is True


@pytest.mark.parametrize(
    "line,label",
    [("[[Figure 3]]", "Figure 3"), ("  [[Fig. 2b]] ", "Fig. 2b"), ("[[table 1]]", "table 1")],
)
def test_a_figure_marker_is_a_line_of_its_own(line, label):
    assert closeread.MARKER.match(line).group(1) == label
    assert closeread.MARKER.match(f"見 {line}") is None


def test_the_reader_puts_each_figure_where_it_is_discussed(tmp_path):
    from paper_daily.desktop import reading

    image = tmp_path / "p03-Figure_2.png"
    image.write_bytes(b"not really a png")
    figures = [Figure("a", "Figure 2", "Fig. 2 Two phases look alike.", 3, image)]
    close = "## 3 Method\n說明。\n[[Fig. 2]]\n看左邊兩格。\n[[Figure 2]]\n[[Table 9]]\n結論。"
    out = reading.render("## 一句話結論\n一句。", close, figures, PALETTE)
    assert out.count("<img ") == 1  # once, and the unknown Table 9 is dropped
    assert image.name in out and "Two phases look alike." in out
    assert out.index("說明") < out.index("<img ") < out.index("看左邊兩格")
    assert "[[" not in out

    pending = reading.render("## 一句話結論\n一句。", None, [], PALETTE)
    assert "逐節精讀" in pending and "close-read" in pending
