"""A reading list read as one field: what goes in, what is kept, what a hand edit protects."""

from __future__ import annotations

import sqlite3

import pytest

from paper_daily import store, survey

DIVE = """## 一句話結論
第一個千支影片的白內障資料集。

## 前導導讀
### 研究當下的狀態
CaDIS [20] 只有 25 支影片。

## 核心洞見
規模與多任務。

## 證據
Table 6 的 phase F1。

## 限制與反駁
只有 56 支有 phase 標註。
"""


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
                "id": "a",
                "title": "Cataract-1K Dataset",
                "venue": "Sci Data",
                "year": 2024,
                "source": "test",
                "abstract": "A dataset.",
            },
            {
                "id": "b",
                "title": "CaDIS: Cataract dataset",
                "venue": "MedIA",
                "year": 2021,
                "source": "test",
                "abstract": "Segmentation data.",
            },
        ],
    )
    c.execute("INSERT INTO lists(id, name, created_at) VALUES ('cat', 'Cataract', 'now')")
    for pos, pid in enumerate(("a", "b")):
        c.execute(
            "INSERT INTO list_papers(list_id, paper_id, position, added_at) VALUES "
            "('cat', ?, ?, 'now')",
            (pid, pos),
        )
    c.execute("INSERT INTO dives(paper_id, body, written_at) VALUES ('a', ?, 'now')", (DIVE,))
    c.commit()
    monkeypatch.setattr(survey, "init_db", lambda: None)
    return c


def test_each_paper_brings_its_account_of_the_field(conn):
    text, count = survey.build_input(conn, "cat")
    assert count == 2
    # Oldest first, so the history reads in order.
    assert text.index("CaDIS") < text.index("Cataract-1K")
    assert "【前導導讀】### 研究當下的狀態" in text
    assert "【限制與反駁】只有 56 支" in text
    assert "摘要:Segmentation data." in text  # no dive: the abstract stands in


def test_a_paper_card_keeps_to_its_share(conn):
    row = conn.execute("SELECT * FROM papers WHERE id='a'").fetchone()
    card = survey.digest(row, DIVE * 40, None, 3, 900)
    assert len(card) <= 900
    assert "後續研究 3 篇" in card


def test_a_survey_is_stored_and_a_hand_edit_is_kept(conn, monkeypatch):
    calls = []

    def complete(prompt, system=None, timeout=0, task=""):
        calls.append(task)
        return "## 這個領域在解決什麼\n" + "白內障手術影片分析。" * 300, "ok"

    monkeypatch.setattr(survey.llm, "complete", complete)
    assert survey.write("cat") == (True, "ok")
    assert calls == ["survey"]
    stored = survey.get(conn, "cat")
    assert stored["papers"] == 2 and not stored["edited"]

    survey.edit("cat", "我改過的綜覽")
    written, reason = survey.write("cat")
    assert not written and "edited by hand" in reason
    assert survey.get(conn, "cat")["body"] == "我改過的綜覽"
    assert survey.write("cat", force=True) == (True, "ok")


def test_a_short_reply_is_not_kept_as_a_survey(conn, monkeypatch):
    monkeypatch.setattr(survey.llm, "complete", lambda *a, **k: ("I cannot help.", "ok"))
    written, reason = survey.write("cat")
    assert not written and "too short" in reason
    assert survey.get(conn, "cat") is None
