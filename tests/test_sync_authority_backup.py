"""Actual authority transactions and exact private bytes; no cloud or owner data."""

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Event

import pytest
from test_sync_blob_service import document, paper
from test_sync_service import operation

from paper_daily import sync_admin
from paper_daily import sync_authority_backup as backup


def dump(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        return list(conn.iterdump())


@pytest.fixture
def state(tmp_path):
    root = tmp_path / "authority"
    sync_admin.initialize(root)
    service = sync_admin.authority(root)
    token = service.enroll("workspace-a", "device-a")
    other = service.enroll("workspace-a", "device-b")
    service.push(token, operation())
    service.push(token, operation("later", base=1, body="Accepted researcher edit"))
    service.push(other, operation("conflict", device="device-b", base=1, body="Retained rival"))
    data = b"%PDF-1.4 exact committed original fixture"
    manifest = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    session = service.blob_begin(token, manifest)
    service.blob_append(token, session["upload_id"], 0, data)
    service.blob_commit(token, session["upload_id"])
    partial = b"unfinished-private-upload"
    declared = {"sha256": hashlib.sha256(partial).hexdigest(), "size": len(partial)}
    session = service.blob_begin(token, declared)
    service.blob_append(token, session["upload_id"], 0, partial[:5])
    return root, service, token, manifest, data


def test_snapshot_keeps_events_conflicts_owned_bytes_and_no_partial_uploads(state, tmp_path):
    root, service, token, manifest, data = state
    before = dump(service.path)
    output = tmp_path / "backup"
    assert backup.export(root, output)["state"] == "backed_up"
    receipt = backup.verify(output)
    assert receipt["state"] == "verified" and receipt["live_restore"] is False
    assert receipt["files"] == 2
    assert dump(output / "authority.sqlite") == before == dump(service.path)
    value = json.loads((output / backup.MANIFEST).read_text())
    objects = [item for item in value["files"] if item["path"].startswith("blobs/")]
    assert objects[0]["sha256"] == manifest["sha256"]
    assert (output / objects[0]["path"]).read_bytes() == data
    assert not list(output.rglob("partial")) and not (output / sync_admin.MARKER).exists()
    with closing(sqlite3.connect(output / "authority.sqlite")) as conn:
        assert conn.execute("SELECT count(*) FROM sync_events").fetchone()[0] == 3
        assert (
            conn.execute("SELECT event FROM sync_events WHERE sequence=3")
            .fetchone()[0]
            .find('"outcome":"conflict"')
            >= 0
        )
    assert service.session_info(token)["device_id"] == "device-a"
    # This is an inspectable operator backup, never an initialized live authority.
    with pytest.raises((ValueError, OSError)):
        sync_admin.authority(output)


def test_sqlite_backup_includes_uncheckpointed_wal(state, tmp_path):
    root, service, token, _, _ = state
    with closing(sqlite3.connect(service.path)) as keeper:
        assert keeper.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        keeper.execute("BEGIN")
        keeper.execute("SELECT count(*) FROM sync_events").fetchone()
        service.push(token, operation("wal-edit", base=2, body="Committed in WAL"))
        assert service.path.with_name(service.path.name + "-wal").stat().st_size > 0
        expected = dump(service.path)
        output = tmp_path / "wal-backup"
        backup.export(root, output)
        assert dump(output / "authority.sqlite") == expected
        assert backup.verify(output)["state"] == "verified"


@pytest.mark.parametrize("kind", ["missing", "damaged", "missing-namespace"])
def test_bad_committed_storage_never_publishes_complete_manifest(state, tmp_path, kind):
    root, service, _, manifest, _ = state
    path = next((root / "blobs").glob(f"*/objects/{manifest['sha256']}"))
    if kind == "missing":
        path.unlink()
    elif kind == "damaged":
        path.write_bytes(b"wrong committed bytes")
    else:
        with service._transaction(write=True) as conn:
            conn.execute("DELETE FROM sync_blob_namespaces")
    before = dump(service.path)
    output = tmp_path / kind
    with pytest.raises((ValueError, OSError)):
        backup.export(root, output)
    assert not (output / backup.MANIFEST).exists()
    assert dump(service.path) == before
    with pytest.raises((ValueError, OSError)):
        backup.verify(output)


def test_cancel_mid_copy_keeps_source_and_releases_lock_for_retry(state, tmp_path, monkeypatch):
    root, service, _, _, _ = state
    output = tmp_path / "cancelled"
    before, cancelled = dump(service.path), Event()
    original = backup._hash

    def cancel(path, check, target=None):
        if target is not None:
            cancelled.set()
        return original(path, check, target)

    with monkeypatch.context() as patch:
        patch.setattr(backup, "_hash", cancel)
        with pytest.raises(backup.BackupCancelled):
            backup.export(root, output, cancelled=cancelled.is_set)
    assert dump(service.path) == before
    assert not (output / backup.MANIFEST).exists()
    service.enroll("workspace-a", "after-cancel")
    assert backup.export(root, tmp_path / "retry")["state"] == "backed_up"


def test_manifest_fsync_failure_is_not_completion_and_never_overwrites(
    state, tmp_path, monkeypatch
):
    root, service, _, _, _ = state
    output = tmp_path / "failed"
    before = dump(service.path)
    write = backup._write

    def fail(path, callback):
        if path.name == ".manifest.pending":
            path.write_bytes(b"partially written manifest")
            raise OSError("Synthetic full disk")
        return write(path, callback)

    with monkeypatch.context() as patch:
        patch.setattr(backup, "_write", fail)
        with pytest.raises(OSError):
            backup.export(root, output)
    assert not (output / backup.MANIFEST).exists()
    assert dump(service.path) == before
    with pytest.raises(FileExistsError):
        backup.export(root, output)
    assert (output / ".manifest.pending").read_bytes() == b"partially written manifest"
    backup.export(root, tmp_path / "retry")


def test_snapshot_reservation_excludes_concurrent_writer_until_capture_completes(
    state, tmp_path, monkeypatch
):
    root, service, _, _, _ = state
    entered, release = Event(), Event()
    original = backup._hash

    def held(path, check, target=None):
        if target is not None:
            entered.set()
            assert release.wait(10)
        return original(path, check, target)

    monkeypatch.setattr(backup, "_hash", held)
    with ThreadPoolExecutor(max_workers=2) as pool:
        export = pool.submit(backup.export, root, tmp_path / "capture")
        try:
            assert entered.wait(10)
            with (
                closing(sqlite3.connect(service.path, timeout=0)) as competing,
                pytest.raises(sqlite3.OperationalError, match="locked"),
            ):
                competing.execute("BEGIN IMMEDIATE")
            pending = pool.submit(service.enroll, "workspace-a", "after-snapshot")
        finally:
            release.set()
        assert export.result(timeout=15)["state"] == "backed_up"
        pending.result(timeout=15)
    with closing(sqlite3.connect(tmp_path / "capture" / "authority.sqlite")) as captured:
        assert captured.execute("SELECT count(*) FROM sync_devices").fetchone()[0] == 2
    with service._transaction() as conn:
        assert conn.execute("SELECT count(*) FROM sync_devices").fetchone()[0] == 3


def test_concurrent_duplicate_output_has_one_completion(state, tmp_path):
    root, _, _, _, _ = state
    output = tmp_path / "one-output"

    def attempt():
        try:
            return backup.export(root, output)["state"]
        except FileExistsError:
            return "reserved"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == ["backed_up", "reserved"]
    assert backup.verify(output)["files"] == 2


@pytest.mark.parametrize("case", ["bytes", "coverage", "traversal", "extra", "duplicate"])
def test_verification_refuses_corruption_missing_coverage_and_unsafe_paths(state, tmp_path, case):
    root, _, _, _, _ = state
    output = tmp_path / "snapshot"
    backup.export(root, output)
    path = output / backup.MANIFEST
    value = json.loads(path.read_text())
    item = value["files"][-1]
    if case == "bytes":
        (output / item["path"]).write_bytes(b"tampered")
    elif case == "coverage":
        (output / item["path"]).unlink()
        value["files"].pop()
    elif case == "traversal":
        item["path"] = "../owner-file"
    elif case == "extra":
        (output / "stray-secret").write_bytes(b"not in a declared backup")
    else:
        value["files"].append(item)
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises((ValueError, OSError)):
        backup.verify(output)


def test_verification_detects_late_change_and_is_read_only(state, tmp_path, monkeypatch):
    root, _, _, _, _ = state
    output = tmp_path / "snapshot"
    backup.export(root, output)
    before = {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    assert backup.verify(output)["state"] == "verified"
    assert before == {
        p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()
    }
    original = backup._objects

    def change_after_hash(conn, check):
        result = original(conn, check)
        target = output / next(iter(result))
        target.write_bytes(b"late replacement")
        return result

    monkeypatch.setattr(backup, "_objects", change_after_hash)
    with pytest.raises(ValueError, match="changed"):
        backup.verify(output)


@pytest.mark.parametrize("budget", [0, -1, 301, float("nan"), float("inf"), True])
def test_invalid_budget_never_creates_output(state, tmp_path, budget):
    root, _, _, _, _ = state
    output = tmp_path / "not-created"
    with pytest.raises(ValueError):
        backup.export(root, output, seconds=budget)
    assert not output.exists()


def test_cli_help_backup_and_read_only_verification(state, tmp_path, capsys):
    root, _, token, _, _ = state
    output = tmp_path / "cli-snapshot"
    assert sync_admin.main(["backup", "--state", str(root), "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "backed_up"
    assert sync_admin.main(["verify-backup", "--output", str(output)]) == 0
    receipt = capsys.readouterr()
    assert token not in receipt.out and json.loads(receipt.out)["live_restore"] is False
    assert sync_admin.main(["verify-backup", "--output", str(tmp_path / "missing")]) == 2
    assert "Traceback" not in capsys.readouterr().err
    for command in ("backup", "verify-backup"):
        with pytest.raises(SystemExit) as result:
            sync_admin.main([command, "--help"])
        assert result.value.code == 0


def test_output_inside_or_above_authority_is_refused(state, tmp_path):
    root, _, _, _, _ = state
    for output in (root, root / "backup", tmp_path):
        with pytest.raises(ValueError):
            backup.export(root, output)


@pytest.mark.parametrize("mode", ["export", "verify"])
def test_event_references_cannot_disappear_from_backup_registry(state, tmp_path, mode):
    root, service, _, manifest, data = state
    token = service.enroll("workspace", "a")
    paper(service, token)
    session = service.blob_begin(token, manifest)
    service.blob_append(token, session["upload_id"], 0, data)
    service.blob_commit(token, session["upload_id"])
    service.push(token, document(manifest))
    output = tmp_path / "snapshot"
    if mode == "verify":
        backup.export(root, output)
        database = output / "authority.sqlite"
    else:
        database = service.path
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("DELETE FROM sync_workspace_blobs WHERE workspace='workspace'")
        conn.commit()
    if mode == "export":
        with pytest.raises(ValueError, match="Retained event"):
            backup.export(root, output)
        assert not (output / backup.MANIFEST).exists()
    else:
        path = output / backup.MANIFEST
        value = json.loads(path.read_text())
        item = next(row for row in value["files"] if row["path"] == "authority.sqlite")
        item.update(
            size=database.stat().st_size, sha256=hashlib.sha256(database.read_bytes()).hexdigest()
        )
        path.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(ValueError, match="Retained event"):
            backup.verify(output)


def test_deadline_between_files_leaves_no_completion_marker(state, tmp_path, monkeypatch):
    root, service, _, _, _ = state
    output = tmp_path / "timeout"
    now = [0]
    monkeypatch.setattr(backup.time, "monotonic", lambda: now[0])
    original = backup._hash

    def expire(path, check, target=None):
        if target is not None:
            now[0] = 2
        return original(path, check, target)

    monkeypatch.setattr(backup, "_hash", expire)
    with pytest.raises(backup.BackupCancelled):
        backup.export(root, output, seconds=1)
    assert not (output / backup.MANIFEST).exists()
    # Cancellation released the real writer reservation.
    service.enroll("workspace-a", "after-timeout")


@pytest.mark.parametrize(
    "body", [b"\xff", b"[" * 1500 + b"]" * 1500, b'{"format":"first","format":"second"}']
)
def test_malformed_manifest_returns_bounded_cli_failure(tmp_path, capsys, body):
    output = tmp_path / "bad-json"
    output.mkdir()
    (output / backup.MANIFEST).write_bytes(body)
    assert sync_admin.main(["verify-backup", "--output", str(output)]) == 2
    receipt = capsys.readouterr()
    assert not receipt.out and "Traceback" not in receipt.err


def test_empty_authority_snapshot_stays_empty_and_missing_source_is_not_created(tmp_path):
    state, output = tmp_path / "authority", tmp_path / "snapshot"
    sync_admin.initialize(state)
    before = dump(state / "authority.sqlite")
    assert backup.export(state, output)["files"] == 1
    assert backup.verify(output)["files"] == 1
    assert dump(output / "authority.sqlite") == before
    missing = tmp_path / "not-an-authority"
    with pytest.raises(OSError):
        backup.export(missing, tmp_path / "not-created")
    assert not missing.exists() and not (tmp_path / "not-created").exists()


def test_actual_module_cli_never_initializes_a_research_workspace(state, tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    root, _, token, _, _ = state
    output = tmp_path / "external-cli-snapshot"
    unused = tmp_path / "must-not-create-research"
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "PAPERFACT_DATA": str(unused),
        "PYTHONUTF8": "1",
    }
    for arguments, expected in (
        (["backup", "--state", str(root), "--output", str(output)], "backed_up"),
        (["verify-backup", "--output", str(output)], "verified"),
    ):
        result = subprocess.run(
            [sys.executable, "-m", "paper_daily", "sync-admin", *arguments],
            env=env,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["state"] == expected
        assert token not in result.stdout + result.stderr
        assert not unused.exists()
