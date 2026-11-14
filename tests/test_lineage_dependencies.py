"""Actual peer publication pins original lifetimes before future Lineage admission."""

import copy
import json
from contextlib import closing, nullcontext
from uuid import uuid4

import pytest
from test_lineage_observation import work
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import file_counts
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_sync_files import drain

from paper_daily import lineage_dependencies as dependencies
from paper_daily import lineage_peer_sources, lineage_sets, lineage_wire, research_lineage
from paper_daily.sync_content import content_id
from paper_daily.sync_journal import canonical_operation as live_canonical


def compound(selected, *, rollback=False, connection=None, verified=None):
    peers, corpus, observed, staged = selected
    client = peers[1]
    with (
        nullcontext(connection) if connection is not None else client.journal.transaction()
    ) as conn:
        operations = lineage_peer_sources.publish_in(conn, client, staged)
        pins = lineage_peer_sources.pins_in(conn, client, staged, operations)
        captured = json.loads(corpus._json)
        report = (
            verified
            if verified is not None
            else research_lineage.verify_snapshot(
                corpus,
                dict(
                    format=research_lineage.PROPOSALS,
                    focal=corpus.focal,
                    statements=[],
                ),
            )
        )
        body = dict(
            format=lineage_sets.FORMAT,
            corpus_id=observed.data["corpus_id"],
            inputs=dict(dive=None, close_reading=None),
            generation=dict(
                task="lineage", backend="fixture", requested_model=None, returned_model=None
            ),
            report=report,
            bindings=[
                dict(source_id=s["id"], paper_id=p["local_id"])
                for s, p in zip(corpus.sources, captured["observed"], strict=True)
            ],
        )
        row = dict(
            paper_id=captured["observed"][0]["local_id"],
            corpus_key=body["corpus_id"],
            body_json=lineage_sets.canonical(body),
            source_hash=lineage_sets.source_hash(body),
            document_hash=corpus.sources[0]["document_hash"],
            written_at="2026-11-13T00:00:00+00:00",
        )
        payload = lineage_wire.encode_row(conn, row)
        frame = dict(
            version=2,
            operation_id=observed.data["request_id"],
            workspace_id=client.journal.workspace_id,
            device_id=client.journal.device_id,
            entity_type="research_content",
            entity_id=content_id(payload["scope"], "lineage", payload["key"]),
            action="put",
            base_revision=0,
            depends_on=None,
            incarnation=observed.data["request_id"],
            parents=[s["parent"] for s in observed.data["sources"]],
            structure_revision=0,
            content_address=dict(feature="lineage", key=payload["key"]),
            payload=payload,
            source_dependencies=pins,
        )
        state = client._optimistic_graph(conn)[0]
        assert dependencies.active(lambda kind, identity: state.get((kind, identity)), frame)
        if rollback:
            raise RuntimeError("later compound action failed")
        return frame, operations


def graph(client):
    with closing(client.journal._connect()) as conn:
        conn.execute("BEGIN")
        return client._optimistic_graph(conn)[0]


def test_actual_same_transaction_pins_are_complete_read_only_and_wire_round_trip(selected):
    client = selected[0][1]
    frame, operations = work(compound, selected)
    before = client.journal.pending()
    encoded = dependencies.canonical_operation(frame)
    assert json.loads(encoded) == frame
    assert len(frame["source_dependencies"]) == len(operations) == 3
    assert {p["incarnation"] for p in frame["source_dependencies"]} == {
        op["incarnation"] for op in operations.values()
    }
    state = graph(client)
    previous = copy.deepcopy(state)
    assert dependencies.active(lambda kind, identity: state.get((kind, identity)), frame)
    assert state == previous and client.journal.pending() == before
    assert json.loads(live_canonical(frame)) == frame


@pytest.mark.parametrize(
    "broken",
    [
        "missing",
        "extra",
        "reorder",
        "wrong-paper",
        "wrong-file",
        "wrong-source",
        "invalid-incarnation",
        "extra-field",
    ],
)
def test_closed_pins_reject_incomplete_or_cross_owner_dependency_data(selected, broken):
    frame, _operations = work(compound, selected)
    pins = frame["source_dependencies"]
    if broken == "missing":
        pins.pop()
    elif broken == "extra":
        pins.append(copy.deepcopy(pins[0]))
    elif broken == "reorder":
        pins.reverse()
    elif broken == "wrong-paper":
        pins[0]["paper_id"] = pins[1]["paper_id"]
    elif broken == "wrong-file":
        pins[0]["file_id"] = pins[1]["file_id"]
    elif broken == "wrong-source":
        pins[0]["source_id"] = pins[1]["source_id"]
    elif broken == "invalid-incarnation":
        pins[0]["incarnation"] = "invalid lifetime"
    else:
        pins[0]["extra"] = True
    with pytest.raises(ValueError):
        dependencies.canonical_operation(frame)


def test_same_hash_original_retire_restore_rejects_old_pins_and_native_recapture(selected):
    peers, _corpus, _observed, prepared = selected
    client = peers[1]
    frame, operations = work(compound, selected)
    old = next(iter(operations.values()))

    def retire_restore():
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

    restored = work(retire_restore)
    assert restored["payload"] == old["payload"] and restored["incarnation"] != old["incarnation"]
    state = graph(client)
    assert not dependencies.active(lambda kind, identity: state.get((kind, identity)), frame)

    def stale_recapture():
        with client.journal.transaction() as conn:
            return lineage_peer_sources.pins_in(conn, client, prepared, operations)

    before = client.journal.pending()
    with pytest.raises(ValueError):
        work(stale_recapture)
    assert client.journal.pending() == before


def test_actual_service_graph_accepts_uploaded_original_pins_only_in_the_right_workspace(selected):
    peers = selected[0]
    service, client, _peer, files, _peer_files, token, _peer_token = peers
    frame, operations = work(compound, selected)
    for op in operations.values():
        drain(lambda op=op: files.upload(op), "uploaded")
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    with service._transaction() as conn:

        def current(kind, identity):
            return service._graph_entity(conn, client.journal.workspace_id, kind, identity)

        assert dependencies.active(current, frame)
        assert not dependencies.active(
            lambda kind, identity: service._graph_entity(conn, "other-workspace", kind, identity),
            frame,
        )

    old = next(iter(operations.values()))

    def retire_restore():
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

    restored = work(retire_restore)
    drain(lambda: files.upload(restored), "uploaded")
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    with service._transaction() as conn:
        assert not dependencies.active(
            lambda kind, identity: service._graph_entity(
                conn, client.journal.workspace_id, kind, identity
            ),
            frame,
        )


def test_source_pin_failure_still_uses_the_outer_compound_rollback(selected):
    peers, _corpus, _observed, _prepared = selected
    client = peers[1]
    before = client.journal.pending()
    with pytest.raises(RuntimeError, match="later compound action"):
        work(compound, selected, rollback=True)
    assert client.journal.pending() == before and file_counts(client) == (0, 0)


def test_retirement_remains_possible_after_originals_are_inactive(selected):
    frame, _operations = work(compound, selected)
    frame.update(action="delete", payload={}, source_dependencies=[])
    assert dependencies.active(lambda *_a: None, frame)
    assert json.loads(dependencies.canonical_operation(frame)) == frame
    frame["source_dependencies"] = [dict(source_id="0" * 64)]
    with pytest.raises(ValueError):
        dependencies.canonical_operation(frame)


def recapture(selected, local_ids=None):
    from paper_daily import lineage_observation

    peers, previous, _observed, _staged = selected
    client, files = peers[1], peers[3]
    local_ids = local_ids or [p["local_id"] for p in json.loads(previous._json)["observed"]]
    corpus = research_lineage.capture(
        client.journal.path,
        local_ids[0],
        local_ids[1:],
        legacy_root=previous._documents[0].path.parent,
    )
    observed = work(lineage_observation.observe, corpus, str(uuid4()), str(uuid4()))
    staged = work(
        lineage_peer_sources.prepare,
        observed,
        store=files.store,
        version_root=files.root,
        client=client,
    )
    return peers, corpus, observed, staged


def test_unavailable_peer_has_no_file_pin_but_its_paper_lifetime_still_matters(selected):
    from test_sync_files import paper_payload

    from paper_daily.research_lifecycle import ensure_lifecycle

    client = selected[0][1]
    portable = str(uuid4())
    client.save(
        client.new_graph_operation(
            "paper",
            portable,
            {
                **paper_payload(),
                "title": "Unavailable selected fourth original",
            },
        )
    )
    with client.journal.transaction() as conn:
        ensure_lifecycle(conn)
        missing = conn.execute(
            "SELECT local_id FROM research_paper_identity WHERE sync_id=?", (portable,)
        ).fetchone()[0]
    local_ids = [p["local_id"] for p in json.loads(selected[1]._json)["observed"]] + [missing]
    chosen = recapture(selected, local_ids)
    frame, _operations = work(compound, chosen)
    assert len(frame["parents"]) == 4 and len(frame["source_dependencies"]) == 3
    assert (
        frame["payload"]["data"]["body_json"]["report"]["sources"][-1]["availability"]
        == "unavailable"
    )
    state = graph(client)
    # Paper deletion remains prohibited by the live retention contract. Exercise
    # this pure guard with an explicitly simulated retired fourth-paper state.
    state[("paper", portable)] = dict(state[("paper", portable)], active=False)
    assert not dependencies.active(lambda kind, identity: state.get((kind, identity)), frame)


def test_equal_bytes_keep_separate_actual_file_and_paper_dependency_owners(selected):
    corpus = selected[1]
    corpus._documents[2].path.write_bytes(corpus._documents[1].path.read_bytes())
    chosen = recapture(selected)
    frame, _operations = work(compound, chosen)
    sources = frame["payload"]["data"]["body_json"]["report"]["sources"]
    pins = frame["source_dependencies"]
    assert sources[1]["document_hash"] == sources[2]["document_hash"]
    assert pins[1]["paper_id"] != pins[2]["paper_id"] and pins[1]["file_id"] != pins[2]["file_id"]
    state = graph(selected[0][1])
    assert dependencies.active(lambda kind, identity: state.get((kind, identity)), frame)
    pins[1]["file_id"] = pins[2]["file_id"]
    with pytest.raises(ValueError, match="exact selected source owner"):
        dependencies.canonical_operation(frame)


@pytest.mark.parametrize("value", [None, [], False])
def test_dependency_codec_rejects_non_object_boundary_data(value):
    with pytest.raises(ValueError, match="must be an object"):
        dependencies.canonical_operation(value)


def test_unknown_graph_metadata_is_not_current_source_authority(selected):
    frame, _operations = work(compound, selected)
    state = graph(selected[0][1])
    first = frame["source_dependencies"][0]
    state[("research_file", first["file_id"])] = "malformed source graph"
    assert not dependencies.active(lambda kind, identity: state.get((kind, identity)), frame)


def test_pin_capture_requires_actual_client_transaction_and_native_staging(selected):
    from dataclasses import replace

    peers, _corpus, _observed, prepared = selected
    client, peer = peers[1], peers[2]
    _frame, operations = work(compound, selected)
    before = client.journal.pending()

    def invalid_inputs():
        with client.journal.transaction() as conn:
            for wrong in (None, peer):
                with pytest.raises(ValueError, match="lineage_client_scope_changed"):
                    lineage_peer_sources.pins_in(conn, wrong, prepared, operations)
            with pytest.raises(ValueError, match="invalid_lineage_peer_staging"):
                lineage_peer_sources.pins_in(
                    conn, client, replace(prepared, _entries=()), operations
                )
        with (
            closing(client.journal._connect()) as conn,
            pytest.raises(ValueError, match="lineage_database_or_binding_changed"),
        ):
            lineage_peer_sources.pins_in(conn, client, prepared, operations)

    work(invalid_inputs)
    assert client.journal.pending() == before and file_counts(client) == (3, 3)
