"""Actual legacy inbox history repairs in bounded, resumable local transactions."""

import json
from contextlib import closing

import pytest
from test_lineage_import_review import compared as compared
from test_lineage_import_review import corpus as corpus
from test_lineage_import_review import dump
from test_lineage_import_review import native_shared as native_shared
from test_lineage_import_review import shared as shared
from test_lineage_jobs import work
from test_package_import import enroll_capture
from test_sync_files import codec as codec
from test_sync_files import drain
from test_sync_files import pair as pair

from paper_daily import lineage_projection, lineage_sets
from paper_daily.lineage_history_repair import TABLE, HistoryRepair
from paper_daily.sync_client import SyncClient
from paper_daily.sync_research import research_projection_writer
from paper_daily.workspace_service import Cancelled, Ticket, WorkspaceChanged


@pytest.fixture
def legacy(compared, pair):
    client, importer, archive, receipt, review = compared
    decision = review.decide({review.conflicts[0]["id"]: "replace"})
    from test_lineage_enrolled_import import mapping_options

    prepared = work(
        importer.prepare, archive, lineage_decision=decision, **mapping_options(receipt)
    )
    work(importer.apply, prepared)
    service, _origin, peer, files, peer_files, token, peer_token = pair
    for operation in client.journal.pending():
        if operation["entity_type"] == "research_file":
            drain(lambda op=operation: files.upload(op), "uploaded")
    for _ in range(20):
        if not importer.client.sync_once(service, token, prepare_push=files.ready_to_push)[
            "pending"
        ]:
            break
    enroll_capture(peer)
    receiving = SyncClient.attach_existing(
        peer.journal, peer.writer, projection_writer=research_projection_writer
    )
    for _ in range(20):
        if not receiving.sync_once(service, peer_token)["received"]:
            break
    with receiving.journal.transaction() as conn:
        histories = conn.execute(
            "SELECT operation_id FROM " + lineage_projection.HISTORY + " ORDER BY rowid"
        ).fetchall()
        assert len(histories) == 2
        old = histories[0][0]
        # Simulate the previous beta's missing catalog entry; real accepted inbox,
        # graph receipts, latest report and cursor remain unchanged.
        conn.execute("DELETE FROM " + lineage_projection.HISTORY + " WHERE operation_id=?", (old,))
    return receiving, peer_files, receipt, old


def stable_snapshot(client):
    with closing(client.journal._connect()) as conn:
        result = {}
        for name, sql in conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"):
            if name not in (TABLE, lineage_projection.HISTORY):
                quoted = '"' + name.replace('"', '""') + '"'
                result[name] = (
                    sql,
                    sorted((tuple(r) for r in conn.execute("SELECT * FROM " + quoted)), key=repr),
                )
        return result


def test_actual_bounded_repair_resumes_and_restores_history_without_research_or_byte_grants(legacy):
    client, _files, receipt, _old = legacy
    service = HistoryRepair(client)
    exact_before = dump(client)
    assert service.status()["more"] and dump(client) == exact_before
    stable = stable_snapshot(client)
    first = service.step(limit=2)
    assert first["scanned"] == first["through"] == 2 and first["more"]
    resumed = HistoryRepair(client)
    assert resumed.status()["through"] == 2
    result = resumed.drain(max_steps=100, seconds=20, limit=2)
    assert not result["more"] and result["restored"] == 1
    assert stable_snapshot(client) == stable
    with closing(client.journal._connect()) as conn:
        assert conn.execute("SELECT count(*) FROM " + lineage_projection.HISTORY).fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM research_file_applied").fetchone()[0] == 0
    assert resumed.step()["restored"] == 0
    local = receipt["identity_mapping"]["focal"]["local_id"]
    assert (
        "alternative bounded interpretation"
        in json.loads(lineage_sets.saved(client.journal.path, local)[0]["body_json"])["report"][
            "statements"
        ][0]["text"].lower()
    )


def test_cancel_after_first_history_insert_rolls_back_whole_batch_and_watermark(
    legacy, monkeypatch
):
    client = legacy[0]
    service, ticket = HistoryRepair(client), Ticket()
    before = dump(client)
    original = lineage_projection._retain_received_in

    def canceled(*args):
        result = original(*args)
        ticket.cancel()
        return result

    monkeypatch.setattr(lineage_projection, "_retain_received_in", canceled)
    with pytest.raises(Cancelled):
        service.step(ticket, limit=128)
    assert dump(client) == before


def test_canceled_drain_keeps_prior_batches_and_can_continue_with_new_ticket(legacy):
    service = HistoryRepair(legacy[0])
    ticket = Ticket()
    seen = []

    def stopped(result):
        seen.append(result)
        ticket.cancel()

    with pytest.raises(Cancelled):
        service.drain(ticket, stopped, max_steps=100, seconds=20, limit=2)
    assert len(seen) == 1 and service.status()["through"] == 2
    assert not service.drain(max_steps=100, seconds=20, limit=2)["more"]


def test_workspace_switch_before_final_commit_preserves_both_databases(
    legacy, monkeypatch, tmp_path
):
    client = legacy[0]
    selected = [client.journal.path]
    service = HistoryRepair(client, current_path=lambda: selected[0])
    before = dump(client)
    original = lineage_projection._retain_received_in

    def switched(*args):
        value = original(*args)
        selected[0] = tmp_path / "another.sqlite"
        return value

    monkeypatch.setattr(lineage_projection, "_retain_received_in", switched)
    with pytest.raises(WorkspaceChanged):
        service.step(limit=128)
    assert dump(client) == before and not selected[0].exists()


def test_byte_budget_stops_at_actual_prefix_instead_of_skipping_next_event(legacy, monkeypatch):
    from paper_daily import lineage_history_repair

    monkeypatch.setattr(lineage_history_repair, "MAX_BATCH_BYTES", 1)
    service = HistoryRepair(legacy[0])
    assert service.step(limit=128)["through"] == 1
    assert service.step(limit=128)["through"] == 2


@pytest.mark.parametrize("damage", ["gap", "receipt", "history"])
def test_corrupt_retained_provenance_is_not_skipped_or_rewritten(legacy, damage):
    client, _files, _receipt, old = legacy
    with client.journal.transaction() as conn:
        if damage == "gap":
            conn.execute("DELETE FROM paperfact_sync_inbox WHERE sequence=1")
        elif damage == "receipt":
            conn.execute(
                "UPDATE paperfact_sync_graph_receipts SET event='{}' WHERE operation_id=?", (old,)
            )
        else:
            event = json.loads(
                conn.execute(
                    "SELECT event FROM paperfact_sync_graph_receipts WHERE operation_id=?", (old,)
                ).fetchone()[0]
            )
            conn.execute(
                "INSERT INTO " + lineage_projection.HISTORY + " VALUES(?,?,?)",
                (old, event["operation"]["entity_id"], "{}"),
            )
    service = HistoryRepair(client)
    before = dump(client)
    with pytest.raises(ValueError, match="gap|receipt|identity"):
        service.step(limit=128)
    assert dump(client) == before


def test_repaired_scientific_history_backups_exclude_device_scan_progress(legacy, tmp_path):
    from test_sync_recovery import archive_rows

    from paper_daily import sync_recovery

    client, files, _receipt, _old = legacy
    assert not HistoryRepair(client).drain(max_steps=100, seconds=20)["more"]
    with closing(client.journal._connect()) as conn:
        originals = conn.execute("SELECT entity_id FROM research_file_desired").fetchall()
    for row in originals:
        drain(lambda key=row[0]: files.download(key), "bound")
    backup = tmp_path / "indexed.zip"
    sync_recovery.create(client.journal.path, backup, blob_store=files.store)
    manifest = sync_recovery.inspect(backup)
    assert TABLE not in repr(manifest)
    assert len(archive_rows(backup, lineage_projection.HISTORY)) == 2
    restored = tmp_path / "indexed-detached"
    sync_recovery.restore_detached(backup, restored)
    import sqlite3

    with closing(sqlite3.connect(restored / "papers.db")) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)).fetchone()


def test_cold_native_workspace_needs_no_history_or_progress_schema(tmp_path):
    from test_sync_files import side

    cold = side(tmp_path, "cold-index")
    client = SyncClient.attach_existing(
        cold.journal, cold.writer, projection_writer=research_projection_writer
    )
    before = dump(client)
    assert not HistoryRepair(client).step()["more"]
    assert dump(client) == before


def test_inspection_and_status_use_no_write_capable_journal_connection(legacy, monkeypatch):
    client = legacy[0]
    before = dump(client)
    with monkeypatch.context() as patch:
        patch.setattr(client.journal, "_connect", lambda: pytest.fail("Status must be read-only"))
        service = HistoryRepair(client)
        assert service.status()["more"]
    assert dump(client) == before
