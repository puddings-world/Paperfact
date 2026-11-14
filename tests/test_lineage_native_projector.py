"""Native graph writer dispatch keeps full staged Lineage provenance under protection."""

import json
from contextlib import closing

import pytest
from test_lineage_observation import work
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import frame_for, rows
from test_lineage_transfer_readiness import prepared as prepared

from paper_daily import lineage_projection as projection
from paper_daily import lineage_sets
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import canonical_operation
from paper_daily.sync_research import research_projection_writer


def dispatch(client, frame, visible):
    with client.journal.transaction() as conn:
        client._write_projection_in(conn, frame, visible=visible)


def test_explicit_native_projector_keeps_put_and_history_while_hiding_without_a_fake_event(
    selected,
):
    original = selected[0][1]
    frame, _sources = frame_for(selected)
    client = SyncClient.attach_existing(
        original.journal, original.writer, projection_writer=research_projection_writer
    )
    before = client.status(), client.journal.pending()
    work(dispatch, client, frame, True)
    assert len(rows(client, lineage_sets.TABLE)) == 1
    work(dispatch, client, frame, False)
    assert rows(client, lineage_sets.TABLE) == []
    assert projection.validate_record(rows(client, projection.TABLE)[0]) == frame
    assert projection.validate_history(rows(client, projection.HISTORY)[0]) == frame
    assert (client.status(), client.journal.pending()) == before
    assert json.loads(canonical_operation(frame)) == frame


def test_custom_client_without_native_projector_refuses_typed_dispatch_without_writes(selected):
    client = selected[0][1]
    frame, _sources = frame_for(selected)
    with closing(client.journal._connect()) as conn:
        before = list(conn.iterdump())
    with pytest.raises(ValueError, match="explicit projection writer"):
        work(dispatch, client, frame, False)
    with closing(client.journal._connect()) as conn:
        assert list(conn.iterdump()) == before


def test_native_projector_rejects_nonboolean_visibility_and_foreign_workspace(selected):
    original = selected[0][1]
    frame, _sources = frame_for(selected)
    client = SyncClient.attach_existing(
        original.journal, original.writer, projection_writer=research_projection_writer
    )
    for value in (None, 0, "hidden"):
        with pytest.raises(ValueError, match="boolean visibility"):
            work(dispatch, client, frame, value)
    with pytest.raises(ValueError, match="another workspace"):
        work(dispatch, client, dict(frame, workspace_id="another-workspace"), True)
    assert rows(client, lineage_sets.TABLE) == []


def test_older_native_workspace_attach_is_readonly_and_typed_write_requires_explicit_upgrade(
    selected,
):
    from paper_daily.sync_deck_publication import runtime
    from paper_daily.sync_research import initialize

    original = selected[0][1]
    frame, _sources = frame_for(selected)
    with original.journal.transaction() as conn:
        conn.execute("DROP TABLE " + projection.TABLE)
        conn.execute("DROP TABLE " + projection.HISTORY)
    with closing(original.journal._connect()) as conn:
        before = list(conn.iterdump())
    attached = runtime(database=original.journal.path)
    assert attached.projection_writer is research_projection_writer
    with closing(original.journal._connect()) as conn:
        assert list(conn.iterdump()) == before
    with pytest.raises(ValueError, match="Initialize the staged Lineage projection"):
        work(dispatch, attached, frame, True)
    with closing(original.journal._connect()) as conn:
        assert list(conn.iterdump()) == before
    with original.journal.transaction() as conn:
        initialize(
            conn, workspace_id=original.journal.workspace_id, device_id=original.journal.device_id
        )
        assert conn.in_transaction
    work(dispatch, attached, frame, True)
    assert len(rows(attached, lineage_sets.TABLE)) == 1
    assert original.journal.pending() == attached.journal.pending()


def test_trusted_lineage_schema_upgrade_rolls_back_with_its_owner_without_rebinding(selected):
    from paper_daily.sync_research import initialize

    client = selected[0][1]
    with client.journal.transaction() as conn:
        conn.execute("DROP TABLE " + projection.TABLE)
        conn.execute("DROP TABLE " + projection.HISTORY)
    with closing(client.journal._connect()) as conn:
        before = list(conn.iterdump())
    with (
        pytest.raises(RuntimeError, match="fixture caller rollback"),
        client.journal.transaction() as conn,
    ):
        initialize(
            conn, workspace_id=client.journal.workspace_id, device_id=client.journal.device_id
        )
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (projection.TABLE,)
        ).fetchone()
        raise RuntimeError("fixture caller rollback")
    with closing(client.journal._connect()) as conn:
        assert list(conn.iterdump()) == before
    with client.journal.transaction() as conn:
        with pytest.raises(ValueError, match="binding differs"):
            initialize(conn, workspace_id=client.journal.workspace_id, device_id="another-device")
        assert conn.in_transaction
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (projection.TABLE,)
        ).fetchone()
    with closing(client.journal._connect()) as conn:
        assert list(conn.iterdump()) == before


def test_actual_receive_projects_later_original_metadata_before_earlier_research_content(prepared):
    from test_lineage_transfer_readiness import upload

    from paper_daily.sync_artifacts import desired_file
    from paper_daily.sync_content import content_id

    pair, frame, originals = prepared
    service, client, peer, files, _peer_files, token, peer_token = pair
    scope = dict(kind="paper", id=frame["parents"][0]["id"])
    payload = dict(
        scope=scope,
        feature="dive",
        key="main",
        source_document_hash=frame["payload"]["source_document_hash"],
        data=dict(
            body="Saved fixture research", written_at="2026-11-13T01:00:00+00:00", spec="fixture"
        ),
    )
    dive = client.new_graph_operation(
        "research_content", content_id(scope, "dive", "main"), payload
    )
    client.save(dive)
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    upload(pair, originals)
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    events = service.pull(peer_token, after=peer.status()["cursor"])
    scientific_sequence = next(
        e["sequence"] for e in events if e["operation"]["operation_id"] == dive["operation_id"]
    )
    assert all(
        e["sequence"] > scientific_sequence
        for e in events
        if e["operation"]["entity_type"] == "research_file"
    )
    projected = []

    def record(conn, operation, *, visible):
        research_projection_writer(conn, operation, visible=visible)
        if operation["entity_type"] not in {"research_file", "research_content"}:
            return
        projected.append(operation["operation_id"])
        if operation["operation_id"] == dive["operation_id"]:
            assert all(desired_file(conn, p["file_id"]) for p in frame["source_dependencies"])

    receiving = SyncClient.attach_existing(peer.journal, peer.writer, projection_writer=record)
    assert receiving.receive(events)["received"] == len(events)
    assert projected[-1] == dive["operation_id"] and len(projected) == 4
    assert receiving.journal.pending() == []
