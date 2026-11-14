"""Real native Lineage conflicts preserve exact sources and explicit restore intent."""

import copy
from uuid import uuid4

import pytest
from test_lineage_live_journey import setup_publication, sync_all
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import rows
from test_sync_files import drain

from paper_daily import lineage_projection, lineage_sets


def edit(client, source, stamp):
    payload = copy.deepcopy(source["payload"])
    payload["data"]["written_at"] = stamp
    with client.journal.transaction() as conn:
        op = client._new_graph_operation(
            conn, "research_content", source["entity_id"], payload, lineage_template=source
        )

        def write(c, value):
            client._guard_content_parent(c, value)
            client.writer(c, value)

        client.journal.apply_in(conn, op, write)
    return op


def conflict(selected, monkeypatch):
    a, _candidate, _receipt, source, originals = setup_publication(selected, monkeypatch)
    b = sync_all(selected, a, originals)
    service, _old, _peer, files, _peer_files, ta, tb = selected[0]
    first = edit(a, source, "2026-11-14T01:00:00+00:00")
    second = edit(b, source, "2026-11-14T02:00:00+00:00")
    a.sync_once(service, ta, prepare_push=files.ready_to_push)
    b.sync_once(service, tb)
    event = next(
        e
        for e in b.history(conflicts_only=True)
        if e["operation"]["operation_id"] == second["operation_id"]
    )
    assert event["outcome"] == "conflict" and event["head"]["operation"] == first
    return a, b, source, originals, event


@pytest.mark.parametrize("choice", ["incoming", "canonical"])
def test_actual_conflict_choices_preserve_sources_and_retry_one_resolution(
    selected, monkeypatch, choice
):
    a, b, source, _originals, event = conflict(selected, monkeypatch)
    service, _old, _peer, files, _peer_files, ta, tb = selected[0]
    resolution = b.resolve_conflict(event["sequence"], choice=choice)
    again = b.resolve_conflict(event["sequence"], choice=choice)
    assert again["operation_id"] == resolution["operation_id"] and not again["applied"]
    intent = next(
        op for op in b.journal.pending() if op["operation_id"] == resolution["operation_id"]
    )
    assert intent["content_address"] == source["content_address"]
    assert intent["source_dependencies"] == source["source_dependencies"]
    b.sync_once(service, tb)
    a.sync_once(service, ta, prepare_push=files.ready_to_push)
    assert a.status()["conflicts"] == b.status()["conflicts"] == 0
    expected = "2026-11-14T02:00:00+00:00" if choice == "incoming" else "2026-11-14T01:00:00+00:00"
    assert rows(a, lineage_sets.TABLE)[0]["written_at"] == expected
    assert rows(b, lineage_sets.TABLE)[0]["written_at"] == expected


def test_source_change_invalidates_displayed_conflict_and_canonical_choice_retires_stale_science(
    selected, monkeypatch
):
    a, b, source, originals, event = conflict(selected, monkeypatch)
    service, _old, _peer, files, _peer_files, ta, tb = selected[0]
    with b.journal.transaction() as conn:
        displayed = b.conflict_observation_in(conn, event["sequence"])
    old_source = originals[0]
    a.save(a.new_graph_operation("research_file", old_source["entity_id"], {}, action="delete"))
    a.sync_once(service, ta, prepare_push=files.ready_to_push)
    b.sync_once(service, tb)
    assert rows(b, lineage_sets.TABLE) == []
    with (
        b.journal.transaction() as conn,
        pytest.raises(ValueError, match="Displayed conflict changed"),
    ):
        b.resolve_conflict_in(conn, event["sequence"], expected=displayed, choice="canonical")
    with pytest.raises(ValueError, match="original dependency"):
        b.resolve_conflict(event["sequence"], choice="incoming")
    result = b.resolve_conflict(event["sequence"], choice="canonical")
    intent = next(op for op in b.journal.pending() if op["operation_id"] == result["operation_id"])
    assert intent["action"] == "delete" and intent["source_dependencies"] == []
    assert intent["content_address"] == source["content_address"]
    b.sync_once(service, tb)
    a.sync_once(service, ta, prepare_push=files.ready_to_push)
    assert a.status()["conflicts"] == b.status()["conflicts"] == 0
    assert rows(a, lineage_sets.TABLE) == rows(b, lineage_sets.TABLE) == []


def test_explicit_science_restore_keeps_original_sources_and_creates_a_new_scientific_epoch(
    selected, monkeypatch
):
    a, _candidate, _receipt, source, originals = setup_publication(selected, monkeypatch)
    b = sync_all(selected, a, originals)
    service, _old, _peer, files, _peer_files, ta, tb = selected[0]
    changed = edit(b, source, "2026-11-14T03:00:00+00:00")
    a.save(a.new_graph_operation("research_content", source["entity_id"], {}, action="delete"))
    a.sync_once(service, ta, prepare_push=files.ready_to_push)
    b.sync_once(service, tb)
    event = next(
        e
        for e in b.history(conflicts_only=True)
        if e["operation"]["operation_id"] == changed["operation_id"]
    )
    with pytest.raises(ValueError, match="restore=True"):
        b.resolve_conflict(event["sequence"])
    result = b.resolve_conflict(event["sequence"], restore=True)
    intent = next(op for op in b.journal.pending() if op["operation_id"] == result["operation_id"])
    assert intent["incarnation"] != source["incarnation"]
    assert intent["source_dependencies"] == source["source_dependencies"]
    b.sync_once(service, tb)
    a.sync_once(service, ta, prepare_push=files.ready_to_push)
    assert len(rows(a, lineage_sets.TABLE)) == len(rows(b, lineage_sets.TABLE)) == 1
    assert a.status()["conflicts"] == b.status()["conflicts"] == 0


def test_source_restore_does_not_revive_the_old_scientific_report(selected, monkeypatch):
    a, _candidate, _receipt, source, originals = setup_publication(selected, monkeypatch)
    b = sync_all(selected, a, originals)
    service, _old, _peer, files, _peer_files, ta, tb = selected[0]
    original = originals[0]
    a.save(a.new_graph_operation("research_file", original["entity_id"], {}, action="delete"))
    a.sync_once(service, ta, prepare_push=files.ready_to_push)
    b.sync_once(service, tb)
    assert rows(a, lineage_sets.TABLE) == rows(b, lineage_sets.TABLE) == []
    restored = a.new_graph_operation(
        "research_file", original["entity_id"], original["payload"], restore=True
    )
    a.save(restored)
    drain(lambda: files.upload(restored), "uploaded")
    a.sync_once(service, ta, prepare_push=files.ready_to_push)
    b.sync_once(service, tb)
    assert rows(a, lineage_sets.TABLE) == rows(b, lineage_sets.TABLE) == []
    assert source["source_dependencies"][0]["incarnation"] != restored["incarnation"]
    assert lineage_projection.validate_record(rows(b, lineage_projection.TABLE)[0]) == source


def test_service_refuses_missing_pins_and_preserves_unknown_source_lifetime_as_conflict(
    selected, monkeypatch
):
    a, _candidate, _receipt, source, originals = setup_publication(selected, monkeypatch)
    sync_all(selected, a, originals)
    service, _old, _peer, _files, _peer_files, ta, _tb = selected[0]
    broken = copy.deepcopy(source)
    broken["operation_id"] = str(uuid4())
    broken["base_revision"] = next(
        e["sequence"] for e in service.pull(ta) if e["operation"] == source
    )
    before = service.pull(ta)
    del broken["source_dependencies"]
    with pytest.raises(ValueError):
        service.push(ta, broken)
    assert service.pull(ta) == before
    broken["source_dependencies"] = copy.deepcopy(source["source_dependencies"])
    broken["source_dependencies"][0]["incarnation"] = str(uuid4())
    result = service.push(ta, broken)
    assert result["outcome"] == "conflict" and result["head"]["operation"] == source
