"""A restored/divergent authority cannot receive queued work before frontier review."""

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy

import httpx
import pytest
from test_continuous_sync import control as control
from test_continuous_sync import enrolled as enrolled
from test_continuous_sync import research as research
from test_continuous_sync import run as run_control
from test_continuous_sync import service as service
from test_sync_client import client as plain_client
from test_sync_client import edit, saved
from test_sync_client import pair as pair
from test_sync_http import endpoint as endpoint
from test_sync_http import request, running

from paper_daily.sync_http import HttpTransport, make_server
from paper_daily.sync_journal import SyncHistoryAdvanced, SyncHistoryUnavailable
from paper_daily.sync_service import ReferenceService


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


def test_http_restart_refuses_existing_session_without_acknowledging_local_work(pair):
    from paper_daily.sync_http import make_server

    service, client, _, token, _ = pair
    edit(client, "Keep this offline note")
    before = snapshot(client.journal.path)
    first = make_server(service)
    with running(first) as url:
        transport = HttpTransport(url)
        transport.session_info(token)
    try:
        with running(make_server(service, port=first.server_port)):
            for _ in range(2):
                with pytest.raises(SyncHistoryUnavailable):
                    client.sync_once(transport, token)
                assert snapshot(client.journal.path) == before and service.pull(token) == []
            with pytest.raises(PermissionError):
                transport.pull("wrong-token")
            with pytest.raises(SyncHistoryUnavailable):
                transport.blob_read(token, "a" * 64, 1, 0, 1)
            with HttpTransport(url) as reconnected:
                assert client.sync_once(reconnected, token)["pending"] == 0
            assert len(service.pull(token)) == 1
    finally:
        transport.close()


@pytest.mark.parametrize(
    "offer", [None, "invalid", ["a" * 32, "b" * 32]],
    ids=["missing", "malformed", "duplicate"],
)
def test_transport_requires_one_valid_instance_before_sending_private_content(offer):
    from test_sync_http import operation

    calls = []

    def reply(request):
        calls.append(request.url.path)
        headers = [("content-type", "application/json")]
        if offer is not None:
            headers.extend(("X-Paperfact-Sync-Instance", value)
                           for value in (offer if isinstance(offer, list) else [offer]))
        body = json.dumps(dict(workspace_id="workspace", device_id="a")).encode()
        return httpx.Response(200, stream=httpx.ByteStream(body), headers=headers)

    with HttpTransport("https://fixture.invalid") as transport:
        transport._client.close()
        transport._client = httpx.Client(transport=httpx.MockTransport(reply))
        with pytest.raises(SyncHistoryUnavailable):
            transport.push("fixture-token", operation())
    assert calls == ["/v1/session/info"]


def test_missing_execution_guard_cannot_be_silently_downgraded(endpoint):
    service, token, url = endpoint
    body = b'{"after":0,"limit":100}'
    headers = [("Authorization", "Bearer " + token), ("Content-Type", "application/json"),
               ("Content-Length", str(len(body)))]
    code, _, value = request(url, token, headers=headers, body=body)
    assert code == 428 and json.loads(value) == {"error": "sync_session_changed"}
    assert service.pull(token) == []


def test_late_python_identity_cannot_replace_an_already_pinned_execution():
    entered, release = threading.Event(), threading.Event()
    calls = []
    body = json.dumps(dict(workspace_id="workspace", device_id="a")).encode()

    class Delayed(httpx.SyncByteStream):
        def __iter__(self):
            entered.set()
            assert release.wait(5)
            yield body

    def reply(request):
        calls.append(request.url.path)
        first = len(calls) == 1
        return httpx.Response(200, stream=Delayed() if first else httpx.ByteStream(body),
            headers={"content-type": "application/json",
                     "X-Paperfact-Sync-Instance": ("a" if first else "b") * 32})

    with HttpTransport("https://fixture.invalid") as transport:
        transport._client.close()
        transport._client = httpx.Client(transport=httpx.MockTransport(reply))
        with ThreadPoolExecutor(max_workers=1) as pool:
            old = pool.submit(transport.session_info, "fixture-token")
            try:
                assert entered.wait(5)
                assert transport.session_info("fixture-token")["device_id"] == "a"
            finally:
                release.set()
            with pytest.raises(SyncHistoryUnavailable):
                old.result(timeout=5)
        assert transport.session_info("fixture-token")["device_id"] == "a"


def test_verified_http_keeps_acknowledged_proof_across_lost_pull_and_restart(pair, monkeypatch):
    authority, local, peer, token, peer_token = pair
    with running(make_server(authority)) as url, HttpTransport(url) as transport:
        transport.session_info(token)
        edit(local, "First verified note")
        local.sync_verified_once(transport, token)
        assert local.history_checkpoint() == authority.history_page(token)["checkpoint"]
        before = local.status()["cursor"]
        edit(local, "Accepted before lost delivery")
        original = transport.history_page

        def delayed(*args, **kwargs):
            if (kwargs.get("after") == before and kwargs.get("limit") == 100
                    and local.history_checkpoint(acknowledged=True)["sequence"] > before):
                raise ConnectionError("Synthetic lost receive")
            return original(*args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(transport, "history_page", delayed)
            with pytest.raises(ConnectionError, match="Synthetic"):
                local.sync_verified_once(transport, token)
        assert local.status()["cursor"] == before
        assert local.status()["awaiting_receipts"] == 1
        accepted = local.history_checkpoint(acknowledged=True)
        assert accepted["sequence"] == before + 1
        restarted = plain_client(local.journal.path, "a")
        assert restarted.history_checkpoint(acknowledged=True) == accepted
        # A rollback between preflight and receive must not falsely finish the pass.
        retained = restarted.history_checkpoint()
        older_tail = {
            "version": 1, "workspace_id": restarted.journal.workspace_id,
            "after": retained, "events": [], "checkpoint": retained, "caught_up": True,
        }
        unchanged = snapshot(restarted.journal.path)
        for _ in range(2):
            with pytest.raises(SyncHistoryUnavailable, match="predates an acknowledged"):
                restarted.receive_history(older_tail)
            assert snapshot(restarted.journal.path) == unchanged
            assert saved(restarted)["body"] == "Accepted before lost delivery"
            assert restarted.status()["awaiting_receipts"] == 1
            assert restarted.history_checkpoint(acknowledged=True) == accepted

        def rolled_back_tail(*args, **kwargs):
            if kwargs.get("after") == before and kwargs.get("limit") == 100:
                return deepcopy(older_tail)
            return original(*args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(transport, "history_page", rolled_back_tail)
            with pytest.raises(SyncHistoryUnavailable, match="predates an acknowledged"):
                restarted.sync_verified_once(transport, token)
        assert snapshot(restarted.journal.path) == unchanged
        edit(restarted, "Causal edit after restart")
        restarted.sync_verified_once(transport, token)
        assert saved(restarted)["body"] == "Causal edit after restart"
        assert restarted.status()["pending"] == restarted.status()["awaiting_receipts"] == 0
        assert restarted.history_checkpoint() == authority.history_page(token)["checkpoint"]
        edit(restarted, "Retry independent local edit", identity="raced-local")
        rival = edit(peer, "Other device advanced history", identity="raced-peer")
        verified = authority.push_verified
        raced = []

        def concurrent_writer(*args, **kwargs):
            if not raced:
                raced.append(authority.push(peer_token, rival))
            return verified(*args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(authority, "push_verified", concurrent_writer)
            with pytest.raises(SyncHistoryAdvanced):
                restarted.sync_verified_once(transport, token)
        assert restarted.status()["pending"] == 1
        restarted.sync_verified_once(transport, token)
        assert saved(restarted, identity="raced-local")["body"] == "Retry independent local edit"
    peer.sync_verified_once(authority, peer_token)
    assert saved(peer)["body"] == "Causal edit after restart"


def test_verified_ack_and_receive_proofs_roll_back_with_their_transactions(pair, monkeypatch):
    authority, local, peer, token, peer_token = pair
    edit(local, "One durable operation")
    with sqlite3.connect(local.journal.path) as conn:
        conn.execute("CREATE TRIGGER reject_ack_proof BEFORE UPDATE OF ack_sequence "
                     "ON paperfact_sync_history_checkpoint BEGIN "
                     "SELECT RAISE(ABORT,'Synthetic proof storage failure'); END")
    with pytest.raises(sqlite3.DatabaseError, match="Synthetic"):
        local.sync_verified_once(authority, token)
    assert local.status()["pending"] == 1 and local.status()["awaiting_receipts"] == 0
    assert local.history_checkpoint(acknowledged=True)["sequence"] == 0
    assert len(authority.pull(token)) == 1
    with sqlite3.connect(local.journal.path) as conn:
        conn.execute("DROP TRIGGER reject_ack_proof")
    local.sync_verified_once(authority, token)
    assert len(authority.pull(token)) == 1 and local.status()["pending"] == 0
    page = authority.history_page(peer_token, checkpoint=peer.history_checkpoint())
    with sqlite3.connect(peer.journal.path) as conn:
        conn.execute("CREATE TRIGGER reject_receive_proof BEFORE UPDATE OF sequence "
                     "ON paperfact_sync_history_checkpoint BEGIN "
                     "SELECT RAISE(ABORT,'Synthetic receive failure'); END")
    before = snapshot(peer.journal.path)
    with pytest.raises(sqlite3.DatabaseError, match="Synthetic"):
        peer.receive_history(page)
    assert snapshot(peer.journal.path) == before and saved(peer) is None
    with sqlite3.connect(peer.journal.path) as conn:
        conn.execute("DROP TRIGGER reject_receive_proof")
    peer.receive_history(page)
    assert saved(peer)["body"] == "One durable operation"
    assert peer.status()["cursor"] == peer.history_checkpoint()["sequence"] == 1
    edit(local, "Keep the operation when an acknowledgment proof is corrupt")
    verified = authority.push_verified

    def invalid_ack(*args, **kwargs):
        response = verified(*args, **kwargs)
        response["checkpoint"]["sha256"] = "0" * 64
        return response

    with monkeypatch.context() as patch:
        patch.setattr(authority, "push_verified", invalid_ack)
        with pytest.raises(SyncHistoryUnavailable, match="proof"):
            local.sync_verified_once(authority, token)
    assert local.status()["pending"] == 1 and local.status()["awaiting_receipts"] == 0
    assert local.history_checkpoint()["sequence"] == 1
    local.sync_verified_once(authority, token)
    assert local.status()["pending"] == 0 and len(authority.pull(token)) == 2



def test_verified_legacy_replay_is_bounded_and_different_past_cannot_upload(
    pair, monkeypatch, tmp_path
):
    authority, local, _peer, token, _peer_token = pair
    for text in ("Original", "Second", "Last"):
        edit(local, text)
        local.sync_once(authority, token)
    assert local.history_checkpoint()["sequence"] == 0
    edit(local, "Unsent work")
    pending = local.journal.pending(1000)
    for expected in (1, 2):
        result = local.sync_verified_once(authority, token, limit=1)
        assert result["history_preparing"] and result["pushed"] == 0
        assert local.history_checkpoint()["sequence"] == expected
        assert local.journal.pending(1000) == pending and saved(local)["body"] == "Unsent work"
    local.sync_verified_once(authority, token, limit=1)
    assert local.status()["pending"] == 0
    edit(local, "Preserve this pending note")
    fork = ReferenceService(tmp_path / "different-past.db")
    fork_token = fork.enroll("workspace", "a")
    for index, event in enumerate(authority.pull(token)):
        operation = deepcopy(event["operation"])
        if index == 0:
            operation["payload"]["body"] = "Different historical branch"
        fork.push(fork_token, operation)
    cursor = local.status()["cursor"]
    assert fork.pull(fork_token, after=cursor - 1) == authority.pull(token, after=cursor - 1)
    before_fork_local = snapshot(local.journal.path)
    with pytest.raises(SyncHistoryUnavailable):
        local.sync_verified_once(fork, fork_token)
    assert snapshot(local.journal.path) == before_fork_local
    assert fork.pull(fork_token)[-1]["sequence"] == cursor
    original = authority.push_verified
    before_events = authority.pull(token)
    before_local = snapshot(local.journal.path)

    def changed_after_preflight(*args, **kwargs):
        with sqlite3.connect(authority.path) as conn:
            conn.execute("UPDATE sync_history SET sha256=? WHERE workspace=? AND sequence=?",
                         ("0" * 64, "workspace", kwargs["checkpoint"]["sequence"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(authority, "push_verified", changed_after_preflight)
    with pytest.raises(SyncHistoryUnavailable):
        local.sync_verified_once(authority, token)
    assert authority.pull(token) == before_events and snapshot(local.journal.path) == before_local


def test_verified_receive_rejects_missing_or_changed_page_without_mutation(pair):
    authority, local, peer, token, peer_token = pair
    edit(local, "Retained source")
    local.sync_verified_once(authority, token)
    page = authority.history_page(peer_token, checkpoint=peer.history_checkpoint())
    before = snapshot(peer.journal.path)
    with pytest.raises(SyncHistoryUnavailable, match="support"):
        peer.sync_verified_once(object(), peer_token)
    assert snapshot(peer.journal.path) == before
    requests = []

    def unsupported(request):
        requests.append(request.url.path)
        return httpx.Response(404)

    with HttpTransport("http://127.0.0.1:1") as transport:
        transport._client.close()
        transport._client = httpx.Client(transport=httpx.MockTransport(unsupported))
        transport._instance = "a" * 32
        with pytest.raises(SyncHistoryUnavailable, match="verified history support"):
            peer.sync_verified_once(transport, peer_token)
    assert requests == ["/v1/history/pull"] and snapshot(peer.journal.path) == before
    for mutation in ("missing", "digest", "record", "workspace", "version", "empty_partial"):
        offered = deepcopy(page)
        if mutation == "missing":
            offered.pop("checkpoint")
        elif mutation == "digest":
            offered["checkpoint"]["sha256"] = "0" * 64
        elif mutation == "record":
            offered["events"][0] = offered["events"][0].replace("Retained source", "Changed source")
        elif mutation == "workspace":
            offered["workspace_id"] = "another-workspace"
        elif mutation == "version":
            offered["version"] = True
        else:
            offered["events"] = []
            offered["checkpoint"] = offered["after"]
            offered["caught_up"] = False
        with pytest.raises(SyncHistoryUnavailable):
            peer.receive_history(offered)
        assert snapshot(peer.journal.path) == before

    peer.receive_history(page)
    edit(local, "First concurrent branch")
    edit(peer, "Keep this conflicting branch")
    local.sync_verified_once(authority, token)
    peer.sync_verified_once(authority, peer_token)
    assert peer.status()["conflicts"] == 1
    assert saved(peer)["body"] == "First concurrent branch"
    assert peer.history(conflicts_only=True)[0]["operation"]["payload"]["body"] == (
        "Keep this conflicting branch")

    local.sync_verified_once(authority, token)
    legacy = edit(local, "Retain an older client's unreceived acknowledgment")
    event = authority.push(token, legacy)
    local.journal.acknowledge(legacy["operation_id"], event["sequence"])
    before_legacy = snapshot(local.journal.path)
    with pytest.raises(SyncHistoryUnavailable, match="explicit history review"):
        local.sync_verified_once(authority, token)
    assert snapshot(local.journal.path) == before_legacy
    assert local.status()["awaiting_receipts"] == 1
