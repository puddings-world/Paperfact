import subprocess
import sys

from paper_daily import dive, paper_highlights, store


def test_reading_lock_serializes_processes_and_releases_after_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_highlights, "CACHE_DIR", tmp_path)
    code = (
        "from pathlib import Path; from paper_daily import paper_highlights as p; "
        f"p.CACHE_DIR=Path({str(tmp_path)!r})\n"
        "try:\n"
        " with p._reading_lock('paper', timeout=0.2): print('acquired')\n"
        "except TimeoutError: print('busy')\n"
    )
    try:
        with paper_highlights._reading_lock("paper"):
            child = subprocess.run(
                [sys.executable, "-c", code], capture_output=True, text=True, timeout=10, check=True
            )
            assert child.stdout.strip() == "busy"
            raise ValueError("simulate a failed analysis")
    except ValueError:
        pass
    child = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=10, check=True
    )
    assert child.stdout.strip() == "acquired"


def test_background_dive_prepares_highlights_and_honors_opt_out(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(paper_highlights, "PDF_DIR", tmp_path)
    store.init_db()
    (tmp_path / "paper.pdf").write_bytes(b"test")
    calls = []

    def prepare(pid):
        calls.append(pid)
        return {"marks": {"mapped": 2, "total": 2}}, "ok"

    monkeypatch.setattr(paper_highlights, "prepare_reading", prepare)
    messages = []
    # A fresh install shows the box unticked, so nothing may be spent yet.
    dive._prepare_highlights("paper", messages.append)
    assert calls == [] and messages == []
    with store.connect() as conn:
        store.set_kv(conn, "ui.auto_highlights", "1")
    dive._prepare_highlights("paper", messages.append)
    assert calls == ["paper"] and "2/2" in messages[0]
    with store.connect() as conn:
        store.set_kv(conn, "ui.auto_highlights", "0")
    dive._prepare_highlights("paper", messages.append)
    assert calls == ["paper"]


def test_background_highlight_failure_is_recorded_without_losing_dive(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(paper_highlights, "PDF_DIR", tmp_path)
    store.init_db()
    with store.connect() as conn:
        store.upsert_papers(
            conn, [dict(id="paper", title="Paper", venue="test", year=2026, source="test")]
        )
        store.set_kv(conn, "ui.auto_highlights", "1")
    (tmp_path / "paper.pdf").write_bytes(b"test")
    monkeypatch.setattr(paper_highlights, "prepare_reading", lambda *a: (None, "AI unavailable"))
    monkeypatch.setattr(dive, "_run", lambda *a: iter([("paper", "saved dive", "ok", "Paper")]))
    messages = []
    assert dive.dive_ahead(paper_id="paper", log=messages.append) == 1
    with store.connect() as conn:
        assert store.get_kv(conn, "analyze.failed.highlights.paper") == "AI unavailable"
        assert (
            conn.execute("SELECT body FROM dives WHERE paper_id='paper'").fetchone()[0]
            == "saved dive"
        )
    assert "講解已保存" in messages[-1]


def test_unmatched_quotes_are_reported_as_missing_marks(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(paper_highlights, "PDF_DIR", tmp_path)
    store.init_db()
    with store.connect() as conn:
        store.set_kv(conn, "ui.auto_highlights", "1")
    (tmp_path / "paper.pdf").write_bytes(b"test")
    monkeypatch.setattr(
        paper_highlights, "prepare_reading", lambda *a: ({"marks": {"mapped": 0, "total": 2}}, "ok")
    )
    dive._prepare_highlights("paper", lambda *a: None)
    with store.connect() as conn:
        assert "無法在 PDF 精確定位" in store.get_kv(conn, "analyze.failed.highlights.paper")
