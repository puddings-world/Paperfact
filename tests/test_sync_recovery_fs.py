"""The final publication primitive must never replace a raced-in directory."""

import ctypes
import errno
import os
from types import SimpleNamespace

import pytest

from paper_daily import sync_recovery_fs as publication


class Native:
    def __init__(self, callback):
        self.callback = callback
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.callback(*args)


def native(monkeypatch, platform, callback):
    function = Native(callback)
    name = "renameat2" if platform == "linux" else "renamex_np"
    library = SimpleNamespace(**{name: function})
    monkeypatch.setattr(publication.sys, "platform", platform)
    monkeypatch.setattr(publication.ctypes, "CDLL", lambda path, **kw: library)
    monkeypatch.setattr(publication.os, "rename", lambda *a: pytest.fail("Unsafe rename fallback"))
    return function


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_native_success_uses_exclusive_flag_and_closed_ctypes_signature(
    tmp_path, monkeypatch, platform
):
    function = native(monkeypatch, platform, lambda *args: 0)
    source, destination = tmp_path / "source", tmp_path / "目的地"
    publication.publish_directory(source, destination)
    expected = (
        (-100, os.fsencode(source), -100, os.fsencode(destination), 1)
        if platform == "linux"
        else (os.fsencode(source), os.fsencode(destination), 4)
    )
    assert function.calls == [expected]
    assert function.restype is ctypes.c_int
    assert function.argtypes[-1] is ctypes.c_uint
    assert len(function.argtypes) == len(expected)


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_raced_in_existing_empty_destination_is_not_replaced(tmp_path, monkeypatch, platform):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    (source / "research").write_text("staged research")

    def race(*args):
        destination.mkdir()  # Arrives after all Python prechecks, before native commit.
        ctypes.set_errno(errno.EEXIST)
        return -1

    native(monkeypatch, platform, race)
    with pytest.raises(FileExistsError) as caught:
        publication.publish_directory(source, destination)
    assert caught.value.errno == errno.EEXIST
    assert caught.value.filename2 == str(destination)
    assert destination.is_dir() and list(destination.iterdir()) == []
    assert (source / "research").read_text() == "staged research"


@pytest.mark.parametrize("platform", ["linux", "darwin"])
@pytest.mark.parametrize(
    "error", [errno.ENOSYS, errno.ENOTSUP, errno.EINVAL, errno.EXDEV, errno.EIO, errno.EACCES]
)
def test_native_failure_is_exact_and_never_falls_back(tmp_path, monkeypatch, platform, error):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()

    def fail(*args):
        ctypes.set_errno(error)
        return -1

    native(monkeypatch, platform, fail)
    with pytest.raises(OSError) as caught:
        publication.publish_directory(source, destination)
    assert caught.value.errno == error
    assert source.is_dir() and not destination.exists()


@pytest.mark.parametrize("platform", ["linux", "darwin", "unsupported-os"])
def test_missing_platform_or_symbol_fails_closed(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(publication.sys, "platform", platform)
    monkeypatch.setattr(publication.ctypes, "CDLL", lambda *a, **kw: SimpleNamespace())
    monkeypatch.setattr(publication.os, "rename", lambda *a: pytest.fail("Unsafe fallback"))
    with pytest.raises(OSError) as caught:
        publication.publish_directory(tmp_path / "source", tmp_path / "destination")
    assert caught.value.errno == errno.ENOTSUP


@pytest.mark.parametrize("existing", [False, True])
def test_real_host_publication_preserves_existing_directory(tmp_path, existing):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    (source / "research").write_text("staged research")
    if existing:
        destination.mkdir()
        with pytest.raises(FileExistsError):
            publication.publish_directory(source, destination)
        assert (source / "research").read_text() == "staged research"
        assert list(destination.iterdir()) == []
    else:
        publication.publish_directory(source, destination)
        assert not source.exists()
        assert (destination / "research").read_text() == "staged research"
