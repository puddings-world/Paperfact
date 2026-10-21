"""深入分析 as one unit: the deep dive, 承先 and 啟後 are made together, every night for
the papers coming up and on request for the paper on screen; the 引用 tab says how
much of each side is actually known; and buttons that start AI work look it."""

import os
import threading

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from paper_daily import analyze, cli, store  # noqa: E402
from paper_daily.desktop import ai_style  # noqa: E402
from paper_daily.desktop.analysis_bar import describe  # noqa: E402
from paper_daily.desktop.cites_pane import coverage  # noqa: E402
from paper_daily.desktop.main import LIGHT  # noqa: E402

NOTHING = {"pdf": False, "dive": False, "highlights": False, "cites": False, "later": False}
EVERYTHING = dict.fromkeys(NOTHING, True)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    with store.connect() as conn:
        store.upsert_papers(conn, [
            dict(id=pid, title=f"Paper {pid}", venue="ICLR", year=2026, source="test")
            for pid in "abcde"
        ])
        for rank, (pid, state) in enumerate(
            [("a", "pending"), ("b", "read"), ("c", "delivered"), ("d", "pending"),
             ("e", "pending")]
        ):
            conn.execute(
                "INSERT INTO queue(paper_id, rank, state) VALUES (?,?,?)", (pid, rank, state)
            )
    return tmp_path


def test_the_night_takes_unread_papers_in_reading_order_that_lack_something(db, monkeypatch):
    done = {"a"}
    monkeypatch.setattr(
        analyze, "status", lambda conn, pid: EVERYTHING if pid in done else dict(NOTHING)
    )
    with store.connect() as conn:
        # a is complete and b already read; c (tonight's, delivered) comes first.
        assert analyze.upcoming(conn, 2) == ["c", "d"]
        assert analyze.upcoming(conn, 10) == ["c", "d", "e"]


def test_a_paper_no_source_has_does_not_hold_up_every_night(db, monkeypatch):
    monkeypatch.setattr(analyze, "PDF_DIR", db)
    with store.connect() as conn:
        assert analyze.left(conn, "a") == ["pdf", "dive", "highlights", "cites", "later"]
        store.set_kv(conn, "analyze.failed.pdf.a", "no source had the PDF")
        # What reads the text cannot start either; 啟後 needs only the title.
        assert analyze.left(conn, "a") == ["later"]
        store.set_kv(conn, "followups.checked.a", "2026-10-18")
        assert analyze.left(conn, "a") == []
        assert analyze.upcoming(conn, 1) == ["c"]
        # The button asks again regardless.
        assert analyze.left(conn, "a", retry=True) == ["pdf", "dive", "highlights", "cites"]


def test_the_explanation_and_the_citations_are_made_side_by_side(db, monkeypatch):
    from paper_daily import (
        cites,
        closeread,
        dive,
        fetch,
        followups,
        paper_highlights,
        resources,
        venues,
    )

    citing = threading.Event()
    seen = {}
    monkeypatch.setattr(analyze, "has_pdf", lambda pid: True)
    monkeypatch.setattr(fetch, "prepare", lambda row: (db / "a.pdf", "text"))
    monkeypatch.setattr(venues, "refresh", lambda *a, **k: None)
    monkeypatch.setattr(resources, "needs_check", lambda *a: False)

    def write_dive(**_kw):
        # Waits for the reference analysis: run one after the other, it never starts.
        seen["side_by_side"] = citing.wait(timeout=5)
        return 1

    def read_references(pid, log):
        citing.set()
        return 12

    monkeypatch.setattr(dive, "dive_ahead", write_dive)
    monkeypatch.setattr(closeread, "write", lambda pid: ("close reading", "ok"))
    monkeypatch.setattr(cites, "analyse", read_references)
    monkeypatch.setattr(
        followups, "analyse", lambda pid, log: seen.setdefault("later", citing.is_set())
    )
    monkeypatch.setattr(
        paper_highlights, "prepare_reading",
        lambda pid: ({"marks": {"mapped": 3, "total": 3}}, "ok"),
    )
    from paper_daily import research_questions

    questions = []
    monkeypatch.setattr(
        research_questions, "ensure", lambda pid: (questions.append(pid), "fixture")
    )
    analyze.analyse("a", log=lambda _m: None)
    assert seen == {"side_by_side": True, "later": True}
    assert questions == ["a"]


def test_cli_analyses_ahead_for_the_queue_or_the_lists(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        analyze, "ahead",
        lambda n, list_id=None, jobs=2, log=None: calls.append((n, list_id, jobs)) or n,
    )
    assert cli.main(["analyze", "--ahead", "4", "--jobs", "2"]) == 0
    assert cli.main(["analyze", "--ahead", "3", "--list", "all", "--jobs", "2"]) == 0
    assert calls == [(4, None, 2), (3, "all", 2)]


def test_the_bar_offers_the_analysis_until_it_is_complete():
    fresh = describe(dict(NOTHING), running=False, failures={})
    assert fresh["button"] == "深入分析" and fresh["primary"]
    assert [text for _k, text in fresh["chips"]] == ["講解", "承先", "啟後"]

    half = dict(NOTHING, pdf=True, dive=True)
    running = describe(half, running=True, failures={})
    assert running["button"] == "停止"
    assert [text for _k, text in running["chips"]] == ["講解 ✓", "承先 …", "啟後 …"]

    failed = describe(half, running=False, failures={"cites": "no references could be read"})
    assert failed["button"] == "重試深入分析"
    assert ("warn", "承先 ✗") in failed["chips"]
    assert "no references could be read" in failed["tip"]

    assert describe(EVERYTHING, running=False, failures={})["button"] is None


def test_the_cites_tab_says_what_is_not_known_yet():
    # The Polar Express case: 59 references and 103 citations read as "8 and none".
    graph = [{"title": f"r{i}", "basis": "graph"} for i in range(8)]
    assert coverage(graph, [], None, 59, 103) == (
        "參考文獻 59 篇尚未分析，目前只列出資料庫裡有的 8 篇 · "
        "後續研究尚未查詢（Semantic Scholar 記錄被引用 103 次）"
    )
    judged = [{"title": f"r{i}", "verdict": "值得", "basis": "context"} for i in range(55)]
    later = [{"title": "x"}] * 40
    assert coverage(judged, later, "2026-10-18", 59, 103) == (
        "參考文獻已分析 55 筆（共 59 篇） · 後續研究 40 篇"
    )
    assert coverage([], [], "2026-10-18", None, None) == "參考文獻尚未分析 · 後續研究 0 篇"


def test_a_button_that_starts_ai_work_says_so():
    QApplication.instance() or QApplication([])
    button = QPushButton("清單綜覽")
    button.setToolTip("把整份清單當成一個研究領域來讀")
    ai_style.mark(button, LIGHT)
    assert button.property("ai") == "secondary" and not button.icon().isNull()
    assert button.toolTip() == "把整份清單當成一個研究領域來讀（使用 AI）"
    ai_style.mark(button, LIGHT, primary=True)
    assert button.property("ai") == "primary"
    assert button.toolTip().count("AI") == 1
    assert "AI" in ai_style.mark(QPushButton("問"), LIGHT).toolTip()
    assert LIGHT["ai"] in ai_style.css(LIGHT, primary=True)


class _Job:
    def __init__(self, args):
        self.args = args
        self.alive = True

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False


@pytest.fixture
def window(db, monkeypatch):
    from paper_daily.desktop import main

    spawned = []

    def popen(cmd, **_kw):
        spawned.append(_Job(cmd[3:]))
        return spawned[-1]

    monkeypatch.setattr(main.subprocess, "Popen", popen)
    app = QApplication.instance() or QApplication([])
    win = main.MainWindow()
    app.processEvents()
    return win, spawned


def test_the_button_analyses_the_paper_on_screen_once_and_idle_work_gives_way(
    window, monkeypatch
):
    win, spawned = window
    spawned.clear()
    # Fresh workspaces no longer start paid analysis implicitly. Opt into the
    # background workflow here to retain its foreground handoff regression check.
    win.remember("background_analysis", "1")
    monkeypatch.setattr(analyze, "upcoming", lambda conn, n, list_id=None: ["d"])
    win.top_up_dives()
    idle = spawned[-1]
    assert idle.args[:3] == ["analyze", "--ahead", "3"]

    win.analyse_now("c")
    assert not idle.alive
    assert spawned[-1].args == ["analyze", "c", "--retry"]
    assert win.analysis_running("c") and not win.analysis_running("d")

    win.analyse_now("c")
    win.top_up_dives()
    assert len(spawned) == 2

    win.stop_analysis()
    assert not win.analysis_running()


def test_the_reader_carries_the_bar_and_its_ai_buttons(window, monkeypatch):
    win, _spawned = window
    reader = win.reader_page
    assert reader.tabs.cornerWidget() is reader.analysis_bar
    assert reader.ask_btn.property("ai") == "primary"
    assert reader.ask_page_btn.property("ai") == "secondary"

    asked = []
    monkeypatch.setattr(win, "analyse_now", asked.append)
    monkeypatch.setattr(reader, "_load_dive", lambda: None)
    reader.paper = win.papers[0] if win.papers else type("P", (), {"id": "c"})()
    reader.analysis_bar.paper_id = reader.paper.id
    reader._dive_source(QUrl("paperfact-analyze:now"))
    assert asked == [reader.paper.id]
