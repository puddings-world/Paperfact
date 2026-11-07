"""Offline generation must distinguish identical parent IDs after replacement."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_research_generation import context, output, rows
from test_research_generation import workspace as _workspace

from paper_daily import research_generation as generation
from paper_daily import store

workspace = _workspace


@pytest.mark.parametrize("replace", [False, True], ids=["delete-recreate", "replace"])
def test_recreated_identical_parent_retains_result_without_changing_research(workspace, replace):
    path, client, _ = workspace
    observed = context(path, "target")
    with store.connect() as conn:
        original = dict(conn.execute("SELECT * FROM papers WHERE id='paper'").fetchone())
        if not replace:
            conn.execute("DELETE FROM papers WHERE id='paper'")
        columns = ",".join(original)
        marks = ",".join("?" for _ in original)
        conn.execute(
            f"INSERT OR REPLACE INTO papers({columns}) VALUES({marks})", tuple(original.values())
        )
    pending = len(client.journal.pending()) if client else 0
    result = generation.publish_generation(observed, row=output("Completed old-parent result"))
    assert result.status == "candidate"
    assert "owner" in result.reason.lower()
    assert rows(path, "SELECT * FROM close_readings") == []
    receipt = rows(path, "SELECT * FROM research_generation_requests")[0]
    assert json.loads(receipt["row_json"])["body"] == "Completed old-parent result"
    if client:
        assert len(client.journal.pending()) == pending


def test_metadata_change_preserves_epoch_and_target_only_edit(workspace):
    path, _, _ = workspace
    observed = context(path, "target")
    token = observed.data["parent_lifecycle"]
    assert len(token) == 32
    with store.connect() as conn:
        conn.execute("UPDATE papers SET title='Renamed paper' WHERE id='paper'")
    assert context(path, "target").data["parent_lifecycle"] == token
    assert (
        generation.publish_generation(observed, row=output("Manual content")).status == "accepted"
    )


def test_observing_inside_transaction_does_not_commit_callers_writes(workspace):
    path, _, _ = workspace
    from paper_daily.research_lifecycle import TABLE, TRIGGERS

    # This scenario starts before lifecycle installation. Enrollment now installs
    # epochs eagerly, so explicitly reconstruct the legacy fixture rather than
    # accidentally observing an already-committed epoch.
    with closing(sqlite3.connect(path)) as conn, conn:
        for trigger in TRIGGERS:
            conn.execute(f'DROP TRIGGER IF EXISTS "{trigger}"')
        conn.execute(f'DROP TABLE IF EXISTS "{TABLE}"')
    with closing(generation._connect(path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE papers SET title='Uncommitted' WHERE id='paper'")
        observed = generation.begin_generation(
            conn, table="close_readings", owner_id="paper", input_reader="target"
        )
        assert conn.in_transaction
        conn.rollback()
    assert rows(path, "SELECT title FROM papers") == [{"title": "Paper"}]
    # An epoch initialized in a rolled-back transaction cannot authorize output.
    assert generation.publish_generation(observed, row=output()).status == "candidate"


def test_legacy_context_is_readable_but_cannot_auto_publish_without_lifecycle(workspace):
    path, _, _ = workspace
    data = context(path, "target").data
    data.pop("parent_lifecycle", None)
    legacy = generation.GenerationContext(generation._context_json(data))
    result = generation.publish_generation(legacy, row=output("Legacy completed output"))
    assert result.status == "candidate"
    receipt = rows(path, "SELECT * FROM research_generation_requests")[0]
    assert generation.validate_request_record(receipt) == receipt
    assert rows(path, "SELECT * FROM close_readings") == []


@pytest.mark.parametrize("invalid", [None, "", "xyz", "F" * 32, 123])
def test_invalid_epoch_is_not_accepted_as_valid_recovery_provenance(workspace, invalid):
    path, _, _ = workspace
    observed = context(path, "target")
    assert generation.publish_generation(observed, row=output()).status == "accepted"
    receipt = rows(path, "SELECT * FROM research_generation_requests")[0]
    data = json.loads(receipt["context_json"])
    data["parent_lifecycle"] = invalid
    receipt["context_json"] = json.dumps(data)
    with pytest.raises(ValueError, match="lifecycle"):
        generation.validate_request_record(receipt)


def test_recreated_list_does_not_receive_old_survey(workspace):
    path, client, _ = workspace
    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES('list','Research','same')")
    with closing(generation._connect(path)) as conn:
        observed = generation.begin_generation(
            conn, table="list_surveys", owner_id="list", input_reader="target"
        )
    with store.connect() as conn:
        conn.execute("DELETE FROM lists WHERE id='list'")
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES('list','Research','same')")
    pending = len(client.journal.pending()) if client else 0
    result = generation.publish_generation(
        observed,
        row={
            "list_id": "list",
            "body": "Completed old survey",
            "papers": 0,
            "spec": "fixture-v1",
            "written_at": "2026-10-26T00:00:00+00:00",
            "edited": 0,
        },
    )
    assert result.status == "candidate"
    assert rows(path, "SELECT * FROM list_surveys") == []
    if client:
        assert len(client.journal.pending()) == pending
