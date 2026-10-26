"""Attachment transfer behavior using only isolated synthetic files."""

import hashlib
import os
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest

from paper_daily.sync_blobs import BlobError, BlobManifest, BlobQuotaError, BlobStore


def manifest(data):
    return BlobManifest(hashlib.sha256(data).hexdigest(), len(data))


@pytest.fixture
def store(tmp_path):
    return BlobStore(tmp_path / "blobs", quota_bytes=1024, max_blob_bytes=512, chunk_bytes=16)


def test_interruption_resume_duplicate_chunks_and_finalization(store):
    data = b"a synthetic PDF body"
    item = manifest(data)
    assert store.begin(item) == {"offset": 0, "complete": False}
    assert not store.available(item)
    assert store.append(item, 0, data[:8]) == 8
    restarted = BlobStore(store.root)
    assert restarted.begin(item) == {"offset": 8, "complete": False}
    assert restarted.append(item, 0, data[:8]) == 8
    assert restarted.append(item, 8, data[8:]) == len(data)
    assert not restarted.available(item)
    final = restarted.finalize(item)
    assert final.read_bytes() == data
    assert restarted.available(item)
    assert restarted.finalize(item) == final
    assert restarted.begin(item) == {"offset": len(data), "complete": True}
    assert restarted.append(item, 0, data[:8]) == len(data)
    assert restarted.usage()["objects"] == 1


def test_interrupted_partial_chunk_can_be_retried(store):
    data = b"abcdefghijk"
    item = manifest(data)
    store.begin(item)
    store.append(item, 0, data[:4])
    assert store.append(item, 0, data[:8]) == 8
    assert store.append(item, 8, data[8:]) == len(data)
    assert store.finalize(item).read_bytes() == data


def test_concurrent_begin_append_and_finish_share_one_blob(store):
    data = b"one attachment"
    item = manifest(data)

    def upload(_):
        another = BlobStore(store.root)
        another.begin(item)
        another.append(item, 0, data)
        return another.finalize(item).read_bytes()

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(upload, range(12))) == [data] * 12
    assert store.usage()["objects"] == 1
    assert store.usage()["reserved_bytes"] == len(data)


def test_wrong_hash_never_publishes_and_cancel_allows_retry(store):
    item = manifest(b"correct")
    store.begin(item)
    store.append(item, 0, b"corrupt")
    with pytest.raises(BlobError, match="hash"):
        store.finalize(item)
    assert not store.available(item)
    with pytest.raises(FileNotFoundError):
        store.verified_path(item)
    assert store.begin(item) == {"offset": 7, "complete": False}
    store.discard_partial(item)
    assert store.usage()["reserved_bytes"] == 0
    store.begin(item)
    store.append(item, 0, b"correct")
    assert store.finalize(item).read_bytes() == b"correct"


def test_missing_or_incomplete_bytes_are_not_available(store):
    item = manifest(b"whole")
    assert not store.available(item)
    store.begin(item)
    store.append(item, 0, b"wh")
    with pytest.raises(BlobError, match="size"):
        store.finalize(item)
    assert not store.available(item)
    assert store.begin(item)["offset"] == 2


def test_changed_retry_and_gap_preserve_existing_bytes(store):
    item = manifest(b"abcdefgh")
    store.begin(item)
    store.append(item, 0, b"abcd")
    with pytest.raises(BlobError, match="differs"):
        store.append(item, 0, b"XXXXefgh")
    with pytest.raises(BlobError, match="gap"):
        store.append(item, 6, b"gh")
    assert store.begin(item)["offset"] == 4
    store.append(item, 4, b"efgh")
    assert store.finalize(item).read_bytes() == b"abcdefgh"
    with pytest.raises(BlobError, match="differs"):
        store.append(item, 0, b"XXXX")
    assert store.verified_path(item).read_bytes() == b"abcdefgh"


def test_quota_reserves_declared_bytes_deduplicates_and_releases(tmp_path):
    store = BlobStore(tmp_path / "blobs", quota_bytes=10)
    first, second = manifest(b"123456"), manifest(b"abcdef")
    store.begin(first)
    store.begin(first)
    assert store.usage() == {"reserved_bytes": 6, "objects": 1, "quota_bytes": 10}
    with pytest.raises(BlobQuotaError):
        store.begin(second)
    assert store.usage()["objects"] == 1
    store.discard_partial(first)
    store.discard_partial(first)
    store.begin(second)
    store.append(second, 0, b"abcdef")
    store.finalize(second)
    with pytest.raises(BlobError, match="finalized"):
        store.discard_partial(second)
    assert store.available(second)


def test_per_file_limit_precedes_creating_transfer(store):
    with pytest.raises(BlobQuotaError):
        store.begin(BlobManifest("a" * 64, 513))
    assert store.usage()["objects"] == 0


@pytest.mark.parametrize(
    "digest,size",
    [
        ("../escape", 1),
        ("A" * 64, 1),
        ("a" * 63, 1),
        ("a" * 64, -1),
        ("a" * 64, True),
        (123, 1),
        ("a" * 64, "1"),
    ],
)
def test_invalid_manifest_cannot_name_a_file(digest, size):
    with pytest.raises(BlobError):
        BlobManifest(digest, size)


@pytest.mark.parametrize(
    "offset,data",
    [(-1, b"a"), (True, b"a"), (0, b""), (0, b"a" * 17), (0, "text"), (4, b"toolong")],
)
def test_invalid_chunk_preserves_transfer(store, offset, data):
    item = manifest(b"12345678")
    store.begin(item)
    with pytest.raises(BlobError):
        store.append(item, offset, data)
    assert store.begin(item)["offset"] == 0


def test_digest_cannot_be_redeclared_with_different_size(store):
    item = manifest(b"hello")
    store.begin(item)
    with pytest.raises(BlobError, match="different size"):
        store.begin(BlobManifest(item.sha256, 4))
    assert store.begin(item)["offset"] == 0


def test_zero_byte_file_is_verified(store):
    item = manifest(b"")
    store.begin(item)
    assert not store.available(item)
    assert store.finalize(item).read_bytes() == b""
    assert store.available(item)


def test_atomic_publish_failure_can_be_retried(store, monkeypatch):
    import paper_daily.sync_blobs as blobs

    data = b"safe content"
    item = manifest(data)
    store.begin(item)
    store.append(item, 0, data)
    original = os.replace

    def fail(*_):
        raise OSError("simulated unavailable storage")

    monkeypatch.setattr(blobs.os, "replace", fail)
    with pytest.raises(OSError):
        store.finalize(item)
    assert not store.available(item)
    assert store.begin(item)["offset"] == len(data)
    monkeypatch.setattr(blobs.os, "replace", original)
    assert store.finalize(item).read_bytes() == data


def test_restart_after_rename_before_metadata_commit(store, monkeypatch):
    import paper_daily.sync_blobs as blobs

    data = b"durable bytes"
    item = manifest(data)
    store.begin(item)
    store.append(item, 0, data)
    original = os.replace

    def interrupted(source, destination):
        original(source, destination)
        raise RuntimeError("simulated process interruption")

    monkeypatch.setattr(blobs.os, "replace", interrupted)
    with pytest.raises(RuntimeError):
        store.finalize(item)
    restarted = BlobStore(store.root)
    assert restarted.begin(item) == {"offset": len(data), "complete": True}
    assert restarted.verified_path(item).read_bytes() == data


def test_corruption_or_loss_after_finalization_is_not_reported_available(store):
    data = b"original"
    item = manifest(data)
    store.begin(item)
    store.append(item, 0, data)
    final = store.finalize(item)
    final.write_bytes(b"tampered")
    assert not store.available(item)
    with pytest.raises(BlobError):
        store.begin(item)
    final.unlink()
    assert not store.available(item)
    with pytest.raises(BlobError, match="missing"):
        store.begin(item)


@pytest.mark.parametrize("location", ["root", "partial", "objects", "index.sqlite", "object"])
def test_reparse_points_are_rejected_before_outside_access(store, monkeypatch, location):
    from pathlib import Path
    from types import SimpleNamespace

    item = manifest(b"synthetic")
    target = store.root if location == "root" else store.root / location
    if location == "object":
        target = store.root / "objects" / item.sha256
    original = Path.lstat

    def linked(path):
        if path == target:
            return SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
        return original(path)

    monkeypatch.setattr(Path, "lstat", linked)
    with pytest.raises(BlobError, match="Symlinks"):
        store.begin(item)


def test_independent_roots_do_not_share_bytes(store, tmp_path):
    data = b"one workspace"
    item = manifest(data)
    store.begin(item)
    store.append(item, 0, data)
    store.finalize(item)
    other = BlobStore(tmp_path / "other")
    assert not other.available(item)
    assert other.usage()["objects"] == 0


def test_retry_after_failed_flush_still_flushes_before_acknowledgment(store, monkeypatch):
    import paper_daily.sync_blobs as blobs

    data = b"durable chunk"
    item = manifest(data)
    store.begin(item)
    real_fsync = os.fsync
    attempts = []

    def fail_once(descriptor):
        attempts.append(descriptor)
        if len(attempts) == 1:
            raise OSError("simulated fsync failure")
        return real_fsync(descriptor)

    monkeypatch.setattr(blobs.os, "fsync", fail_once)
    with pytest.raises(OSError):
        store.append(item, 0, data)
    assert store.append(item, 0, data) == len(data)
    assert len(attempts) == 2
    assert store.finalize(item).read_bytes() == data
