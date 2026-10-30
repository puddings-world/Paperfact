"""Source bytes survive failed creators and retry repairs ownership publication."""

import json
import zipfile

import pytest
from test_claim_jobs import claims as _claims
from test_claim_jobs import job
from test_claim_jobs import ready as _ready
from test_claim_jobs import workspace as _workspace

from paper_daily import llm, source_snapshots, sync_recovery
from paper_daily.ai_types import Completion

claims = _claims
ready = _ready
workspace = _workspace


def test_failed_creator_cannot_delete_another_pending_jobs_original(claims, monkeypatch):
    first, second = job(claims), job(claims)
    original = claims[0][2].path.read_bytes()

    def failed(*args, **kwargs):
        # Another process can capture/own identical source bytes while the first
        # completion is pending. Neither needs terminal generated research yet.
        source_snapshots.retain(second.context, second.snapshot)
        return Completion(None, "Unavailable")

    monkeypatch.setattr(llm, "complete_result", failed)
    with pytest.raises(ValueError, match="Unavailable"):
        first.run()
    owned = source_snapshots.list_owned(claims[0][0])
    assert len(owned) == 2
    assert {row["request_id"] for row in owned} == {
        first.context.request_id,
        second.context.request_id,
    }
    assert all(
        source_snapshots.source_path(claims[0][0], row).read_bytes() == original for row in owned
    )
    serialized = json.dumps(owned)
    assert "Original deep explanation" not in serialized and "api_key" not in serialized
    assert str(claims[0][0]) not in serialized
    backup = claims[0][0].parent / "failed-source-backup.zip"
    sync_recovery.create(claims[0][0], backup)
    with zipfile.ZipFile(backup) as archive:
        assert archive.read("objects/" + owned[0]["sha256"]) == original
        manifest = sync_recovery.inspect(backup)
        record = next(row for row in manifest["tables"] if row["name"] == source_snapshots.TABLE)
        assert record["count"] == 2


def test_bytes_without_receipt_are_repaired_by_same_captured_retry(claims, monkeypatch):
    current = job(claims)
    publish = source_snapshots._publish_receipt
    monkeypatch.setattr(
        source_snapshots,
        "_publish_receipt",
        lambda *a: (_ for _ in ()).throw(OSError("receipt publication stopped")),
    )
    with pytest.raises(OSError, match="stopped"):
        source_snapshots.retain(current.context, current.snapshot)
    assert source_snapshots.list_owned(claims[0][0]) == []
    assert list((claims[0][0].parent / "pdf/.claim-evidence").rglob("*.pdf"))
    monkeypatch.setattr(source_snapshots, "_publish_receipt", publish)
    expected = source_snapshots.retain(current.context, current.snapshot)
    assert source_snapshots.retain(current.context, current.snapshot) == expected
    assert source_snapshots.list_owned(claims[0][0]) == [expected]
    assert not list((claims[0][0].parent / "pdf/.claim-evidence").rglob("*.part"))


def test_receipt_lost_acknowledgement_retry_is_identical_and_backup_restores_provenance(
    claims, monkeypatch
):
    current = job(claims)
    publish = source_snapshots._publish_receipt

    def lost(destination, row):
        publish(destination, row)
        raise OSError("acknowledgement lost")

    monkeypatch.setattr(source_snapshots, "_publish_receipt", lost)
    with pytest.raises(OSError, match="lost"):
        source_snapshots.retain(current.context, current.snapshot)
    monkeypatch.setattr(source_snapshots, "_publish_receipt", publish)
    row = source_snapshots.retain(current.context, current.snapshot)
    assert source_snapshots.list_owned(claims[0][0]) == [row]
    backup = claims[0][0].parent / "source-provenance.zip"
    sync_recovery.create(claims[0][0], backup)
    destination = claims[0][0].parent / "source-provenance-restored"
    sync_recovery.restore_detached(backup, destination)
    # Detached original ownership is archived provenance, never an active job.
    assert source_snapshots.list_owned(destination / "papers.db") == []
    import sqlite3

    with sqlite3.connect(destination / "papers.db") as conn:
        records = conn.execute(
            "SELECT data FROM recovery_records WHERE table_name=?",
            (source_snapshots.TABLE,),
        ).fetchall()
    assert len(records) == 1 and json.loads(records[0][0]) == row
    assert (destination / "objects" / row["sha256"]).is_file()
    with pytest.raises(sync_recovery.RecoveryError, match="detached re-export"):
        sync_recovery.create(destination / "papers.db", claims[0][0].parent / "again.zip")


def test_parallel_captures_publish_only_complete_shared_source_bytes(claims):
    from concurrent.futures import ThreadPoolExecutor

    captured = [job(claims) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as workers:
        futures = [
            workers.submit(source_snapshots.retain, item.context, item.snapshot)
            for item in captured
        ]
        rows = [future.result() for future in futures]
    assert len(source_snapshots.list_owned(claims[0][0])) == 4
    original = claims[0][2].path.read_bytes()
    assert all(
        source_snapshots.source_path(claims[0][0], row).read_bytes() == original for row in rows
    )
    assert not list((claims[0][0].parent / "pdf/.claim-evidence").rglob("*.part"))
