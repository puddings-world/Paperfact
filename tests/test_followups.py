"""A paper's place in its field: references, later work, and the overview of both.

It replaced a lineage drawn inside the corpus, which for a surgical-video dataset
found one ancestor of forty references and five descendants of forty-seven.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from paper_daily import citegraph, followups, store

PID = "ref:c1k"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    c = sqlite3.connect(tmp_path / "papers.db")
    c.row_factory = sqlite3.Row
    c.executescript(store.SCHEMA)
    store._migrate(c)
    store.upsert_papers(c, [
        {"id": PID, "title": "Cataract-1K Dataset for Deep-Learning-Assisted Analysis",
         "venue": "Scientific Data", "year": 2024, "source": "test", "doi": "10.1/c1k"},
        {"id": "ref:cadis", "title": "CaDIS: Cataract dataset for surgical segmentation",
         "venue": "MedIA", "year": 2021, "source": "test", "doi": "10.1/cadis"},
    ])
    for key, title, verdict, purpose in (
        ("31", "Cataract-1k. Synapse https://doi.org/10.7303/syn1 (2024).", "必讀", "資料來源"),
        ("20", "CaDIS: Cataract dataset for surgical segmentation", "值得", "當作主要比較對象"),
        ("3", "A survey of surgical AI", "略過", "背景鋪陳"),
    ):
        c.execute(
            "INSERT INTO cites(paper_id, ref_key, title, verdict, purpose, written_at) "
            "VALUES (?,?,?,?,?, 'now')",
            (PID, key, title, verdict, purpose),
        )
    c.commit()
    return c


def test_references_leave_out_the_papers_own_data_deposit(conn):
    keys = [r["ref_key"] for r in followups.references(conn, PID)]
    assert "31" not in keys
    assert set(keys) == {"20", "3"}


def test_a_reference_already_here_can_be_opened(conn):
    here = followups.in_corpus(conn, None, "CaDIS: Cataract dataset for surgical segmentation")
    assert here == {"id": "ref:cadis", "read": False}
    assert followups.in_corpus(conn, "10.1/CADIS", None)["id"] == "ref:cadis"
    assert followups.in_corpus(conn, None, "Something nobody has added") is None


def test_both_sources_merge_into_one_list():
    openalex = [
        {"id": "W2", "title": "StepAL: Step-Aware Active Learning", "doi": None,
         "citations": 1, "abstract": None},
        {"id": "W3", "title": "AI in ophthalmology: a review", "doi": "10.1/rev", "citations": 7},
    ]
    s2 = [
        # Same paper as W2, found by title; S2 has the abstract and the citing sentence.
        {"id": "S2:a", "title": "StepAL: step-aware active learning", "doi": "10.48550/x",
         "arxiv_id": "2507.22059", "citations": 3, "abstract": "Active learning ...",
         "contexts": ["We evaluate StepAL on Cataract-1k [9]."]},
        {"id": "S2:b", "title": "Only Semantic Scholar has this one", "citations": 0},
    ]
    merged = {w["id"]: w for w in followups.merge(openalex, s2)}
    assert set(merged) == {"W2", "W3", "S2:b"}
    assert merged["W2"]["abstract"] == "Active learning ..."
    assert merged["W2"]["contexts"] == ["We evaluate StepAL on Cataract-1k [9]."]
    assert merged["W2"]["arxiv_id"] == "2507.22059"
    assert merged["W2"]["citations"] == 3


def _fetch(monkeypatch, works):
    monkeypatch.setattr(followups, "work_id", lambda row: "W1")
    monkeypatch.setattr(followups, "_citing_openalex", lambda wid: works)
    monkeypatch.setattr(followups, "_citing_s2", lambda row: [])
    monkeypatch.setattr(citegraph, "links", lambda pid, log=None: 0)
    return followups.fetch(PID)


def test_citing_works_are_stored_judged_and_summarised(conn, monkeypatch):
    assert _fetch(monkeypatch, [
        {"id": "W2", "title": "Test-time adaptation for cataract", "year": 2025,
         "doi": "10.1/tta", "citations": 14, "contexts": ["cross-domain shift of [9]"]},
        {"id": "W3", "title": "AI in ophthalmology: a review", "year": 2025, "citations": 7},
    ]) == 2

    answers = iter([
        json.dumps([
            {"id": 0, "relation": "接續它的跨中心問題", "verdict": "必讀", "why": "直接延伸"},
            {"id": 1, "relation": "x", "verdict": "不是合法的判斷", "why": "x"},
        ], ensure_ascii=False),
        json.dumps({
            "summary": "它補上了多任務標註;之後有人做跨中心適應。",
            "reading": [{"title": "Test-time adaptation for cataract", "direction": "啟後",
                         "why": "直接回應它留下的缺口"}],
        }, ensure_ascii=False),
    ])
    monkeypatch.setattr(followups.llm, "complete", lambda *a, **k: (next(answers), "ok"))
    followups.analyse(PID)

    with store.connect() as c:
        rows = followups.for_paper(c, PID)
        story = followups.overview_for(c, PID)
        assert followups.checked(c, PID)
    first = rows[0]
    assert first["verdict"] == "必讀" and first["relation"] == "接續它的跨中心問題"
    assert first["contexts"] == ["cross-domain shift of [9]"]
    assert rows[1]["verdict"] is None
    assert story["reading"][0]["direction"] == "啟後"
    assert not story["edited"]


def test_a_hand_correction_survives_a_rerun(conn, monkeypatch):
    _fetch(monkeypatch, [{"id": "W2", "title": "Test-time adaptation", "citations": 14}])
    followups.edit_followup(PID, "W2", verdict="值得", relation="我自己的判斷", why="")
    followups.edit_overview(PID, "我寫的脈絡", [])
    monkeypatch.setattr(
        followups.llm, "complete", lambda *a, **k: pytest.fail("nothing left to ask about")
    )
    followups.analyse(PID)
    with store.connect() as c:
        row = followups.for_paper(c, PID)[0]
        story = followups.overview_for(c, PID)
    assert (row["verdict"], row["relation"], row["edited"]) == ("值得", "我自己的判斷", 1)
    assert story["summary"] == "我寫的脈絡" and story["edited"]


def test_a_corrected_reference_keeps_the_correction(conn):
    followups.edit_reference(PID, "3", verdict="值得", purpose="其實是方法出處")
    with store.connect() as c:
        row = c.execute("SELECT * FROM cites WHERE paper_id=? AND ref_key='3'", (PID,)).fetchone()
    assert (row["verdict"], row["purpose"], row["edited"]) == ("值得", "其實是方法出處", 1)


def test_nothing_citing_it_yet_is_still_an_answer(conn, monkeypatch):
    assert _fetch(monkeypatch, []) == 0
    with store.connect() as c:
        assert followups.checked(c, PID) is not None


def test_ahead_asks_only_about_papers_never_asked(conn, monkeypatch):
    conn.execute("INSERT INTO lists(id, name, created_at) VALUES ('cat', 'Cataract', 'now')")
    for pos, pid in enumerate((PID, "ref:cadis")):
        conn.execute(
            "INSERT INTO list_papers(list_id, paper_id, position, added_at) "
            "VALUES ('cat', ?, ?, 'now')",
            (pid, pos),
        )
    store.set_kv(conn, f"followups.checked.{PID}", "2026-10-05")
    conn.commit()
    asked = []
    monkeypatch.setattr(followups, "analyse", lambda pid, log=None: asked.append(pid))
    assert followups.ahead(5) == 1
    assert asked == ["ref:cadis"]
