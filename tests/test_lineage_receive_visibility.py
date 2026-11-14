"""Actual native original events drive staged Lineage visibility, not byte presence."""

import copy
import json
from contextlib import closing

import pytest
from test_lineage_observation import work
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import project, rows
from test_lineage_transfer_readiness import prepared as prepared
from test_lineage_transfer_readiness import upload
from test_sync_files import drain

from paper_daily import lineage_dependencies as dependencies
from paper_daily import lineage_projection as projection
from paper_daily import lineage_sets
from paper_daily.sync_journal import canonical_operation


def reason(client, frame):
    with client.journal.transaction() as conn:
        return dependencies.projection_reason_in(conn, client, frame)


def originals_accepted(prepared):
    pair, frame, originals = prepared
    service, client, _peer, files, _peer_files, token, _peer_token = pair
    upload(pair, originals)
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    return pair, frame, originals


def apply_visibility(client, frame):
    """Stage the future protected receiver write; do not invent a SCI event/outbox."""
    with client.journal.transaction() as conn:
        why = dependencies.projection_reason_in(conn, client, frame)
        if why in {"parent_pending", "parent_deferred", "source_pending", "source_deferred"}:
            return why
        conn.set_authorizer(client.journal._authorize_writer)
        try:
            return projection.apply_in(conn, frame, visible=why is None)
        finally:
            conn.set_authorizer(None)


def test_unreceived_source_is_pending_locally_but_missing_on_the_peer(prepared):
    pair, frame, _originals = prepared
    service, client, peer, _files, _peer_files, _token, peer_token = pair
    peer.sync_once(service, peer_token)
    before = copy.deepcopy(frame), client.journal.pending()
    assert reason(client, frame) == "source_pending"
    assert reason(peer, frame) == "source_missing"
    assert (frame, client.journal.pending()) == before
    assert json.loads(canonical_operation(frame)) == frame


def test_actual_received_source_metadata_is_enough_without_peer_pdf_bytes(prepared, monkeypatch):
    pair, frame, _originals = originals_accepted(prepared)
    service, client, peer, _files, peer_files, _token, peer_token = pair
    peer.sync_once(service, peer_token)

    def unexpected(*_args, **_kwargs):
        pytest.fail("Receive visibility must not read original bytes or call the service")

    monkeypatch.setattr(peer_files.store, "verified_path", unexpected)
    monkeypatch.setattr(service, "session_info", unexpected)
    assert reason(client, frame) is None and reason(peer, frame) is None
    with peer.journal.transaction() as conn:
        projection.initialize_in(conn)
    assert work(apply_visibility, peer, frame)["state"] == "projected"
    assert len(rows(peer, lineage_sets.TABLE)) == 1
    assert peer.journal.pending() == []
    assert projection.validate_history(rows(peer, projection.HISTORY)[0]) == frame


@pytest.mark.parametrize("restore", [False, True])
def test_actual_source_retirement_hides_report_but_preserves_original_put(prepared, restore):
    pair, frame, originals = originals_accepted(prepared)
    service, client, _peer, files, _peer_files, token, _peer_token = pair
    work(project, client, frame)
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
    before = rows(client, lineage_sets.TABLE), rows(client, projection.TABLE)
    assert work(apply_visibility, client, frame) == "source_pending"
    assert (rows(client, lineage_sets.TABLE), rows(client, projection.TABLE)) == before
    if replacement:
        drain(lambda: files.upload(replacement), "uploaded")
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    assert reason(client, frame) == ("source_incarnation" if restore else "source_deleted")
    assert work(apply_visibility, client, frame)["state"] == "hidden"
    assert rows(client, lineage_sets.TABLE) == []
    marker = rows(client, projection.TABLE)[0]
    assert marker["active"] == 0 and projection.validate_record(marker) == frame
    assert projection.validate_history(rows(client, projection.HISTORY)[0]) == frame
    assert client.journal.pending() == []


def test_parent_edit_pending_preserves_science_until_received_metadata_converges(prepared):
    pair, frame, _originals = originals_accepted(prepared)
    service, client, _peer, files, _peer_files, token, _peer_token = pair
    work(project, client, frame)
    parent = frame["parents"][0]
    with closing(client.journal._connect()) as conn:
        import json

        payload = json.loads(
            conn.execute(
                "SELECT operation FROM paperfact_sync_heads "
                "WHERE entity_type='paper' AND entity_id=?",
                (parent["id"],),
            ).fetchone()[0]
        )["payload"]
    renamed = client.new_graph_operation("paper", parent["id"], dict(payload, title="Renamed"))
    client.save(renamed)
    before = rows(client, lineage_sets.TABLE)
    assert work(apply_visibility, client, frame) == "parent_pending"
    assert rows(client, lineage_sets.TABLE) == before
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    assert reason(client, frame) is None
    assert work(apply_visibility, client, frame)["state"] == "projected"
    assert rows(client, lineage_sets.TABLE) == before


def test_receive_scope_is_fixed_but_remote_sender_is_allowed(prepared):
    pair, frame, _originals = originals_accepted(prepared)
    service, client, peer, _files, _peer_files, _token, peer_token = pair
    peer.sync_once(service, peer_token)
    assert frame["device_id"] != peer.journal.device_id
    assert reason(peer, frame) is None
    foreign = dict(frame, workspace_id="another-workspace")
    with pytest.raises(ValueError, match="another workspace"):
        reason(client, foreign)
    with peer.journal.transaction() as conn, pytest.raises(ValueError, match="another research"):
        dependencies.projection_reason_in(conn, client, frame)


def test_typed_retirement_needs_no_current_source_and_does_not_change_its_frame(prepared):
    pair, frame, _originals = prepared
    retired = dict(frame, action="delete", payload={}, source_dependencies=[])
    before = copy.deepcopy(retired)
    assert reason(pair[1], retired) is None
    assert retired == before


def test_any_pending_original_prevents_earlier_missing_source_from_erasing_the_row(prepared):
    pair, frame, originals = originals_accepted(prepared)
    service, client, _peer, files, _peer_files, token, _peer_token = pair
    work(project, client, frame)
    first, second, _third = originals.values()
    deletion = client.new_graph_operation("research_file", first["entity_id"], {}, action="delete")
    client.save(deletion)
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    update = client.new_graph_operation("research_file", second["entity_id"], second["payload"])
    client.save(update)
    before = rows(client, lineage_sets.TABLE), rows(client, projection.TABLE)
    assert work(apply_visibility, client, frame) == "source_pending"
    assert (rows(client, lineage_sets.TABLE), rows(client, projection.TABLE)) == before


@pytest.mark.parametrize("role", ["parent", "source"])
def test_retained_projection_lag_preserves_content_until_the_native_materializer_catches_up(
    prepared, role
):
    pair, frame, _originals = originals_accepted(prepared)
    client = pair[1]
    work(project, client, frame)
    if role == "parent":
        kind, identity = "paper", frame["parents"][0]["id"]
    else:
        kind, identity = "research_file", frame["source_dependencies"][0]["file_id"]
    # Simulate a retained projection behind its genuine received native head.
    # No head, graph, source event, scientific receipt or outbox is fabricated.
    with client.journal.transaction() as conn:
        conn.execute(
            "UPDATE paperfact_sync_heads SET applied_revision=-1 "
            "WHERE entity_type=? AND entity_id=?",
            (kind, identity),
        )
    before = rows(client, lineage_sets.TABLE), rows(client, projection.HISTORY)
    assert work(apply_visibility, client, frame) == role + "_deferred"
    assert (rows(client, lineage_sets.TABLE), rows(client, projection.HISTORY)) == before
    with client.journal.transaction() as conn:
        cursor = conn.execute("SELECT sequence FROM paperfact_sync_cursor").fetchone()[0]
        assert client._materialize_graph(conn, cursor) >= 1
    assert reason(client, frame) is None
    assert work(apply_visibility, client, frame)["state"] == "projected"
    assert (rows(client, lineage_sets.TABLE), rows(client, projection.HISTORY)) == before
    assert client.journal.pending() == []
