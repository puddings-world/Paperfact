"""Real Qt workers; deterministic local service, never real accounts or research."""

import copy
import sqlite3
import threading
import weakref
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThread, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPlainTextEdit, QWidget
from test_workspace_dialog import wait

from paper_daily.desktop.recovery_adoption_dialog import RecoveryAdoptionDialog
from paper_daily.workspace_enrollment import EnrollmentBlocked
from paper_daily.workspace_service import SnapshotChanged, WorkspaceChanged


@pytest.fixture(scope="session")
def app():
    # The desktop owns one QApplication for the whole process. Retain that
    # lifetime while real worker-side recovery allocations trigger Python GC.
    return QApplication.instance() or QApplication([])


class LocalService:
    def __init__(self, database, *, current_path):
        self.database, self.current_path = Path(database), current_path
        stat = self.database.stat()
        self.identity = stat.st_dev, stat.st_ino
        self.calls, self.threads = [], []
        self.entered, self.release = threading.Event(), threading.Event()
        self.hold = self.failure = self.stale = self.blocked = False
        self.report = dict(
            supported=True,
            research_counts=dict(lists=2, papers=3, notes=4),
            history_counts=dict(operations=5),
            retained_blobs=6,
        )

    def _check(self):
        stat = self.database.stat()
        if (stat.st_dev, stat.st_ino) != self.identity or self.current_path() != self.database:
            raise WorkspaceChanged("fixture-private-source")

    def _work(self, ticket):
        self.threads.append(threading.get_ident())
        self.entered.set()
        if self.hold:
            assert self.release.wait(8)
        ticket.check()
        if self.failure:
            raise OSError("fixture-private-error-token")
        if self.stale:
            raise SnapshotChanged("fixture-private-research")

    def inspect(self, *, ticket, progress):
        self.calls.append(("inspect",))
        progress("Inspecting recovered research, history and exact source closure")
        self._work(ticket)
        self.inspection = SimpleNamespace(report=copy.deepcopy(self.report))
        return self.inspection

    def prepare(self, inspection, output, *, backup_output, request_id, ticket, progress):
        assert inspection is self.inspection
        self.calls.append(("prepare", output, backup_output, request_id))
        progress("Creating and inspecting independent recovery backup")
        self._work(ticket)
        if self.blocked:
            raise EnrollmentBlocked(
                dict(supported=False, blockers=["legacy queue pins require migration"])
            )

        def publish():
            output.mkdir()
            with sqlite3.connect(output / "papers.db") as conn:
                conn.execute("CREATE TABLE papers(id TEXT)")
                conn.execute("INSERT INTO papers VALUES('exact-selected-source')")
            backup_output.write_bytes(b"fixture-independent-backup")

        ticket.publish(publish)
        return dict(
            destination=str(output), database=str(output / "papers.db"), backup=str(backup_output)
        )


@pytest.fixture
def view(app, tmp_path):
    source = tmp_path / "restored" / "papers.db"
    source.parent.mkdir()
    source.write_bytes(b"unchanged-source")
    parent = QWidget()
    parent.draft = QPlainTextEdit(parent)
    parent.draft.setPlainText("Unsent question and note draft")
    state = {"current": True}
    opened = []
    dialog = RecoveryAdoptionDialog(
        source,
        parent,
        language="en",
        service_factory=LocalService,
        context_current=lambda: state["current"],
        open_workspace=opened.append,
    )
    dialog.show()
    dialog.workspace_field.setText(str(tmp_path / "editable"))
    dialog.backup_field.setText(str(tmp_path / "backup.zip"))
    dialog.fixture_state, dialog.fixture_parent, dialog.fixture_opened = (
        state,
        weakref.proxy(parent),
        opened,
    )
    yield dialog
    if dialog._worker:
        dialog._worker.ticket.cancel()
        dialog.service.release.set()
        wait(app, lambda: not dialog.busy)
    dialog.close()
    wait(app, lambda: all(not worker.isRunning() for worker in dialog.findChildren(QThread)))
    parent.close()
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def inspect(app, view):
    assert view.start_inspection()
    wait(app, lambda: not view.busy)
    assert view.inspection is not None


def yes(view, monkeypatch):
    monkeypatch.setattr(view, "_confirm", lambda *_: True)


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_empty_explicit_picker_and_cancel_create_no_jobs(app, language, monkeypatch):
    dialog = RecoveryAdoptionDialog(language=language, service_factory=LocalService)
    dialog.show()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a, **_k: ("", ""))
    assert not dialog.choose_source() and not dialog.busy
    assert not dialog.set_source(None) and not dialog.set_source(" ")
    assert not dialog.inspect_button.isEnabled() and not dialog.prepare_button.isEnabled()
    assert dialog.close_button.isDefault() and not dialog.prepare_button.autoDefault()
    assert dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_inspection_is_explicit_worker_only_without_login_and_retains_drafts(
    view, app, monkeypatch
):
    from paper_daily import llm

    def no_ai(*_args, **_kwargs):
        raise AssertionError("No AI or account routing in local recovery")

    monkeypatch.setattr(llm, "settings", no_ai)
    assert view.service.calls == [] and view.inspection is None
    inspect(app, view)
    assert "Lists: 2" in view.report.text() and "History records: 5" in view.report.text()
    assert "Snapshot checked:" in view.report.text()
    assert all(identity != threading.get_ident() for identity in view.service.threads)
    assert view.prepare_button.isEnabled()
    assert view.fixture_parent.draft.toPlainText() == "Unsent question and note draft"
    assert view.service.database.read_bytes() == b"unchanged-source"


def test_progress_handler_runs_on_the_gui_thread(view, app, monkeypatch):
    gui, observed = threading.get_ident(), []
    monkeypatch.setattr(view, "_stage", lambda _message: observed.append(threading.get_ident()))
    inspect(app, view)
    assert observed and observed == [gui]


def test_native_confirmation_defaults_to_cancel_and_never_starts_preparation(view, app):
    inspect(app, view)
    observed = []

    def cancel():
        box = QApplication.activeModalWidget()
        assert isinstance(box, QMessageBox)
        observed.append(box.defaultButton() is box.button(QMessageBox.StandardButton.Cancel))
        box.button(QMessageBox.StandardButton.Cancel).click()

    QTimer.singleShot(0, cancel)
    assert not view.confirm_prepare()
    assert observed == [True] and view.service.calls == [("inspect",)]
    assert not Path(view.workspace_field.text()).exists()


def test_success_duplicate_click_and_explicit_open_preserve_source_and_drafts(
    view, app, monkeypatch
):
    inspect(app, view)
    yes(view, monkeypatch)
    view.service.hold = True
    view.service.entered.clear()
    assert view.confirm_prepare()
    wait(app, view.service.entered.is_set)
    assert not view.confirm_prepare() and not view.start_inspection()
    assert not view.prepare_button.isEnabled()
    view.service.release.set()
    wait(app, lambda: not view.busy)
    assert view.result and view.fixture_opened == []
    assert [call[0] for call in view.service.calls] == ["inspect", "prepare"]
    with sqlite3.connect(view.result["database"]) as conn:
        assert conn.execute("SELECT id FROM papers").fetchall() == [("exact-selected-source",)]
    assert Path(view.result["backup"]).read_bytes() == b"fixture-independent-backup"
    assert not view.confirm_prepare()
    assert view.confirm_open()
    assert not view.confirm_open()
    wait(app, lambda: not view.busy)
    assert len(view.fixture_opened) == 1 and view._opened
    assert view.fixture_parent.draft.toPlainText() == "Unsent question and note draft"
    assert view.service.database.read_bytes() == b"unchanged-source"


def test_failure_retry_keeps_inputs_request_and_sanitizes_error(view, app, monkeypatch):
    inspect(app, view)
    yes(view, monkeypatch)
    paths = view.workspace_field.text(), view.backup_field.text()
    view.service.failure = True
    assert view.confirm_prepare()
    wait(app, lambda: not view.busy)
    assert view.inspection is not None and view.result is None
    assert "fixture-private" not in view.status.text()
    assert (view.workspace_field.text(), view.backup_field.text()) == paths
    assert not Path(paths[0]).exists()
    request = view.service.calls[-1][-1]
    view.service.failure = False
    assert view.confirm_prepare()
    wait(app, lambda: not view.busy)
    assert view.result and view.service.calls[-1][-1] == request


def test_saved_snapshot_change_requires_reinspection_and_keeps_destination_fields(
    view, app, monkeypatch
):
    inspect(app, view)
    yes(view, monkeypatch)
    view.service.stale = True
    assert view.confirm_prepare()
    wait(app, lambda: not view.busy)
    assert view.inspection is None and view.result is None
    assert view.workspace_field.text().endswith("editable")
    assert "Inspect it again" in view.status.text()
    view.service.stale = False
    inspect(app, view)
    assert view.prepare_button.isEnabled()


@pytest.mark.parametrize("action", ["stop", "close", "context", "source-replaced"])
def test_cancel_context_or_close_drops_late_results_and_never_publishes(
    view, app, monkeypatch, action
):
    inspect(app, view)
    yes(view, monkeypatch)
    view.service.hold = True
    view.service.entered.clear()
    assert view.confirm_prepare()
    wait(app, view.service.entered.is_set)
    if action == "stop":
        view.cancel()
    elif action == "close":
        assert not view.close() and not view.disposed
    elif action == "context":
        view.fixture_state["current"] = False
        view._check_context()
    else:
        source = view.service.database
        source.rename(source.with_suffix(".old"))
        source.write_bytes(b"different-workspace")
        view._check_context()
    view.service.release.set()
    wait(app, lambda: not view.busy)
    if action == "close":
        wait(app, lambda: view.disposed)
    assert view.result is None
    assert (
        not Path(view.workspace_field.text()).exists()
        and not Path(view.backup_field.text()).exists()
    )
    assert [call[0] for call in view.service.calls].count("prepare") == 1
    assert view.fixture_parent.draft.toPlainText() == "Unsent question and note draft"


def test_selection_and_paths_are_sealed_across_native_confirmation(
    view, app, monkeypatch, tmp_path
):
    inspect(app, view)
    other = tmp_path / "other.db"
    other.write_bytes(b"other-recovered-workspace")
    old = view.service

    def change_source(*_args):
        assert view.set_source(other)
        return True

    monkeypatch.setattr(view, "_confirm", change_source)
    assert not view.confirm_prepare() and not view.busy
    assert old.calls == [("inspect",)] and view.inspection is None


def test_context_switch_during_open_confirmation_never_launches(view, app, monkeypatch):
    inspect(app, view)
    yes(view, monkeypatch)
    assert view.confirm_prepare()
    wait(app, lambda: not view.busy)

    def switch(*_args):
        view.fixture_state["current"] = False
        return True

    monkeypatch.setattr(view, "_confirm", switch)
    assert not view.confirm_open() and view.fixture_opened == []
    assert Path(view.workspace_field.text()).is_dir()


def test_typed_blocker_stops_repeat_create_without_dropping_fields(view, app, monkeypatch):
    inspect(app, view)
    yes(view, monkeypatch)
    view.service.blocked = True
    assert view.confirm_prepare()
    wait(app, lambda: not view.busy)
    assert not view.prepare_button.isEnabled() and not view.confirm_prepare()
    assert "legacy queue pins require migration" in view.report.text()
    assert view.workspace_field.text().endswith("editable")


def test_cancelled_destination_pickers_keep_inspection_and_field_drafts(view, app, monkeypatch):
    inspect(app, view)
    before = (
        view.inspection,
        view.source_field.text(),
        view.workspace_field.text(),
        view.backup_field.text(),
    )
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a, **_k: ("", ""))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_a, **_k: "")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: ("", ""))
    view.choose_source()
    view.choose_workspace()
    view.choose_backup()
    assert (
        view.inspection,
        view.source_field.text(),
        view.workspace_field.text(),
        view.backup_field.text(),
    ) == before
    assert view.service.calls == [("inspect",)] and not view.busy


@pytest.mark.parametrize("kind", ["empty", "relative", "inside-source", "same", "existing"])
def test_invalid_destinations_never_show_confirmation_or_publish(view, app, monkeypatch, kind):
    inspect(app, view)

    def unexpected(*_args):
        raise AssertionError("Invalid paths must be checked before native confirmation")

    monkeypatch.setattr(view, "_confirm", unexpected)
    if kind == "empty":
        view.workspace_field.clear()
    elif kind == "relative":
        view.workspace_field.setText("relative-folder")
    elif kind == "inside-source":
        view.workspace_field.setText(str(view.service.database.parent / "child"))
    elif kind == "same":
        view.backup_field.setText(view.workspace_field.text())
    else:
        Path(view.workspace_field.text()).mkdir()
    assert not view.confirm_prepare() and not view.busy
    assert view.service.calls == [("inspect",)] and view.result is None


def test_open_confirmation_also_defaults_to_cancel(view, app, monkeypatch):
    inspect(app, view)
    yes(view, monkeypatch)
    assert view.confirm_prepare()
    wait(app, lambda: not view.busy)
    monkeypatch.delattr(view, "_confirm")
    observed = []

    def cancel():
        box = QApplication.activeModalWidget()
        observed.append(box.defaultButton() is box.button(QMessageBox.StandardButton.Cancel))
        box.button(QMessageBox.StandardButton.Cancel).click()

    QTimer.singleShot(0, cancel)
    assert not view.confirm_open()
    assert observed == [True] and view.fixture_opened == [] and not view._opened


def test_pending_work_refuses_new_source_and_ignores_old_progress(view, app, monkeypatch, tmp_path):
    inspect(app, view)
    yes(view, monkeypatch)
    original_source, original_service = view.source_field.text(), view.service
    view.service.hold = True
    view.service.entered.clear()
    assert view.confirm_prepare()
    wait(app, view.service.entered.is_set)
    other = tmp_path / "other.db"
    other.write_bytes(b"another-workspace")
    assert not view.set_source(other)
    before = view.status.text()
    view._worker_stage(object(), view._generation - 1, "Verified candidate ready")
    assert view.status.text() == before
    # Local copying has no account/model input; unrelated reader selection stays independent.
    view.fixture_parent.account = "different-fixture-account"
    view.fixture_parent.paper = "different-fixture-paper"
    view.service.release.set()
    wait(app, lambda: not view.busy)
    assert (
        view.result
        and view.source_field.text() == original_source
        and view.service is original_service
    )


def test_async_report_is_not_clipped_at_default_or_small_window(view, app):
    inspect(app, view)
    assert view.report.height() >= view.report.heightForWidth(view.report.width())
    view.resize(520, 400)
    app.processEvents()
    assert view.scroll.verticalScrollBar().maximum() > 0
    assert view.scroll.horizontalScrollBar().maximum() == 0
    assert view.report.height() >= view.report.heightForWidth(view.report.width())
    assert view.rect().contains(view.close_button.geometry())
    assert view.rect().contains(view.prepare_button.geometry())
