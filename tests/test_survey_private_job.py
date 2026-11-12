"""Survey command confirmation retains the original AI selection."""
from PySide6.QtWidgets import QMessageBox
from test_survey_maintenance_merge import ready as _ready

from paper_daily import llm
from paper_daily.cli_job_protocol import decode_frame

ready = _ready


def test_confirmation_changes_cannot_retarget_the_original_survey(ready, monkeypatch):
    monkeypatch.setattr(llm, "SETTINGS_PATH", ready.database.parent / "llm.json")
    llm.save_settings(profile="selected", backend="openai", model="original-model",
                      api_key="synthetic-private-key", isolated=True)
    llm.use_profile("selected", desktop=True)
    captured = llm.capture_connections()
    def confirm(*_):
        llm.save_settings(profile="selected", model="changed-model", api_key="other-key")
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", confirm)
    dialog = ready.open()
    with llm.connection_scope(captured):
        dialog._run_ready()
    assert len(ready.calls) == 1 and ready.body() == "original roadmap"
    process, program, argv = ready.calls[0]
    assert program == "fixture" and argv[0] == "_desktop-job-v1"
    assert argv[2:] == ["survey", "list", "--force"]
    bound = decode_frame(process._ai_job_handoff._frame, expected_request_id=argv[1],
                         expected_command=argv[2:])
    cfg = bound.routes.settings("survey")
    assert cfg.model == "original-model" and cfg.api_key == "synthetic-private-key"
    assert llm.settings("survey").model == "changed-model"
    assert "synthetic-private-key" not in " ".join(argv)
    assert dialog._running()
    for _ in range(20):
        dialog._run_ready()
    assert len(ready.calls) == 1


def test_zero_exit_before_handshake_is_failure_and_retry_remains_possible(ready, monkeypatch):
    from PySide6.QtCore import QProcess
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Yes)
    dialog = ready.open()
    dialog._run_ready()
    process = dialog.job
    process.finished.emit(0, QProcess.ExitStatus.NormalExit)
    assert dialog.job is None and dialog.run_btn.isEnabled()
    assert ready.body() == "original roadmap"
    assert not process._ai_job_handoff._frame
    jobs = list(ready.window.activity_hub.jobs.values())
    assert jobs and jobs[-1].state == "error"
    dialog._run_ready()
    assert dialog.job is not None and dialog.job is not process
    assert len(ready.calls) == 2
