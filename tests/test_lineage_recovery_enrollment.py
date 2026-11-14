"""Actual editable detached recovery uses fresh authority and preserves old research."""

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from lineage_package_fixture import lineage_archive as lineage_archive
from test_lineage_enrollment import corpus as corpus
from test_lineage_import_originals import loaded as loaded
from test_lineage_jobs import work
from test_lineage_lifecycle import active as active
from test_lineage_live_journey import setup_publication, sync_all
from test_lineage_package_publish import incoming as incoming
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import rows

from paper_daily import lineage_bound_originals, lineage_sets, llm, store, sync_recovery
from paper_daily import research_generation as generation
from paper_daily.manual_highlight_ops import observe_owner
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import research_projection_writer, research_writer


def recover(database, row, tmp_path, *, blobs=None, direct=False):
    original = database.read_bytes()
    archive = tmp_path / "original-backup.zip"
    sync_recovery.create(database, archive, blob_store=blobs)
    root = tmp_path / "detached"
    sync_recovery.restore_detached(archive, root)
    source = root / "papers.db"
    before = source.read_bytes()
    service = RecoveryAdoptionService(source)
    inspection = work(service.inspect)
    assert inspection.report["supported"], inspection.report["blockers"]

    def prepare(*args, **kwargs):
        return (
            service.prepare(*args, **kwargs) if direct else work(service.prepare, *args, **kwargs)
        )

    result = prepare(
        inspection,
        tmp_path / "editable",
        backup_output=tmp_path / "editable-backup.zip",
        request_id=str(uuid4()),
    )
    assert result["editable_copy"] and result["history_preserved"] and not result["uploaded"]
    target = Path(result["database"])
    assert lineage_sets.saved(target, row["paper_id"]) == [row]
    client = SyncClient(
        Journal(target, workspace_id=result["workspace_id"], device_id=result["device_id"]),
        research_writer,
        projection_writer=research_projection_writer,
    )
    scientific = [
        op
        for op in client.journal.pending()
        if op.get("content_address", {}).get("feature") == "lineage"
    ]
    assert len(scientific) == 1 and len(scientific[0]["source_dependencies"]) == 3
    owner = observe_owner(target, row["paper_id"], expected_native=generation._identity(target))
    for selected_source in lineage_sets.decode(row["body_json"])["report"]["sources"]:
        proof = work(lineage_bound_originals.prepare, owner, row, selected_source["id"])
        assert lineage_bound_originals.for_delivery(proof, owner, row, selected_source["id"])
    assert (
        sync_recovery.inspect(tmp_path / "editable-backup.zip")["workspace_id"]
        == result["workspace_id"]
    )
    assert source.read_bytes() == before and database.read_bytes() == original
    with closing(sqlite3.connect(target)) as conn:
        assert conn.execute("SELECT count(*) FROM research_recovery_provenance").fetchone()[0] > 0
    return result, scientific[0]


@pytest.mark.parametrize("direct", [False, True])
def test_generated_detached_recovery_is_editable_with_new_native_original_grants(
    active, tmp_path, direct
):
    owner, row = active
    recover(owner.database, row, tmp_path, direct=direct)


def test_imported_detached_recovery_keeps_receiver_originals_and_separate_history(loaded, tmp_path):
    _incoming, owner, row = loaded
    with closing(sqlite3.connect(owner.database)) as conn, conn:
        for identity, title in conn.execute("SELECT id,title FROM papers").fetchall():
            conn.execute(
                "UPDATE papers SET title_key=? WHERE id=?", (store.title_key(title), identity)
            )
    recover(owner.database, row, tmp_path)


@pytest.mark.parametrize("accepted", [False, True])
def test_native_detached_recovery_allocates_new_workspace_device_and_source_epochs(
    selected, monkeypatch, tmp_path, accepted
):
    client, _candidate, _receipt, old, sources = setup_publication(selected, monkeypatch)
    if accepted:
        sync_all(selected, client, sources)
    row = rows(client, lineage_sets.TABLE)[0]
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No recovery AI"))
    result, fresh = recover(client.journal.path, row, tmp_path, blobs=selected[0][3].store)
    assert result["workspace_id"] != client.journal.workspace_id
    assert result["device_id"] != client.journal.device_id
    assert fresh["operation_id"] != old["operation_id"]
    assert fresh["incarnation"] != old["incarnation"]
    assert not {pin["incarnation"] for pin in fresh["source_dependencies"]} & {
        pin["incarnation"] for pin in old["source_dependencies"]
    }


def test_recovered_native_history_preserves_displaced_versions_without_old_grants(
    selected, monkeypatch, tmp_path
):
    from test_lineage_live_conflicts import edit

    from paper_daily import lineage_versions

    client, _candidate, _receipt, original, _sources = setup_publication(selected, monkeypatch)
    old = rows(client, lineage_sets.TABLE)[0]
    edit(client, original, "2026-11-14T03:00:00+00:00")
    current = rows(client, lineage_sets.TABLE)[0]
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No recovery AI"))
    result, scientific = recover(
        client.journal.path, current, tmp_path, blobs=selected[0][3].store
    )
    target = Path(result["database"])
    owner = observe_owner(target, current["paper_id"], expected_native=generation._identity(target))
    before = target.read_bytes()
    versions = work(lineage_versions.collect, owner)
    assert versions["total"] == 2
    historical = next(item for item in versions["items"] if item["row"] == old)
    active = next(item for item in versions["items"] if item["row"] == current)
    assert historical["origin"] is None
    assert not historical["current"] and historical["occupied"]
    assert active["current"] and active["occupied"]
    assert active["origin"] == dict(kind="native", id=scientific["operation_id"])
    assert target.read_bytes() == before
