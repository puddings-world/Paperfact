"""Actual source publication/transfer results gate future Lineage child readiness."""

import copy
import json
from contextlib import closing

import pytest
from test_lineage_observation import work
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import frame_for
from test_sync_files import drain

from paper_daily import lineage_dependencies
from paper_daily.sync_journal import canonical_operation


@pytest.fixture
def prepared(selected):
    frame, originals = frame_for(selected)
    service, client, peer, files, peer_files, token, peer_token = selected[0]
    # Real paper roots become accepted while source uploads are still deferred.
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    return selected[0], frame, originals


def upload(pair, originals):
    files = pair[3]
    for original in originals.values():
        drain(lambda original=original: files.upload(original), "uploaded")


def test_unfinished_originals_defer_science_without_jobs_or_changes(prepared):
    pair, frame, originals = prepared
    _service, client, _peer, files, _peer_files, _token, _peer_token = pair
    before, unchanged = client.journal.pending(), copy.deepcopy(frame)
    with closing(client.journal._connect()) as conn:
        sql_before = list(conn.iterdump())
    assert files.ready_to_push(frame) is False
    upload(pair, originals)
    # Upload completion is not a metadata-acceptance result.
    assert all(files.ready_to_push(op) for op in originals.values())
    assert files.ready_to_push(frame) is False
    with closing(client.journal._connect()) as conn:
        # Only explicit uploads may add transfer progress; preparation adds nothing.
        after_upload = list(conn.iterdump())
    assert files.ready_to_push(frame) is False
    with closing(client.journal._connect()) as conn:
        assert list(conn.iterdump()) == after_upload
    assert sql_before != after_upload
    assert client.journal.pending() == before and frame == unchanged


def test_source_acknowledgement_without_received_outcome_is_not_acceptance(prepared):
    pair, frame, originals = prepared
    service, client, _peer, files, _peer_files, token, _peer_token = pair
    upload(pair, originals)
    cursor = client.status()["cursor"]
    for original in originals.values():
        event = service.push(token, original)
        assert event["outcome"] == "accepted"
        client.journal.acknowledge(original["operation_id"], event["sequence"])
    assert files.ready_to_push(frame) is False
    client.receive(service.pull(token, after=cursor, limit=100))
    assert files.ready_to_push(frame) is True
    assert json.loads(canonical_operation(frame)) == frame


def test_accepted_originals_do_not_require_another_upload(prepared, monkeypatch):
    pair, frame, originals = prepared
    service, client, _peer, files, _peer_files, token, _peer_token = pair
    upload(pair, originals)
    client.sync_once(service, token, prepare_push=files.ready_to_push)

    def unexpected(*_args, **_kwargs):
        pytest.fail("Readiness must inspect local metadata, not bytes, auth or network")

    monkeypatch.setattr(files.transport, "session_info", unexpected)
    monkeypatch.setattr(files.store, "verified_path", unexpected)
    before = copy.deepcopy(frame), client.journal.pending()
    assert files.ready_to_push(frame) is True
    assert (frame, client.journal.pending()) == before


def test_retired_restored_source_is_a_real_conflict_not_an_infinite_transfer_wait(prepared):
    pair, frame, originals = prepared
    service, client, _peer, files, _peer_files, token, _peer_token = pair
    upload(pair, originals)
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    original = next(iter(originals.values()))

    def restore():
        with client.journal.transaction() as conn:
            deleted = client.new_graph_operation_in(
                conn, "research_file", original["entity_id"], {}, action="delete"
            )
            client.journal.apply_in(conn, deleted, client.writer)
            restored = client.new_graph_operation_in(
                conn, "research_file", original["entity_id"], original["payload"], restore=True
            )
            client.journal.apply_in(conn, restored, client.writer)
        return restored

    restored = work(restore)
    drain(lambda: files.upload(restored), "uploaded")
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    assert files.ready_to_push(frame) is True
    with client.journal.transaction() as conn:
        assert not lineage_dependencies.active(
            lambda kind, identity: client._graph_entity(conn, kind, identity), frame
        )
    assert frame["source_dependencies"][0]["incarnation"] != restored["incarnation"]


@pytest.mark.parametrize("change", ["workspace", "device", "missing-publication", "malformed"])
def test_foreign_or_missing_source_publication_is_not_reported_as_pending_upload(prepared, change):
    pair, frame, _originals = prepared
    files = pair[3]
    frame = copy.deepcopy(frame)
    if change == "workspace":
        frame["workspace_id"] = "another-workspace"
    elif change == "device":
        frame["device_id"] = "another-device"
    elif change == "missing-publication":
        frame["source_dependencies"][0]["incarnation"] = "no-such-source-publication"
    else:
        del frame["source_dependencies"]
    with pytest.raises(ValueError):
        files.ready_to_push(frame)


def test_typed_retirement_has_no_source_upload_requirement(prepared):
    pair, frame, _originals = prepared
    frame = dict(frame, action="delete", payload={}, source_dependencies=[])
    assert pair[3].ready_to_push(frame) is True


def test_conflicted_original_releases_wait_without_rebasing_its_pin(prepared):
    pair, frame, originals = prepared
    service, client, peer, files, _peer_files, token, peer_token = pair
    upload(pair, originals)
    peer.sync_once(service, peer_token)
    original = next(iter(originals.values()))
    competitor = peer.new_graph_operation(
        "research_file", original["entity_id"], original["payload"]
    )
    accepted = service.push(peer_token, competitor)
    assert accepted["outcome"] == "accepted"
    cursor = client.status()["cursor"]
    outcomes = []
    for source in originals.values():
        event = service.push(token, source)
        outcomes.append(event["outcome"])
        client.journal.acknowledge(source["operation_id"], event["sequence"])
    assert sorted(outcomes) == ["accepted", "accepted", "conflict"]
    assert files.ready_to_push(frame) is False
    client.receive(service.pull(token, after=cursor, limit=100))
    before = copy.deepcopy(frame), client.journal.pending()
    assert files.ready_to_push(frame) is True
    with client.journal.transaction() as conn:
        assert not lineage_dependencies.active(
            lambda kind, identity: client._graph_entity(conn, kind, identity), frame
        )
    assert (frame, client.journal.pending()) == before
    assert frame["source_dependencies"][0]["incarnation"] != competitor["incarnation"]


def test_received_peer_originals_need_no_local_upload_or_sender_outbox(prepared):
    pair, frame, originals = prepared
    service, client, peer, files, peer_files, token, peer_token = pair
    upload(pair, originals)
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    peer.sync_once(service, peer_token)
    frame = dict(frame, device_id=peer.journal.device_id)
    assert peer.journal.pending() == []
    with closing(peer.journal._connect()) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_transfers").fetchone()[0] == 0
    assert peer_files.ready_to_push(frame) is True


def test_readiness_requires_the_fixed_database_and_active_transaction(prepared):
    pair, frame, _originals = prepared
    _service, client, peer, _files, _peer_files, _token, _peer_token = pair
    with (
        closing(client.journal._connect()) as conn,
        pytest.raises(ValueError, match="caller transaction"),
    ):
        lineage_dependencies.ready_to_push_in(conn, client, frame)
    with (
        peer.journal.transaction() as conn,
        pytest.raises(ValueError, match="another research database"),
    ):
        lineage_dependencies.ready_to_push_in(conn, client, frame)


@pytest.mark.parametrize("restore", [False, True])
def test_source_retired_before_first_upload_still_drains_without_reviving_science(
    prepared, restore
):
    pair, frame, originals = prepared
    service, client, _peer, files, _peer_files, token, _peer_token = pair
    original = next(iter(originals.values()))

    def retire():
        with client.journal.transaction() as conn:
            deleted = client.new_graph_operation_in(
                conn, "research_file", original["entity_id"], {}, action="delete"
            )
            client.journal.apply_in(conn, deleted, client.writer)
            if restore:
                replacement = client.new_graph_operation_in(
                    conn, "research_file", original["entity_id"], original["payload"], restore=True
                )
                client.journal.apply_in(conn, replacement, client.writer)
                return replacement
        return None

    replacement = work(retire)
    assert files.ready_to_push(frame) is False
    unchanged = copy.deepcopy(frame)
    upload(pair, originals)
    if replacement:
        drain(lambda: files.upload(replacement), "uploaded")
    result = client.sync_once(service, token, prepare_push=files.ready_to_push)
    assert result["pending"] == 0 and result["deferred_push"] == 0
    assert files.ready_to_push(frame) is True
    with client.journal.transaction() as conn:
        assert not lineage_dependencies.active(
            lambda kind, identity: client._graph_entity(conn, kind, identity), frame
        )
    assert frame == unchanged
    assert json.loads(canonical_operation(frame)) == frame
