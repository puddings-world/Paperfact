"""One authenticated workspace/device catalog action, with late-session guards."""

from pathlib import Path

from paper_daily import sync_device_protocol as protocol
from paper_daily.sync_device_management import _device_id, device_label
from paper_daily.workspace_service import WorkspaceChanged
from paper_daily.workspace_sync import EnrollmentRequired, SyncStopped, local_binding


class DeviceContextChanged(SyncStopped):
    """The captured authenticated/local binding can no longer serve this view."""


class DeviceClient:
    def __init__(self, session):
        self.session = session
        with session._state:
            if session._token is None or session.identity is None:
                raise PermissionError("Connect before managing devices")
            self.generation = session._generation
            self.identity = dict(session.identity)

    def current(self):
        """Cheap UI guard; the worker also validates SQL/authenticated bindings."""
        summary = self.session.summary()
        try:
            workspace = self.session.workspace
            info = workspace.path.stat()
            return (
                self.session.generation == self.generation
                and summary["authenticated"]
                and summary["identity"] == self.identity
                and (info.st_dev, info.st_ino) == workspace.identity
                and Path(workspace.current_path()).resolve() == workspace.path
            )
        except (OSError, TypeError, ValueError):
            return False

    def _call(self, name, ticket, validate, *args, **kwargs):
        with self.session._job():
            try:
                self.session._live(self.generation, ticket)
                if (
                    local_binding(self.session.workspace.path, require_capture=True)
                    != self.identity
                ):
                    raise EnrollmentRequired(
                        "Device management requires the current workspace binding"
                    )
                with self.session.authorized(ticket) as (transport, token, identity, live):
                    if identity != self.identity:
                        raise SyncStopped("The device-management connection changed")
                    self.session._live(self.generation, ticket)
                    result = getattr(transport, name)(token, *args, **kwargs)
                    result = validate(result)
                    live()
                    self.session._live(self.generation, ticket)
                    return result
            except (SyncStopped, WorkspaceChanged) as error:
                raise DeviceContextChanged(
                    "The captured device-management binding changed"
                ) from error

    def catalog(self, ticket, *, after=None, limit=50):
        bounds = protocol.catalog_bounds(after, limit)
        return self._call(
            "device_catalog",
            ticket,
            lambda value: protocol.catalog(value, **bounds, identity=self.identity),
            **bounds,
        )

    def rename(self, device_id, label, ticket):
        target, label = _device_id(device_id), device_label(label)
        return self._call(
            "rename_device",
            ticket,
            lambda value: protocol.renamed(value, target, label),
            target,
            label,
        )

    def revoke(self, device_id, ticket):
        target = _device_id(device_id)
        if target == self.identity["device_id"]:
            raise ValueError("Use Disconnect for this device")
        return self._call(
            "revoke_peer", ticket, lambda value: protocol.revoked(value, target), target
        )


    def create_pairing(self, code, ticket):
        """Grant access only through this exact verified, enrolled device context."""
        protocol.pairing_secret(code)
        return self._call(
            "create_pairing", ticket,
            lambda value: protocol.pairing_created(value, self.identity), code,
        )
