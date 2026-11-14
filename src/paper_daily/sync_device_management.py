"""Single-owner device catalog, labels and peer revocation for the reference authority.

Server core only. Every enrolled token in a workspace belongs to one research
owner, so any active device may list, label or revoke its peers. Each method
authenticates the caller inside the same service transaction and scopes every
lookup to the caller's workspace. Token hashes are never selected or returned;
labels are owner-entered plain text and nothing about a device is inferred.
"""

from __future__ import annotations

import re
import time
import unicodedata

from paper_daily.sync_journal import ID

MAX_LABEL_CHARS = 64
MAX_CATALOG_PAGE = 100
PAIRING_SECONDS = 600
MAX_PAIRINGS = 100
PAIRING_COLUMNS = (
    "code_hash", "workspace", "issuer_hash", "expires_at", "claimed_device",
    "claimed_hash", "claim_label",
)


def pairing_secret(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise ValueError("Expected a newly generated 32-byte pairing secret")
    return value

_UNKNOWN_DEVICE = "Unknown device for this workspace"
# Category checks cover C0/DEL/C1 controls, surrogates and line/paragraph
# separators; explicit bidi controls would let a label visually spoof another.
_REJECTED_CATEGORIES = frozenset({"Cc", "Cs", "Zl", "Zp"})
_BIDI_CONTROLS = frozenset(
    "؜‎‏‪‫‬‭‮⁦⁧⁨⁩"
)


class UnknownDeviceError(ValueError):
    """Missing and other-workspace devices are deliberately indistinguishable."""


class CurrentDeviceError(ValueError):
    """A device cannot revoke itself remotely; local Disconnect remains available."""


def _device_id(value, message="Invalid sync identifier"):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError(message)
    return str(value)


def device_label(value):
    """Validate an optional owner-entered label; ``None`` clears it."""
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_LABEL_CHARS:
        raise ValueError(f"Device label must be 1 to {MAX_LABEL_CHARS} characters or null")
    if value != value.strip():
        raise ValueError("Device label must not start or end with whitespace")
    for character in value:
        if (
            unicodedata.category(character) in _REJECTED_CATEGORIES
            or character in _BIDI_CONTROLS
        ):
            raise ValueError("Device label must be single-line plain text")
    return str(value)


class DeviceManagementMixin:
    @staticmethod
    def _device_schema(conn):
        # Lazy, idempotent upgrade of authorities created before labels existed.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(sync_devices)")}
        if "label" not in columns:
            conn.execute("ALTER TABLE sync_devices ADD COLUMN label TEXT")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sync_pairings ("
            "code_hash TEXT PRIMARY KEY,workspace TEXT NOT NULL,issuer_hash TEXT NOT NULL,"
            "expires_at INTEGER NOT NULL,claimed_device TEXT,claimed_hash TEXT,claim_label TEXT)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS sync_pairings_expiry ON sync_pairings(workspace,expires_at)"
        )

    def device_catalog(self, token: str, *, after: str | None = None, limit: int = 50) -> dict:
        """List this workspace's devices by ID after a strict cursor, one bounded page."""
        with self._transaction() as conn:
            workspace, current = self._authenticate(conn, token)
            if after is not None:
                after = _device_id(after, "Invalid device cursor")
            if type(limit) is not int or not 1 <= limit <= MAX_CATALOG_PAGE:
                raise ValueError(f"Device page size must be between 1 and {MAX_CATALOG_PAGE}")
            rows = conn.execute(
                "SELECT device,label,revoked FROM sync_devices "
                "WHERE workspace=? AND device>? ORDER BY device LIMIT ?",
                (workspace, "" if after is None else after, limit + 1),
            ).fetchall()
        page = rows[:limit]
        return {
            "workspace_id": workspace,
            "current_device_id": current,
            "devices": [
                {"device_id": row["device"], "label": row["label"], "revoked": bool(row["revoked"])}
                for row in page
            ],
            "next_cursor": page[-1]["device"] if len(rows) > limit else None,
        }

    def rename_device(self, token: str, device_id: str, label: str | None) -> dict:
        """Set or clear a label on this or a peer device in the caller's workspace."""
        with self._transaction(write=True) as conn:
            workspace, _current = self._authenticate(conn, token)
            device_id, label = _device_id(device_id), device_label(label)
            row = conn.execute(
                "SELECT label FROM sync_devices WHERE workspace=? AND device=?",
                (workspace, device_id),
            ).fetchone()
            if row is None:
                raise UnknownDeviceError(_UNKNOWN_DEVICE)
            changed = row["label"] != label
            if changed:
                conn.execute(
                    "UPDATE sync_devices SET label=? WHERE workspace=? AND device=?",
                    (label, workspace, device_id),
                )
            return {"device_id": device_id, "label": label, "changed": changed}

    def revoke_peer(self, token: str, device_id: str) -> dict:
        """Revoke another device's credential; research, events and cursors are untouched."""
        with self._transaction(write=True) as conn:
            workspace, current = self._authenticate(conn, token)
            device_id = _device_id(device_id)
            if device_id == current:
                raise CurrentDeviceError("Use local Disconnect to stop this device")
            row = conn.execute(
                "SELECT revoked FROM sync_devices WHERE workspace=? AND device=?",
                (workspace, device_id),
            ).fetchone()
            if row is None:
                raise UnknownDeviceError(_UNKNOWN_DEVICE)
            changed = not row["revoked"]
            if changed:
                conn.execute(
                    "UPDATE sync_devices SET revoked=1 WHERE workspace=? AND device=?",
                    (workspace, device_id),
                )
            return {"device_id": device_id, "revoked": True, "changed": changed}


    @staticmethod
    def _pair_now():
        return int(time.time())

    def create_pairing(self, token, code):
        """Explicit trusted-device grant; raw invitation secrets are never persisted."""
        with self._transaction(write=True) as conn:
            workspace, device = self._authenticate(conn, token)
            pairing_secret(code)
            digest, issuer, now = self._token_hash(code), self._token_hash(token), self._pair_now()
            if conn.execute("SELECT 1 FROM sync_devices WHERE token_hash=?", (digest,)).fetchone():
                raise ValueError("Generate a separate pairing secret")
            previous = conn.execute("SELECT * FROM sync_pairings WHERE code_hash=?",
                                    (digest,)).fetchone()
            if previous is not None:
                if (previous["workspace"] != workspace or previous["issuer_hash"] != issuer
                        or previous["claimed_device"] is not None
                        or previous["expires_at"] <= now):
                    raise ValueError("Pairing request is already used; generate a new one")
                expires = previous["expires_at"]
            else:
                count = conn.execute(
                    "SELECT count(*) FROM sync_pairings WHERE workspace=? AND expires_at>?",
                    (workspace, now),
                ).fetchone()[0]
                if count >= MAX_PAIRINGS:
                    raise ValueError("Too many pairing invitations; wait for expiry")
                expires = now + PAIRING_SECONDS
                conn.execute(
                    "INSERT INTO sync_pairings(code_hash,workspace,issuer_hash,expires_at) "
                    "VALUES(?,?,?,?)", (digest, workspace, issuer, expires),
                )
            return {"workspace_id": workspace, "issuer_device_id": device, "expires_at": expires}

    def redeem_pairing(self, code, workspace_id, device_id, credential, label=None):
        """Atomically bind one invite to one fresh credential; exact retries do not rotate it."""
        try:
            pairing_secret(code)
        except ValueError:
            raise PermissionError("Pairing is unavailable or expired") from None
        with self._transaction(write=True) as conn:
            digest = self._token_hash(code)
            invitation = conn.execute("SELECT * FROM sync_pairings WHERE code_hash=?",
                                      (digest,)).fetchone()
            if invitation is None or invitation["expires_at"] <= self._pair_now():
                raise PermissionError("Pairing is unavailable or expired")
            issuer = conn.execute("SELECT workspace,revoked FROM sync_devices WHERE token_hash=?",
                                  (invitation["issuer_hash"],)).fetchone()
            if (issuer is None or issuer["revoked"]
                    or issuer["workspace"] != invitation["workspace"]
                    or workspace_id != invitation["workspace"]):
                raise PermissionError("Pairing is unavailable or expired")
            _device_id(workspace_id)
            _device_id(device_id)
            pairing_secret(credential)
            label = device_label(label)
            claimed_hash = self._token_hash(credential)
            if conn.execute(
                "SELECT 1 FROM sync_pairings WHERE code_hash=?", (claimed_hash,)
            ).fetchone() is not None:
                raise ValueError("Generate a separate device credential")
            if invitation["claimed_device"] is not None:
                if (invitation["claimed_device"] != device_id
                        or invitation["claimed_hash"] != claimed_hash
                        or invitation["claim_label"] != label):
                    raise PermissionError("Pairing is unavailable or expired")
                if self._authenticate(conn, credential) != (workspace_id, device_id):
                    raise PermissionError("Pairing is unavailable or expired")
            else:
                if conn.execute(
                    "SELECT 1 FROM sync_devices WHERE (workspace=? AND device=?) OR token_hash=?",
                    (workspace_id, device_id, claimed_hash),
                ).fetchone() is not None:
                    raise ValueError("Use a new device identity and credential")
                conn.execute(
                    "INSERT INTO sync_devices(token_hash,workspace,device,label) VALUES(?,?,?,?)",
                    (claimed_hash, workspace_id, device_id, label),
                )
                conn.execute(
                    "UPDATE sync_pairings SET claimed_device=?,claimed_hash=?,claim_label=? "
                    "WHERE code_hash=?", (device_id, claimed_hash, label, digest),
                )
            return {"workspace_id": workspace_id, "device_id": device_id}
