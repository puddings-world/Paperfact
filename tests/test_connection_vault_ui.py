"""Remember/load/forget UI uses synthetic credentials and no OS vault."""

import sqlite3
import threading
from contextlib import closing

import pytest
from PySide6.QtWidgets import QApplication
from test_connection_vault import saved as saved_fixture
from test_connection_vault import service as service_fixture
from test_sync_connection_dialog import fill, wait

from paper_daily.connection_vault import VaultUnavailable
from paper_daily.desktop.sync_connection_dialog import SyncConnectionDialog

service = service_fixture
saved = saved_fixture


@pytest.fixture
def dialog(service, saved):
    app = QApplication.instance() or QApplication([])
    view = SyncConnectionDialog(service[0], language="en", vault=saved[0])
    view.show()
    wait(app, lambda: view.binding is not None and not view.busy)
    yield app, view
    if view.busy:
        view.cancel()
        wait(app, lambda: not view.busy)
    view.close()


def verify(dialog, service, remember=False):
    app, view = dialog
    fill(view, service[2])
    view.remember_box.setChecked(remember)
    view.connect_button.click()
    wait(app, lambda: not view.busy)
    assert service[0].summary()["authenticated"]


def test_no_vault_access_without_explicit_choice(dialog, service, saved):
    app, view = dialog
    assert not view.remember_box.isChecked()
    assert not saved[1].calls
    verify(dialog, service)
    assert not saved[1].calls
    assert service[3] == ["session_info"]
    assert not view.credential.text()
    assert view.sync_button.isEnabled()


def test_remember_load_requires_fresh_verify_and_never_syncs(dialog, service, saved):
    app, view = dialog
    verify(dialog, service, remember=True)
    assert saved[0].load() == saved[2]
    assert "remembered" in view.status.text()
    view.disconnect()
    view.load_saved_button.click()
    view.load_saved_button.click()
    assert not view.load_saved()
    assert not view.remember_box.isEnabled()
    wait(app, lambda: not view.busy)
    assert view.credential.text() == service[2]
    assert "Verify and connect" in view.status.text()
    assert not service[0].summary()["authenticated"]
    assert not view.sync_button.isEnabled()
    assert service[3] == ["session_info"]
    view.remember_box.setChecked(False)
    view.connect_button.click()
    wait(app, lambda: not view.busy)
    assert service[3] == ["session_info", "session_info"]
    assert service[0].summary()["authenticated"]
    assert not view.credential.text()


def test_forget_is_explicit_idempotent_and_keeps_current_session(dialog, service, saved):
    app, view = dialog
    verify(dialog, service, remember=True)
    view.forget_saved_button.click()
    view.forget_saved_button.click()
    wait(app, lambda: not view.busy)
    assert saved[0].load() is None
    assert service[0].summary()["authenticated"]
    assert "removed" in view.status.text()
    assert service[3] == ["session_info"]


def test_missing_saved_connection_keeps_manual_entry_available(dialog, saved):
    app, view = dialog
    view.load_saved_button.click()
    wait(app, lambda: not view.busy)
    assert "No saved connection" in view.status.text()
    assert view.connect_button.isEnabled()
    assert not view.credential.text()
    assert saved[1].calls == ["get"]


def test_vault_failure_does_not_discard_successful_connection(dialog, service, saved):
    app, view = dialog

    def unavailable():
        raise VaultUnavailable("not available")

    saved[0]._backend = unavailable
    verify(dialog, service, remember=True)
    assert "could not be remembered" in view.status.text()
    assert not view.credential.text()
    assert view.sync_button.isEnabled()
    assert service[2] not in view.status.text()
    assert not saved[1].rows


@pytest.mark.parametrize("action", ["cancel", "close", "workspace"])
def test_delayed_vault_load_cannot_fill_cancelled_or_different_workspace(
    dialog, service, saved, tmp_path, action
):
    app, view = dialog
    verify(dialog, service, remember=True)
    view.disconnect()
    started, release = threading.Event(), threading.Event()
    original = saved[1].get_password

    def blocked(*args):
        started.set()
        assert release.wait(5)
        return original(*args)

    saved[1].get_password = blocked
    view.load_saved_button.click()
    wait(app, started.is_set)
    try:
        if action == "cancel":
            view.cancel()
        elif action == "close":
            view.close()
        else:
            service[0].workspace.current_path = lambda: tmp_path / "other.db"
            view._check_workspace()
    finally:
        release.set()
    wait(app, lambda: not view.busy)
    assert not view.credential.text()
    assert not service[0].summary()["authenticated"]
    assert service[3] == ["session_info"]
    if action == "close":
        assert view.disposed


def change_binding(session):
    with closing(sqlite3.connect(session.workspace.path)) as conn:
        conn.execute("UPDATE paperfact_sync_identity SET device='different-device'")
        conn.commit()


def test_finished_saved_load_cannot_fill_after_binding_changes_before_gui_delivery(
    dialog, service, saved
):
    app, view = dialog
    verify(dialog, service, remember=True)
    view.disconnect()
    view.load_saved_button.click()
    worker = view._worker
    assert worker.wait(5000)  # No event processing: finished is queued for the GUI.
    assert worker.result == saved[2]
    change_binding(service[0])
    wait(app, lambda: not view.busy)
    assert not view.credential.text()
    assert not service[0].summary()["authenticated"]
    assert view._invalid and not view.connect_button.isEnabled()
    assert view.status.text() == view.t["changed"]
    assert service[3] == ["session_info"]


def test_binding_change_after_saved_details_load_stops_explicit_connect(
    dialog, service
):
    app, view = dialog
    verify(dialog, service, remember=True)
    view.disconnect()
    view.load_saved_button.click()
    wait(app, lambda: not view.busy)
    assert view.credential.text() == service[2]
    change_binding(service[0])
    view.connect_button.click()
    assert not view.busy and view._invalid
    assert not view.credential.text()
    assert not service[0].summary()["authenticated"]
    assert service[3] == ["session_info"]
