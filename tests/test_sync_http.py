"""Loopback-only transport acceptance; no real accounts or external network."""

import http.client
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from paper_daily import sync_http
from paper_daily.sync_http import HttpTransport, make_server
from paper_daily.sync_journal import SyncHistoryUnavailable
from paper_daily.sync_service import AuthorityInUseError, ReferenceService


def operation(identity="operation-a", *, workspace="workspace", device="a", body="Observation"):
    return {
        "version": 1,
        "operation_id": identity,
        "workspace_id": workspace,
        "device_id": device,
        "entity_type": "note",
        "entity_id": "note-" + identity,
        "action": "put",
        "base_revision": 0,
        "depends_on": None,
        "payload": {"paper_id": "paper-a", "body": body},
    }


@contextmanager
def running(server):
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.fixture
def endpoint(tmp_path):
    service = ReferenceService(tmp_path / "service.sqlite")
    token = service.enroll("workspace", "a")
    with running(make_server(service)) as base_url:
        yield service, token, base_url


def request(
    base_url,
    token,
    *,
    path="/v1/pull",
    method="POST",
    body=b'{"after":0,"limit":100}',
    headers=None,
):
    port = int(base_url.rsplit(":", 1)[1])
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        conn.putrequest(method, path)
        supplied = (
            headers
            if headers is not None
            else [
                ("Authorization", "Bearer " + token),
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
            ]
        )
        if headers is None and path != "/v1/session/info":
            code, offered, _ = request(base_url, token, path="/v1/session/info", body=b"{}")
            if code == 200:
                supplied.append(("X-Paperfact-Sync-Instance", offered["X-Paperfact-Sync-Instance"]))
        for name, value in supplied:
            conn.putheader(name, value)
        conn.endheaders(body)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def test_http_push_pull_replay_and_workspace_isolation(endpoint, monkeypatch):
    service, token, url = endpoint
    other = service.enroll("other-workspace", "a")
    peer = service.enroll("workspace", "b")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    with HttpTransport(url) as transport:
        first = transport.push(token, operation())
        assert first["sequence"] == 1
        assert transport.push(token, operation()) == first
        assert transport.pull(peer) == [first]
        assert transport.pull(other) == []
        with pytest.raises(PermissionError, match="authorization"):
            transport.push(other, operation("foreign"))
        assert transport.pull(peer, after=1) == []
    assert len(service.pull(token)) == 1


def test_revoked_token_and_invalid_credentials_are_rejected(endpoint):
    service, token, url = endpoint
    service.revoke(token)
    with HttpTransport(url) as transport:
        with pytest.raises(PermissionError):
            transport.pull(token)
        with pytest.raises(PermissionError):
            transport.pull("not-an-enrolled-token")
        with pytest.raises(PermissionError):
            transport.pull("contains\nnewline")
    status, _, body = request(url, token, headers=[("Content-Length", "0")])
    assert status == 401
    assert json.loads(body) == {"error": "authentication_required"}


@pytest.mark.parametrize(
    "body",
    [
        b'{"after":0,"after":1,"limit":100}',
        b'{"after":0,"limit":NaN}',
        b'{"after":0,"limit":true}',
        b'{"after":0,"limit":1001}',
        b'{"after":-1,"limit":1}',
        b'{"after":0,"limit":1,"token":"private"}',
        b"[]",
        b"not-json",
        b"\xff",
    ],
)
def test_malformed_json_is_fixed_error_without_echo(endpoint, body):
    service, token, url = endpoint
    status, headers, returned = request(url, token, body=body)
    assert status == 400
    assert returned == b'{"error":"invalid_request"}'
    assert "Access-Control-Allow-Origin" not in headers
    assert headers["Cache-Control"] == "no-store"
    assert service.pull(token) == []


@pytest.mark.parametrize(
    "path,method,status",
    [
        ("/v1/enroll", "POST", 404),
        ("/v1/revoke", "POST", 404),
        ("/v1/pull?token=not-logged", "POST", 404),
        ("/v1/pull", "GET", 405),
        ("/v1/pull", "OPTIONS", 405),
        ("/v1/pull", "TRACE", 405),
    ],
)
def test_only_exact_post_routes_exist(endpoint, path, method, status):
    _, token, url = endpoint
    actual, headers, body = request(url, token, path=path, method=method)
    assert actual == status
    assert "Access-Control-Allow-Origin" not in headers
    assert b"not-logged" not in body


@pytest.mark.parametrize(
    "mode,status",
    [
        ("missing-length", 411),
        ("chunked", 400),
        ("encoding", 400),
        ("duplicate-length", 400),
        ("duplicate-auth", 401),
        ("oversized", 413),
        ("wrong-media", 415),
    ],
)
def test_request_headers_are_bounded_and_unambiguous(endpoint, mode, status):
    service, token, url = endpoint
    headers = [("Authorization", "Bearer " + token), ("Content-Type", "application/json")]
    if mode != "missing-length":
        headers.append(
            ("Content-Length", str(sync_http.MAX_REQUEST_BYTES + 1) if mode == "oversized" else "0")
        )
    if mode == "chunked":
        headers.append(("Transfer-Encoding", "chunked"))
    elif mode == "encoding":
        headers.append(("Content-Encoding", "gzip"))
    elif mode == "duplicate-length":
        headers.append(("Content-Length", "0"))
    elif mode == "duplicate-auth":
        headers.append(("Authorization", "Bearer another-token"))
    elif mode == "wrong-media":
        headers[1] = ("Content-Type", "text/plain")
    actual, _, body = request(url, token, headers=headers, body=b"")
    assert actual == status
    assert token.encode() not in body
    assert service.pull(token) == []


def test_service_errors_never_echo_research_or_credentials(endpoint, monkeypatch, capsys):
    service, token, url = endpoint
    private = "private research that must not appear in an error"

    def failing(*args, **kwargs):
        raise RuntimeError(private + token)

    monkeypatch.setattr(service, "push", failing)
    status, _, body = request(
        url,
        token,
        path="/v1/push",
        body=json.dumps({"operation": operation(body=private)}).encode(),
    )
    assert status == 500
    assert body == b'{"error":"service_unavailable"}'
    output = capsys.readouterr()
    assert private not in output.out + output.err
    assert token not in output.out + output.err


def test_pull_returns_bounded_contiguous_prefix_and_resumes(endpoint, monkeypatch):
    service, token, url = endpoint
    events = [service.push(token, operation(f"op-{i}", body="x" * 150)) for i in range(7)]
    cap = len(sync_http._encode(events[0])) + 8
    monkeypatch.setattr(sync_http, "MAX_RESPONSE_BYTES", cap)
    collected, cursor = [], 0
    with HttpTransport(url) as transport:
        while cursor < 7:
            batch = transport.pull(token, after=cursor, limit=100)
            assert len(batch) == 1
            assert len(sync_http._encode(batch)) <= cap
            assert batch[0]["sequence"] == cursor + 1
            collected.extend(batch)
            cursor = batch[-1]["sequence"]
    assert collected == events


def test_oversized_single_event_never_returns_false_empty_success(endpoint, monkeypatch):
    service, token, url = endpoint
    service.push(token, operation())
    monkeypatch.setattr(sync_http, "MAX_RESPONSE_BYTES", 100)
    status, _, body = request(url, token)
    assert status == 500
    assert body == b'{"error":"service_unavailable"}'


@pytest.mark.parametrize("host", ["0.0.0.0", "localhost", "127.0.0.2", "example.test", "::"])
def test_reference_server_cannot_bind_public_or_ambiguous_host(tmp_path, host):
    with pytest.raises(ValueError, match="loopback"):
        make_server(ReferenceService(tmp_path / "service.db"), host=host)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test",
        "http://localhost",
        "http://127.0.0.2",
        "ftp://127.0.0.1",
        "http://name:password@127.0.0.1",
        "https://name@example.test",
        "http://127.0.0.1/base",
        "http://127.0.0.1?",
        "https://example.test#",
        "http://127.0.0.1:0",
        "http://127.0.0.1:70000",
        "https://example.test\\other",
        "http://127.0.0.1\n",
        "not-a-url",
    ],
)
def test_invalid_transport_url_is_rejected_before_network(url):
    with pytest.raises(ValueError):
        HttpTransport(url)


def test_https_transport_construction_is_offline_and_close_is_safe():
    with HttpTransport("https://example.invalid"):
        pass


def test_connection_failure_after_server_close_is_sanitized(tmp_path):
    service = ReferenceService(tmp_path / "service.sqlite")
    token = service.enroll("workspace", "a")
    with running(make_server(service)) as url:
        pass
    with (
        HttpTransport(url, timeout=3) as transport,
        pytest.raises(ConnectionError, match="could not be reached") as error,
    ):
        transport.pull(token)
    assert token not in str(error.value)


@pytest.fixture
def responder():
    state = {"status": 200, "body": b"[]", "headers": {}, "requests": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            state["requests"] += 1
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(state["status"])
            for key, value in state["headers"].items():
                self.send_header(key, value)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(state["body"])

    with running(ThreadingHTTPServer(("127.0.0.1", 0), Handler)) as url:
        yield state, url


def test_redirect_is_never_followed_or_given_credentials(responder):
    state, url = responder
    state.update(status=307, headers={"Location": url + "/unexpected"})
    with HttpTransport(url) as transport, pytest.raises(RuntimeError, match="HTTP 307"):
        transport.pull("fixture-token")
    assert state["requests"] == 1


@pytest.mark.parametrize("kind", ["oversize", "duplicate-json", "encoded", "wrong-shape"])
def test_transport_rejects_unbounded_or_malformed_responses(responder, monkeypatch, kind):
    state, url = responder
    if kind == "oversize":
        monkeypatch.setattr(sync_http, "MAX_RESPONSE_BYTES", 64)
        state["body"] = b"x" * 128
    elif kind == "duplicate-json":
        state["body"] = b'[{"sequence":1,"sequence":2}]'
    elif kind == "encoded":
        state["headers"] = {"Content-Encoding": "gzip"}
    else:
        state["body"] = b'{"private":"must not appear in error"}'
    with HttpTransport(url) as transport, pytest.raises(ValueError) as error:
        transport.pull("fixture-token")
    assert "must not appear" not in str(error.value)


def test_starting_the_server_never_waits_on_a_dns_lookup(tmp_path, monkeypatch):
    import socket

    def no_dns(*_args):
        raise AssertionError("a loopback server must not look up the host name")

    monkeypatch.setattr(socket, "getfqdn", no_dns)
    server = make_server(ReferenceService(tmp_path / "service.db"))
    try:
        assert server.server_name == "127.0.0.1" and server.server_port > 0
    finally:
        server.server_close()


def test_listener_exclusion_failed_bind_and_repeated_close_preserve_authority(tmp_path):
    import socket
    service = ReferenceService(tmp_path / "service.sqlite")
    token = service.enroll("workspace", "a")
    before = service.path.read_bytes()
    first = make_server(service)
    try:
        with pytest.raises(AuthorityInUseError):
            make_server(ReferenceService(service.path))
        with make_server(ReferenceService(tmp_path / "other.sqlite")):
            assert service.session_info(token) == {"workspace_id": "workspace", "device_id": "a"}
    finally:
        first.server_close()
        first.server_close()
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        with pytest.raises(OSError):
            make_server(service, port=occupied.getsockname()[1])
    with make_server(service) as restarted:
        assert restarted.server_port > 0
    assert service.path.read_bytes() == before


def test_listener_claim_survives_close_until_active_requests_drain(tmp_path, monkeypatch):
    import time
    service = ReferenceService(tmp_path / "service.sqlite")
    token = service.enroll("workspace", "a")
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    original, result, errors = service.push, [], []

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "push", held)
    server = make_server(service)
    with running(server) as url:
        def send():
            try:
                with HttpTransport(url) as transport:
                    result.append(transport.push(token, operation()))
            except Exception as error:
                errors.append(error)

        worker = threading.Thread(target=send)
        worker.start()
        assert entered.wait(5)
        server.shutdown()

        def close():
            server.server_close()
            closed.set()

        closer = threading.Thread(target=close)
        closer.start()
        try:
            deadline = time.monotonic() + 5
            while server.socket.fileno() != -1 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.socket.fileno() == -1 and not closed.is_set()
            with pytest.raises(AuthorityInUseError):
                make_server(service)
        finally:
            release.set()
            worker.join(5)
            closer.join(5)
        assert not worker.is_alive() and not closer.is_alive() and closed.is_set()
        assert not result and len(errors) == 1 and isinstance(errors[0], ConnectionError)
        accepted = service.pull(token)
        assert len(accepted) == 1 and accepted[0]["outcome"] == "accepted"
        with running(make_server(service)) as retry_url, HttpTransport(retry_url) as retry:
            assert retry.push(token, operation()) == accepted[0]
            assert service.pull(token) == accepted


def test_listener_claim_is_released_by_process_exit_without_deleting_lock(tmp_path):
    import os
    import subprocess
    import sys
    import time
    service = ReferenceService(tmp_path / "service.sqlite")
    ready = tmp_path / "ready.json"
    script = (
        "import json,sys;from pathlib import Path;"
        "from paper_daily.sync_http import make_server;"
        "from paper_daily.sync_service import ReferenceService;"
        "server=make_server(ReferenceService(Path(sys.argv[1])));"
        "ready=Path(sys.argv[2]);pending=ready.with_suffix('.pending');"
        "pending.write_text(json.dumps({'port':server.server_port}),encoding='utf-8');"
        "pending.replace(ready);sys.stdin.buffer.read(1)"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(service.path), str(ready)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        deadline = time.monotonic() + 8
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if not ready.exists() or child.poll() is not None:
            if child.poll() is None:
                child.kill()
            _out, error = child.communicate(timeout=5)
            raise AssertionError("Fixture listener did not start: "
                                 + error.decode("utf-8", errors="replace")[-2000:])
        assert json.loads(ready.read_text(encoding="utf-8"))["port"] > 0
        paths = list((service.path.parent / ".research-jobs").glob("*.lock"))
        assert len(paths) == 1
        identity = paths[0].stat()
        with pytest.raises(AuthorityInUseError):
            make_server(service)
        child.terminate()
        child.wait(timeout=5)
        with make_server(service):
            assert paths[0].is_file()
            current = paths[0].stat()
            assert (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino)
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)


def test_live_listener_refuses_replaced_or_missing_database_without_recreating_it(tmp_path):
    import os

    service = ReferenceService(tmp_path / "service.sqlite")
    token = service.enroll("workspace", "a")
    service.push(token, operation())
    replacement = ReferenceService(tmp_path / "replacement.sqlite")
    replacement.enroll("foreign-workspace", "other")
    replacement_bytes = replacement.path.read_bytes()
    server = make_server(service)
    with running(server) as url, HttpTransport(url) as transport:
        assert transport.session_info(token)["workspace_id"] == "workspace"
        os.replace(replacement.path, service.path)
        for _ in range(2):
            with pytest.raises(SyncHistoryUnavailable):
                transport.session_info(token)
            with pytest.raises(SyncHistoryUnavailable):
                transport.push(token, operation("do-not-send"))
            assert service.path.read_bytes() == replacement_bytes
        moved = tmp_path / "preserved-replacement.sqlite"
        os.replace(service.path, moved)
        with pytest.raises(SyncHistoryUnavailable):
            transport.session_info(token)
        assert not service.path.exists() and moved.read_bytes() == replacement_bytes
    with pytest.raises(SyncHistoryUnavailable):
        make_server(service)
    restored = ReferenceService(moved)
    assert restored.path.read_bytes() == replacement_bytes
    assert len(restored.device_catalog(restored.enroll("foreign-workspace", "new"))["devices"]) == 2


def test_database_lifetime_is_rechecked_before_commit_and_rejects_hardlink_aliases(
    tmp_path, monkeypatch,
):
    import os
    import sqlite3
    from contextlib import closing

    service = ReferenceService(tmp_path / "service.sqlite")
    token = service.enroll("workspace", "a")
    service.enroll("workspace", "peer")
    original, observe = service._authenticate, service._database_file_identity
    changed = False

    def identity():
        device, inode = observe()
        return (device, inode + 1) if changed else (device, inode)

    def authenticate(*args):
        nonlocal changed
        result = original(*args)
        changed = True
        return result

    with closing(sqlite3.connect(service.path)) as conn:
        before = list(conn.iterdump())
    with monkeypatch.context() as patch:
        patch.setattr(service, "_database_file_identity", identity)
        patch.setattr(service, "_authenticate", authenticate)
        with pytest.raises(SyncHistoryUnavailable):
            service.rename_device(token, "peer", "Must roll back")
    with closing(sqlite3.connect(service.path)) as conn:
        assert list(conn.iterdump()) == before
    assert service.device_catalog(token)["devices"][1]["label"] is None
    alias = tmp_path / "hardlinked.sqlite"
    os.link(service.path, alias)
    try:
        with pytest.raises(SyncHistoryUnavailable):
            service.session_info(token)
        with pytest.raises(SyncHistoryUnavailable):
            ReferenceService(alias)
    finally:
        alias.unlink()
    assert service.session_info(token)["device_id"] == "a"

    from pathlib import Path
    from types import SimpleNamespace

    real_lstat = Path.lstat

    def missing_identity(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if path == service.path:
            return SimpleNamespace(st_mode=info.st_mode, st_nlink=1, st_dev=info.st_dev, st_ino=0)
        return info

    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", missing_identity)
        with pytest.raises(SyncHistoryUnavailable):
            ReferenceService(service.path)
    with closing(sqlite3.connect(service.path)) as conn:
        assert list(conn.iterdump()) == before


def test_listener_close_interrupts_incomplete_headers_without_waiting_for_client(
    tmp_path, monkeypatch,
):
    import socket

    service = ReferenceService(tmp_path / "service.sqlite")
    token = service.enroll("workspace", "a")
    server = make_server(service)
    entered, closed = threading.Event(), threading.Event()
    finish = server.finish_request

    def admitted(*args):
        entered.set()
        return finish(*args)

    monkeypatch.setattr(server, "finish_request", admitted)
    with running(server) as url:
        port = int(url.rsplit(":", 1)[1])
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            client.sendall(b"POST /v1/pull HTTP/1.1\r\nHost: localhost\r\n")
            assert entered.wait(5)
            server.shutdown()

            def close():
                server.server_close()
                closed.set()

            closer = threading.Thread(target=close)
            closer.start()
            try:
                if not closed.wait(2):
                    import sys
                    import traceback

                    stacks = "\n".join(
                        "".join(traceback.format_stack(frame)[-8:])
                        for frame in sys._current_frames().values()
                    )
                    raise AssertionError("Listener did not drain incomplete headers:\n" + stacks)
            finally:
                client.close()
                closer.join(5)
            assert not closer.is_alive() and service.pull(token) == []
            with make_server(service):
                pass


def test_strict_service_refuses_prototype_writes_but_keeps_verified_retry_and_reads(tmp_path):
    import secrets
    import sqlite3
    from contextlib import closing

    from paper_daily.sync_journal import history_seed

    service = ReferenceService(tmp_path / 'authority.sqlite', blob_root=tmp_path / 'blobs')
    token = service.enroll('workspace', 'a')
    service.enroll('workspace', 'peer')
    code = secrets.token_urlsafe(32)
    service.create_pairing(token, code)
    with running(make_server(service, allow_unverified_mutations=False)) as url:
        with closing(sqlite3.connect(service.path)) as conn:
            before = list(conn.iterdump())
        bodies = {
            '/v1/push': {'operation': operation()},
            '/v1/devices/rename': {'device_id': 'peer', 'label': 'Unverified rename'},
            '/v1/devices/revoke': {'device_id': 'peer'},
            '/v1/devices/pairing/create': {'code': secrets.token_urlsafe(32)},
            **{f'/v1/blobs/{name}': {} for name in ('begin', 'append', 'commit', 'cancel')},
        }
        for route, body in bodies.items():
            for _ in range(2):
                status, _, result = request(url, token, path=route, body=json.dumps(body).encode())
                assert status == 412 and result == b'{"error":"sync_history_unavailable"}'
        credential = secrets.token_urlsafe(32)
        claim = dict(workspace_id='workspace', device_id='new', credential=credential, label=None)
        status, _, _ = request(url, code, path='/v1/devices/pairing/redeem',
                               body=json.dumps(claim).encode())
        assert status == 412
        with closing(sqlite3.connect(service.path)) as conn:
            assert list(conn.iterdump()) == before
        assert not list((tmp_path / 'blobs').rglob('*.part'))
        with HttpTransport(url) as transport:
            assert transport.pull(token) == []
            assert len(transport.device_catalog(token)['devices']) == 2
            point = dict(sequence=0, sha256=history_seed('workspace'))
            receipt = transport.push_verified(token, operation(), checkpoint=point)
            assert json.loads(receipt['record'])['operation'] == operation()
            assert transport.push_verified(
                token, operation(), checkpoint=receipt['checkpoint']) == receipt
            assert len(transport.pull(token)) == 1
            assert transport.rename_device(token, 'peer', 'Verified rename',
                                           checkpoint=receipt['checkpoint'])['changed']
            fresh = secrets.token_urlsafe(32)
            transport.create_pairing(token, fresh, checkpoint=receipt['checkpoint'])
        for _ in range(2):
            status, _, result = request(url, fresh, path='/v1/devices/pairing/redeem',
                                       body=json.dumps(claim).encode())
            assert status == 200
            assert json.loads(result) == {'workspace_id': 'workspace', 'device_id': 'new'}
        assert service.session_info(credential) == {'workspace_id': 'workspace', 'device_id': 'new'}
        assert len(service.device_catalog(token)['devices']) == 3
