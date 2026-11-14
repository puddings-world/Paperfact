"""Real native lifecycle facade keeps journal, sources and peer projection aligned."""

from uuid import uuid4

import pytest
from test_lineage_jobs import work
from test_lineage_live_journey import setup_publication, sync_all
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import rows

from paper_daily import lineage_lifecycle as lifecycle
from paper_daily import lineage_projection, lineage_sets, llm
from paper_daily import research_generation as generation
from paper_daily.manual_highlight_ops import observe_owner


def test_native_lifecycle_roundtrip_replicates_without_ai_or_new_source_grants(
    selected, monkeypatch
):
    client, _candidate, _receipt, original, sources = setup_publication(selected, monkeypatch)
    peer = sync_all(selected, client, sources)
    service, _a, _b, files, _peer_files, token, peer_token = selected[0]
    row = rows(client, lineage_sets.TABLE)[0]
    owner = observe_owner(
        client.journal.path,
        row["paper_id"],
        expected_native=generation._identity(client.journal.path),
    )
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No lifecycle AI"))
    request = str(uuid4())

    def change(action, identity, origin=None):
        return work(lifecycle.change, owner, row, request_id=identity, action=action, origin=origin)

    retired = change("retire", request)
    assert retired["state"] == "queued_sync" and retired["operation_id"] == request
    assert retired["applied"] and rows(client, lineage_sets.TABLE) == []
    assert not change("retire", request)["applied"]
    intent = next(op for op in client.journal.pending() if op["operation_id"] == request)
    assert intent["action"] == "delete" and intent["entity_id"] == original["entity_id"]
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    peer.sync_once(service, peer_token)
    assert rows(peer, lineage_sets.TABLE) == []
    assert not change("retire", request)["applied"]

    item = work(lifecycle.history, owner)["items"][0]
    assert item["origin"] == dict(kind="native", id=original["operation_id"])
    restored_id = str(uuid4())
    restored = change("restore", restored_id, item["origin"])
    assert restored["applied"] and restored["state"] == "queued_sync"
    new = next(op for op in client.journal.pending() if op["operation_id"] == restored_id)
    assert new["incarnation"] != original["incarnation"]
    assert new["source_dependencies"] == original["source_dependencies"]
    assert not change("restore", restored_id, item["origin"])["applied"]
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    peer.sync_once(service, peer_token)
    assert rows(client, lineage_sets.TABLE) == rows(peer, lineage_sets.TABLE) == [row]
    assert not change("restore", restored_id, item["origin"])["applied"]
    assert client.status()["conflicts"] == peer.status()["conflicts"] == 0
    assert len(rows(client, lineage_projection.HISTORY)) == 3
    assert all(op["entity_type"] != "research_file" for op in client.journal.pending())

    from test_sync_recovery import archive_rows

    from paper_daily import sync_recovery

    archive = client.journal.path.parent / "native-lifecycle.zip"
    manifest = sync_recovery.create(client.journal.path, archive, blob_store=files.store)
    assert sync_recovery.inspect(archive) == manifest
    assert len(archive_rows(archive, lifecycle.TABLE)) == 2


@pytest.mark.parametrize("restore_source", [False, True])
def test_native_restore_refuses_retired_or_recreated_original_source(
    selected, monkeypatch, restore_source
):
    client, _candidate, _receipt, original, sources = setup_publication(selected, monkeypatch)
    sync_all(selected, client, sources)
    row = rows(client, lineage_sets.TABLE)[0]
    owner = observe_owner(
        client.journal.path,
        row["paper_id"],
        expected_native=generation._identity(client.journal.path),
    )
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No lifecycle AI"))
    work(lifecycle.change, owner, row, request_id=str(uuid4()), action="retire")
    selected_source = sources[0]
    client.save(
        client.new_graph_operation(
            "research_file", selected_source["entity_id"], {}, action="delete"
        )
    )
    if restore_source:
        replacement = client.new_graph_operation(
            "research_file", selected_source["entity_id"], selected_source["payload"], restore=True
        )
        client.save(replacement)
        assert replacement["incarnation"] != selected_source["incarnation"]
    before = client.journal.pending()
    with pytest.raises(ValueError, match="lifetime changed"):
        work(
            lifecycle.change,
            owner,
            row,
            request_id=str(uuid4()),
            action="restore",
            origin=dict(kind="native", id=original["operation_id"]),
        )
    assert client.journal.pending() == before
    assert rows(client, lineage_sets.TABLE) == []
    assert len(work(lifecycle.history, owner)["items"]) == 1


@pytest.mark.parametrize("failure", ["receipt", "cancel-before", "cancel-after"])
def test_native_failed_action_rolls_back_science_history_outbox_but_preserves_caller_note(
    selected, monkeypatch, failure
):
    import sqlite3
    from contextlib import closing

    client, _candidate, _receipt, _original, _sources = setup_publication(selected, monkeypatch)
    row = rows(client, lineage_sets.TABLE)[0]
    owner = observe_owner(
        client.journal.path,
        row["paper_id"],
        expected_native=generation._identity(client.journal.path),
    )
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No lifecycle AI"))
    with closing(sqlite3.connect(owner.database)) as fixture, fixture:
        fixture.execute(lifecycle.SCHEMA)
        if failure == "receipt":
            fixture.execute(
                "CREATE TRIGGER fail_lifecycle BEFORE INSERT ON research_lineage_actions "
                "BEGIN SELECT RAISE(ABORT,'fixture action receipt failure'); END"
            )
    before = client.journal.pending()
    history = rows(client, lineage_projection.HISTORY)
    identity = str(uuid4())
    calls = [0]

    def cancelled():
        calls[0] += 1
        return failure == "cancel-before" or failure == "cancel-after" and calls[0] == 2

    def apply():
        with closing(generation._connect(owner.database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO notes(paper_id,body,created_at) VALUES(?,?,?)",
                (owner.paper_id, "Keep earlier caller note", "2026-11-13T11:00:00+00:00"),
            )
            with pytest.raises(
                sqlite3.IntegrityError if failure == "receipt" else ValueError,
                match="receipt failure|cancelled",
            ):
                lifecycle.apply_in(
                    conn, owner, row, request_id=identity, action="retire", cancelled=cancelled
                )
            assert conn.in_transaction
            conn.commit()

    work(apply)
    assert rows(client, lineage_sets.TABLE) == [row]
    assert rows(client, lineage_projection.HISTORY) == history
    after = client.journal.pending()
    assert all(operation in after for operation in before)
    added = [operation for operation in after if operation not in before]
    assert len(added) == 1 and added[0]["entity_type"] == "note"
    assert added[0]["payload"]["body"] == "Keep earlier caller note"
    assert all(operation["operation_id"] != identity for operation in after)
    assert work(lifecycle.history, owner)["items"] == []
    with closing(sqlite3.connect(owner.database)) as conn:
        assert conn.execute("SELECT body FROM notes").fetchall() == [("Keep earlier caller note",)]
