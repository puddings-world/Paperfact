"""Lineage for papers that are on a reading list rather than in the nightly queue.

A list is one topic, so its papers cite each other; those edges are the only lineage
such a paper can have, because its references are MICCAI and Nature rather than the
three conferences the corpus crawls. While the walk read from `queue`, the tab was
empty for every imported paper -- which is most of what a list is for.
"""

from __future__ import annotations

import sqlite3

import pytest

from paper_daily import pipeline, store
from paper_daily.enrich import s2


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    c = sqlite3.connect(tmp_path / "papers.db")
    c.row_factory = sqlite3.Row
    c.executescript(store.SCHEMA)
    for pid, s2_id, title in [
        ("p:dataset", "s-dataset", "A cataract dataset"),
        ("p:method", "s-method", "A method built on that dataset"),
        ("p:queued", "s-queued", "Something in the nightly queue"),
    ]:
        c.execute(
            "INSERT INTO papers(id, venue, year, title, title_key, authors_json, source, "
            "is_canon, score, crawled_at, s2_id) "
            "VALUES (?,'MICCAI',2025,?,?,'[]','test',0,0.5,'now',?)",
            (pid, title, pid, s2_id),
        )
    c.execute("INSERT INTO lists(id, name, created_at) VALUES ('cataract','Cataract','now')")
    for pos, pid in enumerate(["p:dataset", "p:method"]):
        c.execute(
            "INSERT INTO list_papers(list_id, paper_id, position, added_at) "
            "VALUES ('cataract',?,?,'now')",
            (pid, pos),
        )
    c.execute(
        "INSERT INTO queue(paper_id, rank, state, queued_at) VALUES ('p:queued',1,'pending','now')"
    )
    c.commit()
    return c


def test_list_papers_get_lineage(conn, monkeypatch):
    monkeypatch.setattr(
        s2,
        "references",
        lambda s2_id: (
            [{"paperId": "s-dataset", "isInfluential": True}] if s2_id == "s-method" else []
        ),
    )
    assert pipeline.build_lineage(limit=10) == 1

    edges = conn.execute("SELECT paper_id, ref_paper_id, influential FROM refs").fetchall()
    assert [tuple(e) for e in edges] == [("p:method", "p:dataset", 1)]

    graph = pipeline.lineage_of(conn, "p:dataset")
    assert [r["id"] for r in graph["descendants"]] == ["p:method"]
    assert pipeline.lineage_of(conn, "p:method")["ancestors"][0]["id"] == "p:dataset"


def test_queue_papers_are_still_walked(conn, monkeypatch):
    seen: list[str] = []

    def references(s2_id: str) -> list[dict]:
        seen.append(s2_id)
        return []

    monkeypatch.setattr(s2, "references", references)
    pipeline.build_lineage(limit=10)
    assert "s-queued" in seen
    # Lists first: those papers were chosen deliberately, as in dive-ahead.
    assert seen.index("s-queued") > seen.index("s-dataset")
