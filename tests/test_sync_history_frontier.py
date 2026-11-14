"""A restored/divergent authority cannot receive queued work before frontier review."""

import json
import sqlite3
from contextlib import closing
from copy import deepcopy

import pytest
from test_continuous_sync import control as control
from test_continuous_sync import enrolled as enrolled
from test_continuous_sync import research as research
from test_continuous_sync import run as run_control
from test_continuous_sync import service as service
from test_sync_client import edit
from test_sync_client import pair as pair
from test_sync_http import endpoint as endpoint
from test_sync_http import request

from paper_daily.sync_http import HttpTransport
from paper_daily.sync_journal import SyncHistoryUnavailable


def snapshot(path):
    with closing(sqlite3.connect(path)) as conn:
        return list(conn.iterdump())


@pytest.mark.parametrize("checkpoint", ["received", "acknowledged", "received-and-acknowledged"])
@pytest.mark.parametrize("mode", ["missing", "different", "matching"])
def test_frontier_is_checked_before_prepare_push_and_acknowledgment(pair, mode, checkpoint):
    service, client, _, token, _ = pair
    edit(client, "Accepted history")
    if checkpoint == "received-and-acknowledged":
        client.sync_once(service, token)
        edit(client, "Acknowledged newer history", identity="newer-accepted")
    received_cursor = client.status()["cursor"]
    if checkpoint != "received":
        class InterruptedPull:
            push = service.push

            def pull(self, token, after=0, limit=100):
                if after == received_cursor:
                    raise ConnectionError("Disconnected after acknowledgment")
                return service.pull(token, after, limit)

        with pytest.raises(ConnectionError):
            client.sync_once(InterruptedPull(), token)
        assert client.status()["cursor"] == received_cursor
    else:
        client.sync_once(service, token)
    edit(client, "Offline reading note", identity="pending-note")
    before = snapshot(client.journal.path)
    cursor, calls = len(service.pull(token)), []
    probes = [("pull", value - 1, 1) for value in dict.fromkeys(
        value for value in (client.status()["cursor"], cursor) if value
    )]

    class Transport:
        def pull(self, token, after=0, limit=100):
            calls.append(("pull", after, limit))
            events = service.pull(token, after, limit)
            if mode == "missing":
                return []
            if mode == "different" and after == cursor - 1:
                events = deepcopy(events)
                events[0]["operation"]["payload"]["body"] = "Different authority history"
                events[0]["head"]["operation"] = deepcopy(events[0]["operation"])
            return events

        def push(self, token, operation):
            calls.append(("push",))
            return service.push(token, operation)

    def prepare(operation):
        calls.append(("prepare",))
        return True

    if mode == "matching":
        assert client.sync_once(Transport(), token, prepare_push=prepare)["pending"] == 0
        assert calls[:len(probes) + 2] == probes + [("prepare",), ("push",)]
    else:
        for _ in range(2):
            with pytest.raises(SyncHistoryUnavailable):
                client.sync_once(Transport(), token, prepare_push=prepare)
            assert snapshot(client.journal.path) == before
        assert calls == (probes[:1] if mode == "missing" else probes) * 2
        assert len(service.pull(token)) == cursor


def test_http_cursor_ahead_is_categorical_and_does_not_leak_history(endpoint):
    service, token, url = endpoint
    code, _, body = request(url, token, body=b'{"after":5,"limit":1}')
    assert code == 412 and json.loads(body) == {"error": "sync_history_unavailable"}
    with HttpTransport(url) as transport:
        with pytest.raises(SyncHistoryUnavailable):
            transport.pull(token, after=5, limit=1)
        with pytest.raises(PermissionError):
            transport.pull("wrong-token", after=5, limit=1)
    assert service.pull(token) == []


def test_automatic_sync_pauses_for_history_review_without_touching_research(
    control, service, monkeypatch,
):
    from test_workspace_sync import connect

    from paper_daily.desktop.continuous_sync import status_text

    connect(service)
    _, _, controller, clock = control
    before, calls = snapshot(service[0].workspace.path), []

    def failed(*args):
        calls.append(True)
        raise SyncHistoryUnavailable("private history /private/path")

    monkeypatch.setattr(service[0], "sync", failed)
    controller.enable()
    run_control(control)
    assert not controller.enabled and controller.state == "history"
    assert "preserve" in status_text(controller.summary(), "en")
    assert "private" not in repr(controller.summary())
    clock[0] += 1000
    controller.local_changed()
    controller.tick()
    assert calls == [True] and snapshot(service[0].workspace.path) == before
