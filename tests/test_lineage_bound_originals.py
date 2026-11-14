"""Bound exact-original reads use real staged projections and published fixture PDFs."""

import copy
import shutil
import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest
from test_lineage_observation import work
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import frame_for, project, rows
from test_sync_files import drain

from paper_daily import lineage_bound_originals as originals
from paper_daily import lineage_projection, lineage_sets, llm, research_generation, sync_artifacts
from paper_daily.manual_highlight_ops import observe_owner
from paper_daily.sync_blobs import BlobManifest


def loaded(selected, monkeypatch):
    client = selected[0][1]
    frame, operations = frame_for(selected)
    work(project, client, frame)
    row = rows(client, lineage_sets.TABLE)[0]
    owner = observe_owner(
        client.journal.path,
        row["paper_id"],
        expected_native=research_generation._identity(client.journal.path),
    )
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("Saved-only read"))
    return owner, row, frame, operations


@pytest.mark.parametrize("index", [0, 1, 2])
def test_exact_peer_original_bytes_without_writes_activation_or_model(selected, monkeypatch, index):
    owner, row, frame, _operations = loaded(selected, monkeypatch)
    client = selected[0][1]
    before = client.journal.path.read_bytes()
    pending = client.journal.pending()
    source = selected[1].sources[index]
    snapshot = work(originals.prepare, owner, row, source["id"])
    assert snapshot is not None and originals.metadata_current(snapshot)
    assert originals.for_delivery(snapshot, owner, row, source["id"]) == (
        selected[1]._documents[index].path.read_bytes()
    )
    assert client.journal.path.read_bytes() == before and client.journal.pending() == pending
    with closing(client.journal._connect()) as conn:
        assert not conn.execute("SELECT 1 FROM research_document_desired").fetchall()
    assert frame["source_dependencies"][index]["source_id"] == source["id"]


@pytest.mark.parametrize("changed", ["owner", "row", "source", "closed"])
def test_gui_delivery_rechecks_actual_loaded_owner_and_result(selected, monkeypatch, changed):
    owner, row, frame, _operations = loaded(selected, monkeypatch)
    source = frame["source_dependencies"][1]["source_id"]
    snapshot = work(originals.prepare, owner, row, source)
    if changed == "owner":
        owner = observe_owner(
            owner.database,
            owner.paper_id,
            expected_native=research_generation._identity(owner.database),
        )
    elif changed == "row":
        row = {**row, "written_at": "2026-11-01T00:00:00+00:00"}
    elif changed == "source":
        source = frame["source_dependencies"][0]["source_id"]
    else:
        owner = None
    with pytest.raises(ValueError, match="view changed"):
        originals.for_delivery(snapshot, owner, row, source)


@pytest.mark.parametrize("changed", ["row", "marker", "paper", "retired", "restored", "storage"])
def test_pending_read_cannot_deliver_after_source_projection_or_owner_change(
    selected, monkeypatch, changed
):
    owner, row, frame, operations = loaded(selected, monkeypatch)
    client = selected[0][1]
    source = frame["source_dependencies"][1]["source_id"]
    snapshot = work(originals.prepare, owner, row, source)
    if changed in {"retired", "restored"}:
        old = operations[source]
        with client.journal.transaction() as conn:
            retired = client.new_graph_operation_in(
                conn, "research_file", old["entity_id"], {}, action="delete"
            )
            client.journal.apply_in(conn, retired, client.writer)
            if changed == "restored":
                restored = client.new_graph_operation_in(
                    conn, "research_file", old["entity_id"], old["payload"], restore=True
                )
                client.journal.apply_in(conn, restored, client.writer)
                assert restored["incarnation"] != old["incarnation"]
    else:
        with closing(client.journal._connect()) as conn, conn:
            if changed == "row":
                conn.execute("UPDATE paper_lineage_sets SET written_at='changed'")
            elif changed == "marker":
                conn.execute("DELETE FROM " + lineage_projection.TABLE)
            elif changed == "paper":
                conn.execute(
                    "DELETE FROM research_paper_projection WHERE sync_id=?",
                    (frame["parents"][2]["id"],),
                )
            else:
                conn.execute("DELETE FROM research_file_paths")
    assert not originals.metadata_current(snapshot)
    with pytest.raises(ValueError, match="view changed"):
        originals.for_delivery(snapshot, owner, row, source)
    if changed in {"retired", "restored"}:
        with pytest.raises(ValueError, match="lifetime changed"):
            work(originals.prepare, owner, row, source)


@pytest.mark.parametrize("field,value", [("source_id", "0" * 64), ("_data", b"foreign")])
def test_forged_snapshot_cannot_deliver(selected, monkeypatch, field, value):
    owner, row, frame, _operations = loaded(selected, monkeypatch)
    source = frame["source_dependencies"][0]["source_id"]
    snapshot = work(originals.prepare, owner, row, source)
    forged = replace(snapshot, **{field: value})
    assert not originals.metadata_current(forged)
    with pytest.raises(ValueError, match="native verified snapshot"):
        originals.for_delivery(forged, owner, row, source)


def test_missing_bytes_stay_unavailable_and_same_hash_damaged_bytes_cannot_deliver(
    selected, monkeypatch
):
    owner, row, frame, operations = loaded(selected, monkeypatch)
    source = frame["source_dependencies"][0]["source_id"]
    operation = operations[source]
    store = selected[0][3].store
    asset = operation["payload"]["assets"][0]
    path = store.verified_path(BlobManifest(asset["sha256"], asset["size"]))
    saved = path.read_bytes()
    path.unlink()
    assert work(originals.prepare, owner, row, source) is None
    path.write_bytes(saved)
    snapshot = work(originals.prepare, owner, row, source)
    path.write_bytes(b"x" * len(saved))
    assert not originals.metadata_current(snapshot)
    with pytest.raises(ValueError):
        work(originals.prepare, owner, row, source)


def test_cancel_before_or_during_verification_delivers_nothing(selected, monkeypatch):
    owner, row, frame, _operations = loaded(selected, monkeypatch)
    source = frame["source_dependencies"][0]["source_id"]
    assert work(originals.prepare, owner, row, source, cancelled=lambda: True) is None
    verify = sync_artifacts.verify_closure
    cancelled = False

    def finish(*args):
        nonlocal cancelled
        result = verify(*args)
        cancelled = True
        return result

    monkeypatch.setattr(sync_artifacts, "verify_closure", finish)
    assert work(originals.prepare, owner, row, source, cancelled=lambda: cancelled) is None


def test_unselected_source_is_refused_without_looking_up_another_original(selected, monkeypatch):
    owner, row, _frame, _operations = loaded(selected, monkeypatch)
    before = copy.deepcopy(row)
    with pytest.raises(ValueError, match="not selected"):
        work(originals.prepare, owner, row, "0" * 64)
    assert row == before


def test_native_database_replacement_invalidates_delayed_delivery(selected, monkeypatch, tmp_path):
    owner, row, frame, _operations = loaded(selected, monkeypatch)
    source = frame["source_dependencies"][0]["source_id"]
    snapshot = work(originals.prepare, owner, row, source)
    replacement = tmp_path / "replacement.sqlite"
    shutil.copy2(owner.database, replacement)
    replacement.replace(owner.database)
    assert not originals.metadata_current(snapshot)
    with pytest.raises(ValueError, match="view changed"):
        originals.for_delivery(snapshot, owner, row, source)


def test_receiving_peer_reads_only_its_own_verified_transfer_and_actual_aliases(selected):
    from paper_daily.research_lifecycle import ensure_lifecycle
    from paper_daily.sync_capture import CaptureConnection, install

    service, client, peer, files, peer_files, token, peer_token = selected[0]
    frame, operations = frame_for(selected)
    for operation in operations.values():
        drain(lambda operation=operation: files.upload(operation), "uploaded")
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    peer.sync_once(service, peer_token)
    with closing(sqlite3.connect(peer.journal.path, factory=CaptureConnection)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id=peer.journal.workspace_id, device_id=peer.journal.device_id)
        ensure_lifecycle(conn)
    work(project, peer, frame)
    row = rows(peer, lineage_sets.TABLE)[0]
    owner = observe_owner(
        peer.journal.path,
        row["paper_id"],
        expected_native=research_generation._identity(peer.journal.path),
    )
    source = frame["source_dependencies"][1]["source_id"]
    # Metadata arrival is not permission to borrow the sender's cached PDF.
    assert work(originals.prepare, owner, row, source) is None
    operation = operations[source]
    drain(lambda: peer_files.download(operation["entity_id"]), "bound")
    pending = peer.journal.pending()
    snapshot = work(originals.prepare, owner, row, source)
    assert originals.for_delivery(snapshot, owner, row, source) == (
        selected[1]._documents[1].path.read_bytes()
    )
    assert peer.journal.pending() == pending
    with closing(peer.journal._connect()) as conn:
        assert not conn.execute("SELECT 1 FROM research_document_desired").fetchall()
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_local_source_owners'"
        ).fetchone()
