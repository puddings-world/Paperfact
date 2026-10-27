import sqlite3
import threading
from pathlib import Path

import pytest
from test_sync_recovery import research as research_fixture

from paper_daily import sync_bootstrap
from paper_daily.sync_capture import CaptureConnection, install
from paper_daily.sync_http import HttpTransport, make_server
from paper_daily.sync_service import ReferenceService
from paper_daily.workspace_service import Ticket
from paper_daily.workspace_sync import EnrollmentRequired, SyncSession, SyncStopped

research = research_fixture


@pytest.fixture
def enrolled(research):
    path = research[0]
    conn = sqlite3.connect(path, factory=CaptureConnection)
    try:
        conn.execute("BEGIN")
        install(conn, workspace_id="workspace", device_id="origin-device")
        conn.commit()
    finally:
        conn.close()
    return research


class Native:
    def __init__(self, endpoint, authority, calls):
        with HttpTransport(endpoint) as validator:
            self.base_url = validator.base_url
        self.authority, self.calls = authority, calls

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append(name)
            return getattr(self.authority, name)(*args, **kwargs)

        return call


@pytest.fixture
def service(enrolled, tmp_path):
    authority = ReferenceService(tmp_path / "authority.sqlite")
    token = authority.enroll("workspace", "origin-device")
    calls = []
    controller = SyncSession(
        enrolled[0], transport_factory=lambda endpoint: Native(endpoint, authority, calls)
    )
    return controller, authority, token, calls


def connect(service):
    controller, _, token, _ = service
    return controller.connect(
        "http://127.0.0.1:8765", "workspace", "origin-device", token, Ticket()
    )


def test_connect_only_checks_identity_and_never_persists_token(service, enrolled):
    controller, _, token, calls = service
    before = enrolled[0].read_bytes()
    result = connect(service)
    assert result["state"] == "connected"
    assert calls == ["session_info"]
    assert token not in repr(result) and token not in enrolled[0].read_bytes().decode("latin1")
    assert enrolled[0].read_bytes() == before
    controller.disconnect()
    assert controller._token is None


def test_wrong_device_handshake_rejects_before_any_research(service):
    controller, authority, _, calls = service
    token = authority.enroll("workspace", "another-device")
    with pytest.raises(PermissionError):
        controller.connect("http://127.0.0.1:8765", "workspace", "origin-device", token, Ticket())
    assert calls == ["session_info"] and controller._token is None


def test_manual_sync_acknowledges_and_replays_without_duplicate_operations(service, enrolled):
    controller, authority, token, calls = service
    connect(service)
    expected = len(enrolled[1].journal.pending())
    result = controller.sync(Ticket())
    assert result["pushed"] == expected and result["received"] == expected
    assert result["caught_up"] and result["pending"] == result["awaiting_receipts"] == 0
    assert calls.index("session_info") < calls.index("push")
    again = controller.sync(Ticket())
    assert again["pushed"] == again["received"] == 0
    assert len(authority.pull(token)) == expected


def test_revocation_requires_reconnect_without_losing_outbox(service, enrolled):
    controller, authority, token, calls = service
    connect(service)
    expected = enrolled[1].journal.pending()
    authority.revoke(token)
    with pytest.raises(PermissionError):
        controller.sync(Ticket())
    assert enrolled[1].journal.pending() == expected
    assert controller.summary()["state"] == "reconnect" and controller._token is None
    assert "push" not in calls and "pull" not in calls


def test_unbound_nonempty_workspace_cannot_silently_enroll(research, tmp_path):
    authority = ReferenceService(tmp_path / "authority.sqlite")
    token = authority.enroll("workspace", "origin-device")
    calls = []
    controller = SyncSession(
        research[0], transport_factory=lambda endpoint: Native(endpoint, authority, calls)
    )
    controller.connect("http://127.0.0.1:8765", "workspace", "origin-device", token, Ticket())
    before = research[0].read_bytes()
    with pytest.raises(EnrollmentRequired):
        controller.sync(Ticket())
    assert calls == ["session_info"]
    assert research[0].read_bytes() == before


def test_switch_disconnect_during_push_preserves_retry_identity(service, enrolled, monkeypatch):
    controller, authority, token, calls = service
    connect(service)
    original = authority.push

    def late(*args, **kwargs):
        result = original(*args, **kwargs)
        controller.disconnect()
        return result

    monkeypatch.setattr(authority, "push", late)
    before = enrolled[1].journal.pending()
    with pytest.raises(SyncStopped):
        controller.sync(Ticket())
    assert enrolled[1].journal.pending() == before
    assert len(authority.pull(token)) == 1
    monkeypatch.setattr(authority, "push", original)
    connect(service)
    result = controller.sync(Ticket())
    assert result["pending"] == 0
    assert len(authority.pull(token)) == len(before)


def test_actual_http_join_replays_all_short_pages_and_activates_no_old_outbox(
    service, enrolled, tmp_path
):
    controller, authority, _, _ = service
    connect(service)
    controller.sync(Ticket())
    new_token = authority.enroll("workspace", "new-device")
    server = make_server(authority)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        remote = SyncSession(enrolled[0])
        remote.connect(
            f"http://127.0.0.1:{server.server_port}", "workspace", "new-device", new_token, Ticket()
        )
        destination = tmp_path / "new-workspace"
        first = sync_bootstrap.join(remote, destination, Ticket(), max_pages=1)
        assert first["state"] == "catching_up" and not destination.exists()
        assert first["cursor"] > 0
        result = sync_bootstrap.join(remote, destination, Ticket())
        assert result["state"] == "metadata_ready" and result["active_unchanged"]
        with sqlite3.connect(destination / "papers.db") as conn:
            assert conn.execute("SELECT body FROM notes").fetchall() == [("Saved research",)]
            assert (
                conn.execute("SELECT device FROM paperfact_sync_identity").fetchone()[0]
                == "new-device"
            )
            assert conn.execute("SELECT COUNT(*) FROM paperfact_sync_operations").fetchone()[0] == 0
            assert (
                conn.execute("SELECT COUNT(*) FROM paperfact_sync_inbox").fetchone()[0]
                == result["cursor"]
            )
            blob_root = conn.execute("SELECT blob_root FROM document_reader_paths").fetchone()[0]
            assert Path(blob_root) == destination / "blobs"
        again = sync_bootstrap.join(remote, destination, Ticket())
        assert again["state"] == "metadata_ready"
        assert new_token not in "".join(
            p.read_text(encoding="utf-8") for p in tmp_path.glob(".paperfact-join-*/request.json")
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_join_never_overwrites_nonempty_destination(service, tmp_path):
    controller, authority, _, _ = service
    token = authority.enroll("workspace", "new-device")
    controller.connect("http://127.0.0.1:8765", "workspace", "new-device", token, Ticket())
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep").write_text("keep")
    with pytest.raises(FileExistsError):
        sync_bootstrap.join(controller, existing, Ticket())
    assert (existing / "keep").read_text() == "keep"
    assert not list(tmp_path.glob(".paperfact-join-*"))


def test_unknown_event_is_not_skipped_or_published(service, enrolled, tmp_path, monkeypatch):
    controller, authority, _, _ = service
    connect(service)
    controller.sync(Ticket())
    token = authority.enroll("workspace", "new-device")
    controller.connect("http://127.0.0.1:8765", "workspace", "new-device", token, Ticket())
    original = authority.pull

    def bad(*args, **kwargs):
        events = original(*args, **kwargs)
        if events:
            events[0]["operation"]["entity_type"] = "future_unsupported_research"
        return events

    monkeypatch.setattr(authority, "pull", bad)
    destination = tmp_path / "new-workspace"
    with pytest.raises(ValueError):
        sync_bootstrap.join(controller, destination, Ticket())
    assert not destination.exists()
    staged = next(tmp_path.glob(".paperfact-join-*/workspace/papers.db"))
    with sqlite3.connect(staged) as conn:
        assert conn.execute("SELECT sequence FROM paperfact_sync_cursor").fetchone()[0] == 0
