"""Single-owner device catalog, labels and peer revocation for the reference authority.

Server core only. Every enrolled token in a workspace belongs to one research
owner, so any active device may list, label or revoke its peers. Each method
authenticates the caller inside the same service transaction and scopes every
lookup to the caller's workspace. Token hashes are never selected or returned;
labels are owner-entered plain text and nothing about a device is inferred.
"""

from __future__ import annotations

import unicodedata

from paper_daily.sync_journal import ID

MAX_LABEL_CHARS = 64
MAX_CATALOG_PAGE = 100
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
