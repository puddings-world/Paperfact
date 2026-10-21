"""The 引用 tab as a map: who is on it, how big, and which neighbours cite which."""

from __future__ import annotations

import sqlite3

import pytest

from paper_daily import citegraph, store

PID = "ref:c1k"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    c = sqlite3.connect(tmp_path / "papers.db")
    c.row_factory = sqlite3.Row
    c.executescript(store.SCHEMA)
    store._migrate(c)
    store.upsert_papers(
        c,
        [
            {
                "id": PID,
                "title": "Cataract-1K Dataset for Deep-Learning-Assisted Analysis",
                "venue": "Scientific Data",
                "year": 2024,
                "source": "test",
                "doi": "10.1/c1k",
            },
        ],
    )
    for key, title, year, s2, cites, verdict in (
        ("20", "CaDIS: Cataract dataset for surgical segmentation", 2021, "s2cadis", 300, "值得"),
        (
            "7",
            "U-Net: Convolutional Networks for Biomedical Image Segmentation",
            2015,
            "s2unet",
            90000,
            "略過",
        ),
    ):
        c.execute(
            "INSERT INTO cites(paper_id, ref_key, title, year, s2_id, citations, verdict, "
            "written_at) VALUES (?,?,?,?,?,?,?, 'now')",
            (PID, key, title, year, s2, cites, verdict),
        )
    for wid, title, year, doi in (
        ("W1", "StepAL: Step-aware active learning for cataract surgery", 2025, "10.1/stepal"),
        ("S2:abc", "Surgical video segmentation benchmark", 2025, None),
    ):
        c.execute(
            "INSERT INTO followups(paper_id, work_id, title, year, doi, fetched_at) "
            "VALUES (?,?,?,?,?, 'now')",
            (PID, wid, title, year, doi),
        )
    c.commit()
    return c


@pytest.mark.parametrize(
    "title,expected",
    [
        ("GPTQ: Accurate Post-Training Quantization", "GPTQ"),
        ("Cataract-1K Dataset for Deep-Learning-Assisted Analysis", "Cataract-1K"),
        ("Attention Is All You Need", "AAYN"),
        ("Segment Anything", "SA"),
        ("Pointer Sentinel Mixture Models", "PSMM"),
        ("白內障手術影片分析", "白內"),
        ("", "?"),
    ],
)
def test_a_paper_is_named_in_a_word_or_two(title, expected):
    assert citegraph.label(title) == expected


def test_every_neighbour_points_at_the_paper_the_way_ideas_travel(conn):
    graph = citegraph.build(conn, PID)
    keys = {n.key: n for n in graph.nodes}
    centre = graph.nodes[0].key
    assert graph.nodes[0].side == "center"
    assert ("ref:20", centre) in graph.edges  # the paper cites CaDIS
    assert (centre, "later:W1") in graph.edges  # StepAL cites the paper
    assert keys["ref:7"].radius > keys["ref:20"].radius > keys["later:W1"].radius
    assert graph.checked is None


def test_links_among_neighbours_are_found_and_kept(conn, monkeypatch):
    asked = []

    def batch(url, payload):
        asked.extend(payload["ids"])
        ids = {
            "s2cadis": "P_cadis",
            "s2unet": "P_unet",
            "DOI:10.1/stepal": "P_stepal",
            "abc": "P_bench",
        }
        refs = {"P_cadis": ["P_unet"], "P_stepal": ["P_cadis", "P_unrelated"], "P_bench": []}
        return [
            {
                "paperId": ids[i],
                "citationCount": 5,
                "references": [{"paperId": r} for r in refs.get(ids[i], [])],
            }
            if i in ids
            else None
            for i in payload["ids"]
        ]

    monkeypatch.setattr(citegraph, "post_json", batch)
    assert citegraph.links(PID) == 2
    assert "abc" in asked and "DOI:10.1/stepal" in asked
    graph = citegraph.build(conn, PID)
    assert ("ref:7", "ref:20") in graph.edges  # CaDIS cites U-Net
    assert ("ref:20", "later:W1") in graph.edges  # StepAL cites CaDIS
    assert graph.checked and graph.unplaced == 0
    links = {n.key: n.links for n in graph.nodes}
    assert links["ref:20"] == 2 and links["later:S2:abc"] == 0
    # A citation count the lists lacked comes from the same answer.
    assert next(n for n in graph.nodes if n.key == "later:W1").citations == 5


def test_a_refused_lookup_keeps_what_was_there(conn, monkeypatch):
    def refuse(url, payload):
        raise citegraph.FetchError("429")

    monkeypatch.setattr(citegraph, "post_json", refuse)
    assert citegraph.links(PID) == -1
    assert store.get_kv(conn, f"citegraph.{PID}") is None


def test_a_crowded_side_keeps_its_most_telling_papers(conn):
    graph = citegraph.pick(citegraph.build(conn, PID), 1)
    kept = {n.key for n in graph.nodes}
    assert "ref:20" in kept and "ref:7" not in kept  # 值得 before 略過
    assert graph.hidden == {"ref": 1, "later": 1}
    assert all(a in kept and b in kept for a, b in graph.edges)


def test_older_work_sits_left_and_no_two_circles_overlap(conn):
    graph = citegraph.build(conn, PID)
    pos, heads = citegraph.layout(graph)
    x = {k: p[0] for k, p in pos.items()}
    centre = graph.nodes[0].key
    assert x["ref:7"] < x["ref:20"] < x[centre] < x["later:W1"]
    nodes = graph.nodes
    for i, a in enumerate(nodes):
        for b in nodes[i + 1 :]:
            (ax, ay), (bx, by) = pos[a.key], pos[b.key]
            assert ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 >= a.radius + b.radius
    assert [h for _x, h in heads] == ["2015", "2021", "2024", "2025"]


def test_a_reference_the_text_never_cites_is_left_off_the_map(conn):
    conn.execute(
        "INSERT INTO cites(paper_id, ref_key, title, basis, written_at) "
        "VALUES (?, 'Uncle (2019)', 'Uncle', 'title', 'now')",
        (PID,),
    )
    conn.commit()
    graph = citegraph.build(conn, PID)
    assert "ref:Uncle (2019)" not in {n.key for n in graph.nodes}
    assert graph.unconfirmed == 1
