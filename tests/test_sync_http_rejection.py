"""Error replies survive unread input without an unbounded cleanup phase."""

import http.client
import io
import json
import socket
from types import SimpleNamespace

import pytest
from test_sync_http import running

from paper_daily import sync_http


class Connection:
    def __init__(self):
        self.shutdowns = []
        self.timeouts = []

    def shutdown(self, how):
        self.shutdowns.append(how)

    def settimeout(self, timeout):
        self.timeouts.append(timeout)


class Incoming:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.reads = []

    def read1(self, size):
        self.reads.append(size)
        result = next(self.chunks)
        if isinstance(result, Exception):
            raise result
        return result[:size]


def test_rejected_input_discards_only_bounded_bytes(monkeypatch):
    monkeypatch.setattr(sync_http.time, "monotonic", lambda: 1)
    connection = Connection()
    incoming = Incoming([b"x" * 65536] * 100)
    sync_http._finish_rejection(connection, incoming, io.BytesIO())
    assert connection.shutdowns == [socket.SHUT_WR]
    assert sum(incoming.reads) == sync_http.MAX_REQUEST_BYTES
    assert max(incoming.reads) <= 65536
    assert all(0 < value <= 0.2 for value in connection.timeouts)


def test_rejection_cleanup_has_absolute_deadline_not_per_chunk_timeout(monkeypatch):
    ticks = iter([1, 1.01, 1.10, 1.21])
    monkeypatch.setattr(sync_http.time, "monotonic", lambda: next(ticks))
    connection = Connection()
    incoming = Incoming([b"x"] * 100)
    sync_http._finish_rejection(connection, incoming, io.BytesIO())
    assert len(incoming.reads) == 2
    assert connection.timeouts == pytest.approx([0.19, 0.10])


@pytest.mark.parametrize("end", [b"", TimeoutError(), ConnectionResetError()])
def test_eof_timeout_or_reset_does_not_replace_the_sent_error(end):
    connection = Connection()
    incoming = Incoming([end])
    output = io.BytesIO(b"original response")
    sync_http._finish_rejection(connection, incoming, output)
    assert output.getvalue() == b"original response"
    assert len(incoming.reads) == 1


def test_cleanup_drains_already_buffered_unread_body():
    connection = Connection()
    incoming = io.BufferedReader(io.BytesIO(b"prefix-body"))
    assert incoming.read(7) == b"prefix-"
    sync_http._finish_rejection(connection, incoming, io.BytesIO())
    assert incoming.read() == b""


def test_shutdown_failure_does_not_mask_the_original_response():
    def gone(_):
        raise ConnectionResetError

    connection = SimpleNamespace(shutdown=gone)
    output = io.BytesIO(b"original response")
    sync_http._finish_rejection(connection, Incoming([]), output)
    assert output.getvalue() == b"original response"


@pytest.mark.parametrize(
    "method,path,extra,status",
    [
        ("POST", "/v1/enroll", "", 404),
        ("POST", "/v1/blobs/begin?token=private-test-value", "", 404),
        ("POST", "/v1/pull", "", 401),
        ("GET", "/v1/pull", "", 405),
        ("TRACE", "/v1/pull", "", 405),
        ("POST", "/v1/pull", "Authorization: Bearer test\r\nTransfer-Encoding: chunked\r\n", 400),
        ("POST", "/v1/pull", "Authorization: Bearer test\r\nContent-Length: 2\r\n", 400),
        ("POST", "/v1/pull", "Authorization: Bearer test\r\n", 413),
    ],
)
def test_error_is_complete_before_body_and_allows_bounded_graceful_close(
    method, path, extra, status
):
    with running(sync_http.make_server(object())) as url:
        port = int(url.rsplit(":", 1)[1])
        for _ in range(5):
            with socket.create_connection(("127.0.0.1", port), timeout=1) as conn:
                declared = sync_http.MAX_REQUEST_BYTES + 1 if status == 413 else 2
                conn.sendall(
                    (
                        f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n"
                        f"{extra}Content-Length: {declared}\r\n\r\n"
                    ).encode()
                )
                response = http.client.HTTPResponse(conn)
                response.begin()
                assert response.status == status
                # The peer has received the rejection before sending its unread body.
                # No authentication/service call or full claimed length is required.
                conn.sendall(b"{}")
                conn.shutdown(socket.SHUT_WR)
                data = response.read()
                assert set(json.loads(data)) == {"error"}
                assert b"private-test-value" not in data
                assert conn.recv(1) == b""
                response.close()


def test_absent_body_does_not_delay_error_delivery_or_hold_worker_indefinitely():
    with running(sync_http.make_server(object())) as url:
        port = int(url.rsplit(":", 1)[1])
        with socket.create_connection(("127.0.0.1", port), timeout=1) as conn:
            conn.sendall(
                b"POST /v1/enroll HTTP/1.1\r\nHost: localhost\r\nContent-Length: 2000000000\r\n\r\n"
            )
            response = http.client.HTTPResponse(conn)
            response.begin()
            assert response.status == 404
            assert json.loads(response.read()) == {"error": "not_found"}
            assert conn.recv(1) == b""
