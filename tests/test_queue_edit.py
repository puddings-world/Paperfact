"""Adding and removing papers by hand, on the queue and on a list.

The nightly rebuild deletes and regenerates the pending queue, so anything put there
deliberately has to be protected from it explicitly. That protection is the part
worth testing: without it a paper added by hand, or a reference pulled forward from
the lineage tab, quietly disappears overnight.
"""

from __future__ import annotations

import sqlite3

import pytest

from paper_daily import queue as qmod
from paper_daily import store


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    c = sqlite3.connect(tmp_path / "papers.db")
    c.row_factory = sqlite3.Row
    c.executescript(store.SCHEMA)
    for i, (venue, year, score) in enumerate(
        [("ICLR", 2026, 0.9), ("ICML", 2026, 0.8), ("NeurIPS", 2025, 0.7), ("CVPR", 2024, 0.95)]
    ):
        c.execute(
            "INSERT INTO papers(id, venue, year, title, title_key, authors_json, source, "
            "is_canon, score, crawled_at) VALUES (?,?,?,?,?,'[]','test',0,?,'now')",
            (f"p{i}", venue, year, f"Paper number {i}", f"papernumber{i}", score),
        )
    c.commit()
    return c


def test_add_puts_a_paper_at_the_front(conn):
    qmod.build(conn)
    assert qmod.add(conn, "p2")
    first = qmod.next_papers(conn, 1)[0]
    assert first["id"] == "p2"
    assert first["role"] == "manual"


def test_add_refuses_a_paper_that_is_not_in_the_corpus(conn):
    assert not qmod.add(conn, "nope")


def test_a_manual_paper_survives_the_nightly_rebuild(conn):
    qmod.build(conn)
    qmod.add(conn, "p2", reason="wanted this next")
    qmod.build(conn)
    row = conn.execute("SELECT role, rank, reason FROM queue WHERE paper_id='p2'").fetchone()
    assert row is not None, "a hand-added paper must not be deleted by a re-rank"
    assert row["role"] == "manual"
    assert qmod.next_papers(conn, 1)[0]["id"] == "p2"


def test_a_promoted_companion_keeps_its_place_through_a_rebuild(conn):
    qmod.build(conn)
    conn.execute("INSERT INTO refs(paper_id, ref_paper_id, influential) VALUES ('p0','p2',1)")
    qmod.add_companions(conn, "p0")
    before = conn.execute("SELECT rank FROM queue WHERE paper_id='p2'").fetchone()["rank"]
    qmod.build(conn)
    after = conn.execute("SELECT rank, role FROM queue WHERE paper_id='p2'").fetchone()
    assert after is not None and after["role"] == "companion"
    assert after["rank"] == before


def test_remove_hides_the_paper_but_keeps_what_it_knows(conn):
    qmod.build(conn)
    qmod.mark(conn, "p0", "read")
    assert qmod.remove(conn, "p0")
    row = conn.execute("SELECT state, read_at FROM queue WHERE paper_id='p0'").fetchone()
    assert row["state"] == "skipped"
    assert row["read_at"], "removing must not throw away that it was read"
    assert "p0" not in [r["id"] for r in qmod.next_papers(conn, 10)]


def test_remove_reports_when_there_was_nothing_to_remove(conn):
    qmod.build(conn)
    assert not qmod.remove(conn, "p3")  # CVPR: never in the main queue


def test_adding_a_removed_paper_brings_it_back(conn):
    qmod.build(conn)
    qmod.remove(conn, "p0")
    qmod.add(conn, "p0")
    assert conn.execute(
        "SELECT state FROM queue WHERE paper_id='p0'"
    ).fetchone()["state"] == "pending"


def test_a_read_paper_re_added_stays_read(conn):
    qmod.build(conn)
    qmod.mark(conn, "p1", "read")
    qmod.add(conn, "p1")
    assert conn.execute(
        "SELECT state FROM queue WHERE paper_id='p1'"
    ).fetchone()["state"] == "read"


def test_the_venue_fence_still_holds_for_generated_rows(conn):
    qmod.build(conn)
    # CVPR is in the corpus but must never be ranked into the nightly queue.
    assert not conn.execute("SELECT 1 FROM queue WHERE paper_id='p3'").fetchone()
