"""A bibliography edge must not be presented as established scientific influence."""

import sqlite3
from contextlib import closing

from paper_daily import brief, store


def test_prompt_context_names_citation_direction_without_claiming_influence():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(store.SCHEMA)
        store.upsert_papers(
            conn,
            [
                {"id": "current", "title": "Current study", "year": 2026,
                 "source": "fixture", "venue": "Journal"},
                {"id": "earlier", "title": "Earlier study", "year": 2020,
                 "source": "fixture", "venue": "Journal"},
                {"id": "later", "title": "Later study", "year": 2027,
                 "source": "fixture", "venue": "Journal"},
            ],
        )
        conn.executemany(
            "INSERT INTO refs VALUES(?,?,?)", [("current", "earlier", 1), ("later", "current", 1)]
        )
        context = brief._lineage_context(conn, "current")
        assert "References in this corpus" in context and "Earlier study" in context
        assert "Works in this corpus citing this paper" in context and "Later study" in context
        assert "not endorsement, dependence, or historical influence" in context
        assert "**Builds on" not in context


def test_missing_citation_links_are_unknown_not_a_claim_that_no_prior_work_exists():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.executescript(store.SCHEMA)
        context = brief._lineage_context(conn, "missing")
        assert context == "_No in-corpus citation links recorded yet._"
