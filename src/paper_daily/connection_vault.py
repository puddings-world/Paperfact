"""Explicit OS-vault connection memory, never research data or silent login."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
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

    def __init__(self, workspace, *, backend=native_backend, startup_dir=None):
        self.workspace, self._backend = workspace, backend
        self._baseline = self._context()
        self.account = "v1." + hashlib.sha256(self._baseline).hexdigest()
        from paper_daily.runtime import user_cache_dir

        self.startup_path = Path(startup_dir or user_cache_dir() / "sync-startup") / (
            self.account + ".json"
        )

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

    def startup_record(self):
        """Local opt-in fingerprint only; never accesses the native credential store."""
        if not self.current():
            return None
        try:
            with self.startup_path.open("rb") as stream:
                body = stream.read(1025)
            if len(body) > 1024:
                return None
            value = json.loads(body)
            if (type(value) is not dict or set(value) != {"format", "connection"}
                    or type(value["format"]) is not int or value["format"] != 1):
                return None
            fingerprint = value["connection"]
            if (not isinstance(fingerprint, str) or len(fingerprint) != 64
                    or any(c not in "0123456789abcdef" for c in fingerprint)):
                return None
            return fingerprint
        except (OSError, ValueError, UnicodeError):
            return None

    def set_startup(self, session, enabled, ticket=None):
        """Explicit device-local consent, bound to the exact verified connection."""
        ticket = ticket or Ticket()
        with _LOCK:
            self._check()
            ticket.check()
            if not enabled:
                self.startup_path.unlink(missing_ok=True)
                return
            with session._state:
                generation = session._generation
                identity = session.identity or {}
                connection = Connection(
                    session.endpoint, identity.get("workspace_id"),
                    identity.get("device_id"), session._token,
                )
            # Remember validates the exact live session; no plaintext fallback.
            self.remember(session, connection, ticket)
            fingerprint = hashlib.sha256(connection.encoded().encode()).hexdigest()
            self.startup_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.startup_path.parent,
                    prefix=".consent-", delete=False,
                ) as stream:
                    temporary = Path(stream.name)
                    json.dump({"format": 1, "connection": fingerprint}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                self._check()
                session._live(generation, ticket)
                os.replace(temporary, self.startup_path)
                self._check()
                session._live(generation, ticket)
            except BaseException:
                # A cancelled consent write must not authorize a future startup.
                self.startup_path.unlink(missing_ok=True)
                raise
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

    def reconnect_startup(self, session, expected, ticket):
        """Authenticate only if this exact local opt-in still authorizes the record."""
        with _LOCK:
            self._check()
            ticket.check()
            if (session.workspace.path != self.workspace.path
                    or session.workspace.identity != self.workspace.identity):
                raise WorkspaceChanged("Startup permission belongs to another local workspace")
            generation = session.generation
            if expected is None or self.startup_record() != expected:
                return None
            connection = self.load(ticket)
            session._live(generation, ticket)
            if (connection is None
                    or hashlib.sha256(connection.encoded().encode()).hexdigest() != expected):
                return None
            ticket.check()
            if self.startup_record() != expected:
                return None
            session.connect(
                connection.endpoint, connection.workspace_id, connection.device_id,
                connection.token, ticket,
            )
            generation = session.generation
            try:
                self._check()
                session._live(generation, ticket)
                if self.startup_record() != expected:
                    raise WorkspaceChanged("Startup permission changed")
            except BaseException:
                session.disconnect()
                raise
            return {"generation": generation}

    def forget(self, ticket=None):
        ticket = ticket or Ticket()
        with _LOCK:
            self._check()
            ticket.check()
            self.startup_path.unlink(missing_ok=True)
            try:
                backend = self._backend()
                if backend.get_password(SERVICE, self.account) is not None:
                    backend.delete_password(SERVICE, self.account)
            except Exception:
                raise VaultUnavailable("Native credential storage is unavailable") from None
            self._check()
            ticket.check()
