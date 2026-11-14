"""New-workspace recovery keeps science and refuses stale authority credentials."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Event

import pytest
from test_sync_authority_backup import dump
from test_sync_authority_backup import state as state
from test_sync_blob_service import document, paper
from test_sync_ordering_service import change_set, metadata, order
from test_sync_ordering_service import ready as ready
from test_sync_service import operation
from test_workspace_sync import Native
from test_workspace_sync import enrolled as enrolled
from test_workspace_sync import research as research

from paper_daily import sync_admin
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_authority_restore as recovery
from paper_daily.connection_vault import Connection


@pytest.fixture
def snapshot(state, tmp_path):
    root, service, token, manifest, data = state
    output = tmp_path / "snapshot"
    backup.export(root, output)
    before = dump(service.path)
    return output, root, service, token, manifest, data, before


def saved_files(path):
    return {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def test_exact_science_conflict_and_bytes_recover_with_no_old_session(snapshot, tmp_path):
    source, root, previous, old_token, manifest, data, original = snapshot
    before = saved_files(source)
    target = tmp_path / "recovered"
    result = recovery.restore(source, target, "workspace-a", "recovered-workspace")
    assert result == {
        "state": "restored",
        "workspace_id": "recovered-workspace",
        "events": 3,
        "objects": 1,
        "bytes": len(data),
        "unfinished_uploads_discarded": 1,
        "previous_devices_discarded": 2,
        "requires_enrollment": True,
    }
    service = sync_admin.authority(target)
    with service._transaction() as conn:
        assert conn.execute("SELECT count(*) FROM sync_devices").fetchone()[0] == 0
        assert (
            conn.execute("SELECT count(*) FROM sync_blob_uploads WHERE state='open'").fetchone()[0]
            == 0
        )
    with pytest.raises(PermissionError):
        service.session_info(old_token)
    record = tmp_path / "new-connection.json"
    sync_admin.issue(target, "https://sync.example.org", "recovered-workspace", "new-mac", record)
    token = Connection.decoded(record.read_text()).token
    expected = [
        recovery._event(json.dumps(item), "recovered-workspace")
        for item in previous.pull(old_token)
    ]
    assert service.pull(token) == expected
    assert service.blob_read(token, manifest["sha256"], manifest["size"], 0) == data
    assert previous.pull(old_token)[2]["outcome"] == service.pull(token)[2]["outcome"] == "conflict"
    assert dump(previous.path) == original and saved_files(source) == before
    # The newly reconstructed server remains usable, without changing the old server.
    next_edit = operation(
        "after-recovery", workspace="recovered-workspace", device="new-mac", base=2
    )
    assert service.push(token, next_edit)["sequence"] == 4
    assert len(previous.pull(old_token)) == 3
    assert (
        json.loads((target / "recovery.json").read_text())["source_workspace_id"] == "workspace-a"
    )
    assert not (target / "blobs").samefile(root / "blobs")


def test_old_token_binding_and_ahead_cursor_cannot_silently_resume(snapshot, tmp_path):
    source, _, previous, token, _, _, _ = snapshot
    previous.push(token, operation("not-in-backup", base=2))
    target = tmp_path / "recovered"
    recovery.restore(source, target, "workspace-a", "fresh-workspace")
    service = sync_admin.authority(target)
    with pytest.raises(PermissionError):
        service.pull(token, after=4)
    new = service.enroll("fresh-workspace", "new-mac")
    with pytest.raises(ValueError, match="ahead"):
        service.pull(new, after=4)
    with pytest.raises(PermissionError):
        service.push(new, operation("old-outbox", device="new-mac"))
    assert len(service.pull(new)) == 3


@pytest.mark.parametrize(
    "old,new",
    [("workspace-a", "workspace-a"), ("absent", "fresh"), ("workspace-a", "bad identity")],
)
def test_invalid_mapping_never_creates_recovery_state(snapshot, tmp_path, old, new):
    source = snapshot[0]
    target = tmp_path / "refused"
    with pytest.raises(ValueError):
        recovery.restore(source, target, old, new)
    assert not target.exists()


def test_multiple_workspaces_select_one_without_cross_workspace_bytes(state, tmp_path):
    (
        root,
        service,
        _,
        _,
        _,
    ) = state
    token = service.enroll("unselected", "other-device")
    service.push(token, operation("private-other", workspace="unselected", device="other-device"))
    data = b"unselected private original"
    import hashlib

    manifest = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    session = service.blob_begin(token, manifest)
    service.blob_append(token, session["upload_id"], 0, data)
    service.blob_commit(token, session["upload_id"])
    source = tmp_path / "snapshot"
    backup.export(root, source)
    with pytest.raises(ValueError, match="fresh"):
        recovery.restore(source, tmp_path / "collision", "workspace-a", "unselected")
    target = tmp_path / "selected-only"
    recovery.restore(source, target, "workspace-a", "fresh")
    restored = sync_admin.authority(target)
    current = restored.enroll("fresh", "new-device")
    with pytest.raises(PermissionError):
        restored.blob_read(current, manifest["sha256"], manifest["size"], 0)
    assert len(restored.pull(current)) == 3
    assert b"private-other" not in (target / "authority.sqlite").read_bytes()


def test_typed_paper_document_graph_and_hash_proofs_are_rebuilt(state, tmp_path):
    root, service, _, manifest, data = state
    token = service.enroll("workspace", "a")
    paper(service, token)
    session = service.blob_begin(token, manifest)
    service.blob_append(token, session["upload_id"], 0, data)
    service.blob_commit(token, session["upload_id"])
    service.push(token, document(manifest))
    source = tmp_path / "snapshot"
    backup.export(root, source)
    target = tmp_path / "recovered-graph"
    recovery.restore(source, target, "workspace", "fresh")
    restored = sync_admin.authority(target)
    current = restored.enroll("fresh", "new-device")
    expected = [recovery._event(json.dumps(item), "fresh") for item in service.pull(token)]
    assert restored.pull(current) == expected
    assert restored.blob_read(current, manifest["sha256"], manifest["size"], 0) == data
    with restored._transaction() as conn:
        assert conn.execute("SELECT count(*) FROM sync_graph").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM sync_blob_integrity").fetchone()[0] == 1


def test_cancel_after_partial_replay_has_no_live_marker_and_retry_is_fresh(snapshot, tmp_path):
    source = snapshot[0]
    target = tmp_path / "cancelled"
    original = saved_files(source)
    cancelled = Event()

    def progress(value):
        if value["phase"] == "events" and value["events"] == 1:
            cancelled.set()

    with pytest.raises(backup.BackupCancelled):
        recovery.restore(
            source, target, "workspace-a", "fresh", cancelled=cancelled.is_set, progress=progress
        )
    assert not (target / sync_admin.MARKER).exists()
    with pytest.raises(ValueError):
        sync_admin.authority(target)
    assert saved_files(source) == original
    with pytest.raises(FileExistsError):
        recovery.restore(source, target, "workspace-a", "fresh")
    assert recovery.restore(source, tmp_path / "retry", "workspace-a", "fresh")["events"] == 3


def test_replay_disagreement_does_not_publish_or_weaken_conflict(snapshot, tmp_path, monkeypatch):
    source = snapshot[0]
    target = tmp_path / "disagrees"
    original = recovery.ReferenceService.push

    def different(self, token, operation):
        result = original(self, token, operation)
        if result["outcome"] == "conflict":
            return {**result, "outcome": "accepted"}
        return result

    monkeypatch.setattr(recovery.ReferenceService, "push", different)
    with pytest.raises(ValueError, match="conflicting"):
        recovery.restore(source, target, "workspace-a", "fresh")
    assert not (target / sync_admin.MARKER).exists()


def test_corrupt_backup_and_unknown_schema_are_refused_before_target_creation(snapshot, tmp_path):
    source = snapshot[0]
    database = source / "authority.sqlite"
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("CREATE TABLE unsupported_new_domain(body TEXT)")
        conn.commit()
    with pytest.raises(ValueError):
        recovery.restore(source, tmp_path / "bad-hash", "workspace-a", "fresh")
    import hashlib

    path = source / backup.MANIFEST
    value = json.loads(path.read_text())
    item = next(row for row in value["files"] if row["path"] == "authority.sqlite")
    item.update(
        size=database.stat().st_size, sha256=hashlib.sha256(database.read_bytes()).hexdigest()
    )
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="schema"):
        recovery.restore(source, tmp_path / "new-schema", "workspace-a", "fresh")
    assert not (tmp_path / "bad-hash").exists() and not (tmp_path / "new-schema").exists()


def test_final_marker_failure_leaves_closed_state_and_source_unchanged(
    snapshot, tmp_path, monkeypatch
):
    source = snapshot[0]
    target = tmp_path / "failed-marker"
    before = saved_files(source)
    write = backup._write

    def fail(path, callback):
        if path.name == ".service.pending":
            raise OSError("Synthetic publication failure")
        return write(path, callback)

    monkeypatch.setattr(backup, "_write", fail)
    with pytest.raises(OSError):
        recovery.restore(source, target, "workspace-a", "fresh")
    assert not (target / sync_admin.MARKER).exists() and saved_files(source) == before
    with closing(sqlite3.connect(target / "authority.sqlite")) as conn:
        assert conn.execute("SELECT count(*) FROM sync_devices").fetchone()[0] == 0
    # No database connection/file handle is left pinning the failed directory.
    target.rename(tmp_path / "retained-incomplete")


def test_concurrent_repeated_recovery_cannot_overwrite_one_output(snapshot, tmp_path):
    source = snapshot[0]
    target = tmp_path / "one-result"

    def attempt():
        try:
            return recovery.restore(source, target, "workspace-a", "fresh")["state"]
        except FileExistsError:
            return "reserved"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == ["reserved", "restored"]
    with sync_admin.authority(target)._transaction() as conn:
        assert conn.execute("SELECT count(*) FROM sync_events").fetchone()[0] == 3


def test_snapshot_change_during_replay_cannot_publish(snapshot, tmp_path):
    source = snapshot[0]
    target = tmp_path / "changed-backup"

    def change(value):
        if value["phase"] == "events":
            path = source / backup.MANIFEST
            path.write_bytes(path.read_bytes() + b" ")

    with pytest.raises(ValueError, match="changed"):
        recovery.restore(source, target, "workspace-a", "fresh", progress=change)
    assert not (target / sync_admin.MARKER).exists()


def test_existing_output_and_scope_are_never_overwritten(snapshot, tmp_path):
    source = snapshot[0]
    existing = tmp_path / "owner-data"
    existing.mkdir()
    keep = existing / "keep"
    keep.write_bytes(b"unchanged")
    with pytest.raises(FileExistsError):
        recovery.restore(source, existing, "workspace-a", "fresh")
    assert keep.read_bytes() == b"unchanged"
    for target in (source, source / "inside", source.parent):
        with pytest.raises(ValueError):
            recovery.restore(source, target, "workspace-a", "fresh")


def test_cli_requires_mapping_and_returns_no_credentials(snapshot, tmp_path, capsys):
    source, _, _, old_token, _, _, _ = snapshot
    target = tmp_path / "cli-recovered"
    args = [
        "restore-backup",
        "--input",
        str(source),
        "--state",
        str(target),
        "--workspace",
        "workspace-a",
        "--as-workspace",
        "fresh",
    ]
    assert sync_admin.main(args) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["requires_enrollment"] is True
    assert old_token not in output.out + output.err
    assert sync_admin.main(args) == 2
    assert "Traceback" not in capsys.readouterr().err
    with pytest.raises(SystemExit) as result:
        sync_admin.main(["restore-backup", "--help"])
    assert result.value.code == 0


def test_desktop_old_outbox_is_not_rebound_to_recovered_identity(snapshot, enrolled, tmp_path):
    from paper_daily.workspace_service import Ticket
    from paper_daily.workspace_sync import EnrollmentRequired, SyncSession

    source = snapshot[0]
    target = tmp_path / "desktop-recovery"
    recovery.restore(source, target, "workspace-a", "fresh")
    restored = sync_admin.authority(target)
    token = restored.enroll("fresh", "origin-device")
    local, client, _result, _paper = enrolled
    before = dump(local)
    pending = client.journal.pending()
    calls = []
    session = SyncSession(local, transport_factory=lambda url: Native(url, restored, calls))
    endpoint = "https://recovery.fixture.invalid"
    with pytest.raises(PermissionError):
        session.connect(endpoint, "workspace", "origin-device", token, Ticket())
    session.connect(endpoint, "fresh", "origin-device", token, Ticket())
    try:
        with pytest.raises(EnrollmentRequired, match="new directory"):
            session.sync(Ticket())
    finally:
        session.disconnect()
    assert dump(local) == before and client.journal.pending() == pending
    assert not {"push", "pull", "blob_begin", "blob_append"}.intersection(calls)


def test_empty_workspace_and_budget_failure_do_not_resurrect_devices(tmp_path, monkeypatch):
    root = tmp_path / "empty-service"
    sync_admin.initialize(root)
    old_token = sync_admin.authority(root).enroll("empty-workspace", "old-device")
    source = tmp_path / "empty-snapshot"
    backup.export(root, source)
    target = tmp_path / "empty-recovery"
    result = recovery.restore(source, target, "empty-workspace", "fresh")
    assert result["events"] == result["objects"] == 0 and result["requires_enrollment"]
    with pytest.raises(PermissionError):
        sync_admin.authority(target).session_info(old_token)
    now = [0]
    monkeypatch.setattr(backup.time, "monotonic", lambda: now[0])

    def expire(value):
        if value["phase"] == "verify":
            now[0] = 2

    output = tmp_path / "timed-out"
    with pytest.raises(backup.BackupCancelled):
        recovery.restore(source, output, "empty-workspace", "fresh", seconds=1, progress=expire)
    assert not output.exists()


def test_database_change_between_verification_and_restore_is_not_retrusted(
    snapshot, tmp_path, monkeypatch
):
    source = snapshot[0]
    target = tmp_path / "verification-race"
    inspect = backup._inspect

    def changed(*args, **kwargs):
        proof = inspect(*args, **kwargs)
        with closing(sqlite3.connect(source / "authority.sqlite")) as conn:
            conn.execute("DELETE FROM sync_events")
            conn.commit()
        return proof

    monkeypatch.setattr(backup, "_inspect", changed)
    with pytest.raises(ValueError, match="after verification"):
        recovery.restore(source, target, "workspace-a", "fresh")
    assert not target.exists()


@pytest.mark.parametrize("kind", ["list_order", "workspace_list_order"])
def test_new_workspace_rekeys_order_scope_without_accepting_stale_membership(ready, tmp_path, kind):
    original, old_token, _peer_token = ready
    root = tmp_path / "ordering-service"
    sync_admin.initialize(root)
    service = sync_admin.authority(root)
    token = service.enroll("workspace", "a")
    for event in original.pull(old_token):
        assert service.push(token, event["operation"]) == event
    first = service.push(token, order(service, kind=kind))
    assert first["outcome"] == "accepted"
    identity = first["operation"]["entity_id"]
    arguments = dict(
        kind=kind,
        base=first["sequence"],
        incarnation=first["operation"]["incarnation"],
        structure=metadata(service, kind, identity)["structure_revision"],
    )
    stale = order(service, "stale-set", **arguments)
    change_set(service, token, kind, "add")
    assert service.push(token, stale)["outcome"] == "conflict"
    opaque = order(service, "opaque-set", **arguments)
    opaque["payload"]["observed_set"] = "0" * 64
    assert service.push(token, opaque)["outcome"] == "conflict"
    source, target = tmp_path / "snapshot", tmp_path / "recovered-order"
    backup.export(root, source)
    recovery.restore(source, target, "workspace", "fresh")
    recovered = sync_admin.authority(target)
    current = recovered.enroll("fresh", "new-device")
    expected = [recovery._event(json.dumps(event), "fresh") for event in service.pull(token)]
    assert recovered.pull(current) == expected
    original_digest = first["operation"]["payload"]["observed_set"]
    rekeyed = next(
        event
        for event in expected
        if event["operation"]["operation_id"] == first["operation"]["operation_id"]
    )
    assert rekeyed["operation"]["payload"]["observed_set"] != original_digest
    assert [event["outcome"] for event in expected][-2:] == ["conflict", "conflict"]


@pytest.mark.parametrize("legacy", [False, True])
def test_recovery_accepts_pre_pairing_backups_and_never_carries_device_grants(
    state, tmp_path, legacy
):
    import secrets

    root, old, owner, _manifest, _data = state
    code = secrets.token_urlsafe(32)
    if legacy:
        with old._transaction(write=True) as conn:
            conn.execute("DROP TABLE sync_pairings")
    else:
        old.create_pairing(owner, code)
    original = dump(old.path)
    source, destination = tmp_path / "pair-backup", tmp_path / "pair-recovered"
    backup.export(root, source)
    recovery.restore(source, destination, "workspace-a", "new-workspace")
    restored = sync_admin.authority(destination)
    with restored._transaction() as conn:
        assert conn.execute("SELECT count(*) FROM sync_pairings").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM sync_devices").fetchone()[0] == 0
    with pytest.raises(PermissionError):
        restored.redeem_pairing(code, "new-workspace", "mac", secrets.token_urlsafe(32))
    assert dump(old.path) == original
