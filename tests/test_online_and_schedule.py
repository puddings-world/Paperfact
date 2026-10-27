"""The 分析排程 settings: how often the nightly 深入分析 runs, how much, and
whether the reader says so afterwards."""

import os
from datetime import date

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from paper_daily import analysis_schedule, analyze, cli, store  # noqa: E402

TITLE = "Attention Is All You Need"


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    with store.connect() as conn:
        store.upsert_papers(conn, [
            dict(id="a", title=TITLE, venue="NeurIPS", year=2017, source="test",
                 arxiv_id="1706.03762", page_url="https://papers.nips.cc/x"),
            dict(id="b", title="A Paper Nobody Posted", venue="ICLR", year=2026,
                 source="test"),
            dict(id="c", title="Third", venue="ICLR", year=2026, source="test"),
        ])
        for rank, pid in enumerate("abc"):
            conn.execute("INSERT INTO queue(paper_id, rank, state) VALUES (?,?,'pending')",
                         (pid, rank))
    return tmp_path


# ---- 分析排程 ----------------------------------------------------------------

def test_settings_default_and_clamp(db):
    with store.connect() as conn:
        assert analysis_schedule.load(conn) == {"every": 1, "queue": 4, "lists": 3,
                                                "notify": True}
        store.set_kv(conn, analysis_schedule.KEY,
                     {"every": 5, "queue": 99, "lists": -2, "notify": "yes"})
        assert analysis_schedule.load(conn) == {"every": 1, "queue": 20, "lists": 0,
                                                "notify": True}


def test_how_often_decides_whether_tonight_runs():
    today = date(2026, 10, 19)
    nightly = dict(analysis_schedule.DEFAULTS)
    assert analysis_schedule.due(nightly, None, today)
    assert analysis_schedule.due(nightly, "2026-10-18", today)
    assert not analysis_schedule.due(nightly, "2026-10-19", today)
    weekly = dict(nightly, every=7)
    assert not analysis_schedule.due(weekly, "2026-10-14", today)
    assert analysis_schedule.due(weekly, "2026-10-12", today)
    assert not analysis_schedule.due(dict(nightly, every=0), None, today)
    assert not analysis_schedule.due(dict(nightly, queue=0, lists=0), None, today)
    assert analysis_schedule.describe(dict(nightly, every=2), "2026-10-19", today) == (
        "上次在 2026-10-19 自動分析；2 天後 00:00 會分析主佇列接下來 4 篇、清單裡 3 篇。"
    )
    assert "不會自動分析" in analysis_schedule.describe(dict(nightly, every=0), None, today)


def test_the_scheduled_run_follows_the_settings_and_records_what_it_finished(db, monkeypatch):
    analysed = []
    monkeypatch.setattr(analyze, "upcoming", lambda conn, n, list_id=None: (
        ["a", "b", "c"][:n] if list_id is None else ["c", "d"][:n]
    ))
    monkeypatch.setattr(analyze, "analyse_many",
                        lambda ids, jobs, log: analysed.append(list(ids)) or len(ids))
    monkeypatch.setattr(analyze, "status", lambda conn, pid: {"dive": pid != "b"})
    with store.connect() as conn:
        analysis_schedule.save(conn, {"every": 2, "queue": 2, "lists": 1, "notify": True})
    today = date(2026, 10, 19)
    assert analysis_schedule.run(log=lambda _m: None, today=today) == ["a", "c"]
    assert analysed == [["a", "b", "c"]]
    # Every other day: tomorrow is skipped, the day after runs.
    assert analysis_schedule.run(log=lambda _m: None, today=date(2026, 10, 20)) is None
    assert len(analysed) == 1

    with store.connect() as conn:
        assert analysis_schedule.unseen(conn) == ["a", "c"]
        analysis_schedule.mark_seen(conn)
        assert analysis_schedule.unseen(conn) == []
        store.set_kv(conn, analysis_schedule.BATCH, {"at": "later", "ids": ["c"]})
        analysis_schedule.save(conn, {"every": 2, "queue": 2, "lists": 1, "notify": False})
        assert analysis_schedule.unseen(conn) == []


def test_cli_runs_the_schedule(monkeypatch):
    calls = []
    monkeypatch.setattr(analysis_schedule, "run",
                        lambda jobs, log: calls.append(jobs) or [])
    assert cli.main(["analyze", "--scheduled", "--jobs", "2"]) == 0
    assert calls == [2]


# ---- the window ------------------------------------------------------------

class _Job:
    def poll(self):
        return 0


@pytest.fixture
def window(db, monkeypatch):
    from paper_daily.desktop import main

    monkeypatch.setattr(main.subprocess, "Popen", lambda *a, **k: _Job())
    app = QApplication.instance() or QApplication([])
    win = main.MainWindow()
    app.processEvents()
    return win


def test_the_reader_announces_a_finished_batch_once(window, monkeypatch):
    with store.connect() as conn:
        store.set_kv(conn, analysis_schedule.BATCH, {"at": "t1", "ids": ["a", "b"]})
    window.announce_ready()
    banner = window.ready_banner
    assert not banner.isHidden()
    assert banner.label.text() == (
        f"已深入分析 2 篇，可以讀了：《{TITLE}》、《A Paper Nobody Posted》"
    )
    opened = []
    monkeypatch.setattr(window, "open_anywhere", opened.append)
    banner.open_paper.disconnect()
    banner.open_paper.connect(window.open_anywhere)
    banner.read.click()
    assert opened == ["a"] and banner.isHidden()
    window.announce_ready()
    assert banner.isHidden()


def test_the_settings_dialog_saves_what_was_chosen(window):
    from paper_daily.desktop.analysis_settings import IDLE_KEY, AnalysisSettings

    dialog = AnalysisSettings(window, window.pal)
    # All desktop lists now share one total budget; there is no privileged queue.
    assert dialog.every.currentText() == "每晚" and dialog.lists.value() == 3
    dialog.every.setCurrentIndex(dialog.every.findData(7))
    dialog.lists.setValue(0)
    dialog.notify.setChecked(False)
    dialog.idle.setChecked(True)
    assert "清單" not in dialog.preview.text()
    dialog.every.setCurrentIndex(dialog.every.findData(0))
    assert not dialog.lists.isEnabled()
    dialog.every.setCurrentIndex(dialog.every.findData(7))
    dialog.accept()
    with store.connect() as conn:
        assert analysis_schedule.load(conn) == {"every": 7, "queue": 0, "lists": 0,
                                                "notify": False}
        assert store.get_kv(conn, IDLE_KEY) == "1"
    assert window.schedule_btn.text() == "分析排程"


def test_the_ai_row_names_the_tab_on_screen_not_its_position(window):
    reader = window.reader_page
    window.stack.setCurrentWidget(reader)
    reader.tabs.setCurrentWidget(reader.figure_pane)
    window._refresh_ai_summary()
    assert "圖表" not in window.ai_summary.text()
    reader.tabs.setCurrentWidget(reader.presentation_pane)
    window._refresh_ai_summary()
    assert window.ai_summary.text().startswith("簡報（")


def test_the_ai_row_keeps_its_place_and_height_across_every_reader_tab(window):
    """Hidden on the tabs that use no AI, or wrapping on long names, the row moved
    the whole reader up and down as Ctrl+number flipped the tabs."""
    from paper_daily.desktop.main import AI_ROW_HEIGHT

    reader = window.reader_page
    window.stack.setCurrentWidget(reader)
    for index in range(reader.tabs.count()):
        reader.tabs.setCurrentIndex(index)
        window._refresh_ai_summary()
        assert not window.ai_summary.isHidden(), reader.tabs.tabText(index)
        assert window.ai_summary.height() == AI_ROW_HEIGHT
        assert "\n" not in window.ai_summary.text()


def test_a_reason_that_only_repeats_the_title_is_not_shown():
    from paper_daily.desktop.main import shows_reason

    assert not shows_reason("StepAL: Active Learning", "stepal: active learning ")
    assert not shows_reason("StepAL", None)
    assert shows_reason("StepAL", "cited by the survey as the step-aware baseline")


def test_ctrl_numbers_count_only_shown_tabs_and_jumps_find_their_own_tab(window):
    """A style that hides a tab must not shift what Ctrl+number opens, nor send
    "ask about this passage" to whichever tab now sits third."""
    from paper_daily.desktop import fonts

    reader = window.reader_page
    tabs = reader.tabs
    figures = tabs.indexOf(reader.figure_pane)
    tabs.setTabVisible(figures, False)
    reader._number_tabs()
    assert reader.figure_pane not in reader.numbered_tabs()
    reader._analysis_shortcuts[figures].activated.emit()
    assert tabs.currentWidget() is reader.cites_pane
    badges = reader._tab_badges()
    assert badges[figures] is None and tabs.tabToolTip(figures) == "圖表"
    assert badges[figures + 1] == fonts.key(f"Ctrl+{figures + 1}")
    assert fonts.key(f"Ctrl+{figures + 1}") in tabs.tabToolTip(figures + 1)
    # Moving the tabs around leaves the in-page jumps on the right one.
    tabs.tabBar().moveTab(tabs.indexOf(reader.ask_tab), 0)
    reader._ask_selection("a passage worth asking about")
    assert tabs.currentWidget() is reader.ask_tab


def test_ctrl_tab_steps_through_shown_tabs_and_wraps(window):
    reader = window.reader_page
    tabs = reader.tabs
    tabs.setTabVisible(tabs.indexOf(reader.figure_pane), False)
    shown = reader.numbered_tabs()
    tabs.setCurrentWidget(shown[-1])
    reader.step_tab(1)
    assert tabs.currentWidget() is shown[0]
    reader.step_tab(-1)
    assert tabs.currentWidget() is shown[-1]
    for _ in shown:
        reader.step_tab(1)
        assert tabs.currentWidget() is not reader.figure_pane
