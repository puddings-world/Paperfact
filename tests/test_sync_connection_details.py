"""One paste fills connection settings without login or background-upload consent."""

import threading

import pytest
from test_sync_connection_dialog import dialog as dialog_fixture
from test_sync_connection_dialog import wait
from test_workspace_sync import enrolled as enrolled_fixture
from test_workspace_sync import research as research_fixture
from test_workspace_sync import service as service_fixture

from paper_daily.connection_vault import Connection

research = research_fixture
enrolled = enrolled_fixture
service = service_fixture
dialog = dialog_fixture


def packet(service):
    return Connection("http://127.0.0.1:8765", "workspace", "origin-device", service[2]).encoded()


def test_one_paste_fills_settings_but_requires_explicit_verified_connection(dialog, service):
    app, view = dialog
    view.connection_details.setText(packet(service))
    assert view.load_connection_details()
    wait(app, lambda: not view.busy)
    assert not view.connection_details.text()
    assert view.credential.text() == service[2]
    assert view.endpoint.text() == "http://127.0.0.1:8765"
    assert view.workspace_id.text() == "workspace" and view.device_id.text() == "origin-device"
    assert view.setup_panel.isVisible() and not view.remember_box.isChecked()
    assert service[3] == [] and not service[0].summary()["authenticated"]
    assert service[2] not in view.status.text()
    view.connect_button.click()
    wait(app, lambda: not view.busy)
    assert service[3] == ["session_info"] and service[0].summary()["authenticated"]
    assert not view.credential.text()


@pytest.mark.parametrize("body", ["", "not-json", '{"format":1,"format":1}', "x" * 2000])
def test_invalid_or_empty_details_preserve_fields_and_never_connect(dialog, service, body):
    app, view = dialog
    before = (view.endpoint.text(), view.workspace_id.text(), view.device_id.text())
    view.connection_details.setText(body)
    view.load_connection_details()
    wait(app, lambda: not view.busy)
    assert (view.endpoint.text(), view.workspace_id.text(), view.device_id.text()) == before
    assert not view.credential.text() and service[3] == []
    assert not view.connection_details.text()


@pytest.mark.parametrize("action", ["close", "workspace", "cancel"])
def test_held_parse_deduplicates_and_never_fills_after_context_change(
    dialog, service, monkeypatch, tmp_path, action
):
    app, view = dialog
    body = packet(service)
    started, release = threading.Event(), threading.Event()
    original = Connection.decoded
    calls = []

    def held(cls, value):
        calls.append(value)
        started.set()
        assert release.wait(8)
        return original(value)

    monkeypatch.setattr(Connection, "decoded", classmethod(held))
    view.connection_details.setText(body)
    try:
        assert view.load_connection_details()
        wait(app, started.is_set)
        for _ in range(20):
            assert not view.load_connection_details()
        if action == "close":
            assert not view.close()
        elif action == "workspace":
            service[0].workspace.current_path = lambda: tmp_path / "different.db"
            view._check_workspace()
        else:
            view.cancel()
    finally:
        release.set()
    wait(app, lambda: not view.busy)
    assert calls == [body] and service[3] == []
    assert not view.credential.text() and not view.connection_details.text()
