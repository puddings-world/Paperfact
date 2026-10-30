"""Native change observations invalidate cached proofs, without content rewrites."""

import os

import pytest

from paper_daily import file_change


def test_read_only_observation_is_stable_and_detects_restored_mtime_write(tmp_path):
    path = tmp_path / "research.bin"
    path.write_bytes(b"abcd")
    first = file_change.version(path)
    before = path.stat()
    assert file_change.version(path) == first
    assert path.read_bytes() == b"abcd"
    path.write_bytes(b"wxyz")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    changed = file_change.version(path)
    assert changed[:4] == first[:4]
    assert changed != first


def test_open_handle_cannot_describe_replaced_path(tmp_path):
    path, saved = tmp_path / "source.bin", tmp_path / "saved.bin"
    path.write_bytes(b"abcd")
    with path.open("rb") as stream:
        # Windows cannot rename a CRT-opened file on all filesystems. Point the
        # lookup at another existing file instead; the mismatched handle is real.
        saved.write_bytes(b"abcd")
        with pytest.raises(OSError, match="changed"):
            file_change.version(saved, stream=stream)


def test_native_lookup_failure_never_falls_back_to_creation_time(tmp_path, monkeypatch):
    path = tmp_path / "source.bin"
    path.write_bytes(b"abcd")
    monkeypatch.setattr(file_change, "WINDOWS", True)
    def unavailable(_stream):
        raise OSError("native observation unavailable")
    monkeypatch.setattr(file_change, "_native_change", unavailable)
    with pytest.raises(OSError, match="unavailable"):
        file_change.version(path)


def test_mutating_native_token_during_observation_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "source.bin"
    path.write_bytes(b"abcd")
    monkeypatch.setattr(file_change, "WINDOWS", True)
    tokens = iter([100, 101])
    monkeypatch.setattr(file_change, "_native_change", lambda _stream: next(tokens))
    with pytest.raises(OSError, match="changed"):
        file_change.version(path)


@pytest.mark.parametrize("major,minimum,offset", [(2, 60, 24), (3, 76, 40)])
def test_known_native_revision_formats_preserve_the_exact_sequence(major, minimum, offset):
    import struct
    data = bytearray(minimum)
    struct.pack_into("<IHH", data, 0, minimum, major, 0)
    struct.pack_into("<q", data, offset, 987654321)
    assert file_change._decode_usn(bytes(data)) == 987654321


@pytest.mark.parametrize("case", ["empty", "oversized", "unknown", "truncated", "minor", "zero"])
def test_unknown_native_revision_records_fail_closed(case):
    import struct
    data = bytearray(60)
    struct.pack_into("<IHH", data, 0, 60, 2, 0)
    struct.pack_into("<q", data, 24, 42)
    if case == "empty":
        data = b""
    elif case == "oversized":
        data = bytes(4097)
    elif case == "unknown":
        struct.pack_into("<H", data, 4, 99)
    elif case == "truncated":
        struct.pack_into("<I", data, 0, 1000)
    elif case == "minor":
        struct.pack_into("<H", data, 6, 99)
    else:
        struct.pack_into("<q", data, 24, 0)
    with pytest.raises(OSError):
        file_change._decode_usn(bytes(data))


def test_rapid_same_size_writes_with_restored_mtime_have_distinct_versions(tmp_path):
    path = tmp_path / "rapid.bin"
    path.write_bytes(b"abcd")
    original = path.stat()
    previous = file_change.version(path)
    for index in range(32):
        path.write_bytes(index.to_bytes(4, "big"))
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        current = file_change.version(path)
        assert current != previous
        previous = current
