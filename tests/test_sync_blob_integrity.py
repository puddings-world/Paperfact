"""Bounded verified blob reads: assert bytes inspected, never wall-clock timing."""

import hashlib
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from test_sync_http import running

from paper_daily.sync_blob_service import BLOB_CHUNK_BYTES, BlobUnavailableError
from paper_daily.sync_blobs import BlobError
from paper_daily.sync_http import HttpTransport, make_server
from paper_daily.sync_service import ReferenceService

C = BLOB_CHUNK_BYTES


@pytest.fixture
def ready(tmp_path):
    service = ReferenceService(tmp_path / "authority.sqlite", blob_root=tmp_path / "bytes")
    token = service.enroll("workspace", "device")
    return service, token


def uploaded(service, token, data):
    declared = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    session = service.blob_begin(token, declared)
    for offset in range(0, len(data), C):
        service.blob_append(token, session["upload_id"], offset, data[offset : offset + C])
    service.blob_commit(token, session["upload_id"])
    with service._transaction() as conn:
        path = service._blob_store(conn, "workspace")._path(service._manifest(declared))
    return declared, session["upload_id"], path


def read(service, token, declared, offset=0, limit=C):
    return service.blob_read(token, declared["sha256"], declared["size"], offset, limit)


def count_reads(monkeypatch, path):
    original, counts = Path.open, []

    class Counted:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, size=-1):
            assert 0 <= size <= C, "read work must be explicitly bounded"
            data = self.stream.read(size)
            counts.append(len(data))
            return data

    def opened(candidate, mode="r", *args, **kwargs):
        stream = original(candidate, mode, *args, **kwargs)
        return Counted(stream) if candidate == path and mode == "rb" else stream

    monkeypatch.setattr(Path, "open", opened)
    return counts


@pytest.mark.parametrize(
    "offset,limit,inspected",
    [
        (0, 7, C),
        (C, C, C),
        (C - 1, C, 2 * C),
        (3 * C, 100, 17),
        (3 * C + 16, C, 17),
        (3 * C + 17, C, 0),
    ],
)
def test_requested_range_verifies_at_most_two_blocks(ready, monkeypatch, offset, limit, inspected):
    service, token = ready
    data = b"a" * C + b"b" * C + b"c" * C + b"final-short-block"
    assert len(data) == 3 * C + 17
    declared, _, path = uploaded(service, token, data)
    counts = count_reads(monkeypatch, path)
    assert read(service, token, declared, offset, limit) == data[offset : offset + limit]
    assert sum(counts) == inspected
    assert len(counts) <= 2


def test_empty_object_has_valid_zero_block_index_and_no_read_bytes(ready, monkeypatch):
    service, token = ready
    declared, _, path = uploaded(service, token, b"")
    counts = count_reads(monkeypatch, path)
    assert read(service, token, declared) == b""
    assert counts == []
    with closing(sqlite3.connect(service.path)) as conn:
        assert conn.execute("SELECT block_count FROM sync_blob_integrity").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM sync_blob_blocks").fetchone()[0] == 0


def test_requested_corruption_with_original_size_and_mtime_fails(ready):
    service, token = ready
    declared, _, path = uploaded(service, token, b"a" * C + b"b" * C)
    before = path.stat()
    with path.open("r+b") as stream:
        stream.seek(C + 10)
        stream.write(b"X")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    with pytest.raises(BlobUnavailableError):
        read(service, token, declared, C, 32)


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "extra",
        "reordered",
        "hash",
        "version",
        "size",
        "block-size",
        "count",
        "identity",
        "header-only",
        "blocks-only",
    ],
)
def test_malformed_complete_index_never_falls_back_to_unchecked_read(ready, monkeypatch, damage):
    service, token = ready
    declared, _, path = uploaded(service, token, b"a" * C + b"b" * C)
    with closing(sqlite3.connect(service.path)) as conn:
        if damage == "missing":
            conn.execute("DELETE FROM sync_blob_blocks WHERE block_index=0")
        elif damage == "extra":
            conn.execute(
                "INSERT INTO sync_blob_blocks VALUES('workspace',?,2,?)",
                (declared["sha256"], "a" * 64),
            )
        elif damage == "reordered":
            hashes = conn.execute(
                "SELECT block_hash FROM sync_blob_blocks ORDER BY block_index"
            ).fetchall()
            conn.execute("UPDATE sync_blob_blocks SET block_hash=? WHERE block_index=0", hashes[1])
            conn.execute("UPDATE sync_blob_blocks SET block_hash=? WHERE block_index=1", hashes[0])
        elif damage == "hash":
            conn.execute("UPDATE sync_blob_blocks SET block_hash='malformed' WHERE block_index=0")
        elif damage == "header-only":
            conn.execute("DELETE FROM sync_blob_blocks")
        elif damage == "blocks-only":
            conn.execute("DELETE FROM sync_blob_integrity")
        else:
            field, value = {
                "version": ("version", 99),
                "size": ("size", 1),
                "block-size": ("block_size", 17),
                "count": ("block_count", 1),
                "identity": ("identity", '"not-an-identity"'),
            }[damage]
            conn.execute(f"UPDATE sync_blob_integrity SET {field}=?", (value,))
        conn.commit()
    counts = count_reads(monkeypatch, path)
    with pytest.raises(BlobUnavailableError):
        read(service, token, declared)
    assert sum(counts) <= C  # No full-file backfill of a partial/corrupted index.


def test_legacy_committed_object_backfills_once_after_full_verification(ready, monkeypatch):
    service, token = ready
    data = b"a" * C + b"b" * C + b"c" * C
    declared, _, path = uploaded(service, token, data)
    with closing(sqlite3.connect(service.path)) as conn:
        conn.execute("DELETE FROM sync_blob_blocks")
        conn.execute("DELETE FROM sync_blob_integrity")
        conn.commit()
    counts = count_reads(monkeypatch, path)
    assert read(service, token, declared, 0, 5) == b"a" * 5
    assert sum(counts) == len(data) + C
    counts.clear()
    assert read(service, token, declared, C, 5) == b"b" * 5
    assert sum(counts) == C


def test_corrupt_legacy_object_cannot_manufacture_integrity_index(ready):
    service, token = ready
    declared, _, path = uploaded(service, token, b"original")
    with closing(sqlite3.connect(service.path)) as conn:
        conn.execute("DELETE FROM sync_blob_blocks")
        conn.execute("DELETE FROM sync_blob_integrity")
        conn.commit()
    path.write_bytes(b"tampered")
    with pytest.raises(BlobUnavailableError):
        read(service, token, declared)
    with closing(sqlite3.connect(service.path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sync_blob_integrity").fetchone()[0] == 0


@pytest.mark.parametrize("damage", ["missing", "truncate", "extend", "replace"])
def test_changed_file_identity_or_size_is_not_accepted(ready, damage):
    service, token = ready
    declared, _, path = uploaded(service, token, b"abcdefgh")
    if damage == "missing":
        path.unlink()
    elif damage == "truncate":
        path.write_bytes(b"abc")
    elif damage == "extend":
        with path.open("ab") as stream:
            stream.write(b"extra")
    else:
        replacement = path.with_name("replacement")
        replacement.write_bytes(b"abcdefgh")
        os.replace(replacement, path)
    with pytest.raises(BlobUnavailableError):
        read(service, token, declared)


def test_integrity_and_ownership_publish_atomically_and_retry_after_failure(ready, monkeypatch):
    service, token = ready
    data = b"a" * C + b"b"
    declared = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    session = service.blob_begin(token, declared)
    for offset in range(0, len(data), C):
        service.blob_append(token, session["upload_id"], offset, data[offset : offset + C])
    original = service._publish_integrity

    def interrupted(*args):
        original(*args)
        raise RuntimeError("simulated block publication interruption")

    monkeypatch.setattr(service, "_publish_integrity", interrupted)
    with pytest.raises(RuntimeError, match="interruption"):
        service.blob_commit(token, session["upload_id"])
    with closing(sqlite3.connect(service.path)) as conn:
        assert conn.execute("SELECT state FROM sync_workspace_blobs").fetchone()[0] == "reserved"
        assert conn.execute("SELECT COUNT(*) FROM sync_blob_integrity").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM sync_blob_blocks").fetchone()[0] == 0
    with pytest.raises(PermissionError):
        read(service, token, declared)
    restarted = ReferenceService(service.path, blob_root=service.blob_root)
    assert restarted.blob_begin(token, declared)["complete"]
    assert read(restarted, token, declared, C) == b"b"


def test_failed_full_hash_has_no_integrity_or_owned_metadata(ready):
    service, token = ready
    declared = {"sha256": hashlib.sha256(b"correct").hexdigest(), "size": 7}
    session = service.blob_begin(token, declared)
    service.blob_append(token, session["upload_id"], 0, b"corrupt")
    with pytest.raises(BlobError):
        service.blob_commit(token, session["upload_id"])
    with closing(sqlite3.connect(service.path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sync_blob_blocks").fetchone()[0] == 0
        assert conn.execute("SELECT state FROM sync_workspace_blobs").fetchone()[0] == "reserved"


def test_revocation_during_verification_prevents_ownership_and_does_not_deadlock(
    ready, monkeypatch
):
    service, token = ready
    declared = {"sha256": hashlib.sha256(b"fixture").hexdigest(), "size": 7}
    session = service.blob_begin(token, declared)
    service.blob_append(token, session["upload_id"], 0, b"fixture")
    original = service._compute_integrity

    def revoke_after_scan(*args):
        verified = original(*args)
        service.revoke(token)  # Must not be blocked by an outer authority write transaction.
        return verified

    monkeypatch.setattr(service, "_compute_integrity", revoke_after_scan)
    with pytest.raises(PermissionError):
        service.blob_commit(token, session["upload_id"])
    with closing(sqlite3.connect(service.path)) as conn:
        assert conn.execute("SELECT state FROM sync_workspace_blobs").fetchone()[0] == "reserved"
        assert conn.execute("SELECT COUNT(*) FROM sync_blob_integrity").fetchone()[0] == 0


def test_known_hash_and_copied_block_records_do_not_grant_other_workspace_access(ready):
    service, token = ready
    declared, _, _ = uploaded(service, token, b"private")
    other = service.enroll("other", "device")
    with closing(sqlite3.connect(service.path)) as conn:
        conn.execute(
            "INSERT INTO sync_blob_integrity SELECT 'other',digest,size,version,block_size,"
            "block_count,identity FROM sync_blob_integrity WHERE workspace='workspace'"
        )
        conn.execute(
            "INSERT INTO sync_blob_blocks SELECT 'other',digest,block_index,block_hash "
            "FROM sync_blob_blocks WHERE workspace='workspace'"
        )
        conn.commit()
    with pytest.raises(PermissionError):
        read(service, other, declared)
    service.revoke(token)
    with pytest.raises(PermissionError):
        read(service, token, declared)


def test_actual_loopback_transport_returns_verified_unaligned_range(ready):
    service, token = ready
    data = b"a" * C + b"b" * C
    declared, _, path = uploaded(service, token, data)
    with running(make_server(service)) as url, HttpTransport(url) as transport:
        assert transport.blob_read(token, **declared, offset=C - 2, limit=8) == b"aabbbbbb"
        with path.open("r+b") as stream:
            stream.seek(C)
            stream.write(b"X")
        with pytest.raises(BlobUnavailableError):
            transport.blob_read(token, **declared, offset=C, limit=8)


def test_opened_file_handle_must_match_verified_owned_path(ready, monkeypatch, tmp_path):
    service, token = ready
    declared, _, path = uploaded(service, token, b"private")
    foreign = tmp_path / "other-file"
    foreign.write_bytes(b"secret!")
    original = Path.open

    def substituted(candidate, mode="r", *args, **kwargs):
        if candidate == path and mode == "rb":
            return original(foreign, mode, *args, **kwargs)
        return original(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", substituted)
    with pytest.raises(BlobUnavailableError):
        read(service, token, declared)


def test_linked_object_is_rejected_before_any_content_read(ready, monkeypatch):
    import stat
    from types import SimpleNamespace

    service, token = ready
    declared, _, path = uploaded(service, token, b"private")
    counts = count_reads(monkeypatch, path)
    original = Path.lstat

    def linked(candidate):
        if candidate == path:
            return SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
        return original(candidate)

    monkeypatch.setattr(Path, "lstat", linked)
    with pytest.raises(BlobUnavailableError):
        read(service, token, declared)
    assert counts == []


def test_revocation_during_legacy_backfill_prevents_read_and_index_publication(ready, monkeypatch):
    service, token = ready
    declared, _, _ = uploaded(service, token, b"private")
    with closing(sqlite3.connect(service.path)) as conn:
        conn.execute("DELETE FROM sync_blob_blocks")
        conn.execute("DELETE FROM sync_blob_integrity")
        conn.commit()
    original = service._compute_integrity

    def revoked(*args):
        verified = original(*args)
        service.revoke(token)
        return verified

    monkeypatch.setattr(service, "_compute_integrity", revoked)
    with pytest.raises(PermissionError):
        read(service, token, declared)
    with closing(sqlite3.connect(service.path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sync_blob_integrity").fetchone()[0] == 0
