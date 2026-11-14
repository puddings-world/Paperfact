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

# What a real AI child prints and reads before it does any work.
HANDSHAKE = (
    "import sys\n"
    "from paper_daily.cli_job_protocol import hello_line, ready_line\n"
    "sys.stdout.write(hello_line(sys.argv[1]).decode('ascii')); sys.stdout.flush()\n"
    "sys.stdin.buffer.read()\n"
    "sys.stdout.write(ready_line(sys.argv[1]).decode('ascii')); sys.stdout.flush()\n"
)


def child(args, body):
    """The asked-for command and a stand-in process for it.

    An AI job is launched behind a private startup handshake; the stand-in answers
    it the way the real child does, then runs `body`.
    """
    if args and args[0] == "_desktop-job-v1":
        return list(args[2:]), [sys.executable, "-c", HANDSHAKE + body, args[1]]
    return list(args), [sys.executable, "-c", body]


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


def test_a_partial_result_offers_to_redo_only_what_failed(surface):
    window, hub, board, _ = surface
    redone = []
    handle = begin(window, "Analyse list", key="list", retry_failed=lambda: redone.append(1))
    handle.update(dict(stage="one paper failed", completed=1, total=2, outcome="partial"))
    hub.tick()
    handle.finish()
    assert hub.jobs[handle.token].state == "partial"
    assert board.step.text() == "重試未完成的" and board.result.isVisible()
    board.step.click()
    assert redone == [1]

    whole = begin(window, "Ask", key="whole")
    whole.update(dict(stage="half", outcome="partial"))
    hub.tick()
    whole.finish()
    # Work that cannot redo only its failed part offers nothing extra.
    assert not board.step.isVisible()


def test_retrying_a_list_analysis_asks_again_for_the_failed_steps(workspace, monkeypatch):
    import json

    from paper_daily import runtime, store, work_progress
    from paper_daily.desktop.main import MainWindow

    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('first','first','now')")
        conn.commit()
    event = work_progress.PREFIX + json.dumps(dict(stage="x", completed=1, total=2,
                                                    outcome="partial"))
    runs = []

    def command(*args):
        asked, process = child(args, f"print({event!r}, flush=True)")
        runs.append(asked)
        return process

    monkeypatch.setattr(runtime, "cli_command", command)
    window = MainWindow()
    window.show()
    try:
        window._open_list("first")
        page = window.queue_page
        page._start_ready(["analyze", "--list", "first", "--jobs", "1"])
        token = page._activity.token
        wait_for(lambda: page._job is None)
        hub = window.activity_hub
        hub.tick()
        assert hub.jobs[token].state == "partial"
        assert window.activity_board.step.text() == "重試未完成的"
        window.activity_board.step.click()
        assert runs[-1] == ["analyze", "--list", "first", "--jobs", "1", "--retry"]
        wait_for(lambda: page._job is None)
    finally:
        window.close()
        window.deleteLater()


def test_list_analysis_works_on_one_paper_at_a_time_unless_the_person_raises_it(
    workspace, monkeypatch
):
    from paper_daily import store
    from paper_daily.desktop.analysis_settings import PARALLEL_KEY, AnalysisSettings
    from paper_daily.desktop.main import MainWindow

    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('first','first','now')")
        conn.commit()
    window = MainWindow()
    started = []
    monkeypatch.setattr(type(window.queue_page), "_start",
                        lambda _self, args, then=None: started.append(args))
    try:
        window._open_list("first")
        window.queue_page._analyze_list()
        assert started[-1][-2:] == ["--jobs", "1"]

        dialog = AnalysisSettings(window, window.pal)
        assert dialog.parallel.value() == 1 and dialog.parallel.maximum() == 3
        dialog.parallel.setValue(3)
        dialog.accept()
        window.queue_page._analyze_list()
        assert started[-1][-2:] == ["--jobs", "3"]

        # A hand-edited or stale value can never ask for more than the cap.
        with store.connect() as conn:
            store.set_kv(conn, PARALLEL_KEY, 12)
            conn.commit()
        window.queue_page._analyze_list()
        assert started[-1][-2:] == ["--jobs", "3"]
    finally:
        window.close()
        window.deleteLater()


def test_long_ai_work_waits_its_turn_and_short_work_does_not(surface):
    window, hub, board, _ = surface
    started = []
    first = begin(window, "List analysis", key="first", queued=True)
    first.when_ready(lambda: started.append("first"))
    second = begin(window, "Deep analysis", key="second", queued=True)
    second.when_ready(lambda: started.append("second"))
    third = begin(window, "Survey", key="third", queued=True)
    third.when_ready(lambda: started.append("third"))
    quick = begin(window, "Ask", key="quick")
    assert started == ["first"]
    assert second.waiting and third.waiting and hub.jobs[quick.token].state == "running"
    assert "排隊中" in hub.jobs[second.token].stage
    assert "前面還有 2 個" in hub.jobs[third.token].stage

    # Leaving the line starts nothing; the one behind moves up.
    hub.selected = second.token
    hub.changed.emit()
    assert board.stop.isVisible() and board.stop.text() == "取消排隊"
    board.stop.click()
    assert hub.jobs[second.token].state == "cancelled"
    assert hub.jobs[second.token].stage == "已取消排隊"
    assert "等目前的分析結束" in hub.jobs[third.token].stage

    first.finish()
    wait_for(lambda: started == ["first", "third"])
    assert hub.jobs[third.token].state == "running" and not third.waiting
    third.finish()
    QTest.qWait(20)
    assert started == ["first", "third"]


def test_the_same_waiting_work_is_not_queued_twice(surface):
    window, hub, _board, _ = surface
    begin(window, "List analysis", key="busy", queued=True).when_ready(lambda: None)
    waiting = begin(window, "Deep analysis", key="paper", queued=True)
    again = begin(window, "Deep analysis", key="paper", queued=True)
    assert waiting.waiting and not again.accepted and again.token == waiting.token


def test_a_deep_analysis_asked_for_during_a_list_analysis_runs_after_it(workspace, monkeypatch):
    from paper_daily import runtime, store
    from paper_daily.desktop.main import MainWindow

    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('first','first','now')")
        conn.commit()
    runs = []

    def command(*args):
        code = "import time; time.sleep(30)" if "--list" in args else "print('done')"
        asked, process = child(args, code)
        runs.append(asked[0] if asked[0] != "analyze" or "--list" in asked else asked[1])
        return process

    monkeypatch.setattr(runtime, "cli_command", command)
    window = MainWindow()
    window.show()
    try:
        window._open_list("first")
        page = window.queue_page
        page._start_ready(["analyze", "--list", "first", "--jobs", "1"])
        listed = page._activity.token
        window._spawn_job(["analyze", "paper-1", "--retry"], "paper-1")
        hub = window.activity_hub
        assert runs == ["analyze"] and window.analysis_waiting("paper-1")
        assert not window.analysis_running()

        hub.cancel(listed)
        wait_for(lambda: page._job is None)
        wait_for(lambda: runs == ["analyze", "paper-1"])
        deep = next(j for j in hub.jobs.values() if j.key == "analysis:paper-1")
        wait_for(lambda: deep.state != "running" and (hub.tick() or True))
        assert hub.jobs[listed].state == "cancelled" and deep.state == "done"
    finally:
        window.close()
        window.deleteLater()


def test_a_survey_behind_a_list_analysis_says_it_is_waiting(workspace, monkeypatch):
    from paper_daily import runtime, store
    from paper_daily.desktop.main import MainWindow
    from paper_daily.desktop.survey_dialog import SurveyDialog

    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('x','Research','now')")
        conn.commit()
    monkeypatch.setattr(
        runtime, "cli_command", lambda *_: [sys.executable, "-c", "import time; time.sleep(30)"]
    )
    window = MainWindow()
    window.show()
    dialog = SurveyDialog("x", "Research", window.pal, window)
    try:
        window._open_list("x")
        window.queue_page._start_ready(["analyze", "--list", "x", "--jobs", "1"])
        dialog.show()
        dialog._run_ready()
        assert dialog.job is None and dialog.run_btn.text() == "排隊中…"
        assert "排入工作佇列" in dialog.status.text()
        assert window.queue_page.analyze_btn.text() == "停止分析"
        window.activity_hub.cancel(dialog._activity.token)
        assert dialog.run_btn.text() != "排隊中…" and dialog.job is None
    finally:
        window.activity_hub.cancel(window.queue_page._activity.token)
        wait_for(lambda: window.queue_page._job is None)
        dialog.close()
        window.close()
        window.deleteLater()


def _restart(hub_window):
    from PySide6.QtWidgets import QWidget

    from paper_daily import store
    from paper_daily.desktop import ui_state
    from paper_daily.desktop.activity import ActivityHub

    assert ui_state.flush()
    window = QWidget()
    window.pal = hub_window.pal
    hub = ActivityHub(window)
    with store.connect() as conn:
        return window, hub, hub.report_unfinished(conn)


def test_work_cut_off_by_a_crash_is_reported_once_on_the_next_start(surface):
    from paper_daily import store

    window, hub, _board, _ = surface
    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('x','Research','now')")
        conn.execute("INSERT INTO papers(id,venue,year,title,title_key,source) "
                     "VALUES ('p1','ICLR',2024,'Sparse Attention','sparse attention','test')")
        conn.commit()
    started = []
    begin(window, "清單分析", key="queue:x", queued=True).when_ready(lambda: started.append(1))
    begin(window, "深入分析", key="analysis:p1", paper_id="p1",
          queued=True).when_ready(lambda: started.append(2))
    begin(window, "Ask", key="ask")  # Short work is not worth reporting.

    # The process dies here: nothing finishes, the next start reads what was left.
    _later, after, notice = _restart(window)
    assert notice is not None and notice.state == "interrupted"
    assert "清單分析「Research」" in notice.stage and "深入分析「Sparse Attention」" in notice.stage
    assert "Ask" not in notice.stage
    assert after.selected == notice.token and not after.busy  # Nothing restarts by itself.

    # Seen once: a second start has nothing to say.
    _again, _hub, second = _restart(window)
    assert second is None


def test_work_that_ends_normally_leaves_nothing_to_report(surface):
    window, _hub, _board, _ = surface
    handle = begin(window, "清單分析", key="queue:x", queued=True)
    handle.when_ready(lambda: None)
    handle.finish(cancelled=True)
    _later, _after, notice = _restart(window)
    assert notice is None


def test_each_job_names_its_paper_or_list_and_goes_there(surface):
    from paper_daily import store

    window, hub, board, _ = surface
    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('x','Research','now')")
        conn.execute("INSERT INTO papers(id,venue,year,title,title_key,source) "
                     "VALUES ('p1','ICLR',2024,'Sparse Attention','sparse attention','test')")
        conn.commit()
    went = []
    window._open_list = lambda list_id: went.append(("list", list_id))
    window.open_anywhere = lambda paper_id: went.append(("paper", paper_id))

    begin(window, "清單分析", key="queue:x", queued=True).when_ready(lambda: None)
    deep = begin(window, "深入分析", key="analysis:p1", paper_id="p1", queued=True)
    deep.when_ready(lambda: None)
    assert "深入分析「Sparse Attention」" in board.text.text()
    assert board.go.isVisible()
    board.go.click()
    assert went == [("paper", "p1")]

    panel = JobPanel(hub, window.pal, board)
    panel.refresh()
    rows = [panel.rows.itemAt(i).widget() for i in range(panel.rows.count())]
    texts = [row.accessibleName() for row in rows]
    assert any("清單分析「Research」" in t for t in texts)
    list_row = next(r for r, t in zip(rows, texts, strict=True) if "Research" in t)
    next(b for b in list_row.findChildren(type(board.go)) if b.text() == "前往").click()
    assert went[-1] == ("list", "x")


def test_a_failure_offers_a_way_back_to_where_it_was_asked(surface):
    window, _hub, board, _ = surface
    shown = []
    handle = begin(window, "整理研究問題", key="questions", result=lambda: shown.append(1))
    handle.finish(False, reason="這篇論文還沒有 PDF")
    assert "這篇論文還沒有 PDF" in board.text.text()
    assert not board.result.isVisible() and board.go.isVisible()
    board.go.click()
    assert shown == [1]


def test_the_open_job_list_keeps_its_rows_while_only_the_clock_moves(surface):
    window, hub, board, _ = surface
    stops = []
    handle = begin(window, "Analyse", key="steady", cancel=lambda: stops.append(1))
    panel = JobPanel(hub, window.pal, board)
    panel.refresh()
    row = panel.rows.itemAt(0).widget()
    stop = next(b for b in row.findChildren(type(board.go)) if b.text() == "停止")

    hub.jobs[handle.token].started -= 75
    hub.changed.emit()
    panel.refresh()
    # The same row and the same button, so a press begun before the tick still lands.
    assert panel.rows.itemAt(0).widget() is row and "1:15" in row.accessibleName()
    stop.click()
    assert stops == [1]

    # What a row offers did change: it is rebuilt, and says so.
    panel.refresh()
    rebuilt = panel.rows.itemAt(panel.rows.count() - 1).widget()
    assert rebuilt is not row
    buttons = rebuilt.findChildren(type(board.go))
    assert not next(b for b in buttons if b.text() == "停止").isEnabled()
    handle.finish(cancelled=True)
    panel.refresh()
    last = panel.rows.itemAt(panel.rows.count() - 1).widget()
    assert "停止" not in [b.text() for b in last.findChildren(type(board.go))]
