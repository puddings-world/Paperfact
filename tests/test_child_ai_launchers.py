"""AI and non-AI list child launchers retain routes, workspace and process ownership."""
from pathlib import Path

import pytest
from PySide6.QtCore import QProcess
from shiboken6 import isValid
from test_workspace_transfer_ui import workspace as _workspace

from paper_daily import llm, runtime, store
from paper_daily.cli_job_protocol import decode_frame, hello_line, ready_line
from paper_daily.desktop import add_dialog, queue_view
from paper_daily.desktop.main import MainWindow

workspace = _workspace


@pytest.fixture
def scene(workspace, monkeypatch):
    app, root = workspace
    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('list','Research','now')")
    llm.save_settings(profile="selected", backend="openai", model="before-model",
                      isolated=True, api_key="synthetic-private-key")
    llm.use_profile("selected", desktop=True)
    calls = []
    class Process(QProcess):
        def start(self, program, arguments):
            self.arguments = list(arguments)
            self.sent, self.reply = bytearray(), b""
            calls.append((self, program, self.arguments))

        def write(self, data):
            self.sent.extend(data)
            return len(data)

        def closeWriteChannel(self):
            pass

        def readAllStandardOutput(self):
            raw, self.reply = getattr(self, "reply", b""), b""
            return raw

        def peer_ready(self):
            identity = self.arguments[1]
            for line in (hello_line(identity), ready_line(identity)):
                self.reply = line
                self.readyReadStandardOutput.emit()
            return decode_frame(bytes(self.sent), expected_request_id=identity,
                                expected_command=self.arguments[2:])
    monkeypatch.setattr(add_dialog, "QProcess", Process)
    monkeypatch.setattr(queue_view, "QProcess", Process)
    monkeypatch.setattr(runtime, "cli_command", lambda *args: ["fixture", *args])
    window = MainWindow()
    window.active_list = "list"
    added = add_dialog.AddToListDialog(window.pal, "list", "Research", root, window)
    added.body.setPlainText("A deliberately complete synthetic paper reference")
    yield app, root, window, added, calls
    for process, _program, _args in calls:
        if isValid(process):
            process.errorOccurred.emit(QProcess.ProcessError.FailedToStart)
    added.close()
    window.close()
    window.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("feature", ["add", "queue"])
def test_old_process_signals_cannot_finish_new_attempt(scene, feature):
    _app, _root, window, added, calls = scene
    widget = added if feature == "add" else window.queue_page
    start = widget._start_ready if feature == "add" else lambda: widget._start_ready(
        ["analyze", "--list", "list"])
    pending = (lambda: widget.process) if feature == "add" else lambda: widget._job
    start()
    first = pending()
    first.errorOccurred.emit(QProcess.ProcessError.FailedToStart)
    assert pending() is None
    start()
    second = pending()
    assert second is not None and second is not first
    first.finished.emit(0, QProcess.ExitStatus.NormalExit)
    first.errorOccurred.emit(QProcess.ProcessError.FailedToStart)
    assert pending() is second
    assert len(calls) == 2
    if feature == "add":
        assert not widget.go.isEnabled() and widget._temp.exists()
        assert widget.body.toPlainText() == "A deliberately complete synthetic paper reference"
    else:
        assert widget._activity.token in window.activity_hub.jobs
        assert window.activity_hub.jobs[widget._activity.token].state == "running"


@pytest.mark.parametrize("feature", ["add", "queue"])
def test_ai_child_keeps_original_route_and_exact_workspace(scene, feature):
    _app, root, window, added, calls = scene
    captured = llm.capture_connections()
    llm.save_settings(profile="selected", model="later-model", api_key="replacement-key")
    with llm.connection_scope(captured):
        for _ in range(20):
            if feature == "add":
                added._start_ready()
            else:
                window.queue_page._start_ready(["analyze", "--list", "list"])
    assert len(calls) == 1
    process, program, argv = calls[0]
    assert program == "fixture" and argv[0] == "_desktop-job-v1"
    bound = decode_frame(process._ai_job_handoff._frame, expected_request_id=argv[1],
                         expected_command=argv[2:])
    cfg = bound.routes.settings("list_parse" if feature == "add" else "dive")
    assert cfg.model == "before-model" and cfg.api_key == "synthetic-private-key"
    assert process.processEnvironment().value("PAPERFACT_DATA") == str(root)
    assert "synthetic-private-key" not in " ".join(argv)
    if feature == "add":
        assert argv[2:5] == ["list-add", "list", "--file"]
        assert Path(argv[5]).read_text(encoding="utf-8") == added.body.toPlainText()
    else:
        assert argv[2:] == ["analyze", "--list", "list"]


def test_non_ai_pdf_job_keeps_ordinary_command_and_needs_no_ai_config(scene, monkeypatch):
    _app, root, window, _added, calls = scene
    monkeypatch.setattr(llm, "freeze_connections", lambda *_: pytest.fail("PDF requested AI"))
    window.queue_page._start_ready(["repdf", "fixture"])
    assert len(calls) == 1
    process, _program, argv = calls[0]
    assert argv == ["repdf", "fixture"] and not hasattr(process, "_ai_job_handoff")
    assert process.processEnvironment().value("PAPERFACT_DATA") == str(root)


@pytest.mark.parametrize("feature", ["add", "queue"])
def test_replaced_workspace_starts_no_child_and_keeps_draft(scene, monkeypatch, feature):
    _app, root, window, added, calls = scene
    monkeypatch.setattr(store, "DB_PATH", root / "other.sqlite")
    if feature == "add":
        added._start_ready()
        assert added._temp is None
        assert added.body.toPlainText() == "A deliberately complete synthetic paper reference"
    else:
        window.queue_page._start_ready(["analyze", "--list", "list"])
    assert calls == [] and not (root / "other.sqlite").exists()


@pytest.mark.parametrize("feature", ["add", "queue"])
def test_empty_input_starts_no_job_or_private_handoff(scene, feature):
    _app, _root, window, added, calls = scene
    if feature == "add":
        added.body.clear()
        added._start_ready()
        assert added._temp is None and added.go.isEnabled() and added.status.text()
    else:
        window.queue_page._start_ready([])
        assert window.queue_page._job is None
    assert calls == []


def test_rejecting_pending_add_clears_temp_and_ignores_late_success(scene):
    _app, _root, window, added, _calls = scene
    added._start_ready()
    process, temporary = added.process, added._temp
    assert process._ai_job_handoff._frame and temporary.exists()
    original = added.body.toPlainText()
    added.reject()
    assert added.process is None and added._temp is None and not temporary.exists()
    assert not process._ai_job_handoff._frame and not process._ai_job_handoff.timer.isActive()
    assert not added.added and added.body.toPlainText() == original
    process.finished.emit(0, QProcess.ExitStatus.NormalExit)
    assert not added.added and added.body.toPlainText() == original
    assert all(job.state != "running" for job in window.activity_hub.jobs.values())


@pytest.mark.parametrize("feature", ["add", "queue"])
def test_successful_child_preserves_saved_result_and_completes_once(scene, feature):
    _app, _root, window, added, calls = scene
    visits = []
    if feature == "add":
        added.finished.connect(visits.append)
        added._start_ready()
        process = added.process
        temporary = added._temp
    else:
        window.queue_page._start_ready(["analyze", "--list", "list"],
                                       then=lambda: visits.append("continued"))
        process = window.queue_page._job
    bound = process.peer_ready()
    assert bound.command == tuple(calls[0][2][2:])
    assert bound.routes.settings("list_parse" if feature == "add" else "dive").model == (
        "before-model"
    )
    # Simulated CLI body uses the real isolated research store. UI completion must
    # preserve this saved result and must not replay the operation on a late signal.
    with store.connect() as conn:
        store.upsert_papers(conn, [dict(id="result-paper", title="Saved synthetic result",
                                       venue="fixture", year=2026, source="fixture")])
        conn.execute("INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                     "VALUES ('list','result-paper',0,'now')")
        if feature == "queue":
            conn.execute("INSERT INTO dives(paper_id,body,spec,written_at) "
                         "VALUES ('result-paper','## Saved explanation','fixture','now')")
    process.finished.emit(0, QProcess.ExitStatus.NormalExit)
    process.finished.emit(0, QProcess.ExitStatus.NormalExit)
    with store.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM list_papers WHERE paper_id='result-paper'")
        assert count.fetchone()[0] == 1
        assert conn.execute("SELECT title FROM papers WHERE id='result-paper'").fetchone()[0] == (
            "Saved synthetic result"
        )
        if feature == "queue":
            body = conn.execute("SELECT body FROM dives WHERE paper_id='result-paper'")
            assert body.fetchone()[0] == "## Saved explanation"
    if feature == "add":
        assert added.added and added.process is None and not temporary.exists()
        assert len(visits) == 1
    else:
        assert window.queue_page._job is None and visits == ["continued"]
    assert list(window.activity_hub.jobs.values())[-1].state == "done"


def test_user_stop_remains_cancelled_after_late_crash_signal(scene):
    _app, _root, window, _added, _calls = scene
    widget = window.queue_page
    continued = []
    widget._start_ready(["analyze", "--list", "list"],
                        then=lambda: continued.append(True))
    process, token = widget._job, widget._activity.token
    widget._toggle_analyze()
    assert window.activity_hub.jobs[token].state == "cancelled"
    process.finished.emit(-9, QProcess.ExitStatus.CrashExit)
    assert widget._job is None and continued == []
    assert window.activity_hub.jobs[token].state == "cancelled"
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM list_papers").fetchone()[0] == 0
