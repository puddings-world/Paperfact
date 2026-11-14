"""Explicit native device-pairing packets and retryable receiver state.

No research upload, plaintext credential files, global-account login or implicit
workspace switch. The native vault owns optional cross-process persistence.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from paper_daily.connection_vault import MAX_BYTES, Connection
from paper_daily.sync_device_management import _device_id, pairing_secret
from paper_daily.sync_device_protocol import closed, pairing_claimed, pairing_created
from paper_daily.sync_http import HttpTransport, _decode
from paper_daily.workspace_service import WorkspaceChanged, _safe_path
from paper_daily.workspace_sync import EnrollmentRequired, local_binding

FORMAT = "paperfact.device-pairing.v1"
PENDING = "paperfact.device-pairing-attempt.v1"
MAX_PACKET = 8192


def _json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


@dataclass(frozen=True)
class Invitation:
    endpoint: str
    workspace_id: str
    issuer_device_id: str
    expires_at: int
    code: str = field(repr=False)

    def encoded(self):
        _device_id(self.workspace_id)
        _device_id(self.issuer_device_id)
        pairing_secret(self.code)
        pairing_created(
            dict(
                workspace_id=self.workspace_id,
                issuer_device_id=self.issuer_device_id,
                expires_at=self.expires_at,
            )
        )
        with HttpTransport(self.endpoint) as transport:
            endpoint = transport.base_url
        value = _json(
            dict(
                format=FORMAT,
                endpoint=endpoint,
                workspace_id=self.workspace_id,
                issuer_device_id=self.issuer_device_id,
                expires_at=self.expires_at,
                code=self.code,
            )
        )
        if len(value.encode()) > MAX_PACKET:
            raise ValueError("Pairing packet exceeds its byte budget")
        return value

    @classmethod
    def decoded(cls, body):
        if not isinstance(body, str) or len(body.encode()) > MAX_PACKET:
            raise ValueError("Invalid pairing packet")
        value = _decode(body.encode())
        closed(
            value, {"format", "endpoint", "workspace_id", "issuer_device_id", "expires_at", "code"}
        )
        if value.pop("format") != FORMAT:
            raise ValueError("Unsupported pairing packet")
        invitation = cls(**value)
        normalized = json.loads(invitation.encoded())
        normalized.pop("format")
        return cls(**normalized)


@dataclass(frozen=True)
class Attempt:
    invitation: Invitation = field(repr=False)
    device_id: str
    credential: str = field(repr=False)

    @classmethod
    def start(cls, invitation):
        if type(invitation) is not Invitation:
            raise ValueError("Use a validated invitation")
        invitation.encoded()
        return cls(
            Invitation.decoded(invitation.encoded()), str(uuid4()), secrets.token_urlsafe(32)
        )

    @property
    def connection(self):
        return Connection(
            self.invitation.endpoint, self.invitation.workspace_id, self.device_id, self.credential
        )

    def encoded(self):
        _device_id(self.device_id)
        pairing_secret(self.credential)
        if self.credential == self.invitation.code:
            raise ValueError("Pairing needs an independent device credential")
        body = _json(
            dict(
                format=PENDING,
                invitation=json.loads(self.invitation.encoded()),
                device_id=self.device_id,
                credential=self.credential,
            )
        )
        if len(body.encode("utf-16-le")) > MAX_BYTES:
            raise ValueError("Pairing state exceeds the native credential-store budget")
        return body

    @classmethod
    def decoded(cls, body):
        if not isinstance(body, str) or len(body.encode("utf-16-le")) > MAX_BYTES:
            raise ValueError("Invalid saved pairing")
        value = _decode(body.encode())
        closed(value, {"format", "invitation", "device_id", "credential"})
        if value["format"] != PENDING:
            raise ValueError("Unsupported saved pairing")
        result = cls(
            Invitation.decoded(_json(value["invitation"])), value["device_id"], value["credential"]
        )
        result.encoded()
        return result

    def connect(self, session, ticket, progress=lambda _value: None):
        """Retry the exact credential; a lost claim response does not mint another device."""
        self.encoded()
        expected = {"workspace_id": self.invitation.workspace_id, "device_id": self.device_id}
        epoch = session.generation
        with session._job():
            session._live(epoch, ticket)
            binding = local_binding(session.workspace.path)
            if binding is not None and binding != expected:
                raise EnrollmentRequired("Use the existing identity for an enrolled workspace")
            progress({"stage": "pairing", "phase": "verifying"})
            with session._factory(self.invitation.endpoint) as transport:
                try:
                    identity = transport.session_info(self.credential)
                except PermissionError:
                    session._live(epoch, ticket)
                    progress({"stage": "pairing", "phase": "claiming"})
                    identity = transport.redeem_pairing(
                        self.invitation.code,
                        expected["workspace_id"],
                        self.device_id,
                        self.credential,
                    )
                pairing_claimed(identity, expected["workspace_id"], self.device_id)
                session._live(epoch, ticket)
        session._live(epoch, ticket)
        progress({"stage": "pairing", "phase": "verifying"})
        result = session.connect(
            self.connection.endpoint,
            self.connection.workspace_id,
            self.device_id,
            self.credential,
            ticket,
        )
        return dict(result, generation=session.generation)


def remember_joined(session, destination, ticket, *, vault_factory=None):
    """Remember this device only for the exact newly joined DB, with source fences."""
    from paper_daily.connection_vault import ConnectionVault
    from paper_daily.workspace_sync import SyncSession

    epoch = session.generation
    with session._job():
        session._live(epoch, ticket)
        with session._state:
            identity = dict(session.identity or {})
            connection = Connection(
                session.endpoint,
                identity.get("workspace_id"),
                identity.get("device_id"),
                session._token,
            )
        root = _safe_path(Path(destination))
        database = _safe_path(root / "papers.db")
        info = database.stat()
        identity_on_disk = (info.st_dev, info.st_ino)
        if (
            database == session.workspace.path
            or local_binding(database, require_capture=True) != identity
        ):
            raise ValueError("Remember only this exact joined device workspace")

        def current():
            session._live(epoch, ticket)
            if _safe_path(root / "papers.db") != database:
                raise WorkspaceChanged("Joined workspace path changed")
            latest = database.stat()
            if (latest.st_dev, latest.st_ino) != identity_on_disk:
                raise WorkspaceChanged("Joined workspace database was replaced")
            return database

        target = SyncSession(database, current_path=current, transport_factory=session._factory)
        try:
            target.connect(
                connection.endpoint,
                connection.workspace_id,
                connection.device_id,
                connection.token,
                ticket,
            )
            vault = (vault_factory or ConnectionVault)(target.workspace)
            vault.remember(target, connection, ticket)
            session._live(epoch, ticket)
        finally:
            target.disconnect()
