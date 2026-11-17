"""Drive setup UI uses fake services and never logs in or opens native credentials."""

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QWidget
from test_sync_connection_dialog import wait
from test_workspace_sync import enrolled as enrolled_fixture
from test_workspace_sync import research as research_fixture
from test_workspace_sync import service as service_fixture

from paper_daily.desktop.drive_sync_dialog import DriveSyncDialog

research = research_fixture
enrolled = enrolled_fixture
service = service_fixture


class Setup:
    def __init__(self, *_args, **_kwargs):
        self.valid = True
        self.binding = SimpleNamespace(_check=lambda: None, current=lambda: self.valid)
        self.files = None
        self.calls = 0
        self.release = threading.Event()
        self.fail = False
        self.rollback = False

    def sign_in(self, ticket, progress):
        self.calls += 1
        progress({"stage": "google_login"})
        while not self.release.wait(0.01):
            ticket.check()
        ticket.check()
        if self.fail:
            raise ConnectionError("synthetic offline")
        self.files = object()
        return {"account": {"email": "researcher@example.test"}, "workspaces": [
            {"name": "My research", "workspace_id": "workspace", "folder_id": "folder"}]}

    def rollback_consent(self):
        self.rollback = True


@pytest.fixture
def dialog(service):
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    setup = Setup()
    view = DriveSyncDialog(service[0], owner, language="en",
                           service_factory=lambda *a, **k: setup, owner=owner)
    view.show()
    yield app, view, setup
    setup.release.set()
    if view.busy:
        view.cancel()
        wait(app, lambda: not view.busy)
    view.close()
    owner.close()
    app.processEvents()


def test_login_is_one_visible_job_and_discovery_does_not_enable_sync(dialog):
    app, view, setup = dialog
    assert view.sign_in()
    assert not view.sign_in()
    wait(app, lambda: setup.calls == 1)
    assert not view.login.isEnabled()
    assert view.progress.isVisible()
    assert not view.create.isEnabled()
    setup.release.set()
    wait(app, lambda: not view.busy)
    assert view.account.text() == "researcher@example.test"
    assert view.workspaces.currentText() == "My research"
    assert view.create.isEnabled() and view.join.isEnabled()
    assert not view.auto.isChecked()
    assert not view.session.summary()["authenticated"]


def test_failure_is_retryable_and_stale_result_cannot_choose_another_workspace(dialog):
    app, view, setup = dialog
    setup.fail = True
    setup.release.set()
    view.sign_in()
    wait(app, lambda: not view.busy)
    assert "offline" in view.status.text()
    assert view.login.isEnabled() and not view.create.isEnabled()
    setup.fail = False
    setup.release.clear()
    view.sign_in()
    wait(app, lambda: setup.calls == 2)
    setup.valid = False
    setup.release.set()
    wait(app, lambda: not view.busy)
    assert view.account.text() == "Not connected to Google"
    assert view.workspaces.count() == 0
    assert setup.rollback


def test_close_cancels_worker_and_keeps_widgets_until_it_drains(dialog):
    app, view, setup = dialog
    view.sign_in()
    wait(app, lambda: setup.calls == 1)
    assert not view.close()
    wait(app, lambda: view.disposed)
    assert not view.busy
    assert not view.isVisible()
    assert setup.rollback
    assert not view.session.summary()["authenticated"]
