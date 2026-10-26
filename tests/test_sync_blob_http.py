"""Bounded attachment transport against private loopback fixtures only."""

import base64
import hashlib
import json

import httpx
import pytest
from test_sync_http import request, running

from paper_daily.sync_blob_service import BlobDisabledError, BlobUnavailableError
from paper_daily.sync_blobs import BlobQuotaError
from paper_daily.sync_http import BLOB_CHUNK_BYTES, HttpTransport, make_server
from paper_daily.sync_service import ReferenceService


def manifest(data):
    return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


@pytest.fixture
def endpoint(tmp_path):
    service = ReferenceService(tmp_path / "service.db", blob_root=tmp_path / "blobs")
    token = service.enroll("workspace", "a")
    with running(make_server(service)) as url:
        yield service, token, url


def test_resumable_upload_owned_read_dedup_and_eof_over_http(endpoint):
    service, token, url = endpoint
    data = b"a" * BLOB_CHUNK_BYTES + b"tail"
    description = manifest(data)
    peer = service.enroll("workspace", "peer")
    with HttpTransport(url) as transport:
        started = transport.blob_begin(token, description)
        identity = started["upload_id"]
        first = transport.blob_append(token, identity, 0, data[:BLOB_CHUNK_BYTES])
        assert first == {"offset": BLOB_CHUNK_BYTES}
        assert transport.blob_append(token, identity, 0, data[:BLOB_CHUNK_BYTES]) == first
    with HttpTransport(url) as resumed:
        assert resumed.blob_begin(token, description) == {**started, "offset": BLOB_CHUNK_BYTES}
        resumed.blob_append(token, identity, BLOB_CHUNK_BYTES, b"tail")
        assert resumed.blob_commit(token, identity) == {**description, "complete": True}
        assert resumed.blob_begin(token, description) == {
            **description,
            "upload_id": None,
            "offset": len(data),
            "complete": True,
        }
        assert resumed.blob_read(peer, **description, offset=0) == data[:BLOB_CHUNK_BYTES]
        assert resumed.blob_read(peer, **description, offset=BLOB_CHUNK_BYTES) == b"tail"
        assert resumed.blob_read(peer, **description, offset=len(data)) == b""


def test_cancel_auth_workspace_isolation_and_revocation(endpoint):
    service, token, url = endpoint
    other = service.enroll("other", "b")
    description = manifest(b"abc")
    with HttpTransport(url) as transport:
        identity = transport.blob_begin(token, description)["upload_id"]
        with pytest.raises(PermissionError):
            transport.blob_append(other, identity, 0, b"abc")
        with pytest.raises(PermissionError):
            transport.blob_read(other, **description, offset=0)
        assert transport.blob_cancel(token, identity) == {"cancelled": True}
        identity = transport.blob_begin(token, description)["upload_id"]
        service.revoke(token)
        for action in (
            lambda: transport.blob_begin(token, description),
            lambda: transport.blob_append(token, identity, 0, b"abc"),
            lambda: transport.blob_commit(token, identity),
            lambda: transport.blob_cancel(token, identity),
            lambda: transport.blob_read(token, **description, offset=0),
        ):
            with pytest.raises(PermissionError):
                action()


@pytest.mark.parametrize(
    "route,body",
    [
        ("begin", {"sha256": "0" * 64, "size": True}),
        ("begin", {"sha256": "0" * 64, "size": 1, "path": "secret"}),
        ("append", {"upload_id": "upload", "offset": 0, "data": "!!!"}),
        ("append", {"upload_id": "upload", "offset": 0, "data": "YQ==\n"}),
        ("append", {"upload_id": "upload", "offset": 0, "data": "YR=="}),
        ("append", {"upload_id": "upload", "offset": False, "data": "YQ=="}),
        ("append", {"upload_id": "../other", "offset": 0, "data": "YQ=="}),
        ("append", {"upload_id": "upload", "offset": 0, "data": ""}),
        (
            "append",
            {
                "upload_id": "upload",
                "offset": 0,
                "data": base64.b64encode(b"a" * (BLOB_CHUNK_BYTES + 1)).decode(),
            },
        ),
        ("commit", {"upload_id": "upload", "complete": True}),
        ("cancel", {}),
        ("read", {"sha256": "0" * 64, "size": 1, "offset": 0, "limit": BLOB_CHUNK_BYTES + 1}),
        ("read", {"sha256": "0" * 64, "size": 1, "offset": 2, "limit": 1}),
    ],
)
def test_malformed_blob_requests_are_bounded_and_sanitized(endpoint, route, body):
    _, token, url = endpoint
    status, headers, data = request(
        url, token, path="/v1/blobs/" + route, body=json.dumps(body).encode()
    )
    assert status == 400
    assert json.loads(data) == {"error": "invalid_request"}
    assert headers["Cache-Control"] == "no-store"
    assert token.encode() not in data


def test_blob_routes_reject_query_tokens_and_unknown_routes(endpoint):
    _, token, url = endpoint
    for path in ("/v1/blobs/begin?token=" + token, "/v1/blobs/anything"):
        status, _, data = request(url, token, path=path, body=b"{}")
        assert status == 404
        assert token.encode() not in data


def test_missing_configuration_and_old_server_are_explicit(tmp_path, monkeypatch):
    service = ReferenceService(tmp_path / "service.db")
    token = service.enroll("workspace", "a")
    with (
        running(make_server(service)) as url,
        HttpTransport(url) as transport,
        pytest.raises(BlobDisabledError),
    ):
        transport.blob_begin(token, manifest(b"a"))

    # An older peer's route-not-found response is distinct from corrupt JSON.
    class OldService:
        pass

    with (
        running(make_server(OldService())) as url,
        HttpTransport(url) as transport,
        pytest.raises(BlobDisabledError),
    ):
        transport.blob_begin(token, manifest(b"a"))


def test_quota_maps_to_typed_error_and_lost_owned_bytes_are_retryable(tmp_path):
    service = ReferenceService(
        tmp_path / "service.db", blob_root=tmp_path / "blobs", blob_quota_bytes=3
    )
    token = service.enroll("workspace", "a")
    with running(make_server(service)) as url, HttpTransport(url) as transport:
        with pytest.raises(BlobQuotaError):
            transport.blob_begin(token, manifest(b"four"))
        description = manifest(b"abc")
        identity = transport.blob_begin(token, description)["upload_id"]
        transport.blob_append(token, identity, 0, b"abc")
        transport.blob_commit(token, identity)
        paths = list((tmp_path / "blobs").rglob(description["sha256"]))
        assert len(paths) == 1
        paths[0].unlink()
        with pytest.raises(BlobUnavailableError):
            transport.blob_read(token, **description, offset=0)


@pytest.mark.parametrize(
    "method,result",
    [
        (
            "begin",
            {"upload_id": None, "sha256": "0" * 64, "size": 1, "offset": 0, "complete": True},
        ),
        (
            "begin",
            {"upload_id": "id", "sha256": "0" * 64, "size": 1, "offset": 2, "complete": False},
        ),
        ("append", {"offset": 0}),
        ("append", {"offset": True}),
        ("commit", {"sha256": "0" * 64, "size": 1, "complete": False}),
        ("cancel", {"cancelled": 1}),
        ("read", {"data": ""}),
        ("read", {"data": "YWI="}),
        ("read", {"data": "YR=="}),
    ],
)
def test_transport_does_not_expose_malformed_blob_replies(monkeypatch, method, result):
    with HttpTransport("http://127.0.0.1:1") as transport:
        monkeypatch.setattr(transport, "_post", lambda *args: result)
        calls = {
            "begin": lambda: transport.blob_begin("token", {"sha256": "0" * 64, "size": 1}),
            "append": lambda: transport.blob_append("token", "id", 0, b"a"),
            "commit": lambda: transport.blob_commit("token", "id"),
            "cancel": lambda: transport.blob_cancel("token", "id"),
            "read": lambda: transport.blob_read("token", "0" * 64, 1, 0),
        }
        with pytest.raises(ValueError):
            calls[method]()


def test_connection_failure_keeps_retry_information_outside_transport(endpoint, monkeypatch):
    _, token, url = endpoint
    with HttpTransport(url) as transport:
        description = manifest(b"abc")
        begun = transport.blob_begin(token, description)
    with HttpTransport(url) as disconnected:

        def fail(*args, **kwargs):
            raise httpx.ConnectError("fixture failure")

        monkeypatch.setattr(disconnected._client, "stream", fail)
        with pytest.raises(ConnectionError, match="could not be reached"):
            disconnected.blob_append(token, begun["upload_id"], 0, b"abc")
    with HttpTransport(url) as resumed:
        assert resumed.blob_begin(token, description) == begun


def test_old_server_missing_blob_route_returns_explicit_disabled():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class OldHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    with (
        running(ThreadingHTTPServer(("127.0.0.1", 0), OldHandler)) as url,
        HttpTransport(url) as transport,
        pytest.raises(BlobDisabledError),
    ):
        transport.blob_begin("synthetic-token", manifest(b"abc"))


def test_authenticated_session_identity_and_revocation_do_not_echo_token(endpoint):
    service, token, url = endpoint
    with HttpTransport(url) as transport:
        assert transport.session_info(token) == {"workspace_id": "workspace", "device_id": "a"}
        status, headers, body = request(url, token, path="/v1/session/info", body=b"{}")
        assert status == 200
        assert json.loads(body) == {"workspace_id": "workspace", "device_id": "a"}
        assert token.encode() not in body
        assert headers["Cache-Control"] == "no-store"
        other = service.enroll("other-workspace", "other-device")
        assert transport.session_info(other) == {
            "workspace_id": "other-workspace",
            "device_id": "other-device",
        }
        service.revoke(token)
        for credential in (token, "unknown-session", "invalid\ncredential"):
            with pytest.raises(PermissionError):
                transport.session_info(credential)


def test_session_info_is_available_without_blob_configuration(tmp_path):
    service = ReferenceService(tmp_path / "metadata-only.db")
    token = service.enroll("workspace", "device")
    with running(make_server(service)) as url, HttpTransport(url) as transport:
        assert transport.session_info(token) == {"workspace_id": "workspace", "device_id": "device"}


@pytest.mark.parametrize(
    "body", [b'{"token":"hidden"}', b'{"workspace_id":"forged"}', b"[]", b'{"a":1,"a":2}']
)
def test_session_info_rejects_nonempty_or_malformed_bodies(endpoint, body):
    _, token, url = endpoint
    status, _, data = request(url, token, path="/v1/session/info", body=body)
    assert status == 400 and json.loads(data) == {"error": "invalid_request"}
    assert token.encode() not in data


def test_session_info_rejects_query_tokens_and_missing_auth(endpoint):
    _, token, url = endpoint
    status, _, data = request(url, token, path="/v1/session/info?token=" + token, body=b"{}")
    assert status == 404 and token.encode() not in data
    status, _, data = request(
        url,
        token,
        path="/v1/session/info",
        body=b"{}",
        headers=[("Content-Length", "2"), ("Content-Type", "application/json")],
    )
    assert status == 401 and json.loads(data) == {"error": "authentication_required"}


@pytest.mark.parametrize(
    "reply",
    [
        None,
        [],
        {},
        {"workspace_id": "workspace"},
        {"workspace_id": "workspace", "device_id": "a", "token": "secret"},
        {"workspace_id": "../workspace", "device_id": "a"},
        {"workspace_id": "workspace", "device_id": True},
        {"workspace_id": "workspace", "device_id": "a" * 201},
    ],
)
def test_session_transport_rejects_noncanonical_identity_reply(monkeypatch, reply):
    with HttpTransport("http://127.0.0.1:1") as transport:
        monkeypatch.setattr(transport, "_post", lambda *args: reply)
        with pytest.raises(ValueError):
            transport.session_info("synthetic-token")
