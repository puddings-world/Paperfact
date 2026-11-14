"""Authenticated device actions retain local research and reject late sessions."""

import threading

import pytest
from test_sync_http import running
from test_workspace_sync import connect
from test_workspace_sync import enrolled as enrolled_fixture
from test_workspace_sync import research as research_fixture
from test_workspace_sync import service as service_fixture

from paper_daily.sync_http import HttpTransport, make_server
from paper_daily.workspace_devices import DeviceClient
from paper_daily.workspace_service import Cancelled, Ticket
from paper_daily.workspace_sync import EnrollmentRequired, SyncStopped

research = research_fixture
enrolled = enrolled_fixture
service = service_fixture


def test_real_http_client_list_label_revoke_preserves_research_and_outbox(service, enrolled):
    session, authority, token, _ = service
    authority.enroll("workspace", "peer")
    before, pending = enrolled[0].read_bytes(), enrolled[1].journal.pending()
    with running(make_server(authority)) as endpoint:
        session._factory = HttpTransport
        session.connect(endpoint, "workspace", "origin-device", token, Ticket())
        client = DeviceClient(session)
        assert len(client.catalog(Ticket())["devices"]) == 2
        assert client.rename("peer", "Phone", Ticket())["changed"]
        assert not client.rename("peer", "Phone", Ticket())["changed"]
        assert client.revoke("peer", Ticket())["changed"]
        assert not client.revoke("peer", Ticket())["changed"]
        assert client.catalog(Ticket())["devices"][1]["revoked"]
    assert enrolled[0].read_bytes() == before and enrolled[1].journal.pending() == pending
    assert authority.pull(token) == []


def test_revoked_session_requires_reconnect_without_touching_pending_work(service, enrolled):
    session, authority, token, calls = service
    connect(service)
    client = DeviceClient(session)
    before = enrolled[1].journal.pending()
    authority.revoke(token)
    with pytest.raises(PermissionError):
        client.catalog(Ticket())
    assert session.summary()["state"] == "reconnect" and not client.current()
    assert enrolled[1].journal.pending() == before
    assert "device_catalog" not in calls


@pytest.mark.parametrize("change", ["cancel", "disconnect", "workspace"])
def test_late_catalog_is_discarded_when_original_context_changes(
    service, tmp_path, monkeypatch, change
):
    session, authority, _, _ = service
    connect(service)
    client, ticket = DeviceClient(session), Ticket()
    original = authority.device_catalog

    def late(*args, **kwargs):
        result = original(*args, **kwargs)
        if change == "cancel":
            ticket.cancel()
        elif change == "disconnect":
            session.disconnect()
        else:
            session.workspace.current_path = lambda: tmp_path / "unopened.sqlite"
        return result

    monkeypatch.setattr(authority, "device_catalog", late)
    with pytest.raises((Cancelled, SyncStopped)):
        client.catalog(ticket)
    assert not (tmp_path / "unopened.sqlite").exists()


def test_current_device_revocation_is_local_disconnect_only(service):
    session, _, _, calls = service
    connect(service)
    before = list(calls)
    with pytest.raises(ValueError, match="Disconnect"):
        DeviceClient(session).revoke("origin-device", Ticket())
    assert calls == before and session.summary()["authenticated"]


def test_foreign_connection_cannot_manage_devices_for_local_workspace(service):
    session, authority, _, calls = service
    other = authority.enroll("foreign", "foreign-device")
    session.connect("http://127.0.0.1:8765", "foreign", "foreign-device", other, Ticket())
    with pytest.raises(EnrollmentRequired):
        DeviceClient(session).catalog(Ticket())
    assert calls == ["session_info"]


def test_duplicate_actions_are_one_job_and_identical_retry_is_idempotent(service, monkeypatch):
    session, authority, token, _ = service
    authority.enroll("workspace", "peer")
    connect(service)
    client = DeviceClient(session)
    entered, release = threading.Event(), threading.Event()
    original, calls, results = authority.rename_device, [], []

    def held(*args):
        calls.append(1)
        entered.set()
        assert release.wait(8)
        return original(*args)

    monkeypatch.setattr(authority, "rename_device", held)
    worker = threading.Thread(
        target=lambda: results.append(client.rename("peer", "Phone", Ticket()))
    )
    worker.start()
    try:
        assert entered.wait(8)
        with pytest.raises(SyncStopped):
            client.rename("peer", "Phone", Ticket())
    finally:
        release.set()
        worker.join(8)
    assert not worker.is_alive() and calls == [1] and results[0]["changed"]
    assert not client.rename("peer", "Phone", Ticket())["changed"]
    assert authority.device_catalog(token)["devices"][1]["label"] == "Phone"


def test_cancel_after_remote_commit_keeps_exact_result_for_refresh_retry(service, monkeypatch):
    session, authority, token, _ = service
    authority.enroll("workspace", "peer")
    connect(service)
    client, ticket = DeviceClient(session), Ticket()
    original = authority.rename_device

    def late(*args):
        result = original(*args)
        ticket.cancel()
        return result

    monkeypatch.setattr(authority, "rename_device", late)
    with pytest.raises(Cancelled):
        client.rename("peer", "Phone", ticket)
    assert authority.device_catalog(token)["devices"][1]["label"] == "Phone"
    monkeypatch.setattr(authority, "rename_device", original)
    assert not client.rename("peer", "Phone", Ticket())["changed"]


def test_pairing_uses_the_guarded_device_context_without_changing_local_research(service, enrolled):
    import secrets

    session, authority, _token, _calls = service
    connect(service)
    client, code = DeviceClient(session), secrets.token_urlsafe(32)
    before, pending = enrolled[0].read_bytes(), enrolled[1].journal.pending()
    created = client.create_pairing(code, Ticket())
    assert created["workspace_id"] == "workspace" and created["issuer_device_id"] == "origin-device"
    assert client.create_pairing(code, Ticket()) == created
    session.disconnect()
    with pytest.raises(SyncStopped):
        client.create_pairing(secrets.token_urlsafe(32), Ticket())
    assert enrolled[0].read_bytes() == before and enrolled[1].journal.pending() == pending
    assert authority.device_catalog(service[2])["devices"][0]["device_id"] == "origin-device"
