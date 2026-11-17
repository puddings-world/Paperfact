"""Device-local default workspace; no authorization, migration or research writes."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

RECORD = "active-workspace.json"


def remembered_workspace(record):
    record = Path(record)
    try:
        if record.is_symlink() or record.stat().st_size > 4096:
            return None
        with record.open("rb") as source:
            raw = source.read(4097)
        value = json.loads(raw)
        if (
            not isinstance(value, dict)
            or set(value) != {"format", "root", "database_identity"}
            or type(value["format"]) is not int
            or value["format"] != 1
            or not isinstance(value["root"], str)
        ):
            return None
        root = Path(value["root"])
        if not root.is_absolute() or root.resolve(strict=True) != root:
            return None
        info = (root / "papers.db").lstat()
        identity = value["database_identity"]
        if (
            not isinstance(identity, list)
            or len(identity) != 2
            or any(type(v) is not int for v in identity)
            or not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or [info.st_dev, info.st_ino] != identity
        ):
            return None
        return root
    except (OSError, ValueError, TypeError):
        return None


def remember_workspace(root, *, record=None):
    root = Path(root).resolve(strict=True)
    info = (root / "papers.db").lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Remember an existing regular workspace database")
    if record is None:
        from paper_daily.runtime import user_data_dir

        record = user_data_dir() / RECORD
    record = Path(record)
    record.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=record.parent, prefix=".workspace-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(
                dict(format=1, root=str(root), database_identity=[info.st_dev, info.st_ino]), stream
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, record)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return root
