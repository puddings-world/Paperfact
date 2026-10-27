from pathlib import Path

from PySide6.QtWidgets import QApplication
from test_sync_connection_dialog import connected, dialog, enrolled, research, service, wait
from test_workspace_dialog import app
from test_workspace_dialog import dialog as workspace_dialog

# Re-export fixture dependencies explicitly for pytest.
__all__ = ["app", "dialog", "enrolled", "research", "service", "workspace_dialog"]


def test_restore_offers_explicit_new_window_and_launch_failure_retry(workspace_dialog, tmp_path):
    view = workspace_dialog
    qt = QApplication.instance()
    package = tmp_path / "backup.zip"
    assert view.start_backup(package)
    wait(qt, lambda: not view.busy)
    assert view.inspect_package(package)
    wait(qt, lambda: not view.busy)
    target = tmp_path / "restored"
    assert view.start_restore(target)
    wait(qt, lambda: not view.busy)
    assert view.open_created_button.isEnabled()
    calls = []

    def launch(destination):
        calls.append(destination)
        if len(calls) == 1:
            raise OSError("fixture cannot launch")

    view._open_workspace = launch
    assert not view.open_created() and view.open_created_button.isEnabled()
    assert view.open_created()
    assert not view.open_created() and len(calls) == 2
    assert calls[-1].database_path == target / "papers.db"
    assert view.service.path != calls[-1].database_path
    assert view.isVisible() and not view.disposed


def test_join_opens_only_after_publication_and_does_not_pass_credential(dialog, service, tmp_path):
    qt, view = dialog
    connected(dialog, service)
    view.sync_now()
    wait(qt, lambda: not view.busy)
    token = service[1].enroll("workspace", "new-device")
    view.device_id.setText("new-device")
    view.credential.setText(token)
    view.connect_session()
    wait(qt, lambda: not view.busy)
    assert not view.open_created_button.isEnabled()
    destination = tmp_path / "joined"
    view.start_join(destination)
    wait(qt, lambda: not view.busy)
    assert view.open_created_button.isEnabled()
    calls = []
    view._open_workspace = calls.append
    view.open_created_button.click()
    view.open_created_button.click()
    assert len(calls) == 1 and calls[0].workspace_root == Path(destination)
    assert token not in repr(calls[0]) and view.isVisible()
