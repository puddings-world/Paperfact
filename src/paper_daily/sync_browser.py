"""Opt-in same-origin browser pairing; signed secrets live only in HttpOnly cookies.

The embedding host supplies a private persistent signing key and serves the PWA
on the exact configured HTTPS origin. This module provisions neither hosting nor
account identity. A signed cookie is confidential access material, not encryption.
"""

from __future__ import annotations

import base64
import hmac
import re
import secrets
import time
from urllib.parse import urlsplit
from uuid import uuid4

from paper_daily.sync_device_management import _device_id, pairing_secret
from paper_daily.sync_http import HttpTransport, _closed, _decode, _encode, _session_identity
from paper_daily.sync_pairing import Invitation

SESSION_SECONDS = 14 * 24 * 60 * 60
_COOKIE = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}")


def validate_origin(value):
    with HttpTransport(value) as transport:
        origin = transport.base_url
    parts = urlsplit(origin)
    host = parts.hostname.encode("idna").decode("ascii").lower()
    if ":" in host:
        host = "[" + host + "]"
    port = parts.port
    default_port = port is None or (parts.scheme, port) in {("https", 443), ("http", 80)}
    suffix = "" if default_port else f":{port}"
    canonical = f"{parts.scheme}://{host}{suffix}"
    if origin != canonical:
        raise ValueError("Use the browser's exact canonical service origin")
    return origin


def _b64(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


class BrowserSessions:
    """One authority/origin; callers must exclude cookies and bodies from logs."""

    def __init__(self, service, origin, key, *, clock=None):
        if type(key) is not bytes or len(key) != 32:
            raise ValueError("Supply a dedicated private 32-byte browser signing key")
        self.origin = validate_origin(origin)
        self.service = service
        self._key = key
        self._clock = clock or time.time
        self.secure = urlsplit(self.origin).scheme == "https"
        self.cookie_name = "__Host-paperfact-device" if self.secure else "paperfact-device-local"

    def cookie_from(self, headers):
        """Strict origin + custom JSON-request header; no permissive CORS fallback."""
        if (headers.get_all("Origin", []) != [self.origin]
                or headers.get_all("X-Paperfact-Browser", []) != ["1"]
                or headers.get_all("Sec-Fetch-Site", []) not in ([], ["same-origin"])
                or headers.get_all("Authorization", [])):
            raise PermissionError("Browser request origin is not authorized")
        cookies = headers.get_all("Cookie", [])
        if len(cookies) > 1 or (cookies and len(cookies[0]) > 8192):
            raise PermissionError("Browser session is unavailable")
        matches = []
        for part in (cookies[0].split(";") if cookies else []):
            name, separator, value = part.strip().partition("=")
            if name == self.cookie_name:
                if not separator:
                    raise PermissionError("Browser session is unavailable")
                matches.append(value)
        if len(matches) > 1:
            raise PermissionError("Browser session is unavailable")
        return matches[0] if matches else None

    def require_identity(self, headers, cookie, *, required):
        """Bind a browser request to its tab's observed workspace/device, not just its cookie."""
        workspaces = headers.get_all("X-Paperfact-Workspace", [])
        devices = headers.get_all("X-Paperfact-Device", [])
        if not workspaces and not devices and not required:
            return
        if len(workspaces) != 1 or len(devices) != 1:
            raise PermissionError("Browser request identity is unavailable")
        record = self._open(cookie)
        if workspaces != [record["workspace_id"]] or devices != [record["device_id"]]:
            raise PermissionError("Browser request identity changed")

    def _seal(self, record):
        body = _b64(_encode(record))
        signature = _b64(hmac.digest(self._key, b"paperfact.browser.v1:" + body.encode(), "sha256"))
        value = body + "." + signature
        if len(value) > 3800:
            raise ValueError("Browser pairing exceeds the cookie budget")
        return value

    def _open(self, cookie):
        if (not isinstance(cookie, str) or len(cookie) > 3800
                or not _COOKIE.fullmatch(cookie)):
            raise PermissionError("Browser session is unavailable")
        body, signature = cookie.split(".")
        expected = _b64(hmac.digest(
            self._key, b"paperfact.browser.v1:" + body.encode(), "sha256"))
        if not hmac.compare_digest(signature, expected):
            raise PermissionError("Browser session is unavailable")
        try:
            value = _decode(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            _closed(value, {"format", "origin", "workspace_id", "device_id", "credential",
                            "expires_at", "invitation"})
            if (type(value["format"]) is not int or value["format"] != 1
                    or value["origin"] != self.origin
                    or type(value["expires_at"]) is not int
                    or not self._clock() < value["expires_at"] <= self._clock() + SESSION_SECONDS):
                raise ValueError("Invalid cookie context")
            _device_id(value["workspace_id"])
            _device_id(value["device_id"])
            pairing_secret(value["credential"])
            if value["invitation"] is not None:
                invitation = Invitation.decoded(value["invitation"])
                if (invitation.endpoint != self.origin
                        or invitation.workspace_id != value["workspace_id"]
                        or invitation.code == value["credential"]):
                    raise ValueError("Invalid pending invitation")
            return value
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            raise PermissionError("Browser session is unavailable") from None

    def _header(self, cookie, seconds):
        return (f"{self.cookie_name}={cookie}; Path=/; Max-Age={seconds}; HttpOnly; SameSite=Strict"
                + ("; Secure" if self.secure else ""))

    def prepare(self, value, cookie):
        """Save browser intent before enrollment, without writing authority research."""
        _closed(value, {"invitation"})
        invitation = Invitation.decoded(value["invitation"])
        if invitation.endpoint != self.origin:
            raise ValueError("Open the PWA on the invitation's exact service origin")
        if cookie:
            record = self._open(cookie)
            if record["invitation"] != invitation.encoded():
                raise ValueError("Resume or forget this browser connection before replacing it")
        else:
            record = dict(format=1, origin=self.origin, workspace_id=invitation.workspace_id,
                          device_id=str(uuid4()), credential=secrets.token_urlsafe(32),
                          expires_at=int(self._clock()) + SESSION_SECONDS,
                          invitation=invitation.encoded())
        return ({"workspace_id": record["workspace_id"], "device_id": record["device_id"]},
                self._header(self._seal(record), max(0, int(record["expires_at"] - self._clock()))))

    def complete(self, value, cookie):
        """Exact retry verifies an admitted device before using an expiring grant."""
        _closed(value, set())
        record = self._open(cookie)
        try:
            identity = self.service.session_info(record["credential"])
        except PermissionError:
            if record["invitation"] is None:
                raise
            invitation = Invitation.decoded(record["invitation"])
            identity = self.service.redeem_pairing(
                invitation.code, record["workspace_id"], record["device_id"], record["credential"])
        _session_identity(identity)
        if identity != {"workspace_id": record["workspace_id"], "device_id": record["device_id"]}:
            raise PermissionError("Browser device identity changed")
        record["invitation"] = None
        return identity, self._header(
            self._seal(record), max(0, int(record["expires_at"] - self._clock())))

    def credential(self, cookie):
        record = self._open(cookie)
        if record["invitation"] is not None:
            raise PermissionError("Complete the saved browser pairing first")
        identity = self.service.session_info(record["credential"])
        if identity != {"workspace_id": record["workspace_id"], "device_id": record["device_id"]}:
            raise PermissionError("Browser device identity changed")
        return record["credential"]

    def forget(self, value):
        _closed(value, set())
        return {"forgotten": True}, self._header("", 0)
