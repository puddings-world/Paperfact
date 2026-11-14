"""Actual committed outbox writes wake opted-in sync without remote echo loops."""

import sqlite3

import pytest
from PySide6.QtWidgets import QApplication, QWidget
from test_sync_connection_dialog import wait
from test_workspace_sync import connect
from test_workspace_sync import enrolled as enrolled
from test_workspace_sync import research as research
from test_workspace_sync import service as service

from paper_daily import store
from paper_daily.desktop.continuous_sync import controller_for
from paper_daily.desktop.workspace_changes import WorkspaceChanges
from paper_daily.sync_capture import CaptureConnection, expecting, observe_note


@pytest.fixture
def watched(service, enrolled, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(store, "DB_PATH", enrolled[0])
    owner = QWidget()
    owner.workspace_changes = WorkspaceChanges(owner)
    owner.workspace_changes.timer.stop()
    control = controller_for(owner, service[0])
    control.timer.stop()
    clock = [100.0]
    control.clock = lambda: clock[0]
    yield app, owner, control, clock
    control.stop()
    wait(app, lambda: not control.busy)
    owner.workspace_changes.close()
    owner.close()
    owner.deleteLater()
    app.processEvents()


def run(watched):
    app, _owner, control, _clock = watched
    control.tick()
    wait(app, lambda: not control.busy)


def edit_note(path, text):
    with sqlite3.connect(path, factory=CaptureConnection) as conn:
        local_id = conn.execute("SELECT id FROM notes ORDER BY id LIMIT 1").fetchone()[0]
        with expecting(conn, [observe_note(conn, local_id)]):
            conn.execute("UPDATE notes SET body=? WHERE id=?", (text, local_id))
            conn.commit()


def test_real_note_commit_debounces_and_acknowledgment_does_not_retrigger(
    watched, service, enrolled
):
    _app, owner, control, clock = watched
    connect(service)
    assert control.enable()
    run(watched)
    assert control.state == "idle" and control._next == 130
    owner.workspace_changes.poll()
    assert control.state == "idle" and control._next == 130
    before = len(service[3])
    edit_note(enrolled[0], "Travel note ready to sync")
    owner.workspace_changes.poll()
    assert control.state == "waiting" and control._next == 102
    for _ in range(20):
        owner.workspace_changes.poll()
        control.tick()
    assert len(service[3]) == before
    clock[0] = 102
    run(watched)
    assert control.state == "idle"
    accepted = service[1].pull(service[2])
    assert any(
        event["operation"]["payload"].get("body") == "Travel note ready to sync"
        for event in accepted
    )
    next_poll = control._next
    owner.workspace_changes.poll()
    owner.workspace_changes.poll()
    assert control.state == "idle" and control._next == next_poll
    control.tick()
    assert service[1].pull(service[2]) == accepted


def test_received_peer_change_does_not_schedule_an_extra_local_sync(
    watched, service, enrolled, tmp_path
):
    from test_workspace_sync import Native

    from paper_daily import sync_bootstrap
    from paper_daily.workspace_service import Ticket
    from paper_daily.workspace_sync import SyncSession

    _app, owner, control, clock = watched
    connect(service)
    control.enable()
    run(watched)
    owner.workspace_changes.poll()
    assert control.state == "idle" and control._next == 130
    endpoint = "http://127.0.0.1:8765"
    authority = service[1]
    peer_token = authority.enroll("workspace", "travel-device")

    def factory(url):
        return Native(url, authority, [])

    joining = SyncSession(enrolled[0], transport_factory=factory)
    joining.connect(endpoint, "workspace", "travel-device", peer_token, Ticket())
    destination = tmp_path / "travel"
    assert sync_bootstrap.join(joining, destination, Ticket())["state"] == "metadata_ready"
    joining.disconnect()
    peer = SyncSession(destination / "papers.db", transport_factory=factory)
    peer.connect(endpoint, "workspace", "travel-device", peer_token, Ticket())
    edit_note(destination / "papers.db", "Peer interpretation")
    peer.sync(Ticket())
    peer.disconnect()
    clock[0] = 130
    run(watched)
    assert control.state == "idle"
    with sqlite3.connect(enrolled[0]) as conn:
        assert conn.execute("SELECT body FROM notes").fetchone()[0] == "Peer interpretation"
    deadline = control._next
    owner.workspace_changes.poll()
    owner.workspace_changes.poll()
    assert control.state == "idle" and control._next == deadline


def test_uncommitted_rollback_and_exact_retry_do_not_duplicate_wakeups(watched, enrolled):
    from uuid import uuid4

    _app, owner, _control, _clock = watched
    client = enrolled[1]
    operation = client.new_graph_operation(
        "note", str(uuid4()), dict(paper_id=enrolled[3], body="Committed once")
    )
    events = []
    owner.workspace_changes.local_operations.connect(lambda: events.append(True))
    with (
        pytest.raises(RuntimeError, match="fixture rollback"),
        client.journal.transaction() as conn,
    ):
        client.journal.apply_in(conn, operation, client.writer)
        owner.workspace_changes.poll()
        assert events == []
        raise RuntimeError("fixture rollback")
    owner.workspace_changes.poll()
    assert events == []
    assert client.save(operation)["applied"]
    owner.workspace_changes.poll()
    assert events == [True]
    assert not client.save(operation)["applied"]
    owner.workspace_changes.poll()
    assert events == [True]


def test_local_write_cannot_enable_automatic_sync_without_consent(watched, service, enrolled):
    _app, owner, control, _clock = watched
    connect(service)
    before = list(service[3])
    edit_note(enrolled[0], "Keep local until consent")
    for _ in range(20):
        owner.workspace_changes.poll()
        control.tick()
    assert not control.enabled and not control.busy and control.state == "off"
    assert service[3] == before == ["session_info"]
    assert service[1].pull(service[2]) == []


def test_local_outbox_wakeup_respects_offline_backoff_then_retries(
    watched, service, enrolled, monkeypatch
):
    _app, owner, control, clock = watched
    connect(service)
    actual = service[0].sync
    attempts = []

    def offline(*_a, **_k):
        attempts.append(True)
        raise ConnectionError("fixture offline")

    monkeypatch.setattr(service[0], "sync", offline)
    control.enable()
    run(watched)
    assert control.state == "offline" and control._next == 110
    edit_note(enrolled[0], "Offline note retained")
    for _ in range(10):
        owner.workspace_changes.poll()
        control.tick()
    assert attempts == [True] and control._next == 110
    monkeypatch.setattr(service[0], "sync", actual)
    clock[0] = 110
    run(watched)
    owner.workspace_changes.poll()
    assert control.state == "idle"
    accepted = service[1].pull(service[2])
    assert any(
        event["operation"]["payload"].get("body") == "Offline note retained" for event in accepted
    )


def test_unavailable_reader_does_not_block_other_local_operations(watched, enrolled, monkeypatch):
    from paper_daily.manual_highlight_ops import capture_owner

    _app, owner, _control, _clock = watched
    with sqlite3.connect(enrolled[0]) as conn:
        local = conn.execute("SELECT local_id FROM research_paper_identity").fetchone()[0]
    observed = capture_owner(enrolled[0], local)
    watcher = owner.workspace_changes
    watcher.watch_research(observed, "old-reader")
    local_events, research_events = [], []
    watcher.local_operations.connect(lambda: local_events.append(True))
    watcher.research.connect(research_events.append)
    from paper_daily import reading_change_inputs

    def unavailable(*_a, **_k):
        raise ValueError("Fixture reader no longer owns its context")

    monkeypatch.setattr(reading_change_inputs, "read", unavailable)
    edit_note(enrolled[0], "Other valid local work")
    watcher.poll()
    assert local_events == [True] and research_events == []


def test_manual_sync_catches_new_write_before_observer_without_extra_wakeup(
    watched, service, enrolled
):
    from paper_daily.workspace_service import Ticket

    _app, owner, control, _clock = watched
    connect(service)
    control.enable()
    run(watched)
    owner.workspace_changes.poll()
    assert control.state == "idle"
    edit_note(enrolled[0], "Manual sync already delivered this")
    result = service[0].sync(Ticket())
    assert result["pending"] == 0 and result["awaiting_receipts"] == 0
    deadline = control._next
    owner.workspace_changes.poll()
    assert control.state == "idle" and control._next == deadline


def test_new_operation_acknowledged_before_pull_still_wakes_receipt_recovery(
    watched, service, enrolled
):
    _app, owner, control, clock = watched
    connect(service)
    control.enable()
    run(watched)
    owner.workspace_changes.poll()
    edit_note(enrolled[0], "Accepted but not received yet")
    client = enrolled[1]
    operation = next(
        op
        for op in client.journal.pending()
        if op["payload"].get("body") == "Accepted but not received yet"
    )
    event = service[1].push(service[2], operation)
    assert event["outcome"] == "accepted"
    client.journal.acknowledge(operation["operation_id"], event["sequence"])
    assert client.status()["cursor"] < event["sequence"]
    owner.workspace_changes.poll()
    assert control.state == "waiting" and control._next == 102
    clock[0] = 102
    run(watched)
    assert control.state == "idle"
    assert control.summary()["result"]["awaiting_receipts"] == 0
    deadline = control._next
    owner.workspace_changes.poll()
    assert control.state == "idle" and control._next == deadline
