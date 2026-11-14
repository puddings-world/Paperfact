"""Read-only old-device review, actual journals and verified authority backups."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_sync_client import client, edit

from paper_daily import sync_admin
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_device_recovery as recovery


def dump(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        return list(conn.iterdump())


@pytest.fixture
def prepared(tmp_path):
    root = tmp_path / "authority"
    sync_admin.initialize(root)
    server = sync_admin.authority(root)
    token = server.enroll("workspace", "a")
    device = client(tmp_path / "device.sqlite", "a")
    edit(device, "Backed up note")
    device.sync_once(server, token)
    snapshot = tmp_path / "backup"
    backup.export(root, snapshot)
    return device, server, token, snapshot


def review(prepared, **kwargs):
    return recovery.review(prepared[0].journal.path, prepared[3], "workspace", **kwargs)


def test_caught_up_device_review_is_read_only_and_not_a_replay_authority(prepared):
    device, server, _token, snapshot = prepared
    before = dump(device.journal.path), dump(server.path)
    files = {p.relative_to(snapshot): p.read_bytes() for p in snapshot.rglob("*") if p.is_file()}
    result = review(prepared)
    assert result["backup_sequence"] == result["device_cursor"] == 1
    assert result["journal_already_in_backup"] == 1
    assert not result["requires_preservation"] and not result["replayed"]
    assert result["research_and_files_fully_audited"] is False
    assert before == (dump(device.journal.path), dump(server.path))
    assert files == {
        p.relative_to(snapshot): p.read_bytes() for p in snapshot.rglob("*") if p.is_file()
    }
    assert "Backed up note" not in json.dumps(result)
    assert review(prepared) == result


def test_newer_received_acknowledged_and_unconfirmed_work_remains_distinct(prepared):
    device, server, token, _snapshot = prepared
    edit(device, "Received after backup", identity="new-1")
    device.sync_once(server, token)
    acknowledged = edit(device, "Acknowledged after backup", identity="new-2")
    received = server.push(token, acknowledged)
    device.journal.acknowledge(acknowledged["operation_id"], received["sequence"])
    edit(device, "Still local", identity="new-3")
    before = dump(device.journal.path)
    result = review(prepared)
    assert result["received_after_backup"] == 1
    assert result["acknowledged_after_backup"] == 2
    assert result["unconfirmed_not_in_backup"] == 1
    assert result["journal_already_in_backup"] == 1
    assert result["uncovered_journal_domains"] == {"note": 3}
    assert result["requires_preservation"] and result["device_behind_by"] == 0
    assert dump(device.journal.path) == before
    assert len(device.journal.pending()) == 1


def test_lost_ack_already_in_snapshot_is_not_reported_as_missing_work(prepared, tmp_path):
    device, server, token, _snapshot = prepared
    operation = edit(device, "Successful send with lost reply")
    server.push(token, operation)
    fresh = tmp_path / "later-backup"
    backup.export(server.path.parent, fresh)
    before = dump(device.journal.path)
    result = recovery.review(device.journal.path, fresh, "workspace")
    assert result["journal_already_in_backup"] == 2
    assert result["unconfirmed_not_in_backup"] == 0
    assert result["device_behind_by"] == 1
    assert not result["requires_preservation"]
    assert dump(device.journal.path) == before and len(device.journal.pending()) == 1


@pytest.mark.parametrize("damage", ["prefix", "cursor", "hole", "outbox", "ack", "workspace"])
def test_damaged_or_unrelated_journal_fails_closed_without_changing_it(prepared, damage):
    device, _server, _token, snapshot = prepared
    with closing(sqlite3.connect(device.journal.path)) as conn, conn:
        if damage == "prefix":
            row = conn.execute("SELECT event FROM paperfact_sync_inbox").fetchone()
            event = json.loads(row[0])
            event["operation"]["payload"]["body"] = "Different history"
            conn.execute("UPDATE paperfact_sync_inbox SET event=?", (json.dumps(event),))
        elif damage == "cursor":
            conn.execute("UPDATE paperfact_sync_cursor SET sequence=2")
        elif damage == "hole":
            conn.execute("DELETE FROM paperfact_sync_inbox")
        elif damage == "outbox":
            conn.execute("UPDATE paperfact_sync_operations SET fingerprint=?", ("0" * 64,))
        elif damage == "ack":
            conn.execute("UPDATE paperfact_sync_operations SET server_revision=99")
        else:
            conn.execute("UPDATE paperfact_sync_identity SET workspace='different-workspace'")
    before = dump(device.journal.path)
    with pytest.raises(ValueError):
        recovery.review(device.journal.path, snapshot, "workspace")
    assert dump(device.journal.path) == before


def test_cancellation_and_budget_fail_before_review_and_do_not_mutate(prepared):
    before = dump(prepared[0].journal.path)
    with pytest.raises(backup.BackupCancelled):
        review(prepared, cancelled=lambda: True)
    with pytest.raises(ValueError, match="budget"):
        review(prepared, seconds=True)
    assert dump(prepared[0].journal.path) == before


def test_concurrent_device_change_refuses_stale_counts(prepared, monkeypatch):
    device = prepared[0]
    original = recovery._version
    calls = [0]

    def changed(path):
        calls[0] += 1
        if calls[0] == 2:
            edit(device, "Saved while review was pending", identity="concurrent")
        return original(path)

    monkeypatch.setattr(recovery, "_version", changed)
    with pytest.raises(ValueError, match="changed during review"):
        review(prepared)
    assert len(device.journal.pending()) == 1


def test_record_budget_is_explicit_and_does_not_silently_truncate(prepared, monkeypatch):
    edit(prepared[0], "Another pending note", identity="extra")
    monkeypatch.setattr(recovery, "MAX_RECORDS", 1)
    with pytest.raises(ValueError, match="budget"):
        review(prepared)


def test_cli_returns_safe_counts_and_bounded_error(prepared, capsys):
    args = [
        "review-device-backup",
        "--database",
        str(prepared[0].journal.path),
        "--input",
        str(prepared[3]),
        "--workspace",
        "workspace",
    ]
    assert sync_admin.main(args) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "reviewed"
    args[-1] = "wrong-workspace"
    assert sync_admin.main(args) == 2
    captured = capsys.readouterr()
    assert not captured.out and "Existing files were not overwritten" in captured.err


@pytest.mark.parametrize("action", ["review", "candidates"])
def test_first_read_of_wal_database_keeps_research_and_a_stable_source_lease(prepared, action):
    from paper_daily import sync_recovery_candidates

    device, _server, _token, snapshot = prepared
    path = device.journal.path
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        baseline = list(conn.iterdump())
    # The last writer closed: this is a real WAL header with no existing sidecar.
    wal = path.with_name(path.name + "-wal")
    assert not wal.exists()
    if action == "review":
        result = recovery.review(path, snapshot, "workspace")
        assert result["journal_already_in_backup"] == 1
    else:
        observed = sync_recovery_candidates.prepare(path, snapshot, "workspace")
        assert observed.page()["items"] == []
        observed._check(lambda: None)
    assert dump(path) == baseline
    # Do not normalize away genuine writes after observation.
    before = recovery._version(path)
    edit(device, "A real later research change")
    assert recovery._version(path) != before
    if action == "candidates":
        with pytest.raises(ValueError, match="Recovery inputs changed"):
            observed.page()
