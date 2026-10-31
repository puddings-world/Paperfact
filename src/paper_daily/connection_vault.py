"""Explicit OS-vault connection memory, never research data or silent login."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily.sync_http import _TOKEN, HttpTransport
from paper_daily.sync_journal import _identifier
from paper_daily.workspace_service import Ticket, WorkspaceChanged, _binding, _read, _tables

SERVICE = "io.github.puddings-world.paperfact.sync"
MAX_BYTES = 2400  # Also fits Windows' 2560-byte UTF-16 credential blob limit.
_LOCK = threading.RLock()


class VaultUnavailable(RuntimeError):
    """No usable native vault; the manual in-memory connection still works."""


def native_backend():
    """Lazy selection; never accept plaintext, chained or unknown backends."""
    try:
        import keyring

        selected = keyring.get_keyring()
        if sys.platform == "win32":
            from keyring.backends.Windows import WinVaultKeyring

            expected = WinVaultKeyring
        elif sys.platform == "darwin":
            from keyring.backends.macOS import Keyring

            expected = Keyring
        elif sys.platform.startswith("linux"):
            from keyring.backends.SecretService import Keyring

            expected = Keyring
        else:
            raise VaultUnavailable("No supported native credential store")
        if type(selected) is not expected:
            raise VaultUnavailable("No supported native credential store")
        if sys.platform == "win32":
            # Do not roam this device-specific token through enterprise credentials.
            selected.persist = 2
        return selected
    except Exception:
        raise VaultUnavailable("Native credential storage is unavailable") from None


@dataclass(frozen=True)
class Connection:
    endpoint: str
    workspace_id: str
    device_id: str
    token: str = field(repr=False)

    def encoded(self):
        _identifier(self.workspace_id)
        _identifier(self.device_id)
        if not isinstance(self.token, str) or not _TOKEN.fullmatch(self.token):
            raise ValueError("Invalid device credential")
        with HttpTransport(self.endpoint) as transport:
            endpoint = transport.base_url
        body = json.dumps(
            {"format": 1, "endpoint": endpoint, "workspace_id": self.workspace_id,
             "device_id": self.device_id, "token": self.token},
            sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        )
        if len(body.encode("utf-16-le")) > MAX_BYTES:
            raise ValueError("Connection is too large for native credential storage")
        return body

    @classmethod
    def decoded(cls, body):
        if not isinstance(body, str) or len(body.encode("utf-16-le")) > MAX_BYTES:
            raise ValueError("Invalid stored connection")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Invalid stored connection")
                result[key] = value
            return result

        try:
            data = json.loads(body, object_pairs_hook=unique)
            if (not isinstance(data, dict) or set(data) != {
                "format", "endpoint", "workspace_id", "device_id", "token"
            } or type(data["format"]) is not int or data["format"] != 1):
                raise ValueError("Invalid stored connection")
            connection = cls(**{k: v for k, v in data.items() if k != "format"})
            connection.encoded()
            return connection
        except (ValueError, TypeError, UnicodeError):
            raise ValueError("Invalid stored connection") from None


class ConnectionVault:
    """One exact local database lifetime; all vault access is explicitly invoked.

    No constructor I/O to the system vault, no sync or automatic login. Backend
    injection exists for fixture tests; production uses native_backend exclusively.
    """

    def __init__(self, workspace, *, backend=native_backend):
        self.workspace, self._backend = workspace, backend
        self._baseline = self._context()
        self.account = "v1." + hashlib.sha256(self._baseline).hexdigest()

    def _context(self):
        workspace = self.workspace
        if Path(workspace.current_path()).resolve() != workspace.path:
            raise WorkspaceChanged("The active workspace changed")
        info = workspace.path.stat()
        if (info.st_dev, info.st_ino) != workspace.identity:
            raise WorkspaceChanged("The workspace database was replaced")
        with _read(workspace.path) as conn:
            binding = _binding(conn, _tables(conn))
        after = workspace.path.stat()
        if (after.st_dev, after.st_ino) != workspace.identity:
            raise WorkspaceChanged("The workspace database was replaced")
        return json.dumps(
            [str(workspace.path), workspace.identity, binding],
            separators=(",", ":"), ensure_ascii=True,
        ).encode()

    def _check(self):
        if self._context() != self._baseline:
            raise WorkspaceChanged("The workspace binding changed")

    def current(self):
        """Bounded local metadata guard; no vault lock/access, hashing or network.

        Used once at GUI delivery/explicit connect, not by the periodic poll.
        Unavailable metadata fails closed instead of applying a stale connection.
        """
        try:
            self._check()
        except (OSError, ValueError, sqlite3.Error):
            return False
        return True

    def load(self, ticket=None):
        ticket = ticket or Ticket()
        with _LOCK:
            self._check()
            ticket.check()
            try:
                body = self._backend().get_password(SERVICE, self.account)
            except Exception:
                raise VaultUnavailable("Native credential storage is unavailable") from None
            self._check()
            ticket.check()
            return None if body is None else Connection.decoded(body)

    def remember(self, session, connection, ticket=None):
        """Remember only the exact successful connection, not another entered token."""
        ticket = ticket or Ticket()
        if not isinstance(connection, Connection):
            raise ValueError("A verified connection is required")
        body = connection.encoded()
        with _LOCK:
            self._check()
            ticket.check()
            with session._state:
                generation = session._generation
                accepted = (
                    session.workspace.path == self.workspace.path
                    and session.workspace.identity == self.workspace.identity
                    and session._token == connection.token
                    and session.endpoint == connection.endpoint.rstrip("/")
                    and session.identity == {
                        "workspace_id": connection.workspace_id, "device_id": connection.device_id
                    }
                )
            if not accepted:
                raise ValueError("A matching verified connection is required")
            session._live(generation, ticket)
            try:
                backend = self._backend()
                previous = backend.get_password(SERVICE, self.account)
                backend.set_password(SERVICE, self.account, body)
            except Exception:
                raise VaultUnavailable("Native credential storage is unavailable") from None
            try:
                self._check()
                session._live(generation, ticket)
            except Exception:
                try:
                    if backend.get_password(SERVICE, self.account) == body:
                        if previous is None:
                            backend.delete_password(SERVICE, self.account)
                        else:
                            backend.set_password(SERVICE, self.account, previous)
                except Exception:
                    raise VaultUnavailable(
                        "Review this connection in the system credential store"
                    ) from None
                raise

    def forget(self, ticket=None):
        ticket = ticket or Ticket()
        with _LOCK:
            self._check()
            ticket.check()
            try:
                backend = self._backend()
                if backend.get_password(SERVICE, self.account) is not None:
                    backend.delete_password(SERVICE, self.account)
            except Exception:
                raise VaultUnavailable("Native credential storage is unavailable") from None
            self._check()
            ticket.check()
