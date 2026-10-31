"""Actual recovery service through Qt; no SQL or source hashing on the GUI thread."""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QWidget
from test_workspace_dialog import wait
from test_workspace_enrollment import source as source_fixture

from paper_daily import sync_recovery
from paper_daily.desktop.recovery_adoption_dialog import RecoveryAdoptionDialog
from paper_daily.desktop.workspace_dialog import WorkspaceDialog

source = source_fixture


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def restored(source, tmp_path, *, pin=False):
    if pin:
        with closing(sqlite3.connect(source)) as conn, conn:
            conn.execute(
                "INSERT INTO pins VALUES(?,'paper',?)",
                (pin if isinstance(pin, str) else "queue", "2026-10-30T00:00:00+00:00"),
            )
    archive, folder = tmp_path / "source.zip", tmp_path / "detached"
    sync_recovery.create(source, archive)
    sync_recovery.restore_detached(archive, folder)
    return folder / "papers.db"


def forbid_gui_connections(monkeypatch):
    original, gui = sqlite3.connect, threading.get_ident()

    def connect(*args, **kwargs):
        assert threading.get_ident() != gui, "SQLite belongs on the recovery worker"
        return original(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    return original


def test_actual_inspect_copy_backup_and_explicit_launch_keep_reader_and_drafts(
    app, source, tmp_path, monkeypatch
):
    from paper_daily import llm

    def no_ai(*_args, **_kwargs):
        raise AssertionError("Local adoption must not select an AI account or call a model")

    monkeypatch.setattr(llm, "settings", no_ai)
    monkeypatch.setattr(llm, "complete_result", no_ai)
    database = restored(source, tmp_path)
    before, original_before = database.read_bytes(), source.read_bytes()
    parent = QWidget()
    parent.draft = QPlainTextEdit(parent)
    parent.draft.setPlainText("Keep this unsent question")
    opened = []
    original_connect = forbid_gui_connections(monkeypatch)
    dialog = RecoveryAdoptionDialog(database, parent, language="en", open_workspace=opened.append)
    try:
        dialog.show()
        assert dialog.inspection is None and dialog.start_inspection()
        wait(app, lambda: not dialog.busy, timeout=30)
        assert dialog.inspection.report["supported"]
        assert "Papers: 1" in dialog.report.text()
        output, backup = tmp_path / "editable", tmp_path / "editable.zip"
        dialog.workspace_field.setText(str(output))
        dialog.backup_field.setText(str(backup))
        monkeypatch.setattr(dialog, "_confirm", lambda *_args: True)
        assert dialog.confirm_prepare()
        assert not dialog.confirm_prepare()
        wait(app, lambda: not dialog.busy, timeout=30)
        assert dialog.result and output.is_dir() and backup.is_file()
        assert opened == []
        with closing(original_connect(output / "papers.db")) as conn:
            assert conn.execute("SELECT body FROM notes").fetchall() == [("A research note",)]
            assert (
                conn.execute("SELECT COUNT(*) FROM research_recovery_provenance").fetchone()[0] > 0
            )
        with ThreadPoolExecutor(max_workers=1) as pool:
            verified = pool.submit(sync_recovery.inspect, backup).result(timeout=20)
        assert verified["workspace_id"] == dialog.result["workspace_id"]
        assert dialog.confirm_open()
        wait(app, lambda: not dialog.busy, timeout=20)
        assert len(opened) == 1 and opened[0].database_path == output / "papers.db"
        assert parent.draft.toPlainText() == "Keep this unsent question"
        assert database.read_bytes() == before and source.read_bytes() == original_before
    finally:
        dialog.close()
        parent.close()
        parent.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_actual_queue_pin_is_visible_before_creation_and_preserved(
    app, source, tmp_path, monkeypatch
):
    database = restored(source, tmp_path, pin=True)
    before = database.read_bytes()
    dialog = RecoveryAdoptionDialog(database, language="en")
    try:
        dialog.show()
        dialog.workspace_field.setText(str(tmp_path / "blocked"))
        dialog.backup_field.setText(str(tmp_path / "blocked.zip"))
        assert dialog.start_inspection()
        wait(app, lambda: not dialog.busy, timeout=30)
        assert dialog.inspection and dialog.inspection.report["supported"]
        assert dialog.inspection.report["research_counts"]["pins"] == 1
        assert dialog.prepare_button.isEnabled()
        monkeypatch.setattr(dialog, "_confirm", lambda *_args: True)
        assert dialog.confirm_prepare()
        wait(app, lambda: not dialog.busy, timeout=30)
        assert dialog.result and Path(dialog.result["database"]).is_file()
        with closing(sqlite3.connect(dialog.result["database"])) as conn:
            assert conn.execute("SELECT scope,paper_id FROM pins").fetchall() == [
                ("queue", "paper")
            ]
        assert database.read_bytes() == before
    finally:
        dialog.close()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_workspace_entry_reuses_one_child_and_prefills_only_explicit_restore_path(
    app, source, tmp_path
):
    from paper_daily.workspace_open import WorkspaceDestination

    database = restored(source, tmp_path)
    dialog = WorkspaceDialog(source, language="en")
    try:
        dialog.show()
        wait(app, lambda: not dialog.busy and dialog._ready)
        child = dialog._recovery_adoption_settings()
        assert child is not None and child.source_field.text() == ""
        assert dialog._recovery_adoption_settings() is child
        child.close()
        app.processEvents()
        wait(app, lambda: not dialog.busy)
        dialog.created_destination = WorkspaceDestination(database.parent, database)
        next_child = dialog._recovery_adoption_settings()
        assert next_child is not child
        assert Path(next_child.source_field.text()) == database
        assert next_child.inspection is None  # source selection is not implicit inspection
        assert dialog.service.path == source
        assert dialog.close() and next_child.disposed
    finally:
        dialog.close()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_workspace_close_waits_for_child_worker_and_preserves_reader(
    app, source, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    database = restored(source, tmp_path)
    dialog = WorkspaceDialog(source, language="en")
    entered, release = threading.Event(), threading.Event()
    try:
        dialog.show()
        wait(app, lambda: not dialog.busy and dialog._ready)
        child = dialog._recovery_adoption_settings()
        assert child.set_source(database)

        def held(*_args, **_kwargs):
            entered.set()
            assert release.wait(8)
            return SimpleNamespace(report=dict(supported=True))

        monkeypatch.setattr(child.service, "inspect", held)
        assert child.start_inspection()
        wait(app, entered.is_set)
        assert dialog.busy and not dialog.close()
        assert not dialog.disposed and not child.disposed
        release.set()
        wait(app, lambda: child.disposed and dialog.disposed)
        assert child.inspection is None and source.is_file() and database.is_file()
    finally:
        release.set()
        if dialog.busy:
            wait(app, lambda: not dialog.busy)
        dialog.close()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
