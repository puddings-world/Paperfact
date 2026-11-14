"""Shared pure graph checks must reject stale explicit original dependencies."""

import json

from test_lineage_dependencies import compound
from test_lineage_observation import work
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_sync_files import drain

from paper_daily import lineage_dependencies
from paper_daily.sync_graph import check_preconditions
from paper_daily.sync_journal import canonical_operation


def test_shared_graph_rejects_old_pins_after_actual_service_original_restore(selected):
    service, client, _peer, files, _peer_files, token, _peer_token = selected[0]
    frame, operations = work(compound, selected)
    for operation in operations.values():
        drain(lambda operation=operation: files.upload(operation), "uploaded")
    client.sync_once(service, token, prepare_push=files.ready_to_push)

    def current_check():
        with service._transaction() as conn:

            def entity(kind, identity):
                return service._graph_entity(conn, client.journal.workspace_id, kind, identity)

            def receipt(identity):
                raw = conn.execute(
                    "SELECT event FROM sync_events WHERE workspace=? AND operation_id=?",
                    (client.journal.workspace_id, identity),
                ).fetchone()
                return json.loads(raw[0]) if raw else None

            return lineage_dependencies.active(entity, frame), check_preconditions(
                entity, receipt, frame
            )

    assert current_check() == (True, True)
    old = next(iter(operations.values()))

    def restore_file():
        with client.journal.transaction() as conn:
            deleted = client.new_graph_operation_in(
                conn, "research_file", old["entity_id"], {}, action="delete"
            )
            client.journal.apply_in(conn, deleted, client.writer)
            restored = client.new_graph_operation_in(
                conn, "research_file", old["entity_id"], old["payload"], restore=True
            )
            client.journal.apply_in(conn, restored, client.writer)
            return restored

    restored = work(restore_file)
    assert restored["payload"] == old["payload"]
    assert restored["incarnation"] != old["incarnation"]
    drain(lambda: files.upload(restored), "uploaded")
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    assert current_check() == (False, False)
    assert json.loads(canonical_operation(frame)) == frame
