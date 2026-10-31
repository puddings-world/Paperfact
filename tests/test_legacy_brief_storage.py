"""Legacy derived files use the workspace's existing owned blob root."""

import pytest
from test_sync_capture import bound as bound_fixture
from test_sync_capture import seed

from paper_daily import store
from paper_daily.document_reader import register_document_paths
from paper_daily.legacy_briefs import record_pack
from paper_daily.sync_artifacts import paths, register_paths
from paper_daily.sync_blobs import BlobStore

bound = bound_fixture
STAMP = "2026-10-30T12:34:56+08:00"


def test_existing_custom_document_blob_root_is_reused(bound, tmp_path):
    seed()
    custom = BlobStore(tmp_path / "owned-document-blobs")
    with bound.journal.transaction() as conn:
        register_document_paths(
            conn,
            workspace_id="workspace",
            blob_root=custom.root,
            projection_root=tmp_path / "reader",
            legacy_root=tmp_path / "legacy",
        )
    with store.connect() as conn:
        path = record_pack(
            conn, "local-paper", STAMP, "manual", b"# Exact pack", legacy_day="2026-10-30"
        )
    with store.connect() as conn:
        selected, _root = paths(conn)
        assert selected.root == custom.root
        assert conn.execute("SELECT brief_path FROM reading_log").fetchone()[0] == str(path)
    assert path.read_bytes() == b"# Exact pack"
    assert not (bound.journal.path.parent / "blobs").exists()


def test_conflicting_file_and_document_roots_never_deliver_a_partial_pack(bound, tmp_path):
    seed()
    first, second = BlobStore(tmp_path / "first"), BlobStore(tmp_path / "second")
    with bound.journal.transaction() as conn:
        register_document_paths(
            conn,
            workspace_id="workspace",
            blob_root=first.root,
            projection_root=tmp_path / "reader",
            legacy_root=tmp_path / "legacy",
        )
        register_paths(conn, "workspace", second, tmp_path / "research-versions")
    count = len(bound.journal.pending())
    with pytest.raises(ValueError, match="storage"), store.connect() as conn:
        record_pack(conn, "local-paper", STAMP, "manual", b"# Exact pack", legacy_day="2026-10-30")
    assert len(bound.journal.pending()) == count
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM reading_log").fetchone()[0] == 0


def test_unavailable_registered_store_is_not_created_by_production(bound, tmp_path):
    seed()
    missing = tmp_path / "unavailable-owned-storage"
    with bound.journal.transaction() as conn:
        register_document_paths(
            conn,
            workspace_id="workspace",
            blob_root=missing,
            projection_root=tmp_path / "reader",
            legacy_root=tmp_path / "legacy",
        )
    count = len(bound.journal.pending())
    with pytest.raises(ValueError, match="storage is unavailable"), store.connect() as conn:
        record_pack(conn, "local-paper", STAMP, "manual", b"# Exact pack", legacy_day="2026-10-30")
    assert not missing.exists()
    assert len(bound.journal.pending()) == count
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM reading_log").fetchone()[0] == 0
