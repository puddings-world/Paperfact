"""Disclosure changes do not authenticate, sync or erase typed details."""

from test_connection_vault_ui import dialog as vault_dialog_fixture
from test_connection_vault_ui import saved as saved
from test_connection_vault_ui import verify
from test_sync_connection_dialog import dialog as dialog
from test_sync_connection_dialog import enrolled as enrolled
from test_sync_connection_dialog import research as research
from test_sync_connection_dialog import service as service
from test_sync_connection_dialog import wait


def test_setup_and_advanced_are_collapsed_without_network_actions(dialog, service):
    app, view = dialog
    assert not view.setup_panel.isVisible() and not view.advanced_panel.isVisible()
    assert view.load_saved_button.isVisible()
    view.setup_button.click()
    assert view.endpoint.isVisible() and view.connect_button.isVisible()
    view.endpoint.setText("https://fixture.invalid")
    view.setup_button.click()
    view.setup_button.click()
    assert view.endpoint.text() == "https://fixture.invalid"
    view.advanced_button.click()
    assert view.join_button.isVisible()
    view.advanced_button.click()
    assert not view.join_button.isVisible()
    assert service[3] == []
    assert not view.sync_button.isEnabled()


def test_loaded_connection_exposes_verify_without_syncing(saved_dialog, service, saved):
    app, view = saved_dialog
    verify(saved_dialog, service, remember=True)
    view.disconnect()
    assert not view.setup_panel.isVisible()
    view.load_saved_button.click()
    wait(app, lambda: not view.busy)
    assert view.setup_button.isChecked() and view.connect_button.isVisible()
    assert view.credential.text() == service[2]
    assert not view.sync_button.isEnabled()
    assert service[3] == ["session_info"]



saved_dialog = vault_dialog_fixture
