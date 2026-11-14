"""Fresh-identity and stale-source boundaries of actual detached Lineage adoption."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from test_lineage_enrollment import corpus as corpus
from test_lineage_enrollment import selection
from test_lineage_jobs import work
from test_lineage_lifecycle import active as active
from test_lineage_live_journey import setup_publication
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_sync_recovery import rewrite

from paper_daily import sync_recovery
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.workspace_enrollment import EnrollmentBlocked, EnrollmentService


def mutate_rows(manifest, files, table, change):
    key = "tables/" + table + ".jsonl"
    rows = [json.loads(line) for line in files[key].splitlines()]
    change(rows)
    data = b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for row in rows
    )
    files[key] = data
    import hashlib

    entry = next(item for item in manifest["tables"] if item["name"] == table)
    entry.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())


@pytest.mark.parametrize("stale", ["retired-source", "recreated-source", "recreated-parent"])
def test_archived_source_history_is_not_current_adoption_authority(
    selected, monkeypatch, tmp_path, stale
):
    client, _candidate, _receipt, _scientific, _sources = setup_publication(selected, monkeypatch)
    original = tmp_path / "original.zip"
    sync_recovery.create(client.journal.path, original, blob_store=selected[0][3].store)

    def mutate(manifest, files):
        if stale == "recreated-parent":

            def change(rows):
                rows[0]["incarnation"] = str(uuid4())

            mutate_rows(manifest, files, "research_paper_projection", change)
        else:

            def change(rows):
                if stale == "retired-source":
                    rows[0]["active"] = 0
                else:
                    operation = json.loads(rows[0]["operation"])
                    operation["incarnation"] = str(uuid4())
                    rows[0]["operation"] = json.dumps(
                        operation, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                    )

            mutate_rows(manifest, files, "research_file_desired", change)

    archive = rewrite(original, tmp_path / "stale.zip", mutate)
    # Preserve this valid historical container for inspection, not runtime grants.
    sync_recovery.inspect(archive)
    root = tmp_path / "detached"
    sync_recovery.restore_detached(archive, root)
    source = root / "papers.db"
    before = source.read_bytes()
    service = RecoveryAdoptionService(source)
    inspection = work(service.inspect)
    assert not inspection.report["supported"]
    assert any("Lineage" in reason for reason in inspection.report["blockers"])
    with pytest.raises(EnrollmentBlocked):
        work(
            service.prepare,
            inspection,
            tmp_path / "blocked",
            backup_output=tmp_path / "blocked.zip",
            request_id=str(uuid4()),
        )
    assert not (tmp_path / "blocked").exists() and not (tmp_path / "blocked.zip").exists()
    assert source.read_bytes() == before


def test_recovery_cannot_reuse_current_or_ancestor_enrollment_identity(active, corpus, tmp_path):
    owner, _row = active
    original_request = str(uuid4())
    first = work(
        EnrollmentService(owner.database).prepare,
        tmp_path / "first",
        backup_output=tmp_path / "first.zip",
        request_id=original_request,
        pdfs=selection(corpus),
    )
    sync_recovery.restore_detached(tmp_path / "first.zip", tmp_path / "first-detached")
    first_service = RecoveryAdoptionService(tmp_path / "first-detached" / "papers.db")
    inspection = work(first_service.inspect)
    with pytest.raises(ValueError, match="fresh workspace and device"):
        work(
            first_service.prepare,
            inspection,
            tmp_path / "collision",
            backup_output=tmp_path / "collision.zip",
            request_id=original_request,
        )
    assert not (tmp_path / "collision").exists() and not (tmp_path / "collision.zip").exists()
    second = first_service.prepare(
        inspection,
        tmp_path / "second",
        backup_output=tmp_path / "second.zip",
        request_id=str(uuid4()),
    )
    assert second["workspace_id"] != first["workspace_id"]
    sync_recovery.restore_detached(tmp_path / "second.zip", tmp_path / "second-detached")
    second_service = RecoveryAdoptionService(tmp_path / "second-detached" / "papers.db")
    second_inspection = work(second_service.inspect)
    before = Path(second_service.database).read_bytes()
    with pytest.raises(ValueError, match="fresh workspace and device"):
        work(
            second_service.prepare,
            second_inspection,
            tmp_path / "ancestor-collision",
            backup_output=tmp_path / "ancestor-collision.zip",
            request_id=original_request,
        )
    assert not (tmp_path / "ancestor-collision").exists()
    assert not (tmp_path / "ancestor-collision.zip").exists()
    assert Path(second_service.database).read_bytes() == before
