"""Loopback-only transport acceptance; no real accounts or external network."""

import http.client
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from paper_daily import sync_http
from paper_daily.sync_http import HttpTransport, make_server
from paper_daily.sync_service import ReferenceService


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
