"""Real two-device event/Markdown transfer without sending filesystem paths."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from test_sync_capture import bound as bound_fixture
from test_sync_capture import make, seed

from paper_daily import store
from paper_daily.legacy_briefs import record_pack
from paper_daily.sync_artifacts import paths
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_capture import CaptureConnection, install
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_service import ReferenceService

bound = bound_fixture
STAMP = "2026-10-30T12:34:56.123456+08:00"
DATA = b"# Exact Markdown\r\n\r\n<script>not executed</script>\r\n"


def step(coordinator, operation, direction):
    for _ in range(20):
        result = getattr(coordinator, direction)(
            operation if direction == "upload" else operation["entity_id"]
        )
        if result["state"] in {"uploaded", "bound", "stale", "absent"}:
            return result
    raise AssertionError("Fixture transfer never reached a terminal state")


def test_peer_pending_metadata_edit_then_exact_file_download_and_clear(
    bound, tmp_path, monkeypatch
):
    seed()
    with store.connect() as conn:
        original = record_pack(conn, "local-paper", STAMP, "manual", DATA, legacy_day="2026-10-30")
    file = next(
        op
        for op in bound.journal.pending()
        if op.get("payload", {}).get("feature") == "legacy_brief"
    )
    assert str(original) not in json.dumps(bound.journal.pending())
    service = ReferenceService(tmp_path / "service.db", blob_root=tmp_path / "authority-blobs")
    ta, tb = service.enroll("workspace", "a"), service.enroll("workspace", "b")
    with store.connect() as conn:
        blobs, root = paths(conn)
    sender = FileTransfers(
        bound, blobs, service, origin="https://fixture.invalid", token=ta, version_root=root
    )
    peer = make(tmp_path / "b.db", "b")
    receiver = FileTransfers(
        peer,
        BlobStore(tmp_path / "peer-blobs"),
        service,
        origin="https://fixture.invalid",
        token=tb,
    )
    try:
        assert step(sender, file, "upload")["state"] == "uploaded"
        bound.sync_once(service, ta, prepare_push=sender.ready_to_push)
        peer.sync_once(service, tb)
        with closing(sqlite3.connect(peer.journal.path, factory=CaptureConnection)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            install(conn, workspace_id="workspace", device_id="b")
        monkeypatch.setattr(store, "DB_PATH", peer.journal.path)
        with store.connect() as conn:
            row = conn.execute("SELECT brief_path FROM reading_log").fetchone()
            assert row[0] is None
            conn.execute("UPDATE reading_log SET note='Peer note before download'")
        peer.sync_once(service, tb)
        assert step(receiver, file, "download")["state"] == "bound"
        with store.connect() as conn:
            row = conn.execute(
                "SELECT delivered_at,brief_path,role,note FROM reading_log"
            ).fetchone()
            assert tuple(row)[::3] == (STAMP, "Peer note before download")
            assert row[2] == "manual" and Path(row[1]).read_bytes() == DATA
            conn.execute("UPDATE reading_log SET brief_path=NULL")
        peer.sync_once(service, tb)
        assert step(receiver, file, "download")["state"] == "absent"
        with store.connect() as conn:
            assert conn.execute("SELECT brief_path,note FROM reading_log").fetchone()[0] is None
        assert original.read_bytes() == DATA
    finally:
        sender.close()
        receiver.close()
