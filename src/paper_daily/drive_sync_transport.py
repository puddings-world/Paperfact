"""Drive transport reusing the existing bounded research protocol and validators."""

from __future__ import annotations

from paper_daily import sync_device_protocol as devices
from paper_daily.drive_sync_files import origin
from paper_daily.sync_http import (
    _BLOB_ROUTES,
    _CONTROL_ROUTE,
    _HISTORY_BLOB_ROUTES,
    _TOKEN,
    MAX_REQUEST_BYTES,
    HttpTransport,
    _blob_request,
    _encode,
)


class DriveTransport(HttpTransport):
    def __init__(self, authority):
        self.authority = authority
        # Stable logical origin; no HTTP requests are sent to this reserved name.
        super().__init__(origin(authority.log.folder))
        self._control_supported = True

    def _post(self, path, token, payload):
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise PermissionError("Invalid Drive device credential")
        if len(_encode(payload)) > MAX_REQUEST_BYTES:
            raise ValueError("Drive research request exceeds its protocol limit")
        if path != _CONTROL_ROUTE:
            self._reload_control()
        control = self.control_checkpoint()
        owner = self.authority

        class Bound:
            def __getattr__(self, method):
                return lambda *args, **kwargs: owner.invoke(
                    method, *args, control=control, **kwargs)

        service = Bound()
        if path == "/v1/session/info":
            return owner.invoke("session_info", token)
        if path == _CONTROL_ROUTE:
            return owner.invoke("control_session", token, payload["checkpoint"], control=control)
        if path == "/v1/history/pull":
            return service.history_page(token, **payload)
        if path == "/v1/history/push":
            return service.push_verified(token, payload["operation"],
                                         checkpoint=payload["checkpoint"])
        if path == "/v1/pull":
            return service.pull(token, **payload)
        if path == "/v1/push":
            return service.push(token, payload["operation"])
        if path in devices.ROUTES | devices.HISTORY_ROUTES:
            return devices.request(service, path, token, payload)
        if path in _BLOB_ROUTES | _HISTORY_BLOB_ROUTES:
            return _blob_request(service, path, token, payload)
        raise ValueError("Unsupported Drive research protocol action")
