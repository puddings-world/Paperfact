"""Publish a staged directory without replacing an existing destination.

Linux: renameat2(RENAME_NOREPLACE), man7.org/linux/man-pages/man2/rename.2.html.
Darwin: renamex_np(RENAME_EXCL), Apple XNU bsd/man/man2/rename.2 and sys/stdio.h.
Unsupported kernels/filesystems fail; there is no check-then-rename fallback.
"""

from __future__ import annotations

import ctypes
import errno
import os
import sys
from pathlib import Path


def publish_directory(source, destination):
    """Atomically move a complete stage to a new name on the same filesystem."""
    source, destination = Path(source).absolute(), Path(destination).absolute()
    if sys.platform == "win32":
        # Windows rename refuses any existing destination, including empty folders.
        os.rename(source, destination)
        return
    if sys.platform not in {"linux", "darwin"}:
        raise OSError(errno.ENOTSUP, "Atomic no-replace publication is unsupported")
    name = "renameat2" if sys.platform == "linux" else "renamex_np"
    try:
        library = ctypes.CDLL(None, use_errno=True)
        function = getattr(library, name)
    except (AttributeError, OSError) as exc:
        raise OSError(errno.ENOTSUP, "Atomic no-replace publication is unavailable") from exc
    function.restype = ctypes.c_int
    old, new = os.fsencode(source), os.fsencode(destination)
    if b"\0" in old or b"\0" in new:
        raise ValueError("Directory path contains an embedded NUL")
    if sys.platform == "linux":
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        args = (-100, old, -100, new, 1)  # AT_FDCWD, RENAME_NOREPLACE
    else:
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        args = (old, new, 0x00000004)  # RENAME_EXCL
    ctypes.set_errno(0)
    if function(*args) != 0:
        error = ctypes.get_errno() or errno.EIO
        raise OSError(error, os.strerror(error), str(source), None, str(destination))
