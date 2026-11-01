"""The job tray: stop that really stops, failures that say what to do, an idle poll that sleeps."""

import sys
import threading

from PySide6.QtTest import QTest
from test_activity import surface as _surface
from test_activity import wait_for
from test_workspace_transfer_ui import workspace as _workspace

from paper_daily.desktop.activity import JobPanel, begin
from paper_daily.desktop.ask import AskRunner

workspace, surface = _workspace, _surface


def test_the_poll_sleeps_when_nothing_runs_and_wakes_for_new_work(surface):
    window, hub, _board, _ = surface
    handle = begin(window, "Analyse")
    assert hub._poll.isActive()
    handle.finish()
    hub.tick()
    assert not hub._poll.isActive()
    begin(window, "Again", key="again").finish()
    assert hub._poll.isActive()


def test_stop_is_offered_only_when_the_work_can_stop_and_says_it_is_stopping(surface):
    window, hub, board, _ = surface
    plain = begin(window, "Plain", key="plain")
    assert not board.stop.isVisible()
    plain.finish()

    stops = []
    handle = begin(window, "Analyse", key="stoppable", cancel=lambda: stops.append(1))
    assert board.stop.isVisible() and board.stop.isEnabled()
    board.stop.click()
    board.stop.click()
    # The work decides when it has ended; until then the notice says so, once.
    assert stops == [1] and "正在停止" in board.text.text() and not board.stop.isEnabled()
    handle.finish(cancelled=True)
    assert hub.jobs[handle.token].state == "cancelled" and "工作已停止" in board.text.text()
    assert not board.stop.isVisible()


def test_a_failure_names_its_cause_and_offers_one_next_step(surface):
    window, hub, board, _ = surface
    opened, retried = [], []
    window._ai_settings = lambda: opened.append(1)

    login = begin(window, "Ask", key="login")
    login.finish(False, reason="Claude CLI: please sign in again")
    assert "AI 登入過期" in board.text.text() and board.step.text() == "重新登入"
    assert not board.result.isVisible()
    board.step.click()
    assert opened == [1]

    limit = begin(window, "Ask", key="limit")
    limit.finish(False, reason="HTTP 429: rate limit exceeded")
    assert "額度" in board.text.text() and board.step.text() == "AI 帳號"

    policy = begin(window, "Ask", key="policy", retry=lambda: retried.append(1))
    policy.finish(False, reason="refused under the usage policy")
    # Asking again would be refused again, so nothing is offered.
    assert "內容政策" in board.text.text() and not board.step.isVisible()

    other = begin(window, "Ask", key="other", retry=lambda: retried.append(1))
    other.finish(False, reason="model returned unreadable JSON")
    assert "unreadable JSON" in board.text.text() and board.step.text() == "重試"
    board.step.click()
    assert retried == [1]

    silent = begin(window, "Ask", key="silent")
    silent.finish(False)
    assert "未完成" in board.text.text() and not board.step.isVisible()


def test_the_panel_lists_every_job_with_the_actions_it_really_has(surface):
    window, hub, board, _ = surface
    visited = []
    done = begin(window, "Export", key="done", result=lambda: visited.append("done"))
    done.finish()
    failed = begin(window, "Ask", key="failed", retry=lambda: None)
    failed.finish(False, reason="network down")
    running = begin(window, "Analyse", key="run", cancel=lambda: running.finish(cancelled=True))
    running.update(dict(stage="reading", completed=2, total=5))
    hub.tick()

    board.more.click()
    panel = board.panel
    assert isinstance(panel, JobPanel) and panel.isVisible()
    rows = [panel.rows.itemAt(i).widget() for i in range(panel.rows.count())]
    names = [row.accessibleName() for row in rows]
    assert names[0].startswith("進行中 · Analyse · 2/5 · reading")
    assert names[1].startswith("未完成 · Ask") and names[2].startswith("完成 · Export")
    buttons = [[b.text() for b in row.findChildren(type(board.stop))] for row in rows]
    assert buttons == [["停止"], ["重試"], ["查看結果"]]

    rows[0].findChildren(type(board.stop))[0].click()
    assert hub.jobs[running.token].state == "cancelled"
    rows = [panel.rows.itemAt(i).widget() for i in range(panel.rows.count())]
    rows[2].findChildren(type(board.stop))[0].click()
    assert visited == ["done"] and not panel.isVisible()


def test_a_failed_ai_answer_can_be_asked_again_from_the_notice(surface):
    window, hub, board, _ = surface
    runner = AskRunner(window)
    answers = iter([(None, "Claude CLI timed out"), ("second answer", "ok")])
    saved, errors = [], []
    gate = threading.Event()

    def call(_prompt):
        gate.wait(5)
        return next(answers)

    gate.set()
    runner.start("question", saved.append, errors.append, call=call)
    wait_for(lambda: not runner.busy)
    QTest.qWait(20)
    assert errors == ["Claude CLI timed out"]
    assert "AI 太久沒有回應" in board.text.text() and board.step.text() == "重試"
    board.step.click()
    wait_for(lambda: not runner.busy and saved)
    assert saved == ["second answer"]


def test_stopping_a_list_job_ends_the_process_and_is_not_a_failure(workspace, monkeypatch):
    from paper_daily import runtime, store
    from paper_daily.desktop.main import MainWindow

    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('first','first','now')")
        conn.commit()
    window = MainWindow()
    code = "import time; time.sleep(30)"
    monkeypatch.setattr(runtime, "cli_command", lambda *_: [sys.executable, "-c", code])
    window.show()
    try:
        window._open_list("first")
        window.queue_page._start_ready(["repdf", "fixture"])
        token = window.queue_page._activity.token
        assert window.activity_board.stop.isVisible()
        window.activity_hub.cancel(token)
        wait_for(lambda: window.queue_page._job is None)
        job = window.activity_hub.jobs[token]
        assert job.state == "cancelled" and window.activity_hub.next_step(job) is None
    finally:
        window.close()
        window.deleteLater()


def test_stopping_a_survey_keeps_the_previous_one(workspace, monkeypatch):
    from paper_daily import runtime, store
    from paper_daily.desktop.main import MainWindow
    from paper_daily.desktop.survey_dialog import SurveyDialog

    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('x','Research','now')")
        conn.commit()
    window = MainWindow()
    monkeypatch.setattr(
        runtime, "cli_command", lambda *_: [sys.executable, "-c", "import time; time.sleep(30)"]
    )
    dialog = SurveyDialog("x", "Research", window.pal, window)
    try:
        dialog.show()
        dialog._run_ready()
        token = dialog._activity.token
        window.activity_hub.cancel(token)
        wait_for(lambda: dialog.job is None)
        assert window.activity_hub.jobs[token].state == "cancelled"
        assert "已停止撰寫" in dialog.status.text()
    finally:
        dialog.close()
        window.close()
        window.deleteLater()
