"""Storing and ordering what each reference is doing in a paper.

Coverage is the whole point of the tab: a reference with no answer at all is exactly
the one you cannot judge, so every entry in the publisher's reference list gets a row
-- marked with whether the verdict rests on a citing sentence or on a title alone.
"""

from __future__ import annotations

import sqlite3

import pytest

from paper_daily import cites, store


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    c = sqlite3.connect(tmp_path / "papers.db")
    c.row_factory = sqlite3.Row
    c.executescript(store.SCHEMA)
    return c


def _cite(conn, key, verdict, basis="context", title=None):
    conn.execute(
        "INSERT INTO cites(paper_id, ref_key, title, verdict, basis, written_at) "
        "VALUES ('p', ?, ?, ?, ?, 'now')",
        (key, title or f"Reference {key}", verdict, basis),
    )


def test_reference_order_is_numeric_not_lexicographic(conn):
    """You see "27" on the page and want that card. "10" must not sort before "9"."""
    for key in ("9", "10", "27", "3"):
        _cite(conn, key, "參考")
    conn.commit()
    got = [r["ref_key"] for r in cites.for_paper(conn, "p", order="number")]
    assert got == ["3", "9", "10", "27"]


def test_verdict_order_puts_the_title_only_guesses_last(conn):
    """Two references can share a verdict while one of them rests on a citing
    sentence and the other on nothing but its title. The weaker one goes below."""
    _cite(conn, "1", "值得", basis="title")
    _cite(conn, "2", "值得", basis="context")
    _cite(conn, "3", "必讀", basis="context")
    conn.commit()
    got = [r["ref_key"] for r in cites.for_paper(conn, "p")]
    assert got == ["3", "2", "1"]


def test_bracketed_author_year_citations_are_found():
    """CataractSAM-2 cites as "[Ravi et al., 2024; ...]", across hyphenated line breaks."""
    from paper_daily.cites import contexts

    text = (
        "Introduction\n"
        "Significant challenges persist due to transparent tissues and the visual "
        "similarity of instruments [Gham-\nsarian et al., 2021].\n"
        "Foundation models such as SAM-2 show promise for segmentation "
        "[Ravi et al., 2024; Kirillov et al., 2023] but need adaptation.\n"
    )
    found = contexts(text)
    assert set(found) == {"Ghamsarian et al., 2021", "Ravi et al., 2024", "Kirillov et al., 2023"}
