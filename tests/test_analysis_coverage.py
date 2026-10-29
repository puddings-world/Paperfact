"""A deep analysis counts as done only when what it made covers the paper.

One reply that answered 1 of 22 references stood for a whole paper: counted as done,
深入分析 finished in a second and never asked again, and the 研究脈絡 it needed was
never written while the tab kept offering to write it.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from paper_daily import analyze, cites, config, followups, llm, store
from paper_daily.enrich import s2
from paper_daily.sources import crossref

PID = "ref:wet"
TEXT = (
    "Introduction. Wet-lab training matters for surgical education in ophthalmology [1]. "
    + " ".join(
        f"Prior work number {n} studied a related surgical video task in depth [{n}]."
        for n in range(2, 11)
    )
)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(config, "TEXT_DIR", tmp_path / "text")
    (tmp_path / "text").mkdir()
    (tmp_path / "text" / "ref_wet.txt").write_text(TEXT, encoding="utf-8")
    monkeypatch.setattr(crossref, "reference_list", lambda doi: {})
    monkeypatch.setattr(s2, "references", lambda sid: [])
    monkeypatch.setattr(s2, "papers_by_doi", lambda dois: {})
    store.init_db()
    with store.connect() as c:
        store.upsert_papers(c, [{"id": PID, "title": "WetCat", "venue": "ACM MM",
                                 "year": 2025, "source": "test"}])
    c = sqlite3.connect(tmp_path / "papers.db")
    c.row_factory = sqlite3.Row
    return c


def _answer(keys, preface=""):
    return preface + json.dumps([
        {"key": k, "title": f"Ref {k}", "purpose": "背景", "gist": "g", "verdict": "略過",
         "why": "w"}
        for k in keys
    ], ensure_ascii=False)


def _rows(conn):
    return {r[0] for r in conn.execute("SELECT ref_key FROM cites WHERE paper_id=?", (PID,))}


def test_a_reply_that_stops_early_is_completed_by_asking_for_the_rest(conn, monkeypatch):
    replies = iter([_answer(["1"]), _answer([str(n) for n in range(2, 11)])])
    prompts = []
    monkeypatch.setattr(
        llm, "complete", lambda prompt, **k: (prompts.append(prompt), (next(replies), "ok"))[1]
    )
    stored, reason = cites.analyse_result(PID)
    assert (stored, reason) == (10, "")
    assert _rows(conn) == {str(n) for n in range(1, 11)}
    # The second question is only about what was missing.
    assert "[1] " not in prompts[1] and "[10] " in prompts[1]
    assert cites.complete(conn, PID)


def test_a_fragment_is_kept_but_not_counted_and_prunes_nothing(conn, monkeypatch):
    for key in ("7", "8", "9"):
        conn.execute(
            "INSERT INTO cites(paper_id, ref_key, title, verdict, written_at) "
            "VALUES (?, ?, 'earlier answer', '值得', 'before')", (PID, key),
        )
    conn.commit()
    monkeypatch.setattr(llm, "complete", lambda prompt, **k: (_answer(["1"]), "ok"))
    stored, reason = cites.analyse_result(PID)
    assert stored == 1 and "1/10" in reason
    # The earlier rows the fragment did not repeat are still there.
    assert {"1", "7", "8", "9"} <= _rows(conn)
    assert not cites.complete(conn, PID)
    with store.connect() as c:
        assert analyze.status(c, PID)["cites"] is False


def test_prose_with_brackets_before_the_answer_is_read(conn, monkeypatch):
    preface = "以下是 A 區 [1] 到 [10] 的判讀:\n```json\n"
    monkeypatch.setattr(
        llm, "complete",
        lambda prompt, **k: (_answer([str(n) for n in range(1, 11)], preface) + "\n```", "ok"),
    )
    assert cites.analyse_result(PID) == (10, "")


def test_an_answer_from_before_coverage_is_judged_by_the_markers(conn):
    conn.execute(
        "INSERT INTO cites(paper_id, ref_key, title, written_at) VALUES (?, '1', 't', 'old')",
        (PID,),
    )
    conn.commit()
    assert not cites.complete(conn, PID)
    for n in range(2, 6):
        conn.execute(
            "INSERT INTO cites(paper_id, ref_key, title, written_at) VALUES (?, ?, 't', 'old')",
            (PID, str(n)),
        )
    conn.commit()
    assert cites.complete(conn, PID)


def _judged_followup(conn, verdict):
    conn.execute(
        "INSERT INTO followups(paper_id, work_id, title, year, verdict, relation, why, "
        "fetched_at) VALUES (?, 'W1', 'Later work', 2026, ?, 'extends it', 'w', 'now')",
        (PID, verdict),
    )
    conn.commit()


def test_a_story_is_written_even_when_nothing_is_a_must_read(conn, monkeypatch):
    conn.execute(
        "INSERT INTO cites(paper_id, ref_key, title, verdict, purpose, written_at) "
        "VALUES (?, '1', 'Background survey', '略過', '背景', 'now')", (PID,),
    )
    _judged_followup(conn, "略過")
    store.set_kv(conn, f"followups.checked.{PID}", "now")
    conn.commit()
    asked = []
    story = ('{"summary": "它的位置", "reading": []}', "ok")
    monkeypatch.setattr(llm, "complete", lambda prompt, **k: (asked.append(prompt), story)[1])
    assert followups.overview(PID) == (True, "")
    assert "Background survey" in asked[0]
    assert followups.done(conn, PID)


def test_nothing_judged_is_an_answer_not_a_step_left(conn, monkeypatch):
    store.set_kv(conn, f"followups.checked.{PID}", "now")
    conn.commit()
    assert not followups.done(conn, PID)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("no model call"))
    assert followups.overview(PID) == (False, followups.NOTHING_TO_TELL)
    assert followups.done(conn, PID)


def test_an_unreachable_service_is_a_reason_not_a_crash(conn, monkeypatch):
    from paper_daily.http import FetchError

    def offline(pid, log):
        raise FetchError("429 from OpenAlex")

    monkeypatch.setattr(followups, "fetch", offline)
    judged, reason = followups.analyse_result(PID)
    assert judged == 0 and "暫時無法連線" in reason
    assert not followups.done(conn, PID)


def test_the_context_box_never_offers_a_button_that_will_do_nothing():
    pytest.importorskip("PySide6")
    from paper_daily.desktop.cites_pane import story_note

    background = {"refs": [{"verdict": "略過"}], "later": [], "story": None, "asked": "now"}
    text, action = story_note({**background, "untold": True})
    assert "沒有可整理" in text and action is None
    text, action = story_note({**background, "why": "研究脈絡未完成：AI 回覆格式無法解析"})
    assert "上次沒有完成" in text and "格式無法解析" in text and action == "run-all"
    text, action = story_note({**background, "partial": True})
    assert "分析參考文獻" in text and action == "run-all"
    written = {**background, "story": {"summary": "s"}}
    assert story_note(written) == ("", "refresh")
