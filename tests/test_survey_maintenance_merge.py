"""Roadmap confirmation and reopened survey jobs use disposable local state."""
from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
from shiboken6 import isValid

from paper_daily import runtime, store, survey
from paper_daily.desktop import activity
from paper_daily.desktop.survey_dialog import SurveyDialog


@pytest.fixture
def ready(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    database = tmp_path / "papers.db"
    monkeypatch.setattr(store, "DB_PATH", database)
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('list','Topic','now')")
        conn.execute("INSERT INTO list_surveys VALUES ('list','original roadmap',0,?,'now',0)",
                     (survey.ROADMAP_SPEC,))
    calls = []

    class Process(QProcess):
        def start(self, program, arguments):
            calls.append((self, program, list(arguments)))

    import paper_daily.desktop.survey_dialog as dialogs
    monkeypatch.setattr(dialogs, "QProcess", Process)
    monkeypatch.setattr(runtime, "cli_command", lambda *args: ["fixture", *args])
    monkeypatch.setattr(activity, "process_environment", lambda process: None)
    window = QWidget()
    window.activity_hub = activity.ActivityHub(window)
    palette = {key: "#333333" for key in
               ("muted", "surface", "ink", "border", "firm", "accent", "accentSoft", "ground",
                "faint",
                "ai", "onAi", "aiStrong", "aiSoft", "sunk", "done", "warn")}
    window.pal = palette
    made = []

    def open_dialog():
        dialog = SurveyDialog("list", "Topic", palette, window, language="en")
        made.append(dialog)
        return dialog

    def body():
        with closing(sqlite3.connect(database)) as conn, conn:
            return conn.execute("SELECT body FROM list_surveys WHERE list_id='list'").fetchone()[0]

    yield SimpleNamespace(app=app, database=database, calls=calls, window=window,
                          open=open_dialog, body=body)
    for process, _program, _args in calls:
        if isValid(process) and any(dialog.job is process for dialog in made):
            process.finished.emit(0, QProcess.ExitStatus.NormalExit)
    window.activity_hub._poll.stop()
    for dialog in made:
        dialog.close()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_cancel_keeps_roadmap_and_starts_no_job(ready, monkeypatch):
    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: (
        prompts.append(args), QMessageBox.StandardButton.No)[1])
    dialog = ready.open()
    dialog._run_ready()
    assert len(prompts) == 1
    assert ready.calls == [] and ready.body() == "original roadmap"
    assert dialog.run_btn.isEnabled()


def test_explicit_replacement_starts_one_forced_job(ready, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog = ready.open()
    for _ in range(5):
        dialog._run_ready()
    assert len(ready.calls) == 1
    arguments = ready.calls[0][2]
    assert arguments[0] == "_desktop-job-v1" and len(arguments[1]) == 32
    assert arguments[2:] == ["survey", "list", "--force"]
    assert ready.body() == "original roadmap"
    assert not dialog.run_btn.isEnabled()


def test_changed_roadmap_during_confirmation_is_not_replaced(ready, monkeypatch):
    def confirm(*_args):
        with closing(sqlite3.connect(ready.database)) as conn, conn:
            conn.execute("UPDATE list_surveys SET body='newer roadmap' WHERE list_id='list'")
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    dialog = ready.open()
    dialog._run_ready()
    assert ready.calls == [] and ready.body() == "newer roadmap"
    assert dialog.status.text()


def test_workspace_switch_during_confirmation_starts_no_job(ready, monkeypatch):
    other = ready.database.with_name("other.db")
    shutil.copyfile(ready.database, other)

    def confirm(*_args):
        monkeypatch.setattr(store, "DB_PATH", other)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    dialog = ready.open()
    dialog._run_ready()
    assert ready.calls == [] and ready.body() == "original roadmap"


def test_reopening_tracks_existing_job_and_completion(ready, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    first = ready.open()
    first._run_ready()
    first.close()
    reopened = ready.open()
    assert not reopened.run_btn.isEnabled()
    assert not reopened.edit_btn.isVisible()
    reopened._run_ready()
    assert len(ready.calls) == 1 and ready.body() == "original roadmap"
    process = ready.calls[0][0]
    process.finished.emit(0, QProcess.ExitStatus.NormalExit)
    ready.app.processEvents()
    assert reopened.run_btn.isEnabled()
    assert ready.body() == "original roadmap"
    ready.calls.clear()


def test_native_database_replacement_rejects_old_dialog(ready, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog = ready.open()
    replacement = ready.database.with_name("replacement.db")
    shutil.copyfile(ready.database, replacement)
    replacement.replace(ready.database)
    dialog._run_ready()
    assert ready.calls == [] and ready.body() == "original roadmap"


def test_failed_launch_retry_ignores_old_process_signals(ready, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog = ready.open()
    dialog._run_ready()
    first = ready.calls[0][0]
    first.errorOccurred.emit(QProcess.ProcessError.FailedToStart)
    assert dialog.job is None and dialog.run_btn.isEnabled()
    assert ready.body() == "original roadmap"
    dialog._run_ready()
    second = ready.calls[1][0]
    assert second is not first and dialog.job is second
    first.finished.emit(0, QProcess.ExitStatus.NormalExit)
    first.errorOccurred.emit(QProcess.ProcessError.FailedToStart)
    assert dialog.job is second
    assert not dialog.run_btn.isEnabled()
    assert ready.body() == "original roadmap"
    dialog._run_ready()
    assert len(ready.calls) == 2
