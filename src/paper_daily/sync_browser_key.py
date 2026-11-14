"""Private operator signing keys, separate from authority/research backup state."""

from __future__ import annotations

import base64
import json
import os
import secrets
import stat
from pathlib import Path

from paper_daily.sync_http import _closed, _decode
from paper_daily.workspace_service import _safe_path

FORMAT = "paperfact.browser-signing-key.v1"
MAX_BYTES = 1024


def _validate_stat(info, *, uid=None):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= MAX_BYTES:
        raise ValueError("Use one bounded regular browser-key file, not a link")
    if uid is not None and (info.st_uid != uid or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError("Browser-key file must be owned by this user with private permissions")


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink


def load_key(path):
    """Read a fixed private key; construction never creates/rotates a missing key."""
    path = _safe_path(Path(path))
    uid = getattr(os, "geteuid", lambda: None)()
    before = path.stat()
    _validate_stat(before, uid=uid)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        _validate_stat(opened, uid=uid)
        if _identity(before) != _identity(opened):
            raise ValueError("Browser-key file changed before reading")
        data = os.read(fd, MAX_BYTES + 1)
        after = os.fstat(fd)
        _validate_stat(after, uid=uid)
        if (
            _identity(after) != _identity(opened)
            or _safe_path(path) != path
            or _identity(path.stat()) != _identity(opened)
        ):
            raise ValueError("Browser-key file changed while reading")
    finally:
        os.close(fd)
    record = _decode(data)
    _closed(record, {"format", "key"})
    if record["format"] != FORMAT or not isinstance(record["key"], str):
        raise ValueError("Unsupported browser-key record")
    text = record["key"]
    if len(text) != 43:
        raise ValueError("Expected a separate 32-byte browser signing key")
    try:
        key = base64.b64decode(text + "=", altchars=b"-_", validate=True)
    except ValueError:
        raise ValueError("Invalid browser signing key") from None
    if len(key) != 32 or base64.urlsafe_b64encode(key).decode().rstrip("=") != text:
        raise ValueError("Invalid browser signing key")
    return key


def create_key(output):
    """Exclusive creation, stable retries; no overwrite or automatic credential rotation."""
    path = _safe_path(Path(output))
    if path.exists():
        load_key(path)
        return {"state": "already_exists", "key_file": str(path)}
    key = secrets.token_bytes(32)
    record = dict(format=FORMAT, key=base64.urlsafe_b64encode(key).decode().rstrip("="))
    body = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    except FileExistsError:
        load_key(path)
        return {"state": "already_exists", "key_file": str(path)}
    # Failed writes remain unconfirmed for operator review; never delete/replace
    # an existing path or silently generate a different key on the next serve.
    with os.fdopen(fd, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    if load_key(path) != key:
        raise ValueError("Browser-key publication could not be verified")
    return {"state": "created", "key_file": str(path)}
