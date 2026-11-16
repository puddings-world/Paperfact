"""Explicit authenticated retry can restore absent finalized bytes without new research."""

from test_sync_transfers import attach, bound, send
from test_sync_transfers import setup as setup


def test_explicit_download_retry_restores_missing_original_and_keeps_version(setup, tmp_path):
    _, receiver, _, _, _, stores, transfers, _, identity = setup
    operation, manifest, data = attach(setup, tmp_path)
    send(setup, operation)
    transfer = transfers[1]
    assert transfer.download(identity)["state"] == "bound"
    previous = bound(receiver, identity)
    pending = receiver.journal.pending(1000)
    stores[1]._path(manifest).unlink()
    assert transfer.download(identity)["state"] == "failed"
    assert not stores[1]._path(manifest).exists()
    assert transfer.download(identity, retry=True)["state"] == "bound"
    assert stores[1].verified_path(manifest).read_bytes() == data
    assert bound(receiver, identity) == previous
    assert receiver.journal.pending(1000) == pending


def test_explicit_retry_preserves_corrupt_finalized_bytes_for_review(setup, tmp_path):
    _, receiver, _, _, _, stores, transfers, _, identity = setup
    operation, manifest, _ = attach(setup, tmp_path)
    send(setup, operation)
    transfer = transfers[1]
    assert transfer.download(identity)["state"] == "bound"
    previous = bound(receiver, identity)
    path = stores[1]._path(manifest)
    path.write_bytes(b"corrupt final object")
    assert transfer.download(identity, retry=True)["state"] == "failed"
    assert path.read_bytes() == b"corrupt final object"
    assert bound(receiver, identity) == previous
