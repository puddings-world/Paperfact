"""Required historical claim sources are verified independently of primary B."""

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

from test_source_enrollment import claimed
from test_sync_files import drain
from test_workspace_enrollment import prepare
from test_workspace_enrollment import source as source_fixture

from paper_daily import store
from paper_daily.document_reader import DocumentReader
from paper_daily.sync_artifacts import paths
from paper_daily.sync_blobs import BlobManifest, BlobStore
from paper_daily.sync_client import SyncClient
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare as prepare_sync
from paper_daily.sync_research import research_writer
from paper_daily.sync_service import ReferenceService
from paper_daily.sync_source_files import resolved
from paper_daily.sync_transfers import DocumentTransfers
from paper_daily.workspace_offline import OfflineService
from paper_daily.workspace_sync_files import AttachmentSteps

source = source_fixture


def prepared(source, tmp_path):
    primary, _cache, original = claimed(source)
    result = prepare(source, tmp_path, pdfs={"paper": primary})
    db = Path(result["database"])
    return result, db, primary.read_bytes(), original


def test_required_A_is_offline_ready_with_B_but_missing_or_corrupt_A_never_ready(source, tmp_path):
    result, db, current, original = prepared(source, tmp_path)
    service = OfflineService(db)
    report = service.status(["paper"])
    assert report["ready"] and report["papers"][0]["ready"]
    items = report["papers"][0]["artifacts"]
    assert (
        len(items) == 1
        and items[0]["source_state"] == "original"
        and items[0]["state"] == "verified"
    )
    assert report["required_assets"] == 3  # primary B, source JSON, original A
    resumed = service.verification(["paper"])
    assert resumed.advance()["ready"]
    assert resumed.advance()["ready"]
    with closing(sqlite3.connect(db)) as conn:
        location = paths(conn)[0]._path(
            BlobManifest(hashlib.sha256(original).hexdigest(), len(original))
        )
    saved = location.read_bytes()
    location.write_bytes(b"x" * len(saved))
    assert not service.status(["paper"])["ready"]
    assert not resumed.advance()["ready"]
    location.write_bytes(saved)
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("DELETE FROM research_file_applied")
    assert not service.status(["paper"])["ready"]
    # Unused private source history never becomes a required current offline asset.
    assert DocumentReader.from_workspace(db).resolve("paper").path.read_bytes() == current


def test_two_device_list_metadata_download_selects_original_A_and_primary_B(source, tmp_path):
    result, db, current, original = prepared(source, tmp_path)
    workspace = result["workspace_id"]
    a = SyncClient(
        Journal(db, workspace_id=workspace, device_id=result["device_id"]), research_writer
    )
    peer_db = tmp_path / "peer.db"
    with closing(sqlite3.connect(peer_db)) as conn:
        conn.executescript(store.SCHEMA)
    prepare_sync(peer_db, workspace_id=workspace, device_id="peer")
    b = SyncClient(Journal(peer_db, workspace_id=workspace, device_id="peer"), research_writer)
    server = ReferenceService(tmp_path / "authority.sqlite", blob_root=tmp_path / "authority-blobs")
    ta, tb = server.enroll(workspace, result["device_id"]), server.enroll(workspace, "peer")
    with a.journal.transaction() as conn:
        blob_store, version_root = paths(conn)
    fa = FileTransfers(
        a, blob_store, server, origin="https://fixture.invalid", token=ta, version_root=version_root
    )
    da = DocumentTransfers(a, blob_store, server, origin="https://fixture.invalid", token=ta)

    def ready(op):
        if op["entity_type"] == "research_file":
            drain(lambda: fa.upload(op), "uploaded")
        elif op["entity_type"] == "paper_document":
            drain(lambda: da.upload(op), "uploaded")
        return True

    a.sync_once(server, ta, limit=1000, prepare_push=ready)
    b.sync_once(server, tb, limit=1000)
    peer_blobs = BlobStore(tmp_path / "peer-blobs")
    dbt = DocumentTransfers(b, peer_blobs, server, origin="https://fixture.invalid", token=tb)
    fbt = FileTransfers(b, peer_blobs, server, origin="https://fixture.invalid", token=tb)
    with b.journal.transaction() as conn:
        portable, local = conn.execute(
            "SELECT sync_id,local_id FROM research_paper_identity"
        ).fetchone()
        assert resolved(conn, portable, hashlib.sha256(original).hexdigest()) is None
    # Real shared selection helper must include original_source, not only deck slots.
    adapter = type(
        "Transport",
        (),
        {
            "base_url": "https://fixture.invalid",
            "__getattr__": lambda self, name: getattr(server, name),
        },
    )()
    steps = AttachmentSteps(b, adapter, tb, lambda: None, lambda _event: None, budget=32)
    download = steps.download_selected([portable])
    assert download["completed_targets"] == 2 and download["remaining_targets"] == 0
    with b.journal.transaction() as conn:
        assert (
            resolved(conn, portable, hashlib.sha256(original).hexdigest()).read_bytes() == original
        )
        row = conn.execute(
            "SELECT document_hash,body_json FROM paper_claim_sets WHERE paper_id=?", (local,)
        ).fetchone()
        assert row[0] == hashlib.sha256(original).hexdigest()
    assert DocumentReader.from_workspace(peer_db).resolve(local).path.read_bytes() == current
    # Restart keeps ownership and original metadata; no AI/account calls are involved.
    assert steps.download_selected([portable])["completed_targets"] == 2
    steps.close()
    fa.close()
    da.close()
    dbt.close()
    fbt.close()
