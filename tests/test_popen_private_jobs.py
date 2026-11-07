"""Real disposable children, no provider calls or research data."""
import json
import os
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QWidget
from test_cites_views import pane as cites_surface_fixture
from test_reader_chat import reader as reader_fixture
from test_research_chat import legacy as legacy_fixture

from paper_daily import llm, runtime
from paper_daily.desktop.activity import ActivityHub, begin

legacy = legacy_fixture
reader = reader_fixture
cites_surface = cites_surface_fixture


def settle(app, predicate, seconds=None):
    from paper_daily.desktop.popen_job import STARTUP_SECONDS
    seconds = STARTUP_SECONDS + 7 if seconds is None else seconds
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return
        time.sleep(.002)
    pytest.fail("synthetic child did not drain")


def test_main_zero_exit_without_ready_is_error_and_preserves_draft(reader, monkeypatch):
    app, window, view = reader
    before = view.ask_box.text()
    monkeypatch.setattr(runtime, "cli_command", lambda *_: [sys.executable, "-c", "pass"])
    window._spawn_job(["analyze", "local-paper"], "local-paper")
    token = window._analysis_activity.token
    settle(app, lambda: (window.activity_hub.tick() or
                        window.activity_hub.jobs[token].state != "running"))
    assert window.activity_hub.jobs[token].state == "error"
    assert view.ask_box.text() == before


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    llm.save_settings(profile="chosen", backend="openai", model="before",
                      api_key="synthetic-key", isolated=True)
    llm.use_profile("chosen", desktop=True)
    return llm.capture_connections()


def bootstrap_code(task="dive", gate=None):
    # Actual bootstrap validates the frame then calls our non-provider CLI stub.
    hold = ("import pathlib,time; gate=pathlib.Path(" + repr(str(gate)) + "); "
            "exec('while not gate.exists(): time.sleep(.005)'); " if gate else "")
    return hold + """
import sys,types
from concurrent.futures import ThreadPoolExecutor
from paper_daily import integration_entry
def run(command):
    from paper_daily import llm,work_progress
    def nested(_):
        with llm.connection_scope(llm.capture_connections()):
            return llm.settings(TASK).model
    with ThreadPoolExecutor(max_workers=2) as pool:
        models=list(pool.map(nested, range(2)))
    assert models[0]==models[1]
    work_progress.report(models[0],1,1)
    return 0
sys.modules['paper_daily.cli']=types.SimpleNamespace(main=run)
raise SystemExit(integration_entry.main(sys.argv[1:]))
""".replace("TASK", repr(task))


def launch_code(monkeypatch, command, code, *, executable=None, **options):
    from paper_daily.desktop import popen_job
    monkeypatch.setattr(runtime, "cli_command",
                        lambda *args: [executable or sys.executable, "-c", code, *args])
    # A base interpreter outside the venv cannot import the editable package.
    source = str(Path(__file__).resolve().parents[1] / "src")
    path = os.pathsep.join(filter(None, (source, os.environ.get("PYTHONPATH"))))
    env = dict(os.environ, PAPERFACT_PROGRESS="1", PYTHONUNBUFFERED="1",
               PYTHONIOENCODING="utf-8", PYTHONPATH=path)
    return popen_job.launch(command, env=env, **options)


def observe(app, process):
    window = QWidget()
    window.activity_hub = hub = ActivityHub(window)
    handle = begin(window, "Synthetic child", key="same-job")
    hub.watch_popen(handle, process)
    return window, hub, handle


def drained(app, hub, handle):
    settle(app, lambda: (hub.tick() or hub.jobs[handle.token].state != "running"))
    return hub.jobs[handle.token]


def test_real_bootstrap_pins_original_routes_and_pool_after_profile_switch(
        app, configured, monkeypatch, tmp_path):
    gate = tmp_path / "child-start"
    with llm.connection_scope(configured):
        process = launch_code(monkeypatch, ["analyze", "paper", "--retry"],
                              bootstrap_code(gate=gate))
    window, hub, handle = observe(app, process)
    llm.save_settings(profile="chosen", model="after", api_key="different-synthetic-key")
    assert "synthetic-key" not in repr(process.args)
    gate.touch()
    job = drained(app, hub, handle)
    assert job.state == "done" and "before" in job.history
    assert "after" not in job.history
    assert process.wait(timeout=1) == 0 and process.stdin.closed and process.stdout.closed
    assert not process._paperfact_ai_handoff._frame
    assert process._paperfact_ai_handoff.done
    window.close()


@pytest.mark.parametrize("code", ["pass", "print('ordinary output')",
    "import sys;print('@paperfact-ai-job 1 hello '+('b'*32),flush=True)",
    "print('x'*129,flush=True)",
    "import time;time.sleep(20)",
    "import sys,time;print('@paperfact-ai-job 1 hello '+sys.argv[2],flush=True);time.sleep(20)",
    "import sys;print('@paperfact-ai-job 1 hello '+sys.argv[2],flush=True)",
    "import sys;print('@paperfact-ai-job 1 ready '+sys.argv[2],flush=True)"])
def test_startup_failure_timeout_and_zero_exit_never_succeed(app, configured, monkeypatch, code):
    process = launch_code(monkeypatch, ["analyze", "paper"], code, timeout=.25)
    window, hub, handle = observe(app, process)
    job = drained(app, hub, handle)
    assert job.state != "done"
    assert process.poll() is not None and process.stdin.closed and process.stdout.closed
    assert not process._paperfact_ai_handoff._frame
    assert process._paperfact_ai_handoff.failed and process._paperfact_ai_handoff.done
    assert not process._paperfact_ai_handoff._timer.is_alive()
    window.close()


def test_cancel_held_startup_drains_no_late_progress_then_retry(
        app, configured, monkeypatch, tmp_path):
    gate = tmp_path / "never"
    process = launch_code(monkeypatch, ["analyze", "paper"], bootstrap_code(gate=gate))
    window, hub, handle = observe(app, process)
    hub.watch_popen(handle, process)
    assert not begin(window, "again", key="same-job").accepted
    process.terminate()
    handle.finish(cancelled=True)
    settle(app, lambda: getattr(process, "_paperfact_output_done", False))
    gate.touch()
    hub.tick()
    assert process.poll() is not None
    assert not process._paperfact_ai_handoff._timer.is_alive()
    assert hub.jobs[handle.token].state == "cancelled"
    retry = launch_code(monkeypatch, ["analyze", "paper"], bootstrap_code())
    new = begin(window, "retry", key="same-job")
    hub.watch_popen(new, retry)
    assert drained(app, hub, new).state == "done"
    assert "before" not in hub.jobs[handle.token].history
    window.close()


def test_non_ai_launch_preserves_argv_environment_and_ordinary_stdin(monkeypatch):
    from paper_daily.desktop import popen_job
    seen = []
    monkeypatch.setattr(llm, "freeze_connections", lambda *_: pytest.fail("non-AI read config"))
    monkeypatch.setattr(runtime, "cli_command", lambda *a: ["fixture", *a])
    value = object()
    result = popen_job.launch(["cite-links", "paper"],
        popen=lambda args, **kw: seen.append((args, kw)) or value, env={"ordinary": "yes"})
    assert result is value
    assert seen == [(["fixture", "cite-links", "paper"], {"env": {"ordinary": "yes"}})]


@pytest.mark.parametrize("text,expected", [("Short title",False),("x"*160,False),
    ("x"*161,True),("Title\nSecond line",True),("REFERENCES\nShort title",False),
    ("2608.17522",False),("https://arxiv.org/abs/2608.17522v2",False),("",False)])
def test_list_append_ai_decision_matches_actual_shared_predicate(text, expected):
    from paper_daily import lists
    from paper_daily.desktop.popen_job import command_tasks
    assert lists.needs_ai_parse(text) is expected
    assert command_tasks(["list-add","target",text,"--doi","10.synthetic/test"]) == (
        ("list_parse",) if expected else ())


@pytest.mark.parametrize("command,tasks", [(["cites","p"],("citations",)),
    (["followups","p"],("followups","overview")),
    (["followups","p","--with-cites"],("followups","overview","citations")),
    (["dive-ahead","2"],("dive",))])
def test_only_actual_nested_tasks_declared(command, tasks):
    from paper_daily.desktop.popen_job import command_tasks
    assert command_tasks(command) == tasks


@pytest.mark.parametrize("command,task", [( ["cites","p"],"citations"),
    (["followups","p","--with-cites"],"overview"),
    (["list-add","target","Long title "*20],"list_parse")])
def test_cites_launch_uses_real_private_bootstrap_for_ai(
        app, configured, monkeypatch, tmp_path, command, task):
    from paper_daily.desktop import cites_pane
    gate = tmp_path / "start"
    monkeypatch.setattr(runtime, "cli_command", lambda *a: [sys.executable,"-c",
                       bootstrap_code(task, gate),*a])
    with llm.connection_scope(configured):
        process = cites_pane._spawn(*command)
    llm.save_settings(profile="chosen", model="after")
    gate.touch()
    settle(app, lambda: getattr(process,"_paperfact_output_done",False))
    assert process.wait(timeout=1) == 0
    handoff = process._paperfact_ai_handoff
    assert handoff.ready and not handoff.failed and handoff.done
    assert not handoff._frame and process.stdin.closed


def test_failed_popen_releases_private_payload_and_does_not_retry(configured, monkeypatch):
    from paper_daily.desktop import popen_job
    calls=[]
    def fail(*a, **k):
        calls.append(1)
        raise OSError("synthetic startup")
    with pytest.raises(OSError):
        popen_job.launch(["analyze","p"],popen=fail)
    assert calls == [1]


def test_main_launch_pinned_before_held_child_duplicates_and_navigation(
        reader, configured, monkeypatch, tmp_path):
    app, window, view = reader
    gate = tmp_path / "release"
    monkeypatch.setattr(runtime,"cli_command",lambda *a:[sys.executable,"-c",
                       bootstrap_code(gate=gate),*a])
    seen=[]
    monkeypatch.setattr(window,"open_anywhere",lambda pid:seen.append(pid))
    with llm.connection_scope(configured):
        window._spawn_job(["analyze","local-paper"],"local-paper")
    original=window._dive_job
    token=window._analysis_activity.token
    for _ in range(30):
        window._spawn_job(["analyze","local-paper"],"local-paper")
    assert window._dive_job is original
    # The input and navigation remain usable during the actual pipe wait.
    view.ask_box.setText("Unsent draft for next paper")
    view.paper = type("Paper",(),{"id":"another-paper"})()
    llm.save_settings(profile="chosen",model="after")
    app.processEvents()
    assert original.poll() is None
    gate.touch()
    settle(app,lambda:(window.activity_hub.tick() or
                      window.activity_hub.jobs[token].state != "running"))
    assert window.activity_hub.jobs[token].state == "done"
    assert "before" in window.activity_hub.jobs[token].history
    assert view.ask_box.text() == "Unsent draft for next paper"
    assert not seen


def test_actual_list_append_branch_uses_shared_parse_predicate(tmp_path, monkeypatch):
    from paper_daily import lists, store
    monkeypatch.setattr(store,"DB_PATH",tmp_path/"papers.db")
    store.init_db()
    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('target','Target','now')")
    parsed=[]
    monkeypatch.setattr(lists,"parse_bibliography",lambda text,log:parsed.append(text) or
        [{"title":"Parsed title","authors":[],"venue":"","year":0}])
    monkeypatch.setattr(lists,"_store_entry",lambda *a,**k:("saved",True,"added"))
    assert lists.add_paper("target","Short title")["added"] == 1
    assert parsed == []
    long="Long source title "*20
    assert lists.add_paper("target",long,doi="10.synthetic/test")["added"] == 1
    assert parsed == [long.strip()]


def test_pipe_write_runs_off_gui_and_partial_binary_writes_complete(
        app, configured, monkeypatch):
    import threading

    from paper_daily.cli_job_protocol import decode_frame
    from paper_daily.desktop import popen_job
    writes=[]
    process=launch_code(monkeypatch,["analyze","paper"],bootstrap_code())
    original=process.stdin
    received=bytearray()
    class Binary:
        def write(self,data):
            writes.append(threading.get_ident())
            count=original.buffer.write(data[:7])
            received.extend(data[:count])
            return count
        def flush(self):
            original.buffer.flush()
    class Input:
        buffer=Binary()
        @property
        def closed(self):
            return original.closed
        def close(self):
            original.close()
    process.stdin=Input()
    window,hub,handle=observe(app,process)
    assert drained(app,hub,handle).state == "done"
    assert writes and set(writes) != {threading.get_ident()}
    assert threading.get_ident() not in writes
    bound=decode_frame(bytes(received),expected_request_id=process.args[-3],
                       expected_command=["analyze","paper"])
    assert bound.routes.settings("dive").api_key == "synthetic-key"
    assert "synthetic-key" not in repr(process._paperfact_ai_handoff)
    assert popen_job.FAILURE not in hub.jobs[handle.token].history
    window.close()


def test_private_job_keeps_task_override_and_account_context(
        app, configured, monkeypatch, tmp_path):
    llm.save_settings(profile="override",backend="openai",model="special",isolated=True,
                      api_key="synthetic-override")
    llm.save_task_choices({"overview":(llm.settings(profile="override"), "special")})
    before=llm.capture_configured_connections()
    gate=tmp_path/"start"
    with llm.connection_scope(before):
        process=launch_code(monkeypatch,["followups","paper"],bootstrap_code("overview",gate))
    window,hub,handle=observe(app,process)
    llm.save_task_choices({"overview":(llm.settings(profile="chosen"), None)})
    gate.touch()
    job=drained(app,hub,handle)
    assert job.state == "done" and "special" in job.history
    window.close()


_OBSERVATIONS = []


@pytest.fixture(autouse=True)
def owned_children(monkeypatch, request):
    from paper_daily.desktop import popen_job
    processes=[]
    original=popen_job.launch
    def launch(*args,**kwargs):
        process=original(*args,**kwargs)
        if hasattr(process,"_paperfact_ai_handoff"):
            processes.append(process)
        return process
    monkeypatch.setattr(popen_job,"launch",launch)
    yield
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        if not getattr(process,"_paperfact_reader_started",False):
            popen_job.watch_detached(process)
        app=QApplication.instance()
        settle(app,lambda process=process:getattr(process,"_paperfact_output_done",False),seconds=7)
        proof=process._paperfact_ai_handoff
        start=proof.milestones["started"]
        _OBSERVATIONS.append({"case":request.node.name.split("[",1)[0],
            "pid":process.pid,"phase":proof.phase,"ready":proof.ready,
            "failed":proof.failed,"done":proof.done,"returncode":process.poll(),
            "reader_done":process._paperfact_output_done,
            "watchdog_alive":proof._timer.is_alive(),
            "milestones_seconds":{key:round(value-start,3)
                                  for key,value in proof.milestones.items()}})
        assert proof.done and not proof._frame and not proof._timer.is_alive()
    target=Path(__file__).resolve().parents[1]/"build"/"popen-observations.json"
    target.write_text(json.dumps(_OBSERVATIONS,indent=2),encoding="utf-8")


def test_cites_repeated_clicks_and_close_pending_keep_one_original_job(
        app,cites_surface,configured,monkeypatch,tmp_path):
    from paper_daily.desktop import ai_access
    monkeypatch.setattr(ai_access,"_bridge",None)
    gate=tmp_path/"release-cites"
    monkeypatch.setattr(runtime,"cli_command",lambda *a:[sys.executable,"-c",
                       bootstrap_code("citations",gate),*a])
    with llm.connection_scope(configured):
        cites_surface._run_cites()
        first=cites_surface._cites_job
        for _ in range(30):
            cites_surface._run_cites()
    assert cites_surface._cites_job is first and first.poll() is None
    cites_surface.close()
    llm.save_settings(profile="chosen",model="after")
    gate.touch()
    settle(app,lambda:getattr(first,"_paperfact_output_done",False))
    assert first.poll() == 0 and first._paperfact_ai_handoff.ready
    assert cites_surface._closed


def test_stdout_eof_is_not_native_completion(app,configured,monkeypatch,tmp_path):
    gate=tmp_path/"native-exit"
    # Direct native interpreter: a venv redirector may keep its inherited pipe
    # open independently of the test child's fd1/2. This stdlib-only child uses
    # the actual closed protocol without importing a provider or executing CLI.
    code = native_eof_code(gate)
    process=launch_code(monkeypatch,["analyze","paper"],code,
                        executable=sys._base_executable)
    window,hub,handle=observe(app,process)
    settle(app,lambda:process._paperfact_ai_handoff.ready and process.stdout.closed)
    assert process.poll() is None
    assert not getattr(process,"_paperfact_output_done",False)
    assert not process._paperfact_ai_handoff.done
    assert hub.jobs[handle.token].state == "running"
    gate.touch()
    assert drained(app,hub,handle).state == "done"
    window.close()


def native_eof_code(gate):
    return """
import sys,os,pathlib,time
from paper_daily.cli_job_protocol import hello_line,read_frame,ready_line
request=sys.argv[2]
sys.stdout.write(hello_line(request).decode());sys.stdout.flush()
read_frame(sys.stdin.buffer,expected_request_id=request,expected_command=sys.argv[3:])
sys.stdout.write(ready_line(request).decode());sys.stdout.flush()
os.close(1);os.close(2)
gate=pathlib.Path(GATE)
while not gate.exists():time.sleep(.005)
os._exit(0)
""".replace("GATE",repr(str(gate)))


def test_cancel_after_stdout_eof_reaps_actual_native_child(
        app,configured,monkeypatch,tmp_path):
    gate=tmp_path/"native-exit-cancel"
    process=launch_code(monkeypatch,["analyze","paper"],native_eof_code(gate),
                        executable=sys._base_executable)
    window,hub,handle=observe(app,process)
    settle(app,lambda:process._paperfact_ai_handoff.ready and process.stdout.closed)
    assert process.poll() is None and not process._paperfact_ai_handoff.done
    process.terminate()
    handle.finish(cancelled=True)
    settle(app,lambda:getattr(process,"_paperfact_output_done",False))
    assert process.poll() is not None and process._paperfact_ai_handoff.done
    assert hub.jobs[handle.token].state == "cancelled"
    window.close()


@pytest.mark.parametrize("already_cancelled",[False,True])
def test_private_startup_negative_kill_is_error_but_user_cancel_is_retained(
        app,already_cancelled):
    from types import SimpleNamespace
    window=QWidget()
    window.activity_hub=hub=ActivityHub(window)
    handle=begin(window,"Synthetic startup")
    process=SimpleNamespace(poll=lambda:-9,_paperfact_output_done=True,
        _paperfact_ai_handoff=SimpleNamespace(failed=True,effective_code=lambda code:2))
    hub._processes[handle.token]=process
    if already_cancelled:
        handle.finish(cancelled=True)
    hub.tick()
    assert hub.jobs[handle.token].state == ("cancelled" if already_cancelled else "error")
    assert not hub._processes
    window.close()
