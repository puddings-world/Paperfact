"""Progress, single flight and focus safety without paid model/network calls."""

import io
import json
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from test_presentation_pane import pane as _pane
from test_workspace_transfer_ui import workspace as _workspace

from paper_daily import work_progress
from paper_daily.desktop.activity import ActivityBoard, ActivityHub, begin, consume
from paper_daily.desktop.ask import AskRunner
from paper_daily.desktop.main import LIGHT

workspace = _workspace
pane = _pane


def wait_for(condition):
    for _ in range(500):
        QTest.qWait(10)
        if condition():
            return
    pytest.fail("fixture work did not finish")


@pytest.fixture
def surface(workspace):
    window = QWidget()
    window.pal = LIGHT
    window.active_list = "list-a"
    layout = QVBoxLayout(window)
    window.activity_hub = hub = ActivityHub(window)
    board = ActivityBoard(hub, QLabel("AI settings"), LIGHT)
    layout.addWidget(board)
    editor = QLineEdit()
    layout.addWidget(editor)
    window.resize(900, 180)
    window.show()
    window.activateWindow()
    QTest.qWait(10)
    yield window, hub, board, editor
    for job in list(hub.jobs.values()):
        hub.finish(job.token, cancelled=True)
    window.close()
    window.deleteLater()


def test_progress_is_explicit_local_metadata_and_observer_is_scoped(monkeypatch, capsys):
    monkeypatch.delenv("PAPERFACT_PROGRESS", raising=False)
    work_progress.report("preparing")
    assert capsys.readouterr().out == ""
    events = []
    with work_progress.observe(events.append):
        work_progress.report("reading", 1, 4, paper_id="fixture")
    assert events == [dict(stage="reading", completed=1, total=4, paper_id="fixture")]
    monkeypatch.setenv("PAPERFACT_PROGRESS", "1")
    work_progress.report("ready", outcome="partial")
    line = capsys.readouterr().out.strip()
    assert work_progress.parse(line) == dict(stage="ready", outcome="partial")
    assert len(events) == 1


@pytest.mark.parametrize("line", ["normal output", "@paperfact-progress {bad",
                                 "@paperfact-progress []", '@paperfact-progress {"stage": 3}'])
def test_unstructured_output_is_not_treated_as_progress(line):
    assert work_progress.parse(line) is None


def test_progress_frame_can_span_multiple_pipe_reads(surface):
    window, hub, board, _ = surface
    handle = begin(window, "Analyse")
    line = work_progress.PREFIX + json.dumps(dict(stage="extracting", completed=1, total=4))
    pending = consume(handle, line[:15])
    assert consume(handle, line[15:] + "\n", pending) == ""
    hub.tick()
    assert "extracting" in board.text.text()
    assert board.bar.value() == 25


def test_notice_is_immediate_single_flight_and_retry_is_new_job(surface):
    window, hub, board, _ = surface
    first = begin(window, "Analyse", key="paper:x")
    assert hub.busy and "Analyse" in board.text.text()
    assert board.bar.maximum() == 0
    for _ in range(30):
        repeated = begin(window, "Analyse", key="paper:x")
        assert not repeated.accepted and repeated.token == first.token
    assert len(hub.jobs) == 1
    first.finish(False)
    assert not hub.busy and "未完成" in board.text.text()
    retried = begin(window, "Analyse", key="paper:x")
    assert retried.accepted and retried.token != first.token


def test_elapsed_wait_is_dynamic_but_does_not_invent_a_percentage(surface):
    window, hub, board, _ = surface
    handle = begin(window, "Analyse")
    hub.jobs[handle.token].started = time.monotonic() - 62
    hub.tick()
    assert "1:02" in board.text.text()
    assert board.bar.maximum() == 0
    handle.update(dict(stage="checking", completed=2, total=5))
    hub.tick()
    assert board.bar.value() == 40
    handle.finish()
    assert "內容已更新" in board.text.text() and board.bar.value() == 100
    handle.stage("stale event")
    hub.tick()
    assert "stale" not in board.text.text()


def test_progress_counts_are_scoped_to_paper_and_partial_is_not_success(surface):
    window, hub, board, _ = surface
    handle = begin(window, "Analyse", paper_id="a")
    handle.update(dict(stage="checking", paper_id="b", completed=4, total=5))
    hub.tick()
    assert board.bar.maximum() == 0
    handle.update(dict(stage="checking", paper_id="a", completed=3, total=5))
    handle.update(dict(stage="unavailable source", outcome="partial"))
    handle.finish()
    assert hub.jobs[handle.token].state == "partial"
    assert board.bar.value() == 60 and "部分完成" in board.text.text()


@pytest.mark.parametrize("done,total", [(True, 4), (-1, 4), (5, 4), (0, 0), (1, None)])
def test_invalid_counts_remain_indeterminate(surface, done, total):
    window, hub, board, _ = surface
    handle = begin(window, "Analyse")
    handle.update(dict(stage="checking", completed=done, total=total))
    hub.tick()
    assert board.bar.maximum() == 0


def test_focus_moves_from_launch_button_to_notice_then_result(surface):
    window, hub, board, editor = surface
    button = QPushButton("Generate", window)
    window.layout().addWidget(button)
    button.setFocus()
    handle = begin(window, "Analyse", result=editor.setFocus)
    assert QApplication.focusWidget() is board
    handle.finish()
    QTest.qWait(20)
    assert QApplication.focusWidget() is editor


@pytest.mark.parametrize("change", ["typing", "list", "paper", "new-job"])
def test_completion_does_not_steal_focus_after_interaction_or_navigation(surface, change):
    window, hub, board, editor = surface
    visited = []
    handle = begin(window, "Analyse", result=lambda: visited.append("result"))
    if change == "typing":
        editor.setFocus()
        QTest.keyClicks(editor, "notes")
    elif change == "list":
        window.active_list = "list-b"
    elif change == "paper":
        window.reader_page = SimpleNamespace(paper=SimpleNamespace(id="other"))
    else:
        other = begin(window, "Other", key="other")
    handle.finish()
    QTest.qWait(20)
    assert not visited
    if change == "new-job":
        other.finish(cancelled=True)
    hub.selected = handle.token
    hub.changed.emit()
    board.result.click()
    assert visited == ["result"]


def test_modal_has_one_live_notice_and_destroyed_owner_is_safe(surface):
    window, hub, _board, _ = surface
    modal = QDialog(window)
    QVBoxLayout(modal)
    visited = []
    first = begin(modal, "Export", key="export", result=lambda: visited.append("result"))
    assert hasattr(modal, "_activity_board")
    assert len(modal.findChildren(ActivityBoard)) == 1
    assert not begin(modal, "Export", key="export").accepted
    modal.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    first.finish()
    QTest.qWait(20)
    assert not visited


def test_popen_completion_drains_last_partial_event_before_rendering(surface):
    window, hub, board, _ = surface
    handle = begin(window, "Analyse")
    process = SimpleNamespace(stdout=io.StringIO(
        work_progress.PREFIX + json.dumps(dict(stage="missing source", outcome="partial")) + "\n"
    ), poll=lambda: 0)
    hub.watch_popen(handle, process)
    wait_for(lambda: getattr(process, "_paperfact_output_done", False))
    hub.tick()
    assert "部分完成" in board.text.text() and not hub.busy


@pytest.mark.parametrize("fails", [False, True])
def test_real_worker_stages_and_result_are_visible_under_click_flood(surface, fails):
    window, hub, board, _ = surface
    runner = AskRunner(window)
    release = threading.Event()
    calls, saved, errors = [], [], []

    def call(prompt):
        calls.append(prompt)
        work_progress.report("fixture extraction")
        assert release.wait(5)
        return (None, "fixture failure") if fails else ("fixture content", "ok")

    try:
        for _ in range(30):
            runner.start("fixture", saved.append, errors.append, call=call, task="slides")
        wait_for(lambda: "fixture extraction" in board.text.text())
        assert len(calls) == 1 and hub.busy
    finally:
        release.set()
        wait_for(lambda: not runner.busy)
        QTest.qWait(20)
    assert not hub.busy
    assert saved == ([] if fails else ["fixture content"])
    assert errors == (["fixture failure"] if fails else [])
    assert ("未完成" if fails else "內容已更新") in board.text.text()
    runner.start("retry", saved.append, errors.append, call=lambda _: ("retry saved", "ok"))
    wait_for(lambda: not runner.busy)
    assert saved[-1] == "retry saved"


def test_window_close_waits_for_active_work_and_can_close_after_completion(workspace):
    from paper_daily.desktop.main import MainWindow

    window = MainWindow()
    window.show()
    handle = begin(window.reader_page, "Analyse")
    assert window.close() is False
    assert window.isVisible() and window.activity_hub.busy
    handle.finish()
    QTest.qWait(20)
    assert window.close() is True
    window.deleteLater()


def test_survey_reopen_cannot_launch_duplicate_process(workspace, monkeypatch):
    import sys

    from paper_daily import runtime, store
    from paper_daily.desktop.main import MainWindow
    from paper_daily.desktop.survey_dialog import SurveyDialog

    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('x','Research','now')")
        conn.commit()
    window = MainWindow()
    gate = workspace[1] / "finish"
    code = ("import pathlib,time; p=pathlib.Path(" + repr(str(gate)) + "); "
            "exec('while not p.exists(): time.sleep(0.01)')")
    monkeypatch.setattr(runtime, "cli_command", lambda *args: [sys.executable, "-c", code])
    first = SurveyDialog("x", "Research", window.pal, window)
    second = SurveyDialog("x", "Research", window.pal, window)
    try:
        first._run_ready()
        first.close()
        for _ in range(30):
            second._run_ready()
        assert second.job is None and "正在撰寫" in second.status.text()
        assert sum(j.state == "running" for j in window.activity_hub.jobs.values()) == 1
    finally:
        gate.touch()
        wait_for(lambda: first.job is None)
        first.close()
        second.close()
        window.close()
        window.deleteLater()


def test_batch_reports_real_counts_and_partial_failure(workspace, monkeypatch):
    from paper_daily import analyze, store

    with store.connect() as conn:
        for pid in ("a", "b", "c"):
            conn.execute("INSERT INTO papers(id,title,title_key,venue,year,source) "
                         "VALUES (?,?,'synthetic',?,2020,?)",
                         (pid, "Synthetic paper", "fixture", "https://example.org"))
        conn.commit()
    monkeypatch.setattr(analyze, "pending", lambda *a: ["a", "b", "c"])

    def analyze_fixture(pid, *_):
        if pid == "c":
            raise ValueError("fixture")
        return dict(pdf=True, dive=pid == "a")

    monkeypatch.setattr(analyze, "analyse", analyze_fixture)
    events = []
    with work_progress.observe(events.append):
        assert analyze.analyse_many(["a", "b", "c"], log=lambda _: None) == 1
    assert [(e["completed"], e["total"]) for e in events] == [(0, 3), (1, 3), (2, 3), (3, 3)]
    assert sum(e.get("outcome") == "partial" for e in events) == 2


@pytest.mark.parametrize("fail", [False, True])
def test_pdf_export_progress_and_duplicate_click_preserve_output(surface, pane, fail):
    import pymupdf

    window, hub, board, _ = surface
    widget, deck, _app, root = pane
    widget.setParent(window)
    target = root / "slides.pdf"
    if fail:
        target = root / "missing-directory" / "slides.pdf"
    widget._export_pdf(target)
    if not fail:
        first = widget._pdf_job
        for _ in range(30):
            widget._export_pdf(root / "duplicate.pdf")
            assert widget._pdf_job is first
        wait_for(lambda: widget._pdf_job is None)
        hub.tick()
        with pymupdf.open(target) as document:
            assert len(document) == len(deck.slides)
        assert not (root / "duplicate.pdf").exists()
        assert board.bar.value() == 100
        assert "PDF 已匯出" in board.text.text()
    else:
        assert widget._pdf_job is None and not target.exists()
        assert "PDF 未匯出" in board.text.text()
    assert not hub.busy


def test_cancel_does_not_navigate_and_history_can_show_done_while_other_job_runs(surface):
    window, hub, board, _ = surface
    visited = []
    first = begin(window, "First", key="first", result=lambda: visited.append("first"))
    first.finish(cancelled=True)
    QTest.qWait(10)
    assert not visited
    second = begin(window, "Second", key="second")
    board._select(first.token)
    assert "工作已停止" in board.text.text()
    assert board.result.isVisible() and hub.busy
    second.finish()


def test_completed_queue_job_can_return_to_original_list(workspace, monkeypatch):
    import sys

    from paper_daily import runtime, store
    from paper_daily.desktop.main import MainWindow

    with store.connect() as conn:
        for list_id in ("first", "other"):
            conn.execute("INSERT INTO lists(id,name,created_at) VALUES (?,?,'now')",
                         (list_id, list_id))
        conn.commit()
    window = MainWindow()
    monkeypatch.setattr(runtime, "cli_command", lambda *_: [sys.executable, "-c", "pass"])
    window.show()
    try:
        window._open_list("first")
        window.queue_page._start_ready(["repdf", "fixture"])
        token = window.queue_page._activity.token
        window._open_list("other")
        wait_for(lambda: window.queue_page._job is None)
        QTest.qWait(20)
        assert window.active_list == "other"
        window.activity_hub.goto(token)
        assert window.active_list == "first"
        assert window.stack.currentWidget() is window.queue_page
    finally:
        window.close()
        window.deleteLater()

