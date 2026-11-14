"""Capacity bounds survive real competing reports without blocking receive cursors."""

import copy
from uuid import uuid4

import pytest
from test_lineage_jobs import work
from test_lineage_live_conflicts import edit
from test_lineage_live_journey import setup_publication, sync_all
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import rows

from paper_daily import lineage_dependencies, lineage_observation, lineage_sets, research_lineage
from paper_daily.sync_content import content_id


def new_report(client, source):
    # A distinct explicit saved corpus, using actual synchronized original pins.
    template = copy.deepcopy(source)
    payload = template["payload"]
    key = str(uuid4())
    payload["key"] = payload["data"]["body_json"]["corpus_id"] = key
    payload["data"]["source_hash"] = lineage_sets.source_hash(payload["data"]["body_json"])
    template["content_address"]["key"] = key
    template["entity_id"] = content_id(payload["scope"], "lineage", key)
    lineage_dependencies.canonical_operation(template)
    with client.journal.transaction() as conn:
        operation = client._new_graph_operation(
            conn, "research_content", template["entity_id"], payload, lineage_template=template
        )

        def write(c, op):
            client._guard_content_parent(c, op)
            client.writer(c, op)

        client.journal.apply_in(conn, operation, write)
    return operation


def test_local_capacity_rejects_new_corpus_without_changing_saved_reports_or_outbox(
    selected, monkeypatch
):
    monkeypatch.setattr(lineage_sets, "MAX_SETS", 1)
    client, _result, _receipt, source, _sources = setup_publication(selected, monkeypatch)
    before_rows, before_pending = rows(client, lineage_sets.TABLE), client.journal.pending()
    with pytest.raises(ValueError, match="Lineage.*capacity"):
        new_report(client, source)
    assert rows(client, lineage_sets.TABLE) == before_rows
    assert client.journal.pending() == before_pending
    with pytest.raises(research_lineage.LineageError, match="lineage_set_limit"):
        work(lineage_observation.observe, selected[1], str(uuid4()), str(uuid4()))
    # Full capacity must still allow editing the existing corpus and exact reads.
    changed = edit(client, source, "2026-11-15T01:00:00+00:00")
    assert changed["entity_id"] == source["entity_id"]
    assert len(lineage_sets.saved(client.journal.path, before_rows[0]["paper_id"])) == 1


def test_competing_device_creates_preserve_conflict_and_receive_progress_then_free_capacity(
    selected, monkeypatch
):
    monkeypatch.setattr(lineage_sets, "MAX_SETS", 2)
    client, _result, _receipt, source, sources = setup_publication(selected, monkeypatch)
    peer = sync_all(selected, client, sources)
    service, _a, _b, files, _peer_files, token, peer_token = selected[0]
    first = new_report(client, source)
    second = new_report(peer, source)
    assert len(rows(client, lineage_sets.TABLE)) == len(rows(peer, lineage_sets.TABLE)) == 2
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    peer.sync_once(service, peer_token)
    event = next(
        e for e in peer.history() if e["operation"]["operation_id"] == second["operation_id"]
    )
    assert event["outcome"] == "conflict" and event["head"]["operation"] is None
    assert peer.status()["cursor"] == service.pull(peer_token)[-1]["sequence"]
    # An accepted competing report can briefly wait behind our rejected optimistic
    # row; an empty next page must retry it without losing or resetting the cursor.
    peer.sync_once(service, peer_token)
    assert {r["corpus_key"] for r in rows(peer, lineage_sets.TABLE)} == {
        source["payload"]["key"],
        first["payload"]["key"],
    }
    assert len(rows(client, lineage_sets.TABLE)) == 2
    retired = client.new_graph_operation(
        "research_content", first["entity_id"], {}, action="delete"
    )
    client.save(retired)
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    peer.sync_once(service, peer_token)
    resolved = peer.resolve_conflict(event["sequence"], choice="incoming")
    peer.sync_once(service, peer_token)
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    assert resolved["applied"]
    expected = {source["payload"]["key"], second["payload"]["key"]}
    assert {r["corpus_key"] for r in rows(client, lineage_sets.TABLE)} == expected
    assert {r["corpus_key"] for r in rows(peer, lineage_sets.TABLE)} == expected
    assert client.status()["conflicts"] == peer.status()["conflicts"] == 0


def test_authority_allows_existing_corpus_edit_at_capacity(selected, monkeypatch):
    monkeypatch.setattr(lineage_sets, "MAX_SETS", 1)
    client, _result, _receipt, source, sources = setup_publication(selected, monkeypatch)
    peer = sync_all(selected, client, sources)
    service, _a, _b, files, _peer_files, token, peer_token = selected[0]
    operation = edit(client, source, "2026-11-15T01:00:00+00:00")
    client.sync_once(service, token, prepare_push=files.ready_to_push)
    peer.sync_once(service, peer_token)
    event = next(e for e in peer.history() if e["operation"] == operation)
    assert event["outcome"] == "accepted"
    assert rows(peer, lineage_sets.TABLE)[0]["written_at"] == "2026-11-15T01:00:00+00:00"
    assert len(rows(client, lineage_sets.TABLE)) == len(rows(peer, lineage_sets.TABLE)) == 1
