import gc
import sqlite3

import pytest
from test_workspace_sync import Native, connect
from test_workspace_sync import enrolled as enrolled_fixture
from test_workspace_sync import research as research_fixture
from test_workspace_sync import service as service_fixture

from paper_daily import sync_bootstrap
from paper_daily.workspace_service import Cancelled, Ticket
from paper_daily.workspace_sync import SyncSession, SyncStopped

research = research_fixture
enrolled = enrolled_fixture
service = service_fixture


def new_device(service):
    controller, authority, _, _ = service
    connect(service)
    controller.sync(Ticket())
    token = authority.enroll("workspace", "new-device")
    controller.connect("http://127.0.0.1:8765", "workspace", "new-device", token, Ticket())
    return token


def test_restart_resumes_durable_prefix_without_old_device_outbox(service, tmp_path):
    token = new_device(service)
    controller, authority, _, calls = service
    destination = tmp_path / "joined"
    first = sync_bootstrap.join(controller, destination, Ticket(), max_pages=1)
    assert first["state"] == "catching_up" and not destination.exists()
    restarted = SyncSession(
        controller.workspace.path,
        transport_factory=lambda endpoint: Native(endpoint, authority, calls),
    )
    assert not restarted.summary()["authenticated"]
    restarted.connect("http://127.0.0.1:8765", "workspace", "new-device", token, Ticket())
    result = sync_bootstrap.join(restarted, destination, Ticket())
    assert result["state"] == "metadata_ready"
    with sqlite3.connect(destination / "papers.db") as conn:
        assert conn.execute("SELECT body FROM notes").fetchall() == [("Saved research",)]
        assert conn.execute("SELECT COUNT(*) FROM paperfact_sync_operations").fetchone() == (0,)


def test_cancel_after_final_path_registration_is_resumable(service, tmp_path, monkeypatch):
    new_device(service)
    original = sync_bootstrap._register_final_paths
    ticket = Ticket()

    def cancel_after(*args):
        original(*args)
        ticket.cancel()

    monkeypatch.setattr(sync_bootstrap, "_register_final_paths", cancel_after)
    destination = tmp_path / "joined"
    with pytest.raises(Cancelled):
        sync_bootstrap.join(service[0], destination, ticket)
    assert not destination.exists()
    monkeypatch.setattr(sync_bootstrap, "_register_final_paths", original)
    assert sync_bootstrap.join(service[0], destination, Ticket())["state"] == "metadata_ready"
    with sqlite3.connect(destination / "papers.db") as conn:
        assert conn.execute("SELECT blob_root FROM document_reader_paths").fetchone() == (
            str(destination / "blobs"),
        )


def test_final_publication_failure_preserves_resumable_stage(service, tmp_path, monkeypatch):
    new_device(service)
    original = sync_bootstrap.publish_directory
    destination = tmp_path / "joined"

    def fail_final(source, target):
        if target == destination:
            raise OSError("fixture publication failure")
        original(source, target)

    monkeypatch.setattr(sync_bootstrap, "publish_directory", fail_final)
    with pytest.raises(OSError):
        sync_bootstrap.join(service[0], destination, Ticket())
    assert not destination.exists()
    monkeypatch.setattr(sync_bootstrap, "publish_directory", original)
    assert sync_bootstrap.join(service[0], destination, Ticket())["state"] == "metadata_ready"


def test_current_device_cannot_be_cloned_into_new_directory(service, tmp_path):
    connect(service)
    with pytest.raises(ValueError, match="newly issued"):
        sync_bootstrap.join(service[0], tmp_path / "clone", Ticket())
    assert not list(tmp_path.glob(".paperfact-join-*"))


def test_lost_accepted_response_retries_same_operation_without_duplicate(service, monkeypatch):
    controller, authority, token, _ = service
    connect(service)
    original = authority.push

    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise ConnectionError("fixture lost response")

    monkeypatch.setattr(authority, "push", lost)
    with pytest.raises(ConnectionError):
        controller.sync(Ticket())
    assert controller.summary()["state"] == "offline"
    assert len(authority.pull(token)) == 1
    monkeypatch.setattr(authority, "push", original)
    result = controller.sync(Ticket())
    events = authority.pull(token)
    assert result["pending"] == 0
    assert len({event["operation"]["operation_id"] for event in events}) == len(events)


def test_replaced_source_after_remote_accept_does_not_ack_into_replacement(
    service, enrolled, monkeypatch
):
    controller, authority, _, _ = service
    connect(service)
    original = authority.push
    # The shared legacy fixture uses sqlite connection context managers, which
    # end transactions but leave cyclic wrappers for GC. Close those before
    # simulating an external file replacement on Windows.
    gc.collect()
    database = enrolled[0]
    saved = database.with_suffix(".before-replacement")
    replacement = []

    def replace(*args, **kwargs):
        result = original(*args, **kwargs)
        database.rename(saved)
        database.write_bytes(saved.read_bytes())
        replacement.append(database.read_bytes())
        return result

    monkeypatch.setattr(authority, "push", replace)
    with pytest.raises(SyncStopped):
        controller.sync(Ticket())
    assert database.read_bytes() == replacement[0]
    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM paperfact_sync_operations WHERE server_revision IS NOT NULL"
        ).fetchone() == (0,)
