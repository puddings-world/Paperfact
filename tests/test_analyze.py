"""One call that makes whatever a paper is missing, and knows what that is."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from paper_daily import analyze, store
from paper_daily.sources import arxiv


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    store._migrate(conn)
    store.upsert_papers(conn, [
        {"id": "ref:a", "title": "A", "venue": "MICCAI 2026", "year": 2026, "source": "test"},
    ])
    return conn


def test_status_says_what_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(analyze, "PDF_DIR", tmp_path)
    conn = _db()
    assert analyze.status(conn, "ref:a") == {
        "pdf": False, "dive": False, "highlights": False, "cites": False, "later": False,
    }
    (tmp_path / "ref_a.pdf").write_bytes(b"%PDF-")
    conn.execute("INSERT INTO dives(paper_id, body, written_at) VALUES ('ref:a', 'x', 'now')")
    conn.execute(
        "INSERT INTO close_readings(paper_id, body, written_at) VALUES ('ref:a', 'x', 'now')"
    )
    store.set_kv(conn, "followups.checked.ref:a", "2026-10-08")
    # Asking the field is half of 啟後; the 研究脈絡 written from it is the rest.
    assert analyze.status(conn, "ref:a")["later"] is False
    conn.execute(
        "INSERT INTO paper_context(paper_id, summary, reading_json, written_at, edited) "
        "VALUES ('ref:a', 'story', '[]', 'now', 0)"
    )
    state = analyze.status(conn, "ref:a")
    assert state == {"pdf": True, "dive": True, "highlights": False, "cites": False, "later": True}
    assert analyze.summary(state) == "原文✓ 講解✓ 原文重點✗ 承先✗ 啟後✓"


def test_a_step_that_failed_is_not_retried_unless_asked(monkeypatch, tmp_path):
    monkeypatch.setattr(analyze, "PDF_DIR", tmp_path)
    conn = _db()
    assert analyze.pending(conn, ["ref:a"]) == ["ref:a"]
    for step in analyze.STEPS:
        store.set_kv(conn, f"analyze.failed.{step}.ref:a", "no source had it")
    assert analyze.pending(conn, ["ref:a"]) == []
    assert analyze.pending(conn, ["ref:a"], retry=True) == ["ref:a"]
    # Supplying the PDF by hand is what clears it.
    store.set_kv(conn, "analyze.failed.pdf.ref:a", None)
    assert analyze.pending(conn, ["ref:a"]) == ["ref:a"]


def test_many_skips_papers_with_nothing_left(monkeypatch):
    conn = _db()

    @contextmanager
    def same():
        yield conn

    monkeypatch.setattr(analyze, "connect", same)
    monkeypatch.setattr(analyze, "pending", lambda *_a, **_k: [])
    lines = []
    assert analyze.analyse_many(["ref:a"], log=lines.append) == 0
    assert lines == ["nothing to analyse: every paper has all it can get"]


def test_a_bare_arxiv_id_is_read_from_arxiv(monkeypatch):
    xml = (
        "<feed><entry><id>http://arxiv.org/abs/2608.17522v1</id>"
        "<published>2026-08-19T00:00:00Z</published>"
        "<title>Explainable AI-Powered Framework for\n  Video-Based Skill Assessment</title>"
        "<summary> Persistent shortages in the surgical workforce. </summary>"
        "<author>\n<name>Mohammad Javad Ahmadi</name></author>"
        "<author><name>Hamid D. Taghirad</name></author></entry></feed>"
    )
    monkeypatch.setattr(arxiv, "fetch_text", lambda *_a, **_k: xml)
    for text in ("2608.17522", "arXiv:2608.17522v2", "https://arxiv.org/abs/2608.17522"):
        assert arxiv.BARE_ID.match(text).group(1) == "2608.17522"
    assert not arxiv.BARE_ID.match("Explainable AI-Powered Framework")
    paper = arxiv.by_id("2608.17522")
    assert paper == {
        "title": "Explainable AI-Powered Framework for Video-Based Skill Assessment",
        "authors": ["Mohammad Javad Ahmadi", "Hamid D. Taghirad"],
        "abstract": "Persistent shortages in the surgical workforce.",
        "year": 2026,
        "arxiv_id": "2608.17522",
    }


def test_existing_deep_analysis_still_prepares_missing_highlights(monkeypatch, tmp_path):
    from paper_daily import cites, paper_highlights, resources, venues

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    with store.connect() as conn:
        store.upsert_papers(
            conn, [dict(id="paper", title="Paper", venue="test", year=2026, source="test")]
        )
        conn.execute("INSERT INTO dives(paper_id,body,written_at) VALUES ('paper','dive','now')")
        conn.execute(
            "INSERT INTO close_readings(paper_id,body,written_at) VALUES ('paper','close','now')"
        )
        store.set_kv(conn, "followups.checked.paper", "now")
    ready, calls = [], []
    monkeypatch.setattr(analyze, "has_pdf", lambda pid: True)
    monkeypatch.setattr(paper_highlights, "is_prepared", lambda conn, pid: bool(ready))
    monkeypatch.setattr(venues, "refresh", lambda *a, **kw: None)
    monkeypatch.setattr(resources, "needs_check", lambda *a: False)
    monkeypatch.setattr(cites, "analyse", lambda *a, **kw: 0)

    def prepare(pid):
        calls.append(pid)
        ready.append(True)
        return {"marks": {"mapped": 2, "total": 2}}, "ok"

    monkeypatch.setattr(paper_highlights, "prepare_reading", prepare)
    with store.connect() as conn:
        assert analyze.pending(conn, ["paper"]) == ["paper"]
    result = analyze.analyse("paper", log=lambda *a: None)
    assert calls == ["paper"] and result["highlights"] and result["dive"]
    analyze.analyse("paper", log=lambda *a: None)
    assert calls == ["paper"]
