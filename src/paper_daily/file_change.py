"""Private file-version observations; never a substitute for initial byte hashing.

Windows stat ctime is a creation timestamp on supported Python versions. Read
FILE_BASIC_INFO.ChangeTime from the same handle to invalidate cached byte proofs
with its per-file USN revision, including same-clock-tick writes and restored
mtime. An unavailable native token
fails closed. This is not protection against a hostile filesystem/kernel that
can forge every metadata field. Callers retain byte hashes and reparse guards.
"""

import ctypes
import os
import struct
import sys
from functools import lru_cache
from pathlib import Path

WINDOWS = sys.platform == "win32"


def _stat_version(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@lru_cache(maxsize=1)
def _windows_api():
    from ctypes import wintypes

    class BasicInfo(ctypes.Structure):
        _fields_ = [
            ("CreationTime", ctypes.c_longlong),
            ("LastAccessTime", ctypes.c_longlong),
            ("LastWriteTime", ctypes.c_longlong),
            ("ChangeTime", ctypes.c_longlong),
            ("FileAttributes", wintypes.DWORD),
        ]

    library = ctypes.WinDLL("kernel32", use_last_error=True)
    get_info = library.GetFileInformationByHandleEx
    get_info.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    return library, get_info, BasicInfo


def _decode_usn(data):
    if not isinstance(data, bytes) or not 8 <= len(data) <= 4096:
        raise OSError("Invalid bounded file revision record")
    length, major, minor = struct.unpack_from("<IHH", data)
    layout = {2: (60, 24), 3: (76, 40)}.get(major)
    if layout is None or minor != 0 or not layout[0] <= length <= len(data):
        raise OSError("Unsupported file revision record")
    revision = struct.unpack_from("<q", data, layout[1])[0]
    if revision <= 0:
        raise OSError("Filesystem does not expose a usable file revision")
    return revision


@lru_cache(maxsize=1)
def _usn_api():
    from ctypes import wintypes

    library, _get_info, _kind = _windows_api()
    invoke = library.DeviceIoControl
    invoke.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    invoke.restype = wintypes.BOOL
    return invoke


def _native_usn(stream):
    import msvcrt
    from ctypes import wintypes

    output, returned = ctypes.create_string_buffer(4096), wintypes.DWORD()
    if not _usn_api()(
        msvcrt.get_osfhandle(stream.fileno()), 0x000900EB, None, 0,
        output, len(output), ctypes.byref(returned), None,
    ):
        raise OSError(ctypes.get_last_error(), "File revision observation unavailable")
    return _decode_usn(output.raw[:returned.value])


def _native_change(stream):
    import msvcrt

    _library, get_info, kind = _windows_api()
    value = kind()
    handle = msvcrt.get_osfhandle(stream.fileno())
    if not get_info(handle, 0, ctypes.byref(value), ctypes.sizeof(value)):
        raise OSError(ctypes.get_last_error(), "File change observation unavailable")
    if value.ChangeTime <= 0:
        raise OSError("Filesystem does not expose a usable file change observation")
    return value.ChangeTime, _native_usn(stream)


def _opened_version(path, stream):
    first = _native_change(stream) if WINDOWS else None
    opened = _stat_version(os.fstat(stream.fileno()))
    current = _stat_version(path.stat())
    last = _native_change(stream) if WINDOWS else None
    if opened != current or first != last:
        raise OSError("File changed while observing its version")
    return (*opened, first) if WINDOWS else opened


def version(path, *, stream=None):
    """Opaque local version. Existing tuple positions stay stable; no file writes."""
    path = Path(path)
    if stream is not None:
        return _opened_version(path, stream)
    if not WINDOWS:
        return _stat_version(path.stat())
    with path.open("rb") as handle:
        return _opened_version(path, handle)
