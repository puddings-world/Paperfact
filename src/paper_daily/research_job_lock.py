"""Nonblocking, database-scoped producer exclusion without stale PID leases."""

from __future__ import annotations

import errno
import hashlib
import os
import re
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def claim(database: str | Path, feature: str, owner_id: str):
    """Yield whether this caller owns the job; never wait and rerun a duplicate.

    The OS releases ownership on close or process exit. Keep the small lock file:
    unlinking it could let a second inode admit another producer while one runs.
    This prevents duplicate local work, not changes from another device; observed
    input/output checks still guard publication. No database transaction is held.
    """
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", feature):
        raise ValueError("Invalid research job feature")
    if not isinstance(owner_id, str) or not owner_id or len(owner_id) > 1024:
        raise ValueError("Invalid research job owner")
    database = Path(database).resolve(strict=True)
    if not database.is_file():
        raise ValueError("Research database is not a file")
    key = "\0".join((os.path.normcase(str(database)), feature, owner_id))
    folder = database.parent / ".research-jobs"
    folder.mkdir(exist_ok=True)
    path = folder / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".lock")
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        acquired = False
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
        try:
            yield acquired
        finally:
            if acquired:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
