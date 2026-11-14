"""Closed device actions and one-time pairing; responses contain no credentials."""

from paper_daily.sync_device_management import (
    MAX_CATALOG_PAGE,
    _device_id,
    device_label,
    pairing_secret,
)

ROUTES = {"/v1/devices/" + name for name in ("list", "rename", "revoke")}
PAIR_CREATE = "/v1/devices/pairing/create"
PAIR_REDEEM = "/v1/devices/pairing/redeem"
ROUTES |= {PAIR_CREATE, PAIR_REDEEM}


def pairing_created(value, identity=None):
    closed(value, {"workspace_id", "issuer_device_id", "expires_at"})
    _device_id(value["workspace_id"])
    _device_id(value["issuer_device_id"])
    if type(value["expires_at"]) is not int or not 0 < value["expires_at"] < 2**63:
        raise ValueError("Invalid pairing expiry")
    if identity is not None and (value["workspace_id"], value["issuer_device_id"]) != (
        identity["workspace_id"], identity["device_id"]
    ):
        raise ValueError("Pairing belongs to another authenticated device")
    return value


def pairing_claimed(value, workspace_id, device_id):
    closed(value, {"workspace_id", "device_id"})
    if value != {"workspace_id": workspace_id, "device_id": device_id}:
        raise ValueError("Pairing response belongs to another device")
    _device_id(workspace_id)
    _device_id(device_id)
    return value



def closed(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("Invalid device-management fields")


def catalog_bounds(after, limit):
    if after is not None:
        _device_id(after)
    if type(limit) is not int or not 1 <= limit <= MAX_CATALOG_PAGE:
        raise ValueError("Invalid device page bounds")
    return {"after": after, "limit": limit}


def catalog(value, *, after=None, limit=50, identity=None):
    catalog_bounds(after, limit)
    closed(value, {"workspace_id", "current_device_id", "devices", "next_cursor"})
    _device_id(value["workspace_id"])
    _device_id(value["current_device_id"])
    if identity is not None and (value["workspace_id"], value["current_device_id"]) != (
        identity["workspace_id"],
        identity["device_id"],
    ):
        raise ValueError("Device catalog belongs to another authenticated binding")
    rows = value["devices"]
    if not isinstance(rows, list) or len(rows) > limit:
        raise ValueError("Device catalog exceeds its page bound")
    previous = after or ""
    for row in rows:
        closed(row, {"device_id", "label", "revoked"})
        _device_id(row["device_id"])
        device_label(row["label"])
        if type(row["revoked"]) is not bool or row["device_id"] <= previous:
            raise ValueError("Invalid device catalog state or order")
        if row["device_id"] == value["current_device_id"] and row["revoked"]:
            raise ValueError("Authenticated current device cannot be revoked")
        previous = row["device_id"]
    cursor = value["next_cursor"]
    if cursor is not None:
        _device_id(cursor)
        if len(rows) != limit or cursor != previous:
            raise ValueError("Invalid device catalog continuation")
    return value


def renamed(value, device_id, label):
    closed(value, {"device_id", "label", "changed"})
    _device_id(value["device_id"])
    device_label(value["label"])
    if (
        value["device_id"] != device_id
        or value["label"] != label
        or type(value["changed"]) is not bool
    ):
        raise ValueError("Invalid device rename response")
    return value


def revoked(value, device_id):
    closed(value, {"device_id", "revoked", "changed"})
    _device_id(value["device_id"])
    if (
        value["device_id"] != device_id
        or value["revoked"] is not True
        or type(value["changed"]) is not bool
    ):
        raise ValueError("Invalid peer revocation response")
    return value


def request(service, path, token, value):
    # Authenticate before validating target/shape. Every core method authenticates
    # again within its own read/write transaction; this is no mutation authority.
    if path == PAIR_REDEEM:
        closed(value, {"workspace_id", "device_id", "credential", "label"})
        result = service.redeem_pairing(token, **value)
        return pairing_claimed(result, value["workspace_id"], value["device_id"])
    identity = service.session_info(token)
    if path == PAIR_CREATE:
        closed(value, {"code"})
        result = service.create_pairing(token, pairing_secret(value["code"]))
        return pairing_created(result, identity)
    if path.endswith("/list"):
        closed(value, {"after", "limit"})
        bounds = catalog_bounds(**value)
        result = service.device_catalog(token, **bounds)
        return catalog(result, **bounds, identity=identity)
    if path.endswith("/rename"):
        closed(value, {"device_id", "label"})
        target, label = _device_id(value["device_id"]), device_label(value["label"])
        return renamed(service.rename_device(token, target, label), target, label)
    closed(value, {"device_id"})
    target = _device_id(value["device_id"])
    return revoked(service.revoke_peer(token, target), target)
