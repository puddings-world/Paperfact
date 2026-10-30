"""A restored modification timestamp cannot certify changed offline bytes."""

import os

from test_sync_transfers import setup as transfer_setup_fixture
from test_workspace_offline import prepared as prepared_fixture

from paper_daily.workspace_offline_verification import OfflineVerification

prepared = prepared_fixture
transfer_setup = transfer_setup_fixture


def test_same_size_corruption_with_restored_mtime_invalidates_native_pdf_proof(prepared):
    service, _client, local, _portable, blob_store, manifest, data = prepared
    session = OfflineVerification(service, [local])
    assert session.advance()["ready"]
    path = blob_store.verified_path(manifest)
    before = path.stat()
    path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    result = session.advance()
    assert not result["ready"]
    assert result["papers"][0]["pdf"]["state"] == "unavailable"
