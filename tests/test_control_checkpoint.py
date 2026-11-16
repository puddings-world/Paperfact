"""Observed control prefixes survive reconnect; no live credentials or research."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from test_sync_http import running
from test_sync_recovery import research as research_fixture

from paper_daily import sync_admin
from paper_daily.sync_http import HttpTransport, make_server
from paper_daily.sync_journal import SyncHistoryUnavailable

research = research_fixture


def rewind(service, snapshot, marker):
    with closing(sqlite3.connect(snapshot)) as source, closing(
        sqlite3.connect(service.path)
    ) as target:
        source.backup(target)
    (service.path.parent / sync_admin.MARKER).write_bytes(marker)


def capture(service, destination):
    with closing(sqlite3.connect(service.path)) as source, closing(
        sqlite3.connect(destination)
    ) as target:
        source.backup(target)
    return (service.path.parent / sync_admin.MARKER).read_bytes()


def test_observed_control_prefix_is_checked_in_the_actual_transaction(tmp_path):
    state = tmp_path / "authority"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    token = service.enroll("workspace", "desktop")
    initial = service.control_session(token)["checkpoint"]
    snapshot = tmp_path / "earlier.sqlite"
    marker = capture(service, snapshot)
    service.rename_device(token, "desktop", "Renamed")
    response = service.control_session(token, initial)
    latest = response["checkpoint"]
    assert response["accepted"] == initial and latest["sequence"] > initial["sequence"]
    with service.control_execution(initial):
        assert service.session_info(token)["device_id"] == "desktop"
    rewind(service, snapshot, marker)
    # The retained local marker/SQL are mutually valid and token still authenticates.
    assert service.session_info(token)["device_id"] == "desktop"
    with pytest.raises(SyncHistoryUnavailable), service.control_execution(latest):
        service.session_info(token)
    with pytest.raises(SyncHistoryUnavailable):
        service.control_session(token, latest)
    assert service.control_session(token)["checkpoint"] == initial


def test_http_transport_keeps_control_knowledge_across_reconnect_and_refuses_rollback(tmp_path):
    state = tmp_path / "authority"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    token = service.enroll("workspace", "desktop")
    snapshot = tmp_path / "earlier.sqlite"
    marker = capture(service, snapshot)
    saved = [None]
    identity = dict(workspace_id="workspace", device_id="desktop")

    def remember(point, _known):
        saved[0] = point

    with running(make_server(service)) as endpoint:
        with HttpTransport(endpoint) as transport:
            transport.bind_control_checkpoint(lambda: saved[0], remember, identity)
            assert transport.session_info(token) == identity
            first = json.loads(json.dumps(saved[0]))
            service.rename_device(token, "desktop", "Renamed")
            assert transport.session_info(token) == identity
            assert saved[0]["sequence"] > first["sequence"]
        latest = json.loads(json.dumps(saved[0]))
        rewind(service, snapshot, marker)
        with HttpTransport(endpoint) as transport:
            transport.bind_control_checkpoint(lambda: saved[0], remember, identity)
            with pytest.raises(SyncHistoryUnavailable):
                transport.session_info(token)
        assert saved[0] == latest


def test_desktop_connection_retains_control_scope_across_restart(tmp_path, research):
    from paper_daily.workspace_service import Ticket
    from paper_daily.workspace_sync import SyncSession

    database = research[0]
    state = tmp_path / "official"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    token = service.enroll("workspace", "origin-device")
    snapshot = tmp_path / "initial.sqlite"
    marker = capture(service, snapshot)
    with running(make_server(service)) as endpoint:
        session = SyncSession(database)
        session.connect(endpoint, "workspace", "origin-device", token, Ticket())
        service.rename_device(token, "origin-device", "Travel laptop")
        with session.authorized(Ticket()) as (transport, current, _identity, _live):
            assert transport.session_info(current)["device_id"] == "origin-device"
        session.disconnect()
        with sqlite3.connect(database) as conn:
            saved = conn.execute(
                "SELECT key,value FROM kv WHERE key LIKE 'ui.sync.control.%'"
            ).fetchall()
        assert len(saved) == 1 and token not in saved[0][1]
        latest = json.loads(saved[0][1])["checkpoint"]
        rewind(service, snapshot, marker)
        reopened = SyncSession(database)
        with pytest.raises(SyncHistoryUnavailable):
            reopened.connect(endpoint, "workspace", "origin-device", token, Ticket())
        assert not reopened.summary()["authenticated"]
        with sqlite3.connect(database) as conn:
            value = conn.execute("SELECT value FROM kv WHERE key=?", (saved[0][0],)).fetchone()[0]
            assert json.loads(value)["checkpoint"] == latest
            assert conn.execute("SELECT count(*) FROM notes").fetchone()[0] > 0


def test_device_control_compare_and_swap_cancellation_and_private_capture(research):
    from paper_daily.sync_capture import CaptureConnection, install
    from paper_daily.workspace_control import ControlKnowledge
    from paper_daily.workspace_service import Cancelled, Ticket

    database, client, *_ = research
    conn = sqlite3.connect(database, factory=CaptureConnection)
    try:
        conn.execute("BEGIN")
        install(conn, workspace_id="workspace", device_id="origin-device")
        conn.commit()
    finally:
        conn.close()
    pending = len(client.journal.pending())
    ticket = Ticket()
    identity = dict(workspace_id="workspace", device_id="origin-device")
    store = ControlKnowledge(database, identity, ticket.check)
    first = dict(authority_id="11111111-1111-4111-8111-111111111111", sequence=1, sha256="a" * 64)
    latest = dict(first, sequence=2, sha256="b" * 64)
    assert store.load() is None
    store.remember(first, None)
    store.remember(latest, first)
    with pytest.raises(SyncHistoryUnavailable):
        store.remember(first, None)
    with pytest.raises(SyncHistoryUnavailable):
        store.remember(first, latest)
    assert store.load() == latest and len(client.journal.pending()) == pending
    foreign = ControlKnowledge(database, dict(identity, device_id="another"), ticket.check)
    assert foreign.load() is None
    ticket.cancel()
    with pytest.raises(Cancelled):
        store.remember(dict(latest, sequence=3), latest)
    assert ControlKnowledge(database, identity, lambda: None).load() == latest


@pytest.mark.parametrize("rollback", [False, True])
def test_join_stage_and_published_workspace_retain_control_knowledge(tmp_path, research, rollback):
    from paper_daily import sync_bootstrap
    from paper_daily.workspace_control import ControlKnowledge
    from paper_daily.workspace_service import Ticket
    from paper_daily.workspace_sync import SyncSession

    database, client, *_ = research
    state = tmp_path / "join-authority"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    original = service.enroll("workspace", "origin-device")
    client.sync_once(service, original)
    token = service.enroll("workspace", "travel-device")
    snapshot = tmp_path / "join-old.sqlite"
    marker = capture(service, snapshot)
    service.rename_device(token, "travel-device", "Travel laptop")
    identity = dict(workspace_id="workspace", device_id="travel-device")
    destination = tmp_path / "joined"
    with running(make_server(service)) as endpoint:
        session = SyncSession(database)
        session.connect(endpoint, **identity, token=token, ticket=Ticket())
        partial = sync_bootstrap.join(session, destination, Ticket(), max_pages=1)
        assert partial["state"] == "catching_up" and not destination.exists()
        stage = Path(partial["stage"]) / "workspace" / "papers.db"
        retained = ControlKnowledge(stage, identity, lambda: None).load()
        assert retained is not None
        if rollback:
            session.disconnect()
            # Simulate reopening an older source workspace while keeping the newer join stage.
            with sqlite3.connect(database) as conn:
                conn.execute("DELETE FROM kv WHERE key LIKE 'ui.sync.control.%'")
            rewind(service, snapshot, marker)
            session = SyncSession(database)
            session.connect(endpoint, **identity, token=token, ticket=Ticket())
            with pytest.raises(SyncHistoryUnavailable):
                sync_bootstrap.join(session, destination, Ticket())
            assert not destination.exists()
            assert ControlKnowledge(stage, identity, lambda: None).load() == retained
        else:
            result = sync_bootstrap.join(session, destination, Ticket())
            assert result["state"] == "metadata_ready"
            joined = ControlKnowledge(destination / "papers.db", identity, lambda: None)
            assert joined.load() == retained
            reopened = SyncSession(destination / "papers.db")
            reopened.connect(endpoint, **identity, token=token, ticket=Ticket())
            assert reopened.summary()["authenticated"]


def test_http_request_requires_control_and_rechecks_after_authentication(tmp_path, monkeypatch):
    import httpx

    from paper_daily.sync_http import _control_encode

    state = tmp_path / "request-authority"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    token = service.enroll("workspace", "desktop")
    snapshot = tmp_path / "request-old.sqlite"
    marker = capture(service, snapshot)
    service.rename_device(token, "desktop", "Newer state")
    with running(make_server(service)) as endpoint, HttpTransport(endpoint) as transport:
        transport.session_info(token)
        point = transport.control_checkpoint()
        headers = {"Authorization": "Bearer " + token,
                   "X-Paperfact-Sync-Instance": transport._instance}
        body = dict(after=0, limit=100)
        with httpx.Client(base_url=endpoint, headers=headers) as raw:
            assert raw.post("/v1/pull", json=body).status_code == 428
            assert raw.post("/v1/pull", json=body, headers={
                "X-Paperfact-Control-Checkpoint": "invalid"}).status_code == 400
            guarded = {"X-Paperfact-Control-Checkpoint": _control_encode(point)}
            assert raw.post("/v1/pull", json=body, headers=guarded).status_code == 200
            original = service.pull

            def changed_between_auth_and_actual_read(*args, **kwargs):
                rewind(service, snapshot, marker)
                return original(*args, **kwargs)

            monkeypatch.setattr(service, "pull", changed_between_auth_and_actual_read)
            response = raw.post("/v1/pull", json=body, headers=guarded)
            assert response.status_code == 412
            assert response.json() == {"error": "sync_history_unavailable"}
