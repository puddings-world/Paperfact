"""Real canonical unbound primaries: no fabricated source/claim ownership."""

import ctypes
import hashlib
import os
import shutil
import sqlite3
import struct
from contextlib import closing

import pytest
from test_proposal_recovery_current import local as local
from test_proposal_recovery_current import manual as manual
from test_proposal_recovery_current import native
from test_proposal_recovery_current import no_external as no_external
from test_proposal_recovery_current import scientific as scientific

from paper_daily import proposal_recovery_primary as primary
from paper_daily.fetch import _safe_name


@pytest.fixture
def source(manual, scientific):
    pdfs = manual["database"].parent / "pdf"
    pdfs.mkdir()
    path = pdfs / (_safe_name("local-paper") + ".pdf")
    path.write_bytes(scientific[5])
    return {**manual, "pdf": path, "bytes": scientific[5]}


def collect(source, **kwargs):
    with closing(sqlite3.connect(source["snapshot"])) as conn:
        return primary.collect(
            source["database"],
            conn,
            ["local-paper"],
            source["temporary"],
            expected_native=source["native"],
            **kwargs,
        )


def test_actual_pdf_and_source_parent_capture_is_readonly_and_rechecks(source):
    before = source["database"].read_bytes()
    result = collect(source)
    assert result.check() and len(result.rows) == 1
    row = result.rows[0]
    assert row["sha256"] == hashlib.sha256(source["bytes"]).hexdigest()
    assert result.objects[row["sha256"]].read_bytes() == source["bytes"]
    assert result.aliases[source["pdf"]] == (row["sha256"], len(source["bytes"]))
    assert (
        source["database"].read_bytes() == before and source["pdf"].read_bytes() == source["bytes"]
    )
    row["paper_id"] = "caller mutation"
    assert result.rows[0]["paper_id"] == "local-paper"


@pytest.mark.parametrize("change", ["database", "pdf", "paper"])
def test_replacement_or_changed_parent_refuses_after_real_capture(source, change):
    result = collect(source)
    if change == "database":
        replacement = source["database"].with_name("primary-replacement.sqlite")
        shutil.copyfile(source["database"], replacement)
        assert native(replacement) != source["native"]
        os.replace(replacement, source["database"])
    elif change == "pdf":
        replacement = source["pdf"].with_name("replacement.pdf")
        replacement.write_bytes(source["bytes"])
        assert native(replacement) != native(source["pdf"])
        os.replace(replacement, source["pdf"])
    else:
        with closing(sqlite3.connect(source["database"])) as conn, conn:
            conn.execute("UPDATE papers SET title='Different parent' WHERE id='local-paper'")
    with pytest.raises((ValueError, OSError)):
        result.check()


def test_cancel_after_actual_read_never_returns_missing_and_explicit_retry_keeps_bytes(
    source, monkeypatch
):
    original = primary.validate_pdf
    allowed = True

    def validated(data):
        nonlocal allowed
        original(data)
        allowed = False

    monkeypatch.setattr(primary, "validate_pdf", validated)
    before = source["database"].read_bytes()
    with pytest.raises(ValueError, match="cancelled"):
        collect(source, current=lambda: allowed)
    assert source["database"].read_bytes() == before
    assert source["pdf"].read_bytes() == source["bytes"]
    monkeypatch.setattr(primary, "validate_pdf", original)
    retry = collect(source)
    assert retry.check() and retry.objects[retry.rows[0]["sha256"]].read_bytes() == source["bytes"]


def _directory_link(link, target):
    if os.name != "nt":
        link.symlink_to(target, target_is_directory=True)
        return
    # Create our own fixture NTFS mountpoint, no process/privilege/ACL changes.
    from ctypes import wintypes

    link.mkdir()
    substitute = ("\\??\\" + str(target.resolve())).encode("utf-16-le")
    display = str(target.resolve()).encode("utf-16-le")
    names = substitute + b"\0\0" + display + b"\0\0"
    body = struct.pack("<HHHH", 0, len(substitute), len(substitute) + 2, len(display)) + names
    data = struct.pack("<IHH", 0xA0000003, len(body), 0) + body
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.DeviceIoControl.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    handle = kernel.CreateFileW(str(link), 0x40000000, 7, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        returned = wintypes.DWORD()
        buffer = ctypes.create_string_buffer(data)
        if not kernel.DeviceIoControl(
            handle, 0x000900A4, buffer, len(data), None, 0, ctypes.byref(returned), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)


@pytest.mark.parametrize("kind", ["primary", "current"])
def test_actual_stage_directory_link_never_writes_to_foreign_sibling(source, tmp_path, kind):
    from test_proposal_recovery_current import collect as collect_current

    escape = tmp_path / (kind + "-escape")
    escape.mkdir()
    sentinel = escape / "preserve.txt"
    sentinel.write_bytes(b"Prior unrelated fixture bytes")
    folder = "observed-common-primaries" if kind == "primary" else "observed-current-objects"
    link = source["temporary"] / folder
    _directory_link(link, escape)
    try:
        with pytest.raises(ValueError, match="link|reparse"):
            collect(source) if kind == "primary" else collect_current(source)
        assert list(escape.iterdir()) == [sentinel]
        assert sentinel.read_bytes() == b"Prior unrelated fixture bytes"
        assert source["pdf"].read_bytes() == source["bytes"]
    finally:
        if os.name == "nt":
            link.rmdir()
        else:
            link.unlink()


@pytest.mark.parametrize("appears", [False, True])
def test_unavailable_original_stays_unknown_and_late_primary_appearance_invalidates(
    source, appears
):
    source["pdf"].unlink()
    before = source["database"].read_bytes()
    result = collect(source)
    assert result.rows == [] and result.objects == {} and result.aliases == {}
    assert result.check()
    if appears:
        source["pdf"].write_bytes(source["bytes"])
        with pytest.raises(ValueError):
            result.check()
    else:
        assert result.check() and not source["pdf"].exists()
    assert source["database"].read_bytes() == before


@pytest.mark.parametrize("change", ["cancel", "parent-incarnation"])
def test_missing_capture_is_still_bound_to_actual_parent_lifetime_and_caller(source, change):
    from paper_daily.research_lifecycle import parent_lifecycle

    source["pdf"].unlink()
    result = collect(source)
    assert result.rows == []
    if change == "parent-incarnation":
        # Controlled external SQL repair; this does not claim protocol deletion support.
        with closing(sqlite3.connect(source["database"])) as conn, conn:
            old = parent_lifecycle(conn, "paper", "local-paper")
            row = conn.execute("SELECT * FROM papers WHERE id='local-paper'").fetchone()
            conn.execute("DELETE FROM papers WHERE id='local-paper'")
            conn.execute("INSERT INTO papers VALUES(" + ",".join("?" for _ in row) + ")", row)
            assert parent_lifecycle(conn, "paper", "local-paper") != old
    baseline = source["database"].read_bytes()
    with pytest.raises(ValueError):
        result.check(current=lambda: change != "cancel")
    assert source["database"].read_bytes() == baseline and not source["pdf"].exists()
