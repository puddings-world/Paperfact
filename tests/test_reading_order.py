"""Older papers pulled forward never arrive as a run: new work follows each one."""

from __future__ import annotations

import sqlite3

import pytest

from paper_daily import brief, store
from paper_daily import queue as qmod

QUEUE = [  # (id, rank, role), front first
    ("new1", 1.0, "main"),
    ("old1", 1.1, "companion"),
    ("old2", 1.2, "companion"),
    ("old3", 1.3, "canon"),
    ("new2", 2.0, "main"),
    ("new3", 3.0, "main"),
    ("new4", 4.0, "main"),
]


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    c = sqlite3.connect(tmp_path / "papers.db")
    c.row_factory = sqlite3.Row
    c.executescript(store.SCHEMA)
    c.execute("INSERT INTO lists(id,name,created_at) VALUES ('ml','ML','now')")
    for position, (paper, rank, role) in enumerate(QUEUE):
        c.execute(
            "INSERT INTO papers(id, venue, year, title, title_key, authors_json, source, "
            "is_canon, score, crawled_at) VALUES (?,'ICLR',2026,?,?,'[]','test',0,0.5,'now')",
            (paper, paper, paper),
        )
        c.execute(
            "INSERT INTO queue(paper_id, rank, state, role, queued_at) "
            "VALUES (?,?,'pending',?,'now')", (paper, rank, role),
        )
        # The adopted list keeps the order of an earlier day: older papers at the end.
        c.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,state,added_at) "
            "VALUES ('ml',?,?,'pending','now')",
            (paper, position + (100 if role != "main" else 0)),
        )
    c.commit()
    return c


def _deliver_all(conn, monkeypatch):
    monkeypatch.setattr(brief, "build_pack", lambda conn, row: None)
    order = []
    while (delivered := brief.deliver_next(conn)) is not None:
        order.append(delivered[0]["id"])
        # Distinct, increasing times: the rule reads the most recent deliveries.
        conn.execute("UPDATE queue SET delivered_at=? WHERE paper_id=?",
                     (f"2026-01-{len(order):02d}", delivered[0]["id"]))
    return order


def test_nightly_delivery_puts_two_new_papers_after_each_older_one(conn, monkeypatch):
    assert _deliver_all(conn, monkeypatch) == [
        "new1", "old1", "new2", "new3", "old2", "new4", "old3"
    ]


def test_older_papers_still_arrive_once_no_new_paper_is_left(conn, monkeypatch):
    conn.execute("DELETE FROM queue WHERE paper_id IN ('new2','new3','new4')")
    assert _deliver_all(conn, monkeypatch) == ["new1", "old1", "old2", "old3"]


def test_the_adopted_list_follows_what_was_opened_in_it(conn):
    def open_in_list(paper, at):
        conn.execute("UPDATE list_papers SET state='delivered', delivered_at=? "
                     "WHERE list_id='ml' AND paper_id=?", (at, paper))

    # Tonight's delivery was an older paper, opened from deep in the list.
    open_in_list("old1", "2026-01-01")
    order = []
    for day in range(2, 7):
        paper = qmod.next_up(conn, "ml")["id"]
        order.append(paper)
        open_in_list(paper, f"2026-01-{day:02d}")
    assert order == ["new1", "new2", "old2", "new3", "new4"]
    assert qmod.next_up(conn, "ml")["id"] == "old3"
    open_in_list("old3", "2026-01-07")
    assert qmod.next_up(conn, "ml") is None


def test_nightly_delivery_skips_what_was_finished_in_the_adopted_list(conn, monkeypatch):
    store.set_kv(conn, "lists.legacy_queue", "ml")
    conn.execute("UPDATE list_papers SET state='read' WHERE paper_id='new1'")
    conn.execute("UPDATE list_papers SET state='delivered' WHERE paper_id='old1'")
    assert _deliver_all(conn, monkeypatch)[:2] == ["old1", "new2"]


def test_next_in_the_adopted_list_leaves_the_block_of_an_older_delivery(tmp_path, monkeypatch):
    import os

    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from paper_daily import llm
    from paper_daily.desktop import main as m

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    store.init_db()
    with store.connect() as db:
        db.execute("INSERT INTO lists(id,name,created_at) VALUES ('ml','ML','now')")
        store.set_kv(db, "lists.legacy_queue", "ml")
        # List order of an earlier day: the older paper sits among its own year.
        rows = [("new1", 2026, 1.0, "main", 0), ("new2", 2026, 2.0, "main", 1),
                ("old1", 2017, 1.1, "companion", 50), ("old2", 2017, 900.0, "main", 51)]
        store.upsert_papers(db, [dict(id=p, title=p, venue="ICLR", year=year, source="test")
                                 for p, year, *_ in rows])
        for paper, _year, rank, role, position in rows:
            db.execute("INSERT INTO queue(paper_id, rank, state, role, queued_at) "
                       "VALUES (?,?,'pending',?,'now')", (paper, rank, role))
            db.execute("INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                       "VALUES ('ml',?,?,'now')", (paper, position))
    monkeypatch.setattr(m.ReaderPage, "_check_resources", lambda self: None)
    monkeypatch.setattr(m.ReaderPage, "_prepare_reading_highlights", lambda self: None)
    window = m.MainWindow()
    monkeypatch.setattr(window, "top_up_dives", lambda *a, **k: None)
    try:
        window.show()
        window.open_paper("old1")
        app.processEvents()
        window.open_next_unread()
        app.processEvents()
        assert window.reader_page.paper.id == "new1"
        window.open_next_unread()
        assert window.reader_page.paper.id == "new2"
        # With the front read, the rest of the ranking follows.
        window.open_next_unread()
        assert window.reader_page.paper.id == "old2"
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()
