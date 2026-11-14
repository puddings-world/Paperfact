"""Source visibility follows actual received prefix inside the receive transaction."""

from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_transfer_readiness import prepared as prepared
from test_lineage_transfer_readiness import upload

from paper_daily.lineage_dependencies import projection_reason_in


def test_current_receive_prefix_does_not_reclassify_just_received_originals_as_pending(
    prepared, monkeypatch
):
    pair, frame, originals = prepared
    service, client, _peer, files, _peer_files, token, _peer_token = pair
    upload(pair, originals)
    observed = []
    original_materialize = client._materialize

    def inspect_after_native_projection(conn, cursor):
        result = original_materialize(conn, cursor)
        saved_cursor = conn.execute("SELECT sequence FROM paperfact_sync_cursor").fetchone()[0]
        assert saved_cursor < cursor
        observed.append(projection_reason_in(conn, client, frame))
        assert observed[-1] is None
        return result

    monkeypatch.setattr(client, "_materialize", inspect_after_native_projection)
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    assert observed == [None]
    assert client.journal.pending() == []


def test_acknowledged_original_without_received_event_still_preserves_pending_state(prepared):
    pair, frame, originals = prepared
    service, client, _peer, _files, _peer_files, token, _peer_token = pair
    upload(pair, originals)
    for source in originals.values():
        event = service.push(token, source)
        client.journal.acknowledge(source["operation_id"], event["sequence"])
    with client.journal.transaction() as conn:
        assert projection_reason_in(conn, client, frame) == "source_pending"
