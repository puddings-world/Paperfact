"""Ranking, queue ordering and CLI argument tests.

These cover the decisions that actually determine what gets read, so they assert
behaviour rather than implementation: newest-year-first ordering, that a recent paper
can outrank an old one, and that the classifier keeps benchmarks out of the
principle bucket.
"""

import pytest

from paper_daily.cli import parse_venues, parse_years
from paper_daily.config import ScoreWeights
from paper_daily.rank.canon import canon_index
from paper_daily.rank.classify import TYPE_WEIGHT, classify
from paper_daily.rank.score import _percentiles, score_all
from paper_daily.store import title_key, upsert_papers


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_DAILY_DATA", str(tmp_path))
    import importlib

    from paper_daily import config, store

    importlib.reload(config)
    importlib.reload(store)
    store.init_db()
    return store


def test_parse_years():
    assert parse_years("2016-2019") == [2016, 2017, 2018, 2019]
    assert parse_years("2024") == [2024]
    assert parse_years("2020,2024") == [2020, 2024]
    assert parse_years("2024,2023-2024") == [2023, 2024]


def test_parse_venues():
    assert parse_venues(None) == ["ICLR", "ICML", "NeurIPS"]
    assert parse_venues("iclr,neurips") == ["ICLR", "NeurIPS"]
    assert parse_venues("nonsense") == ["ICLR", "ICML", "NeurIPS"]


def test_title_key_ignores_punctuation_and_case():
    assert title_key("Attention Is All You Need!") == title_key("attention is all you need")
    assert title_key("LoRA: Low-Rank Adaptation") == title_key("LoRA Low Rank Adaptation")


def test_percentiles_are_ties_aware():
    p = _percentiles([1.0, 1.0, 5.0, 9.0])
    assert p[1.0] == 0.0
    assert p[9.0] == 1.0
    assert 0.0 < p[5.0] < 1.0


def test_classify_prefers_title_signal():
    assert (
        classify("MathVista: Evaluating Mathematical Reasoning", "we show that")[0] == "benchmark"
    )
    assert (
        classify("Understanding deep learning requires rethinking generalization", "")[0]
        == "principle"
    )
    assert classify("A New Model for Images", "we train a network")[0] == "method"
    # A Datasets & Benchmarks track paper is a benchmark whatever its title says.
    assert classify("Deep Theory of Everything", "", "Datasets_and_Benchmarks")[0] == "benchmark"


def test_type_weight_orders_principle_above_application():
    assert TYPE_WEIGHT["principle"] > TYPE_WEIGHT["method"] > TYPE_WEIGHT["application"]
    assert TYPE_WEIGHT["application"] > TYPE_WEIGHT["benchmark"]


def test_canon_index_is_keyed_by_normalised_title():
    idx = canon_index()
    assert title_key("Attention Is All You Need") in idx
    assert title_key("Denoising Diffusion Probabilistic Models") in idx


def _paper(pid, year, title, cites, award=None, h=10, venue="ICLR"):
    return {
        "id": pid,
        "venue": venue,
        "year": year,
        "title": title,
        "title_key": title_key(title),
        "abstract": "",
        "award": award,
        "citation_count": cites,
        "author_strength": h,
        "source": "test",
    }


def test_recent_paper_can_outrank_old_one(db):
    """Citation velocity, not raw count: an old paper with more total citations must
    not automatically beat a recent one. This is what makes newest-first coherent.

    Neither paper gets an award, so the award weight cannot mask the effect being
    tested: 500 citations over ~10 years is 50/yr, 400 over ~1 year is 400/yr.
    """
    with db.connect() as conn:
        upsert_papers(
            conn,
            iter(
                [
                    _paper("old", 2016, "Old Theorem Paper", cites=500, award=None),
                    _paper("new", 2025, "New Theorem Paper", cites=400, award=None),
                ]
            ),
        )
        score_all(conn, ScoreWeights())
        scores = {r["id"]: r["score"] for r in conn.execute("SELECT id, score FROM papers")}
    assert scores["new"] > scores["old"]


def test_queue_is_year_block_descending(db):
    from paper_daily import queue as qmod

    with db.connect() as conn:
        upsert_papers(
            conn,
            iter(
                [
                    _paper("a", 2024, "Weak Recent Paper", cites=1, award=None),
                    _paper("b", 2020, "Strong Old Paper", cites=9999, award="oral"),
                ]
            ),
        )
        score_all(conn, ScoreWeights())
        qmod.build(conn, per_year=10)
        order = [r["id"] for r in qmod.next_papers(conn, 10)]
    # 2024 comes first even though the 2020 paper scores higher.
    assert order[0] == "a"


def test_delivered_papers_are_not_requeued(db):
    from paper_daily import queue as qmod

    with db.connect() as conn:
        upsert_papers(
            conn,
            iter(
                [
                    _paper("a", 2024, "First Paper", cites=10, award="oral"),
                    _paper("b", 2024, "Second Paper", cites=5),
                ]
            ),
        )
        score_all(conn, ScoreWeights())
        qmod.build(conn, per_year=10)
        first = qmod.next_papers(conn, 1)[0]["id"]
        qmod.mark(conn, first, "delivered")
        qmod.build(conn, per_year=10)  # rebuild, as refresh does
        remaining = [r["id"] for r in qmod.next_papers(conn, 10)]
    assert first not in remaining


def test_newest_year_still_ranks_without_citations(db):
    """The newest conference year has no citations and no author h-index yet --
    Semantic Scholar matched 18 of ICLR 2026's 5468 papers. Award and paper type
    must still separate that block, or the year the reader starts on is unordered.
    """
    rows = [
        {
            "id": "plain", "venue": "ICLR", "year": 2026, "title": "A Method For Things",
            "title_key": title_key("A Method For Things"), "abstract": "we train a network",
            "award": None, "citation_count": None, "author_strength": None, "source": "test",
        },
        {
            "id": "oral-principle", "venue": "ICLR", "year": 2026,
            "title": "Understanding Why Transformers Generalize",
            "title_key": title_key("Understanding Why Transformers Generalize"),
            "abstract": "we prove a generalization bound", "award": "oral",
            "citation_count": None, "author_strength": None, "source": "test",
        },
    ]
    with db.connect() as conn:
        upsert_papers(conn, iter(rows))
        score_all(conn, ScoreWeights())
        scores = {r["id"]: r["score"] for r in conn.execute("SELECT id, score FROM papers")}
    assert scores["oral-principle"] > scores["plain"]


def test_upsert_preserves_enrichment_on_recrawl(db):
    with db.connect() as conn:
        upsert_papers(conn, iter([_paper("a", 2024, "A Paper", cites=42)]))
        # A re-crawl supplies roster columns only, with no citation data.
        upsert_papers(
            conn,
            iter(
                [
                    {
                        "id": "a",
                        "venue": "ICLR",
                        "year": 2024,
                        "title": "A Paper",
                        "title_key": title_key("A Paper"),
                        "source": "virtual",
                    }
                ]
            ),
        )
        row = conn.execute("SELECT citation_count FROM papers WHERE id='a'").fetchone()
    assert row["citation_count"] == 42
