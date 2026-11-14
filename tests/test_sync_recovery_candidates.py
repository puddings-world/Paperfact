"""Actual old journals and snapshots; candidate review never replays research."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest
from test_sync_authority_restore_native import publish
from test_sync_client import client, edit
from test_sync_device_recovery import dump
from test_sync_device_recovery import prepared as prepared
from test_sync_files import PAPER
from test_sync_files import codec as codec
from test_sync_files import pair as pair

from paper_daily import sync_authority_backup as backup
from paper_daily import sync_recovery_candidates as candidates


def index(prepared, **options):
    return candidates.prepare(prepared[0].journal.path, prepared[3], "workspace", **options)


def test_caught_up_review_has_no_candidates_and_changes_nothing(prepared):
    device, server, _token, _snapshot = prepared
    before = dump(device.journal.path), dump(server.path)
    value = index(prepared)
    page = value.page()
    assert page["change_count"] == 0 and page["items"] == [] and page["next_offset"] is None
    assert not page["replayed"] and not page["research_and_files_fully_audited"]
    assert before == (dump(device.journal.path), dump(server.path))


def test_unique_pages_merge_own_receipts_and_keep_peer_work_without_payloads(prepared, tmp_path):
    device, server, token, _snapshot = prepared
    edit(device, "Received after backup", identity="received-local")
    device.sync_once(server, token)
    acknowledged = edit(device, "Acknowledged but not received", identity="acknowledged")
    reply = server.push(token, acknowledged)
    device.journal.acknowledge(acknowledged["operation_id"], reply["sequence"])
    edit(device, "Unconfirmed private finding", identity="local-pending")
    peer = client(tmp_path / "peer.sqlite", "b")
    peer_token = server.enroll("workspace", "b")
    remote = edit(peer, "Peer's more recent finding", identity="peer-note")
    server.push(peer_token, remote)
    device.receive(server.pull(token))
    before = dump(device.journal.path), dump(server.path)
    value = index(prepared)
    pages = [value.page(limit=2)]
    pages.append(value.page(after=pages[0]["next_offset"], limit=2))
    items = [item for page in pages for item in page["items"]]
    assert len(items) == len({item["operation_id"] for item in items}) == 4
    assert pages[-1]["next_offset"] is None and pages[0]["change_count"] == 4
    assert all(
        text not in json.dumps(pages)
        for text in [
            "Received after backup",
            "Unconfirmed private finding",
            "Peer's more recent finding",
            str(device.journal.path),
        ]
    )
    assert {item["entity_id"] for item in items} == {
        "received-local",
        "acknowledged",
        "local-pending",
        "peer-note",
    }
    assert len([item for item in items if item["received_sequence"] is not None]) == 3
    chosen = next(item for item in items if item["entity_id"] == "local-pending")
    detail = value.details(chosen["change_id"])
    assert detail["operation"]["payload"]["body"] == "Unconfirmed private finding"
    assert (
        detail["payload_is_private"]
        and not detail["replayed"]
        and not detail["files_verified_for_change"]
    )
    assert value.page(limit=2) == pages[0]
    assert before == (dump(device.journal.path), dump(server.path))
    assert len(device.journal.pending()) == 1


def test_received_conflict_preserves_candidate_and_canonical_head(prepared, tmp_path):
    device, server, token, _snapshot = prepared
    peer = client(tmp_path / "peer.sqlite", "b")
    peer_token = server.enroll("workspace", "b")
    proposed = edit(peer, "A conflicting interpretation")
    assert server.push(peer_token, proposed)["outcome"] == "conflict"
    device.receive(server.pull(token))
    value = index(prepared)
    row = value.page()["items"][0]
    assert row["received_outcome"] == "conflict" and row["stream"] == "received"
    detail = value.details(row["change_id"])
    assert detail["operation"]["payload"]["body"] == "A conflicting interpretation"
    assert detail["received_event"]["head"]["operation"]["payload"]["body"] == "Backed up note"
    assert not detail["replayed"]


def test_lost_ack_already_in_backup_is_not_a_recovery_candidate(prepared, tmp_path):
    device, server, token, _snapshot = prepared
    operation = edit(device, "Send succeeded, acknowledgment lost", identity="lost-ack")
    server.push(token, operation)
    later = tmp_path / "later"
    backup.export(server.path.parent, later)
    value = candidates.prepare(device.journal.path, later, "workspace")
    assert value.page()["items"] == [] and len(device.journal.pending()) == 1


def test_foreign_selection_and_tampered_observation_are_refused(prepared):
    edit(prepared[0], "New private work", identity="pending")
    first, second = index(prepared), index(prepared)
    change = first.page()["items"][0]["change_id"]
    with pytest.raises(ValueError, match="Select a change"):
        second.details(change)
    with pytest.raises(ValueError, match="original prepared"):
        replace(first, _rows_json="[]").page()
    with pytest.raises(ValueError, match="Select a change"):
        first.details("z" * 64)


def test_source_change_invalidates_pages_and_details_without_losing_work(prepared):
    device = prepared[0]
    edit(device, "Initial pending", identity="first")
    value = index(prepared)
    change = value.page()["items"][0]["change_id"]
    edit(device, "Saved during review", identity="second")
    before = dump(device.journal.path)
    for call in (value.page, lambda: value.details(change)):
        with pytest.raises(ValueError, match="inputs changed"):
            call()
    assert dump(device.journal.path) == before and len(device.journal.pending()) == 2


@pytest.mark.parametrize(
    "arguments",
    [{"after": True}, {"after": -1}, {"after": 100}, {"limit": True}, {"limit": 0}, {"limit": 51}],
)
def test_closed_page_bounds(prepared, arguments):
    with pytest.raises(ValueError):
        index(prepared).page(**arguments)


def test_cancellation_and_index_budget_refuse_without_partial_publication(prepared, monkeypatch):
    edit(prepared[0], "Private work", identity="pending")
    before = dump(prepared[0].journal.path)
    with pytest.raises(backup.BackupCancelled):
        index(prepared, cancelled=lambda: True)
    value = index(prepared)
    with pytest.raises(backup.BackupCancelled):
        value.page(cancelled=lambda: True)
    monkeypatch.setattr(candidates, "MAX_INDEX_BYTES", 10)
    with pytest.raises(ValueError, match="index budget"):
        index(prepared)
    assert dump(prepared[0].journal.path) == before


def test_actual_native_app_note_is_reviewed_without_replay_or_legacy_conversion(pair, tmp_path):
    publish(pair, tmp_path)
    device = pair[1]
    operation = device.new_graph_operation(
        "note", str(uuid4()), {"paper_id": PAPER, "body": "Native offline note"}
    )
    device.save(operation)
    before = dump(device.journal.path)
    value = candidates.prepare(device.journal.path, tmp_path / "authority-snapshot", "workspace")
    item = value.page()["items"][0]
    detail = value.details(item["change_id"])
    assert detail["operation"] == operation and detail["operation"]["version"] == 2
    assert detail["operation"]["parents"][0]["kind"] == "paper"
    assert dump(device.journal.path) == before and len(device.journal.pending()) == 1


def test_actual_native_list_membership_and_delete_remain_distinct_candidates(pair, tmp_path):
    from test_sync_files import paper_payload

    from paper_daily.sync_schema_v2 import membership_id

    publish(pair, tmp_path)
    device = pair[1]
    list_id = str(uuid4())
    edits = [
        device.new_graph_operation(
            "paper", PAPER, {**paper_payload(), "title": "A newer paper title"}
        )
    ]
    device.save(edits[0])
    edits.append(
        device.new_graph_operation("list", list_id, {"name": "Recovered reading", "note": None})
    )
    device.save(edits[-1])
    edits.append(
        device.new_graph_operation(
            "membership",
            membership_id(list_id, PAPER),
            dict(
                list_id=list_id, paper_id=PAPER, citation=None, added_at="2026-11-14T00:00:00+00:00"
            ),
        )
    )
    device.save(edits[-1])
    edits.append(device.new_graph_operation("list", list_id, {}, action="delete"))
    device.save(edits[-1])
    before = dump(device.journal.path)
    value = candidates.prepare(device.journal.path, tmp_path / "authority-snapshot", "workspace")
    page = value.page()
    assert page["format"] == candidates.FORMAT
    assert len(page["items"]) == 4 and all(row["protocol_version"] == 2 for row in page["items"])
    assert [value.details(row["change_id"])["operation"] for row in page["items"]] == edits
    assert [(row["entity_type"], row["action"]) for row in page["items"]] == [
        ("paper", "put"),
        ("list", "put"),
        ("membership", "put"),
        ("list", "delete"),
    ]
    assert dump(device.journal.path) == before and len(device.journal.pending()) == 4


def test_backup_identity_change_invalidates_prepared_observation(prepared):
    edit(prepared[0], "A private finding", identity="pending")
    value = index(prepared)
    change = value.page()["items"][0]["change_id"]
    manifest = prepared[3] / backup.MANIFEST
    manifest.write_bytes(manifest.read_bytes() + b" ")
    for call in (value.page, lambda: value.details(change)):
        with pytest.raises(ValueError, match="inputs changed"):
            call()


def test_duplicate_post_backup_received_identity_is_not_counted_twice(prepared, tmp_path):
    import copy
    import sqlite3
    from contextlib import closing

    device, server, token, _snapshot = prepared
    peer = client(tmp_path / "peer.sqlite", "b")
    peer_token = server.enroll("workspace", "b")
    operation = edit(peer, "A peer finding", identity="peer")
    event = server.push(peer_token, operation)
    device.receive(server.pull(token))
    duplicate = copy.deepcopy(event)
    duplicate["sequence"] += 1
    duplicate["head"]["revision"] = duplicate["sequence"]
    with closing(sqlite3.connect(device.journal.path)) as conn, conn:
        conn.execute(
            "INSERT INTO paperfact_sync_inbox VALUES(?,?,?)",
            (duplicate["sequence"], json.dumps(duplicate), duplicate["outcome"]),
        )
        conn.execute("UPDATE paperfact_sync_cursor SET sequence=?", (duplicate["sequence"],))
    before = dump(device.journal.path)
    with pytest.raises(ValueError, match="repeats an operation identity"):
        index(prepared)
    assert dump(device.journal.path) == before
