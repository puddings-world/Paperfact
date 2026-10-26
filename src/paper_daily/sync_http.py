"""Bounded loopback HTTP adapter and explicit sync transport.

The stdlib server is for local integration, not public deployment. Production TLS,
identity enrollment, abuse controls and deployment belong to a separate service.
"""

from __future__ import annotations

import json
import math
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import httpx

from paper_daily.sync_journal import canonical_operation

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
    411: "content_length_required",
    413: "request_too_large",
    415: "unsupported_media_type",
    500: "service_unavailable",
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


class _RequestError(Exception):
    def __init__(self, status):
        self.status = status


class _Server(ThreadingHTTPServer):
    daemon_threads = True

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

        def _error(self, code):
            self._reply(code, _encode({"error": _ERRORS[code]}))

        def _request(self):
            if self.path not in ("/v1/push", "/v1/pull"):
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
            except PermissionError:
                self._error(403)
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
