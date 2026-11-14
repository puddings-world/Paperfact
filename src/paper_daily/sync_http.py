"""Bounded loopback HTTP adapter and explicit sync transport.

The stdlib server is for local integration, not public deployment. Production TLS,
account enrollment, abuse controls and deployment remain separate hosting concerns.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
import socket
import socketserver
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import httpx

from paper_daily import sync_device_protocol as devices
from paper_daily.sync_blob_service import BlobDisabledError, BlobUnavailableError
from paper_daily.sync_blobs import BlobManifest, BlobQuotaError
from paper_daily.sync_device_management import (
    PairingUnavailableError,
    UnknownDeviceError,
    _device_id,
    device_label,
)
from paper_daily.sync_journal import ID, canonical_operation

BLOB_CHUNK_BYTES = 256 * 1024
_BLOB_ROUTES = {"/v1/blobs/" + name for name in ("begin", "append", "commit", "cancel", "read")}
MAX_REQUEST_BYTES = 512 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_TOKEN = re.compile(r"[A-Za-z0-9._~-]{1,4096}")
_LOOPBACK = {"127.0.0.1", "::1"}
_ERRORS = {
    400: "invalid_request",
    401: "authentication_required",
    403: "access_denied",
    404: "not_found",
    405: "method_not_allowed",
    408: "request_timeout",
    409: "blob_unavailable",
    411: "content_length_required",
    413: "request_too_large",
    415: "unsupported_media_type",
    500: "service_unavailable",
    503: "blob_service_disabled",
}


def _encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON field")
        value[key] = item
    return value


def _reject_constant(_value):
    raise ValueError("Invalid JSON constant")


def _decode(data):
    return json.loads(
        data.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant
    )


def _closed(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("Unexpected blob fields")
    return value


def _session_identity(value):
    _closed(value, {"workspace_id", "device_id"})
    if any(
        not isinstance(identity, str) or not ID.fullmatch(identity) for identity in value.values()
    ):
        raise ValueError("Invalid session identity response")
    return value


def _manifest(value):
    _closed(value, {"sha256", "size"})
    BlobManifest(**value)
    if value["size"] > 2**63 - 1:
        raise ValueError("Invalid blob size")
    return value


def _offset(value):
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError("Invalid blob offset")
    return value


def _upload_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("Invalid upload identity")
    return value


def _blob_data(value, *, empty=False):
    if not isinstance(value, str) or len(value) > 4 * ((BLOB_CHUNK_BYTES + 2) // 3):
        raise ValueError("Invalid blob chunk encoding")
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Invalid blob chunk encoding") from None
    if (
        len(data) > BLOB_CHUNK_BYTES
        or (not data and not empty)
        or base64.b64encode(data).decode("ascii") != value
    ):
        raise ValueError("Invalid blob chunk")
    return data


def _blob_request(service, path, token, value):
    name = path.rsplit("/", 1)[1]
    method = getattr(service, "blob_" + name, None)
    if method is None:
        raise BlobDisabledError("Blob transport is unavailable")
    if name == "begin":
        return method(token, _manifest(value))
    if name in ("commit", "cancel"):
        _closed(value, {"upload_id"})
        return method(token, _upload_id(value["upload_id"]))
    if name == "append":
        _closed(value, {"upload_id", "offset", "data"})
        return method(
            token,
            _upload_id(value["upload_id"]),
            _offset(value["offset"]),
            _blob_data(value["data"]),
        )
    _closed(value, {"sha256", "size", "offset", "limit"})
    _manifest({"sha256": value["sha256"], "size": value["size"]})
    offset, limit = _offset(value["offset"]), value["limit"]
    if offset > value["size"] or type(limit) is not int or not 1 <= limit <= BLOB_CHUNK_BYTES:
        raise ValueError("Invalid blob read bounds")
    data = method(token, value["sha256"], value["size"], offset, limit)
    if not isinstance(data, bytes) or len(data) > min(limit, value["size"] - offset):
        raise RuntimeError("Invalid blob service response")
    return {"data": base64.b64encode(data).decode("ascii")}


class _RequestError(Exception):
    def __init__(self, status):
        self.status = status


def _finish_rejection(connection, incoming, outgoing):
    """Send the error first, then bound unread-body cleanup before TCP close.

    Closing with unread input can reset the peer before it receives the JSON
    error on Windows. Half-close output and discard input without trusting its
    framing, allocating the claimed body, or extending the absolute deadline.
    """
    try:
        outgoing.flush()
        connection.shutdown(socket.SHUT_WR)
        deadline = time.monotonic() + 0.2
        remaining = MAX_REQUEST_BYTES
        while remaining:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                break
            connection.settimeout(timeout)
            chunk = incoming.read1(min(64 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
    except OSError:
        # A disconnected/timed-out peer must not trigger a second error reply
        # after the original response has already been sent and half-closed.
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # HTTPServer.server_bind asks DNS for the host's full name, which can take
        # half a minute on a Mac with no reverse lookup for the address. A loopback
        # server never uses that name.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def handle_error(self, request, client_address):
        # Exceptions must not print request context, credentials or research.
        pass


def make_server(service, host="127.0.0.1", port=0) -> ThreadingHTTPServer:
    """Bind a loopback-only reference server; the caller starts/stops its thread."""
    if host not in _LOOPBACK:
        raise ValueError("Reference sync HTTP binds only literal loopback addresses")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Invalid sync server port")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "PaperfactSync"
        sys_version = ""

        def setup(self):
            self.request.settimeout(10)
            super().setup()

        def log_message(self, format, *args):
            pass

        def send_error(self, code, message=None, explain=None):
            self._error(405 if code == 501 else code if code in _ERRORS else 400)

        def _reply(self, code, data):
            self.close_connection = True
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
            if code >= 400:
                _finish_rejection(self.connection, self.rfile, self.wfile)

        def _error(self, code):
            self._reply(code, _encode({"error": _ERRORS[code]}))

        def _request(self):
            if self.path not in (
                {"/v1/push", "/v1/pull", "/v1/session/info"} | _BLOB_ROUTES | devices.ROUTES
            ):
                raise _RequestError(404)
            authorization = self.headers.get_all("Authorization", [])
            if len(authorization) != 1 or not authorization[0].startswith("Bearer "):
                raise _RequestError(401)
            token = authorization[0][7:]
            if not _TOKEN.fullmatch(token):
                raise _RequestError(401)
            if self.headers.get_all("Transfer-Encoding") or self.headers.get_all(
                "Content-Encoding"
            ):
                raise _RequestError(400)
            lengths = self.headers.get_all("Content-Length", [])
            if not lengths:
                raise _RequestError(411)
            if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,9}", lengths[0]):
                raise _RequestError(400)
            size = int(lengths[0])
            if size > MAX_REQUEST_BYTES:
                raise _RequestError(413)
            types = self.headers.get_all("Content-Type", [])
            if len(types) != 1 or types[0].split(";", 1)[0].strip().lower() != "application/json":
                raise _RequestError(415)
            data = self.rfile.read(size)
            if len(data) != size:
                raise _RequestError(400)
            value = _decode(data)
            if not isinstance(value, dict):
                raise _RequestError(400)
            return token, value

        def do_POST(self):
            try:
                token, value = self._request()
                if self.path == "/v1/push":
                    if set(value) != {"operation"}:
                        raise _RequestError(400)
                    response = _encode(service.push(token, value["operation"]))
                    if len(response) > MAX_RESPONSE_BYTES:
                        raise _RequestError(500)
                elif self.path == "/v1/session/info":
                    _closed(value, set())
                    method = getattr(service, "session_info", None)
                    if method is None:
                        raise _RequestError(404)
                    identity = method(token)
                    try:
                        _session_identity(identity)
                    except ValueError:
                        raise RuntimeError("Invalid session identity response") from None
                    response = _encode(identity)
                elif self.path in devices.ROUTES:
                    response = _encode(devices.request(service, self.path, token, value))
                    if len(response) > MAX_RESPONSE_BYTES:
                        raise _RequestError(500)
                elif self.path in _BLOB_ROUTES:
                    response = _encode(_blob_request(service, self.path, token, value))
                    if len(response) > MAX_RESPONSE_BYTES:
                        raise _RequestError(500)
                else:
                    if set(value) != {"after", "limit"}:
                        raise _RequestError(400)
                    after, limit = value["after"], value["limit"]
                    if type(after) is not int or after < 0:
                        raise _RequestError(400)
                    if type(limit) is not int or not 1 <= limit <= 1000:
                        raise _RequestError(400)
                    # At most four maximum-size events are materialized per request.
                    events = service.pull(token, after=after, limit=min(limit, 4))
                    chunks, total = [], 2
                    for event in events:
                        chunk = _encode(event)
                        next_size = total + len(chunk) + bool(chunks)
                        if next_size > MAX_RESPONSE_BYTES:
                            if not chunks:
                                raise _RequestError(500)
                            break
                        chunks.append(chunk)
                        total = next_size
                    response = b"[" + b",".join(chunks) + b"]"
                self._reply(200, response)
            except _RequestError as exc:
                self._error(exc.status)
            except BlobUnavailableError:
                self._error(409)
            except BlobDisabledError:
                self._error(503)
            except BlobQuotaError:
                self._error(413)
            except PermissionError:
                self._error(401 if self.path in devices.ROUTES else 403)
            except UnknownDeviceError:
                self._error(404)
            except (ValueError, TypeError, RecursionError, UnicodeError):
                self._error(400)
            except TimeoutError:
                self._error(408)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except Exception:
                self._error(500)

        def _unsupported(self):
            self._error(405)

        do_GET = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _unsupported

    if host == "::1":

        class IPv6Server(_Server):
            address_family = socket.AF_INET6

        return IPv6Server((host, port), Handler)
    return _Server((host, port), Handler)


class HttpTransport:
    """Synchronous, bounded transport; only explicit push/pull calls use the network."""

    def __init__(self, base_url: str, *, timeout: float = 10):
        if (
            not isinstance(base_url, str)
            or "?" in base_url
            or "#" in base_url
            or "\\" in base_url
            or any(ord(ch) <= 32 or ord(ch) == 127 for ch in base_url)
        ):
            raise ValueError("Invalid sync service URL")
        parts = urlsplit(base_url)
        if (
            parts.scheme not in ("http", "https")
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.path not in ("", "/")
        ):
            raise ValueError("Invalid sync service URL")
        if parts.scheme == "http" and parts.hostname not in _LOOPBACK:
            raise ValueError("Remote sync services require HTTPS")
        if parts.port is not None and not 1 <= parts.port <= 65535:
            raise ValueError("Invalid sync service port")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValueError("Sync timeout must be between zero and 60 seconds")
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def _post(self, path, token, payload):
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise PermissionError("Invalid sync credential")
        data = _encode(payload)
        if len(data) > MAX_REQUEST_BYTES:
            raise ValueError("Sync request exceeds the transport limit")
        try:
            with self._client.stream(
                "POST",
                self.base_url + path,
                content=data,
                headers={
                    "Authorization": "Bearer " + token,
                    "Content-Type": "application/json",
                    "Accept-Encoding": "identity",
                },
            ) as response:
                if response.status_code in (401, 403):
                    raise PermissionError("Sync authorization was rejected")
                if response.status_code == 409:
                    raise BlobUnavailableError("Sync attachment bytes are unavailable; retry later")
                if response.status_code == 503 or (
                    response.status_code == 404 and path in _BLOB_ROUTES
                ):
                    raise BlobDisabledError("Sync attachment transport is unavailable")
                if response.status_code == 413 and path in _BLOB_ROUTES:
                    raise BlobQuotaError("Sync attachment quota or transfer limit exceeded")
                if (response.status_code == 404
                        and path in {devices.PAIR_CREATE, devices.PAIR_REDEEM}):
                    raise PairingUnavailableError("Pairing is unavailable on this service")
                if response.status_code != 200:
                    raise RuntimeError(f"Sync service returned HTTP {response.status_code}")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ValueError("Encoded sync responses are not supported")
                if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
                    raise ValueError("Invalid sync response type")
                length = response.headers.get("content-length")
                if length is not None and (
                    not length.isdigit() or int(length) > MAX_RESPONSE_BYTES
                ):
                    raise ValueError("Sync response exceeds the transport limit")
                chunks, total = [], 0
                for chunk in response.iter_raw(chunk_size=8192):
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        raise ValueError("Sync response exceeds the transport limit")
                    chunks.append(chunk)
                try:
                    return _decode(b"".join(chunks))
                except (ValueError, UnicodeError, RecursionError):
                    raise ValueError("Invalid sync HTTP response") from None
        except httpx.TimeoutException:
            raise TimeoutError("Sync service timed out") from None
        except httpx.HTTPError:
            raise ConnectionError("Sync service could not be reached") from None

    def push(self, token, operation):
        canonical_operation(operation)
        result = self._post("/v1/push", token, {"operation": operation})
        if not isinstance(result, dict):
            raise ValueError("Invalid sync push response")
        return result

    def pull(self, token, after=0, limit=100):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Invalid sync pull bounds")
        result = self._post("/v1/pull", token, {"after": after, "limit": limit})
        if not isinstance(result, list) or len(result) > limit:
            raise ValueError("Invalid sync pull response")
        return result

    def session_info(self, token):
        """Resolve authenticated identity before binding a workspace transfer session."""
        return _session_identity(self._post("/v1/session/info", token, {}))

    def create_pairing(self, token, code):
        value = self._post(devices.PAIR_CREATE, token, {"code": devices.pairing_secret(code)})
        return devices.pairing_created(value)

    def redeem_pairing(self, code, workspace_id, device_id, credential, label=None):
        value = self._post(devices.PAIR_REDEEM, devices.pairing_secret(code), {
            "workspace_id": _device_id(workspace_id), "device_id": _device_id(device_id),
            "credential": devices.pairing_secret(credential), "label": device_label(label),
        })
        return devices.pairing_claimed(value, workspace_id, device_id)

    def device_catalog(self, token, *, after=None, limit=50):
        bounds = devices.catalog_bounds(after, limit)
        return devices.catalog(self._post("/v1/devices/list", token, bounds), **bounds)

    def rename_device(self, token, device_id, label):
        target, label = _device_id(device_id), device_label(label)
        result = self._post("/v1/devices/rename", token, {"device_id": target, "label": label})
        return devices.renamed(result, target, label)

    def revoke_peer(self, token, device_id):
        target = _device_id(device_id)
        result = self._post("/v1/devices/revoke", token, {"device_id": target})
        return devices.revoked(result, target)

    def blob_begin(self, token, manifest):
        manifest = dict(_manifest(manifest))
        result = self._post("/v1/blobs/begin", token, manifest)
        _closed(result, {"upload_id", "sha256", "size", "offset", "complete"})
        if (
            _manifest({"sha256": result["sha256"], "size": result["size"]}) != manifest
            or type(result["complete"]) is not bool
            or _offset(result["offset"]) > manifest["size"]
        ):
            raise ValueError("Invalid blob begin response")
        if result["complete"]:
            if result["upload_id"] is not None or result["offset"] != manifest["size"]:
                raise ValueError("Invalid completed blob response")
        else:
            _upload_id(result["upload_id"])
        return result

    def blob_append(self, token, upload_id, offset, data):
        _upload_id(upload_id)
        _offset(offset)
        if not isinstance(data, bytes) or not 0 < len(data) <= BLOB_CHUNK_BYTES:
            raise ValueError("Expected a nonempty bounded blob chunk")
        result = self._post(
            "/v1/blobs/append",
            token,
            {
                "upload_id": upload_id,
                "offset": offset,
                "data": base64.b64encode(data).decode("ascii"),
            },
        )
        _closed(result, {"offset"})
        if _offset(result["offset"]) < offset + len(data):
            raise ValueError("Invalid blob append response offset")
        return result

    def blob_commit(self, token, upload_id):
        result = self._post("/v1/blobs/commit", token, {"upload_id": _upload_id(upload_id)})
        _closed(result, {"sha256", "size", "complete"})
        _manifest({"sha256": result["sha256"], "size": result["size"]})
        if result["complete"] is not True:
            raise ValueError("Blob commit was not complete")
        return result

    def blob_cancel(self, token, upload_id):
        result = self._post("/v1/blobs/cancel", token, {"upload_id": _upload_id(upload_id)})
        _closed(result, {"cancelled"})
        if result["cancelled"] is not True:
            raise ValueError("Invalid blob cancellation response")
        return result

    def blob_read(self, token, sha256, size, offset, limit=BLOB_CHUNK_BYTES):
        value = dict(_manifest({"sha256": sha256, "size": size}))
        if _offset(offset) > size or type(limit) is not int or not 1 <= limit <= BLOB_CHUNK_BYTES:
            raise ValueError("Invalid blob read bounds")
        value.update(offset=offset, limit=limit)
        result = self._post("/v1/blobs/read", token, value)
        _closed(result, {"data"})
        data = _blob_data(result["data"], empty=True)
        if len(data) != min(limit, size - offset):
            raise ValueError("Blob read returned an incomplete or oversized range")
        return data
