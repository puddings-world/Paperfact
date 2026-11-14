"""Real fresh-authority join and native client comparisons; no candidate replay."""

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from uuid import uuid4

import pytest
from test_sync_authority_restore_native import publish
from test_sync_device_recovery import dump
from test_sync_files import PAPER
from test_sync_files import codec as codec
from test_sync_files import pair as files_pair
from test_workspace_sync import Native

from paper_daily import sync_bootstrap
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_target as target
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.workspace_service import Ticket
from paper_daily.workspace_sync import SyncSession


@pytest.fixture
def pair(tmp_path, monkeypatch, codec):
    import test_sync_files as files

    from paper_daily import store
    from paper_daily.sync_client import SyncClient
    from paper_daily.sync_journal import Journal
    from paper_daily.sync_research import prepare, research_writer

    def closed_side(root, name):
        path = root / (name + ".sqlite")
        # sqlite3.Connection's transaction context does not close the handle.
        # Finish fixture initialization before taking physical source leases.
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.executescript(store.SCHEMA)
        prepare(path, workspace_id="workspace", device_id=name)
        return SyncClient(Journal(path, workspace_id="workspace", device_id=name), research_writer)

    monkeypatch.setattr(files, "side", closed_side)
    return files_pair.__wrapped__(tmp_path, monkeypatch, codec)


def attached(path):
    with closing(_readonly_connection(path)) as conn:
        return conn._capture_client


@pytest.fixture
def prepared(pair, tmp_path, tmp_path_factory):
    old = pair[1]
    identity = str(uuid4())
    baseline = old.new_graph_operation(
        "note", identity, dict(paper_id=PAPER, body="Backed up note")
    )
    old.save(baseline)
    old.save(old.new_graph_operation("list", "backed-list", {"name": "Backed list", "note": None}))
    service = publish(pair, tmp_path)
    token = service.enroll("fresh-research", "travel")
    session = SyncSession(old.journal.path, transport_factory=lambda url: Native(url, service, []))
    destination = tmp_path_factory.mktemp("fresh-recovery-target") / "workspace"
    session.connect("https://recovery.fixture.invalid", "fresh-research", "travel", token, Ticket())
    try:
        assert sync_bootstrap.join(session, destination, Ticket())["state"] == "metadata_ready"
    finally:
        session.disconnect()
    operation = old.new_graph_operation(
        "note", identity, dict(paper_id=PAPER, body="Old device's unsent revision")
    )
    old.save(operation)
    source = candidates.prepare(old.journal.path, tmp_path / "authority-snapshot", "workspace")
    change = source.page()["items"][0]["change_id"]
    return old, source, change, destination / "papers.db", operation


def test_exact_recovered_target_compares_source_and_current_without_writes(prepared):
    old, source, change, path, operation = prepared
    before = dump(old.journal.path), dump(path)
    observed = target.observe(source, path)
    value = observed.compare(change)
    assert value["state"] == "compared" and not value["blocking_reasons"]
    assert value["source"]["operation"] == operation
    assert value["target"]["accepted_operation"]["payload"]["body"] == "Backed up note"
    assert value["target"]["difference"] == "different_payload"
    assert value["target"]["workspace_id"] == "fresh-research"
    assert (
        not value["replayed"]
        and not value["typed_apply_implemented"]
        and not value["originals_verified"]
    )
    assert before == (dump(old.journal.path), dump(path))
    assert len(old.journal.pending()) == 1 and attached(path).journal.pending() == []


def test_new_target_pending_edits_remain_distinct_and_are_not_overwritten(prepared):
    old, source, change, path, _operation = prepared
    client = attached(path)
    note = source.details(change)["operation"]["entity_id"]
    edit = client.new_graph_operation(
        "note", note, dict(paper_id=PAPER, body="New Mac's later interpretation")
    )
    client.save(edit)
    before = dump(path)
    observed = target.observe(source, path)
    value = observed.compare(change)
    assert value["target"]["effective_operation"] == edit
    assert value["target"]["accepted_operation"]["payload"]["body"] == "Backed up note"
    assert value["target"]["pending_operations"] == [edit]
    assert dump(path) == before and len(old.journal.pending()) == len(client.journal.pending()) == 1


def test_target_parent_deletion_requires_explicit_recovery(prepared):
    from paper_daily.sync_schema_v2 import membership_id

    old, source, _change, path, _operation = prepared
    operation = old.new_graph_operation(
        "membership",
        membership_id("backed-list", PAPER),
        dict(
            list_id="backed-list",
            paper_id=PAPER,
            citation=None,
            added_at="2026-11-14T00:00:00+00:00",
        ),
    )
    old.save(operation)
    source = candidates.prepare(old.journal.path, source.snapshot, source.workspace)
    change = next(
        row["change_id"] for row in source.page()["items"] if row["entity_type"] == "membership"
    )
    client = attached(path)
    client.save(client.new_graph_operation("list", "backed-list", {}, action="delete"))
    value = target.observe(source, path).compare(change)
    assert "target_parent_retired" in value["blocking_reasons"]
    assert not value["typed_apply_implemented"] and not value["replayed"]


@pytest.mark.parametrize("damage", ["prefix", "cursor"])
def test_unrelated_or_incomplete_recovered_history_is_refused(prepared, damage):
    _old, source, _change, path, _operation = prepared
    with closing(sqlite3.connect(path)) as conn, conn:
        if damage == "prefix":
            row = conn.execute("SELECT event FROM paperfact_sync_inbox WHERE sequence=2").fetchone()
            event = json.loads(row[0])
            event["operation"]["payload"]["body"] = "A different authority history"
            event["head"]["operation"] = event["operation"]
            conn.execute(
                "UPDATE paperfact_sync_inbox SET event=? WHERE sequence=2", (json.dumps(event),)
            )
        else:
            conn.execute("DELETE FROM paperfact_sync_inbox WHERE sequence>=2")
            conn.execute("UPDATE paperfact_sync_cursor SET sequence=1")
    before = dump(path)
    with pytest.raises(ValueError, match="prefix|complete recovered backup"):
        target.observe(source, path)
    assert dump(path) == before


def test_old_workspace_and_missing_target_are_refused_without_creation(prepared, tmp_path):
    old, source, _change, _path, _operation = prepared
    with pytest.raises(ValueError, match="separate fresh"):
        target.observe(source, old.journal.path)
    absent = tmp_path / "missing" / "papers.db"
    with pytest.raises((ValueError, FileNotFoundError)):
        target.observe(source, absent)
    assert not absent.parent.exists()


def test_target_change_invalidates_existing_comparison_without_losing_edit(prepared):
    _old, source, change, path, _operation = prepared
    observed = target.observe(source, path)
    client = attached(path)
    client.save(
        client.new_graph_operation(
            "note", str(uuid4()), dict(paper_id=PAPER, body="Saved after preview")
        )
    )
    before = dump(path)
    with pytest.raises(ValueError, match="target changed"):
        observed.compare(change)
    assert dump(path) == before and len(client.journal.pending()) == 1


def test_forged_target_observation_and_budgets_refuse(prepared, monkeypatch):
    _old, source, change, path, _operation = prepared
    observed = target.observe(source, path)
    with pytest.raises(ValueError, match="original prepared"):
        replace(observed, graph_json="[]").compare(change)
    monkeypatch.setattr(target, "MAX_STATE_BYTES", 1)
    with pytest.raises(ValueError, match="state budget"):
        target.observe(source, path)


def test_cancellation_has_no_replay_or_target_mutation(prepared):
    from paper_daily.sync_authority_backup import BackupCancelled

    _old, source, change, path, _operation = prepared
    before = dump(path)
    with pytest.raises(BackupCancelled):
        target.observe(source, path, cancelled=lambda: True)
    observed = target.observe(source, path)
    with pytest.raises(BackupCancelled):
        observed.compare(change, cancelled=lambda: True)
    assert dump(path) == before and attached(path).journal.pending() == []


def test_target_note_deletion_is_explicit_and_not_silently_restored(prepared):
    _old, source, change, path, operation = prepared
    client = attached(path)
    deletion = client.new_graph_operation("note", operation["entity_id"], {}, action="delete")
    client.save(deletion)
    before = dump(path)
    value = target.observe(source, path).compare(change)
    assert value["target"]["difference"] == "retired"
    assert "target_restore_requires_confirmation" in value["blocking_reasons"]
    assert value["target"]["effective_operation"] == deletion
    assert not value["replayed"] and dump(path) == before


def test_invalid_graph_metadata_is_not_used_as_target_authority(prepared):
    _old, source, _change, path, _operation = prepared
    with closing(sqlite3.connect(path)) as conn, conn:
        raw = conn.execute(
            "SELECT metadata FROM paperfact_sync_graph WHERE entity_type='paper'"
        ).fetchone()
        metadata = json.loads(raw[0])
        metadata["active"] = "yes"
        conn.execute(
            "UPDATE paperfact_sync_graph SET metadata=? WHERE entity_type='paper'",
            (json.dumps(metadata),),
        )
    before = dump(path)
    with pytest.raises(ValueError, match="graph metadata is invalid"):
        target.observe(source, path)
    assert dump(path) == before


def test_invalid_head_revision_is_refused_without_repair(prepared):
    _old, source, change, path, operation = prepared
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "UPDATE paperfact_sync_heads SET revision=-1 WHERE entity_type='note' AND entity_id=?",
            (operation["entity_id"],),
        )
    observed = target.observe(source, path)
    before = dump(path)
    with pytest.raises(ValueError, match="head revision is invalid"):
        observed.compare(change)
    assert dump(path) == before


def test_old_source_edit_during_target_preparation_is_retained_and_invalidates_result(
    prepared, monkeypatch
):
    old, source, _change, path, _operation = prepared
    bounded = target._bounded
    saved = []

    def change(*args, **kwargs):
        result = bounded(*args, **kwargs)
        if not saved:
            old.save(
                old.new_graph_operation(
                    "note", str(uuid4()), dict(paper_id=PAPER, body="New old-device finding")
                )
            )
            saved.append(True)
        return result

    monkeypatch.setattr(target, "_bounded", change)
    before = dump(path)
    with pytest.raises(ValueError, match="inputs changed"):
        target.observe(source, path)
    assert saved == [True] and len(old.journal.pending()) == 2 and dump(path) == before


def test_target_edit_after_read_before_delivery_is_retained_and_invalidates_result(
    prepared, monkeypatch
):
    _old, source, _change, path, _operation = prepared
    client = attached(path)
    original = target.candidates.review._version
    calls = []

    def changed(database):
        if database == path:
            calls.append(True)
            if len(calls) == 2:
                client.save(
                    client.new_graph_operation(
                        "note", str(uuid4()), dict(paper_id=PAPER, body="Fresh target finding")
                    )
                )
        return original(database)

    monkeypatch.setattr(target.candidates.review, "_version", changed)
    with pytest.raises(ValueError, match="Target changed during"):
        target.observe(source, path)
    assert len(client.journal.pending()) == 1
