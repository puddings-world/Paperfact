"""Explicit device-local Drive grants; never part of research or sync payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from paper_daily.connection_vault import _LOCK, MAX_BYTES, ConnectionVault, VaultUnavailable
from paper_daily.drive_sync_files import DriveFiles, decode, identifier
from paper_daily.google_slides import SCOPE, GoogleSession, read_client
from paper_daily.sync_journal import _identifier
from paper_daily.workspace_service import Ticket

SERVICE = "io.github.puddings-world.paperfact.drive-sync"
FORMAT = "paperfact.drive-grant.v1"


@dataclass(frozen=True)
class DriveGrant:
    owner_id: str
    client_id: str
    workspace_id: str
    folder_id: str
    head_id: str
    refresh_token: str = field(repr=False)

    def encoded(self):
        identifier(self.owner_id)
        identifier(self.folder_id)
        identifier(self.head_id)
        _identifier(self.workspace_id)
        if (not isinstance(self.client_id, str) or len(self.client_id) > 300
                or not self.client_id.endswith(".apps.googleusercontent.com")
                or any(ord(c) < 33 or ord(c) > 126 for c in self.client_id)):
            raise ValueError("Invalid Google desktop client")
        if (not isinstance(self.refresh_token, str) or not self.refresh_token
                or len(self.refresh_token) > 2000
                or any(ord(c) < 33 or ord(c) > 126 for c in self.refresh_token)):
            raise ValueError("Google did not provide a reusable desktop grant")
        body = json.dumps({"format": FORMAT, **self.__dict__}, sort_keys=True,
                          separators=(",", ":"), ensure_ascii=True)
        if len(body.encode("utf-16-le")) > MAX_BYTES:
            raise ValueError("Drive grant exceeds the native credential limit")
        return body

    @classmethod
    def decoded(cls, body):
        if not isinstance(body, str) or len(body.encode("utf-16-le")) > MAX_BYTES:
            raise ValueError("Invalid native Drive grant")
        value = decode(body.encode("utf-8"), MAX_BYTES)
        if (not isinstance(value, dict) or set(value) != {
                "format", "owner_id", "client_id", "workspace_id", "folder_id", "head_id",
                "refresh_token"} or value["format"] != FORMAT):
            raise ValueError("Unsupported native Drive grant")
        result = cls(**{key: item for key, item in value.items() if key != "format"})
        result.encoded()
        return result

    def session(self, *, client_reader=read_client):
        """No refresh/network here; client changes require explicit authorization."""
        client = client_reader()
        if client.get("client_id") != self.client_id:
            raise PermissionError("The Google desktop client changed; reconnect Drive")
        return GoogleSession(client, {"refresh_token": self.refresh_token}, 0)


class DriveVault:
    """A verified grant for one local database lifetime, saved only on explicit action.

    Remembering the grant does not enable uploads or permit opening the native
    store at startup. The desktop must retain its separate local opt-in guard.
    """

    def __init__(self, workspace, *, library=False, **options):
        # Reuse exactly the existing database-lifetime and platform-vault boundary.
        self.binding = ConnectionVault(workspace, **options)
        bindings = json.loads(self.binding._baseline)[2]
        self.service = SERVICE
        self.folder_role = "workspace"
        if library:
            if bindings:
                raise ValueError("Use workspace authorization for an enrolled workspace")
            self.workspace_id = "directory.personal"
            self.service = SERVICE + ".library"
            self.folder_role = "directory"
            return
        if not bindings:
            raise ValueError("Enroll the local workspace before remembering Drive")
        self.workspace_id = bindings[0][1][0]

    def load(self, ticket=None):
        ticket = ticket or Ticket()
        with _LOCK:
            self.binding._check()
            ticket.check()
            try:
                body = self.binding._backend().get_password(self.service, self.binding.account)
            except Exception:
                raise VaultUnavailable("Native Drive credential storage is unavailable") from None
            self.binding._check()
            ticket.check()
            grant = None if body is None else DriveGrant.decoded(body)
            if grant is not None and grant.workspace_id != self.workspace_id:
                raise PermissionError("Saved Drive grant belongs to another workspace")
            return grant

    def remember(self, files: DriveFiles, folder_id, head_id, workspace_id, ticket=None,
                 *, owner_id=None):
        ticket = ticket or Ticket()
        self.binding._check()
        ticket.check()
        if workspace_id != self.workspace_id:
            raise PermissionError("Drive grant belongs to another local workspace")
        session = files.session
        owner = files.account()
        if owner_id is not None and owner["id"] != owner_id:
            raise PermissionError("The reviewed Google account changed")
        files.read_head(head_id, folder_id, workspace_id, folder_role=self.folder_role)
        if files.session is not session:
            raise PermissionError("Google account changed while remembering Drive")
        scopes = session.token.get("scope")
        if scopes is not None and (not isinstance(scopes, str) or SCOPE not in scopes.split()):
            raise PermissionError("Drive file authorization is required")
        grant = DriveGrant(owner["id"], session.client.get("client_id"), workspace_id,
                           folder_id, head_id, session.token.get("refresh_token"))
        body = grant.encoded()
        with _LOCK:
            self.binding._check()
            ticket.check()
            try:
                backend = self.binding._backend()
                previous = backend.get_password(self.service, self.binding.account)
                backend.set_password(self.service, self.binding.account, body)
            except Exception:
                raise VaultUnavailable("Native Drive credential storage is unavailable") from None
            try:
                self.binding._check()
                ticket.check()
                if files.session is not session:
                    raise PermissionError("Google account changed while remembering Drive")
            except Exception:
                try:
                    if backend.get_password(self.service, self.binding.account) == body:
                        if previous is None:
                            backend.delete_password(self.service, self.binding.account)
                        else:
                            backend.set_password(self.service, self.binding.account, previous)
                except Exception:
                    raise VaultUnavailable("Review Drive in the system credential store") from None
                raise
        return grant

    def forget(self, ticket=None):
        ticket = ticket or Ticket()
        with _LOCK:
            self.binding._check()
            ticket.check()
            try:
                backend = self.binding._backend()
                if backend.get_password(self.service, self.binding.account) is not None:
                    backend.delete_password(self.service, self.binding.account)
            except Exception:
                raise VaultUnavailable("Native Drive credential storage is unavailable") from None
            self.binding._check()
            ticket.check()
