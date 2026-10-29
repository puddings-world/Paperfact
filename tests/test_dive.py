"""Which papers a dive run picks, and in what order.

Selection is the whole behaviour of `dive-ahead`: everything after it is one model
call. A rewrite that re-picks the papers it just rewrote would spend a night going
nowhere, so the spec marker is worth a test.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

import pytest

from paper_daily import dive, store


@pytest.fixture
def conn(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    c = sqlite3.connect(tmp_path / "papers.db")
    c.row_factory = sqlite3.Row
    c.executescript(store.SCHEMA)
    rows = [
        ("p1", "ICLR", 2026, "Front of the queue", 1.0),
        ("p2", "ICLR", 2026, "Second", 2.0),
        ("p3", "ICML", 2025, "Third", 3.0),
    ]
    for pid, venue, year, title, rank in rows:
        c.execute(
            "INSERT INTO papers(id, venue, year, title, title_key, authors_json, "
            "source, is_canon, crawled_at) VALUES (?,?,?,?,?,'[]','test',0,'now')",
            (pid, venue, year, title, title.lower()),
        )
        c.execute(
            "INSERT INTO queue(paper_id, rank, state, role) VALUES (?,?,?,?)",
            (pid, rank, "pending", "main"),
        )
    c.commit()
    return c


def _dive(conn, paper_id: str, spec: str | None) -> None:
    conn.execute(
        "INSERT INTO dives(paper_id, body, written_at, spec) VALUES (?,?,?,?)",
        (paper_id, "body", "2026-01-01T00:00:00Z", spec),
    )
    conn.commit()


def test_normal_run_takes_papers_with_no_dive_in_queue_order(conn):
    _dive(conn, "p1", dive.DIVE_SPEC)
    picked = dive._select(conn, 5, None, None, rewrite=False)
    assert [r["id"] for r in picked] == ["p2", "p3"]


def test_rewrite_takes_only_dives_from_an_older_spec(conn):
    _dive(conn, "p1", "ancient")
    _dive(conn, "p2", dive.DIVE_SPEC)
    picked = dive._select(conn, 5, None, None, rewrite=True)
    assert [r["id"] for r in picked] == ["p1"]


def test_rewrite_goes_in_queue_order_not_by_age(conn):
    # p3 is the oldest dive but the last paper anyone will read.
    conn.execute(
        "INSERT INTO dives(paper_id, body, written_at) VALUES ('p3','b','2020-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO dives(paper_id, body, written_at) VALUES ('p1','b','2026-09-01T00:00:00Z')"
    )
    conn.commit()
    picked = dive._select(conn, 5, None, None, rewrite=True)
    assert [r["id"] for r in picked] == ["p1", "p3"]


def test_rewrite_includes_papers_already_read(conn):
    conn.execute("UPDATE queue SET state='read' WHERE paper_id='p1'")
    _dive(conn, "p1", None)
    conn.commit()
    assert [r["id"] for r in dive._select(conn, 5, None, None, rewrite=True)] == ["p1"]
    # ... and a normal run still leaves read papers alone.
    conn.execute("DELETE FROM dives WHERE paper_id='p1'")
    conn.commit()
    assert "p1" not in [r["id"] for r in dive._select(conn, 5, None, None, rewrite=False)]


def test_a_dead_backend_is_fatal_and_a_refusal_is_not():
    assert dive._fatal("Invalid API key -- run `claude` once to sign in again")
    assert dive._fatal("Please authenticate first")
    # A bulk rewrite spent a whole batch reporting this one paper at a time.
    assert dive._fatal("reply too short to be a dive: You're out of usage credits.")
    assert not dive._fatal("HTTP 429: rate limited")
    assert not dive._fatal("reply too short to be a dive: I cannot summarise this")


def test_the_database_is_not_held_open_across_the_model_call(monkeypatch, conn, tmp_path):
    """The pack is built, the connection closed, and only then is the model called.

    Holding a write transaction open for the minutes a dive takes is what made three
    workers collide and kill a bulk run with "database is locked".
    """
    from paper_daily import brief, llm, store

    open_connections = []
    real_connect = store.connect

    @contextmanager
    def counting_connect():
        with real_connect() as c:
            open_connections.append(c)
            try:
                yield c
            finally:
                open_connections.remove(c)

    monkeypatch.setattr(dive, "connect", counting_connect)
    monkeypatch.setattr(brief, "pack_text", lambda c, row: ("pack text", None))

    during: list[int] = []

    def fake_complete(prompt, system=None, timeout=900, cfg=None, **kwargs):
        during.append(len(open_connections))
        return "x" * 900, "ok"

    monkeypatch.setattr(llm, "complete", fake_complete)
    body, reason = dive._generate_for("p1")
    assert (body is not None, reason) == (True, "ok")
    assert during == [0], "no connection may be open while the model is answering"


def test_a_dive_rolled_forward_gets_its_close_reading_too(conn, monkeypatch):
    _dive(conn, "p1", "old-spec")
    monkeypatch.setattr(dive, "init_db", lambda: None)
    monkeypatch.setattr(dive, "_generate_for", lambda pid: ("講解" * 500, "ok"))
    monkeypatch.setattr(dive, "_prepare_highlights", lambda pid, log: None)
    written = []
    monkeypatch.setattr(
        dive.closeread, "write", lambda pid: (written.append(pid), ("逐節", "ok"))[1]
    )
    assert dive.dive_ahead(1, rewrite=True) == 1
    assert written == ["p1"]


def test_a_paper_the_model_keeps_refusing_is_not_picked_every_night(conn, monkeypatch):
    monkeypatch.setattr(dive, "init_db", lambda: None)
    monkeypatch.setattr(
        dive, "_generate_for",
        lambda pid: (None, "API Error: safeguards flagged this session"),
    )
    dive.dive_ahead(1)
    assert [r["id"] for r in dive._select(conn, 3, None, None, False)] == ["p2", "p3"]
    # Asked for by name -- the 深入分析 button -- it is still written.
    assert [r["id"] for r in dive._select(conn, 1, "p1", None, False)] == ["p1"]


def test_a_paper_that_fails_a_few_times_is_set_aside(conn, monkeypatch):
    monkeypatch.setattr(dive, "init_db", lambda: None)
    monkeypatch.setattr(dive, "_generate_for", lambda pid: (None, "claude CLI failed (exit 1)"))
    for _ in range(dive.GIVE_UP_AFTER - 1):
        dive.dive_ahead(1)
        assert [r["id"] for r in dive._select(conn, 1, None, None, False)] == ["p1"]
    dive.dive_ahead(1)
    assert [r["id"] for r in dive._select(conn, 1, None, None, False)] == ["p2"]


def test_the_nightly_rewrite_respects_only_when_i_press(conn, monkeypatch):
    from paper_daily import analysis_schedule, cites, cli

    called = []
    monkeypatch.setattr(dive, "dive_ahead", lambda **k: called.append("dive") or 0)
    monkeypatch.setattr(cites, "analyse_ahead", lambda **k: called.append("cites") or 0)
    with store.connect() as c:
        analysis_schedule.save(c, {**analysis_schedule.DEFAULTS, "every": 0})
    cli.main(["dive-ahead", "6", "--rewrite", "--scheduled"])
    cli.main(["cites-ahead", "2", "--rewrite", "--scheduled"])
    assert called == []
    with store.connect() as c:
        analysis_schedule.save(c, {**analysis_schedule.DEFAULTS, "every": 1})
    cli.main(["dive-ahead", "6", "--rewrite", "--scheduled"])
    cli.main(["cites-ahead", "2", "--rewrite", "--scheduled"])
    assert called == ["dive", "cites"]


def test_a_highlight_run_that_timed_out_is_tried_again_later(conn, monkeypatch, tmp_path):
    from paper_daily import paper_highlights

    monkeypatch.setattr(paper_highlights, "PDF_DIR", tmp_path)
    (tmp_path / f"{paper_highlights._safe_name('p1')}.pdf").write_bytes(b"%PDF")
    with store.connect() as c:
        store.set_kv(c, "ui.auto_highlights", "1")
    cases = ((paper_highlights.TRANSIENT + "逾時", False), ("沒有可讀取的原文文字", True))
    for reason, kept in cases:
        monkeypatch.setattr(
            paper_highlights, "prepare_reading", lambda pid, reason=reason: (None, reason)
        )
        dive._prepare_highlights("p1", lambda _m: None)
        with store.connect() as c:
            recorded = store.get_kv(c, "analyze.failed.highlights.p1")
        assert (recorded is not None) is bool(kept)
