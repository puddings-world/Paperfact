"""Proposing records that are the same paper. Cases are taken from a real library."""

import json
import sqlite3

import pytest

from paper_daily import paper_identity


@pytest.fixture
def conn():
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE papers (id TEXT PRIMARY KEY, title TEXT, year INTEGER, doi TEXT,
            arxiv_id TEXT, s2_id TEXT, authors_json TEXT);
        CREATE TABLE list_papers (list_id TEXT, paper_id TEXT);
        CREATE TABLE notes (id INTEGER PRIMARY KEY, paper_id TEXT, body TEXT);
        """
    )
    return db


def add(conn, pid, title, year=2020, authors=("Ada Lovelace",), listed=False, notes=0, **ids):
    conn.execute(
        "INSERT INTO papers VALUES (?,?,?,?,?,?,?)",
        (
            pid,
            title,
            year,
            ids.get("doi"),
            ids.get("arxiv"),
            ids.get("s2"),
            json.dumps(list(authors)),
        ),
    )
    if listed:
        conn.execute("INSERT INTO list_papers VALUES ('L', ?)", (pid,))
    for _ in range(notes):
        conn.execute("INSERT INTO notes(paper_id, body) VALUES (?, 'n')", (pid,))


def kinds(groups):
    return {(g.kind, tuple(sorted(g.papers))) for g in groups}


def test_a_shared_identifier_is_the_same_paper_and_the_copy_with_notes_is_kept(conn):
    # The roster files it under 2018, Semantic Scholar under its 2017 preprint.
    add(
        conn,
        "ICLR:2018:v298",
        "All-but-the-Top: Simple and Effective Postprocessing",
        2018,
        arxiv="1702.01417",
    )
    add(
        conn,
        "ICLR:2017:s2",
        "All-but-the-Top: Simple and Effective Postprocessing",
        2017,
        arxiv="https://arxiv.org/abs/1702.01417v2",
        listed=True,
        notes=2,
    )
    [group] = paper_identity.find(conn)
    assert group.kind == "same" and group.keep == "ICLR:2017:s2"
    assert group.reasons == ["arXiv 1702.01417"]
    assert group.research == {"ICLR:2017:s2": 3, "ICLR:2018:v298": 0}


def test_doi_forms_and_the_arxiv_doi_are_one_identifier(conn):
    add(conn, "a", "Variational Continual Learning", doi="https://doi.org/10.17863/CAM.35471")
    add(conn, "b", "Variational Continual Learning", doi="10.17863/cam.35471")
    add(conn, "c", "Neural Map: Structured Memory", doi="10.48550/arXiv.1702.08360")
    add(conn, "d", "Neural Map: Structured Memory", arxiv="1702.08360")
    assert kinds(paper_identity.find(conn)) == {("same", ("a", "b")), ("same", ("c", "d"))}


def test_a_shared_identifier_with_unrelated_titles_is_flagged_not_merged(conn):
    add(conn, "a", "Target Propagation", 2015, doi="10.5167/uzh-198834")
    add(conn, "b", "A Theoretical Framework for Target Propagation", 2020, doi="10.5167/uzh-198834")
    assert kinds(paper_identity.find(conn)) == {("check", ("a", "b"))}


def test_identical_titles_in_a_list_are_likely_duplicates(conn):
    add(
        conn,
        "ICML:2026:v67238",
        "Position: Anthropomorphic Misalignment Research",
        2026,
        listed=True,
    )
    add(conn, "ICML:2026:gupta26e", "Position: Anthropomorphic Misalignment Research", 2026)
    [group] = paper_identity.find(conn)
    assert (group.kind, group.reasons, group.keep) == ("likely", ["title"], "ICML:2026:v67238")


@pytest.mark.parametrize(
    "mine, other",
    [
        (
            "Dissecting Supervised Constrastive Learning",
            "Dissecting Supervised Contrastive Learning",
        ),
        (
            "Even Faster SVD Decomposition Yet Without Agonizing Pain",
            "LazySVD: Even Faster SVD Decomposition Yet Without Agonizing Pain",
        ),
    ],
)
def test_a_misspelt_or_extended_title_by_the_same_author_is_likely(conn, mine, other):
    add(conn, "a", mine, 2016, authors=("Zeyuan Allen-Zhu",), listed=True)
    add(conn, "b", other, 2016, authors=("Z. Allen-Zhu",))
    assert kinds(paper_identity.find(conn)) == {("likely", ("a", "b"))}


@pytest.mark.parametrize(
    "mine, other, years, authors",
    [
        # same_paper alone accepts this pair; nothing else connects them.
        (
            "Language Modeling Is Compression",
            "Proxy Compression for Language Modeling",
            (2024, 2026),
            ("Grégoire Delétang", "Zheng Wu"),
        ),
        # The same author's follow-ups.
        (
            "PredRNN: Recurrent Neural Networks for Predictive Learning",
            "PredRNN++: Recurrent Neural Networks for Predictive Learning",
            (2017, 2018),
            ("Yunbo Wang", "Yunbo Wang"),
        ),
        (
            "QMIX: Monotonic Value Function Factorisation for Deep Multi-Agent RL",
            "Weighted QMIX: Monotonic Value Function Factorisation for Deep Multi-Agent RL",
            (2018, 2020),
            ("Tabish Rashid", "Tabish Rashid"),
        ),
    ],
)
def test_similar_titles_that_are_different_papers_are_left_alone(conn, mine, other, years, authors):
    add(conn, "a", mine, years[0], authors=(authors[0],), listed=True)
    add(conn, "b", other, years[1], authors=(authors[1],))
    assert paper_identity.find(conn) == []


def test_different_arxiv_ids_keep_identical_titles_apart(conn):
    add(conn, "a", "Attention Is All You Need", listed=True, arxiv="1706.03762")
    add(conn, "b", "Attention Is All You Need", arxiv="2501.00001")
    assert paper_identity.find(conn) == []


def test_title_search_starts_from_the_papers_asked_about(conn):
    add(conn, "a", "Observational Scaling Laws", 2024, listed=True)
    add(conn, "b", "Observational Scaling Laws", 2024)
    add(conn, "c", "Corpus Only Paper Title Here", 2020)
    add(conn, "d", "Corpus Only Paper Title Here", 2020)
    add(conn, "e", "Shared Identifier", s2="S")
    add(conn, "f", "Shared Identifier", s2="s")
    # Corpus-only title twins are not compared unless asked; identifiers always are.
    assert kinds(paper_identity.find(conn)) == {("likely", ("a", "b")), ("same", ("e", "f"))}
    assert kinds(paper_identity.find(conn, within=["c"])) == {("likely", ("c", "d"))}


def test_the_duplicates_command_reports_groups_and_changes_nothing(monkeypatch, tmp_path, capsys):
    from paper_daily import cli, store

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                dict(
                    id="ref:star",
                    title="STaR: Bootstrapping Reasoning With Reasoning",
                    venue="arXiv",
                    year=2022,
                    source="list",
                    arxiv_id="2203.14465",
                ),
                dict(
                    id="NeurIPS:2022:star",
                    title="STaR: Bootstrapping Reasoning With Reasoning",
                    venue="NeurIPS",
                    year=2022,
                    source="s2",
                    arxiv_id="2203.14465",
                ),
            ],
        )
        conn.execute("INSERT INTO notes(paper_id, body, created_at) VALUES ('ref:star','n','now')")
        before = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    assert cli.main(["duplicates"]) == 0
    out = capsys.readouterr().out
    assert "same paper  (arXiv 2203.14465)" in out
    assert "keep ref:star" in out and "1 same, 0 to check, 0 likely" in out
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == before
