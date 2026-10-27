import threading
import time

import pytest
from PySide6.QtWidgets import QApplication
from test_workspace_sync import enrolled as enrolled_fixture
from test_workspace_sync import research as research_fixture
from test_workspace_sync import service as service_fixture

from paper_daily.desktop.sync_connection_dialog import SyncConnectionDialog
from paper_daily.desktop.workspace_dialog import WorkspaceDialog

research = research_fixture
enrolled = enrolled_fixture
service = service_fixture


def wait(app, condition, timeout=8):
    end = time.monotonic() + timeout
    while not condition():
        app.processEvents()
        if time.monotonic() > end:
            raise AssertionError("Fixture worker did not finish")
        time.sleep(0.005)
    app.processEvents()


@pytest.fixture
def dialog(service):
    app = QApplication.instance() or QApplication([])
    view = SyncConnectionDialog(service[0], language="en")
    view.show()
    wait(app, lambda: view.binding is not None and not view.busy)
    yield app, view
    if view.busy:
        view.cancel()
        wait(app, lambda: not view.busy)
    view.close()


def fill(view, token, device="origin-device"):
    view.endpoint.setText("http://127.0.0.1:8765")
    view.workspace_id.setText("workspace")
    view.device_id.setText(device)
    view.credential.setText(token)


def connected(dialog, service):
    app, view = dialog
    fill(view, service[2])
    view.connect_button.click()
    wait(app, lambda: not view.busy)
    assert view.sync_button.isEnabled()


def test_actual_connect_then_manual_sync_uses_own_identity_and_clears_password(dialog, service):
    app, view = dialog
    assert service[3] == [] and not view.sync_button.isEnabled()
    assert view.workspace_id.text() == "workspace"
    connected(dialog, service)
    assert view.credential.text() == "" and "no research has been sent" in view.status.text()
    assert service[3] == ["session_info"]
    view.sync_button.click()
    wait(app, lambda: not view.busy)
    assert "pending 0" in view.status.text()
    assert "Last manual sync" in view.identity_label.text()
    assert service[2] not in view.status.text()


def test_empty_connection_and_repeat_clicks_never_duplicate_handshake(dialog, service, monkeypatch):
    app, view = dialog
    view.connect_button.click()
    assert not view.busy and service[3] == []
    assert "Enter the service" in view.status.text()
    entered, release = threading.Event(), threading.Event()
    original = service[1].session_info
    calls = []

    def held(token):
        calls.append(1)
        entered.set()
        assert release.wait(8)
        return original(token)

    monkeypatch.setattr(service[1], "session_info", held)
    fill(view, service[2])
    view.connect_button.click()
    wait(app, entered.is_set)
    assert not view.connect_session()
    assert not view.sync_now()
    release.set()
    wait(app, lambda: not view.busy)
    assert calls == [1] and view.sync_button.isEnabled()


def test_disconnect_during_handshake_cannot_install_late_credential(dialog, service, monkeypatch):
    app, view = dialog
    entered, release = threading.Event(), threading.Event()
    original = service[1].session_info

    def held(token):
        entered.set()
        assert release.wait(8)
        return original(token)

    monkeypatch.setattr(service[1], "session_info", held)
    fill(view, service[2])
    view.connect_session()
    wait(app, entered.is_set)
    view.disconnect()
    release.set()
    wait(app, lambda: not view.busy)
    assert not service[0].summary()["authenticated"]
    assert not view.sync_button.isEnabled() and view.credential.text() == ""


def test_editing_endpoint_invalidates_old_route_before_retry(dialog, service):
    _, view = dialog
    connected(dialog, service)
    view.endpoint.setText("https://other.invalid")
    assert not service[0].summary()["authenticated"]
    assert not view.sync_button.isEnabled()
    assert "push" not in service[3]


def test_auth_failure_retains_local_pending_work_and_visible_retry(dialog, service, enrolled):
    app, view = dialog
    before = enrolled[1].journal.pending()
    fill(view, "rejected-fixture-token")
    view.connect_button.click()
    wait(app, lambda: not view.busy)
    assert "Credential rejected" in view.status.text() and not view.sync_button.isEnabled()
    assert enrolled[1].journal.pending() == before
    connected(dialog, service)
    assert service[0].summary()["authenticated"]


def test_new_device_join_real_dialog_publishes_separate_metadata_workspace(
    dialog, service, tmp_path
):
    app, view = dialog
    connected(dialog, service)
    view.sync_now()
    wait(app, lambda: not view.busy)
    new_token = service[1].enroll("workspace", "new-device")
    fill(view, new_token, "new-device")
    view.connect_session()
    wait(app, lambda: not view.busy)
    assert not view.sync_button.isEnabled() and view.join_button.isEnabled()
    destination = tmp_path / "new-workspace"
    assert view.start_join(destination)
    assert not view.start_join(destination)
    wait(app, lambda: not view.busy)
    assert (destination / "papers.db").is_file()
    assert "Active workspace unchanged" in view.status.text()
    assert "attachments still need downloading" in view.status.text()
    assert service[0].workspace.path.is_file()


def test_close_while_sync_running_waits_without_destroying_worker(dialog, service, monkeypatch):
    app, view = dialog
    connected(dialog, service)
    original = service[1].push
    entered, release = threading.Event(), threading.Event()

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(service[1], "push", held)
    view.sync_now()
    wait(app, entered.is_set)
    try:
        assert not view.close() and not view.disposed
    finally:
        release.set()
    wait(app, lambda: view.disposed)
    assert service[0]._token is not None


def test_workspace_change_drops_result_and_blocks_retry(dialog, service, tmp_path, monkeypatch):
    app, view = dialog
    connected(dialog, service)
    active = [service[0].workspace.path]
    service[0].workspace.current_path = lambda: active[0]
    original = service[1].pull

    def switch(*args, **kwargs):
        result = original(*args, **kwargs)
        active[0] = tmp_path / "other.db"
        return result

    monkeypatch.setattr(service[1], "pull", switch)
    view.sync_now()
    wait(app, lambda: not view.busy)
    assert not (tmp_path / "other.db").exists()
    assert "Active workspace changed" in view.status.text()
    assert not view.sync_button.isEnabled()


def test_real_workspace_entry_reuses_memory_session_and_nested_close(enrolled, service):
    app = QApplication.instance() or QApplication([])
    parent = WorkspaceDialog(enrolled[0], language="en")
    parent._workspace_sync_session = service[0]
    parent.show()
    wait(app, lambda: parent._ready and not parent.busy)
    parent.sync_connection_button.click()
    child = parent._sync_dialog
    wait(app, lambda: child.binding is not None and not child.busy)
    assert child.session is service[0]
    fill(child, service[2])
    child.connect_session()
    wait(app, lambda: not child.busy)
    child.close()
    wait(app, lambda: not parent.busy)
    parent.sync_connection_button.click()
    reopened = parent._sync_dialog
    wait(app, lambda: reopened.binding is not None and not reopened.busy)
    assert reopened.session is service[0] and reopened.sync_button.isEnabled()
    assert reopened.credential.text() == ""
    parent.close()
    wait(app, lambda: parent.disposed)


def test_no_model_call_on_connect_sync_or_join(dialog, service, monkeypatch, tmp_path):
    from paper_daily import llm

    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("Sync called AI"))
    app, view = dialog
    connected(dialog, service)
    view.sync_now()
    wait(app, lambda: not view.busy)
    assert service[0].summary()["last_success"]


def test_no_source_writes_while_merely_opening_connection(dialog, service, enrolled):
    _, view = dialog
    assert service[3] == []
    assert not view.busy and enrolled[1].journal.pending()


@pytest.mark.parametrize("cancel_at", ["folder", "name", "blank", "invalid", "confirmation", None])
def test_join_picker_normal_and_cancel_paths(dialog, service, tmp_path, monkeypatch, cancel_at):
    from paper_daily.desktop import sync_connection_dialog as module

    app, view = dialog
    connected(dialog, service)
    view.sync_now()
    wait(app, lambda: not view.busy)
    token = service[1].enroll("workspace", "picker-device")
    fill(view, token, "picker-device")
    view.connect_session()
    wait(app, lambda: not view.busy)
    assert view.join_button.isEnabled()
    monkeypatch.setattr(
        module.QFileDialog,
        "getExistingDirectory",
        lambda *a, **k: "" if cancel_at == "folder" else str(tmp_path),
    )
    name = (
        " "
        if cancel_at == "blank"
        else "../escape"
        if cancel_at == "invalid"
        else "chosen-workspace"
    )
    monkeypatch.setattr(module.QInputDialog, "getText", lambda *a, **k: (name, cancel_at != "name"))
    monkeypatch.setattr(
        module.QMessageBox,
        "question",
        lambda *a, **k: (
            module.QMessageBox.StandardButton.No
            if cancel_at == "confirmation"
            else module.QMessageBox.StandardButton.Yes
        ),
    )
    before = list(service[3])
    view.choose_join()
    if cancel_at is not None:
        assert not view.busy and service[3] == before
        assert not (tmp_path / "chosen-workspace").exists()
        assert not list(tmp_path.glob(".paperfact-join-*"))
    else:
        view.choose_join()  # Activation while the first worker runs stays inert.
        wait(app, lambda: not view.busy)
        assert (tmp_path / "chosen-workspace/papers.db").is_file()
        assert view.created_destination.workspace_root == tmp_path / "chosen-workspace"
        assert view.open_created_button.isEnabled()
        assert service[0].workspace.path != view.created_destination.database_path
