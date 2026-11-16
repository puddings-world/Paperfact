"""Private reference-service setup never opens a research workspace or prints tokens."""

import json

import pytest

from paper_daily import sync_admin
from paper_daily.connection_vault import Connection
from paper_daily.sync_service import ReferenceService


def test_setup_issue_and_retry_are_explicit_and_preserve_one_device(tmp_path, capsys):
    state = tmp_path / "service"
    sync_admin.initialize(state)
    sync_admin.initialize(state)
    output = tmp_path / "new-device.json"
    args = (state, "http://127.0.0.1:8765", "workspace", "mac-device", output)
    assert sync_admin.issue(*args)["state"] == "enrolled"
    before = output.read_bytes()
    assert sync_admin.issue(*args)["state"] == "already_enrolled"
    assert output.read_bytes() == before
    record = Connection.decoded(before.decode("utf-8"))
    authority = sync_admin.authority(state)
    assert authority.session_info(record.token) == {
        "workspace_id": "workspace", "device_id": "mac-device"
    }
    assert record.token not in capsys.readouterr().out
    if __import__("os").name != "nt":
        assert output.stat().st_mode & 0o077 == 0


def test_initialization_refuses_an_unrelated_nonempty_research_directory(tmp_path):
    research = tmp_path / "research"
    research.mkdir()
    keep = research / "papers.db"
    keep.write_bytes(b"owner research must stay untouched")
    with pytest.raises(ValueError):
        sync_admin.initialize(research)
    assert keep.read_bytes() == b"owner research must stay untouched"
    assert list(research.iterdir()) == [keep]


@pytest.mark.parametrize("case", ["existing", "private-state-output", "remote-http", "bad-id"])
def test_invalid_issue_never_enrolls_or_overwrites_output(tmp_path, case):
    state = tmp_path / "service"
    sync_admin.initialize(state)
    output, endpoint, device = tmp_path / "private.json", "https://sync.example.org", "mac"
    if case == "existing":
        output.write_text("preserve unrelated file", encoding="utf-8")
    elif case == "private-state-output":
        output = state / "private.json"
    elif case == "remote-http":
        endpoint = "http://example.org"
    else:
        device = "bad id"
    with pytest.raises((ValueError, OSError)):
        sync_admin.issue(state, endpoint, "workspace", device, output)
    with sync_admin.authority(state)._transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sync_devices").fetchone()[0] == 0
    if case == "existing":
        assert output.read_text(encoding="utf-8") == "preserve unrelated file"
    else:
        assert not output.exists()


def test_credential_sink_failure_rolls_back_device_and_allows_exact_retry(tmp_path):
    service = ReferenceService(tmp_path / "authority.db")

    def failed(_token):
        raise OSError("fixture full disk")

    with pytest.raises(OSError):
        service.enroll("workspace", "new-device", before_commit=failed)
    token = service.enroll("workspace", "new-device")
    assert service.session_info(token)["device_id"] == "new-device"


def test_admin_cli_receipt_omits_credential_and_help_does_not_initialize(tmp_path, capsys):
    state, output = tmp_path / "service", tmp_path / "connection.json"
    assert sync_admin.main(["init", "--state", str(state)]) == 0
    assert sync_admin.main([
        "issue", "--state", str(state), "--endpoint", "https://sync.example.org",
        "--workspace", "workspace", "--device", "new-device", "--output", str(output),
    ]) == 0
    token = Connection.decoded(output.read_text(encoding="utf-8")).token
    receipts = capsys.readouterr()
    assert token not in receipts.out + receipts.err
    assert all(isinstance(json.loads(line), dict) for line in receipts.out.splitlines())


def test_output_flush_failure_removes_only_new_file_and_rolls_back_issue(tmp_path, monkeypatch):
    state, output = tmp_path / "service", tmp_path / "private.json"
    sync_admin.initialize(state)

    def fail(_fd):
        raise OSError("fixture flush failure")

    with monkeypatch.context() as patch:
        patch.setattr(sync_admin.os, "fsync", fail)
        with pytest.raises(OSError):
            sync_admin.issue(state, "https://sync.example.org", "workspace", "mac", output)
    assert not output.exists()
    with sync_admin.authority(state)._transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sync_devices").fetchone()[0] == 0
    assert sync_admin.issue(
        state, "https://sync.example.org", "workspace", "mac", output
    )["state"] == "enrolled"


def test_serve_closes_socket_on_keyboard_interrupt(tmp_path, monkeypatch, capsys):
    state = tmp_path / "service"
    sync_admin.initialize(state)
    closed = []

    class Server:
        server_port = 8765

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            closed.append(True)

    monkeypatch.setattr(sync_admin, "make_server", lambda *_args, **_kwargs: Server())
    assert sync_admin.main(["serve", "--state", str(state)]) == 0
    assert closed == [True]
    assert json.loads(capsys.readouterr().out)["url"] == "http://127.0.0.1:8765"


def test_real_console_entry_serves_issued_binding_without_creating_research(tmp_path):
    import os
    import subprocess
    import sys
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    from paper_daily.sync_http import HttpTransport

    state, output = tmp_path / "service", tmp_path / "connection.json"
    sync_admin.initialize(state)
    sync_admin.issue(state, "http://127.0.0.1:8765", "workspace", "mac", output)
    record = Connection.decoded(output.read_text(encoding="utf-8"))
    source = Path(__file__).resolve().parents[1] / "src"
    unused = tmp_path / "must-not-create-research"
    child = subprocess.Popen(
        [sys.executable, "-m", "paper_daily", "sync-admin", "serve", "--state", str(state),
         "--port", "0"],
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(source), "PAPERFACT_DATA": str(unused)},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    reader = ThreadPoolExecutor(max_workers=1)
    try:
        ready = json.loads(reader.submit(child.stdout.readline).result(timeout=15))
        assert ready["state"] == "serving"
        with HttpTransport(ready["url"]) as transport:
            assert transport.session_info(record.token) == {
                "workspace_id": "workspace", "device_id": "mac"
            }
        assert not unused.exists()
    finally:
        child.terminate()
        child.wait(timeout=10)
        reader.shutdown(wait=True)
        child.stdout.close()
        child.stderr.close()


def test_issued_record_at_codec_limit_is_readable_and_retryable(tmp_path, monkeypatch):
    from paper_daily import connection_vault

    state, output = tmp_path / "service", tmp_path / "connection.json"
    sync_admin.initialize(state)
    token = "fixture-boundary-device-token"
    monkeypatch.setattr("paper_daily.sync_service.secrets.token_urlsafe", lambda _size: token)
    body = Connection("https://sync.example.org", "workspace", "mac", token).encoded()
    monkeypatch.setattr(connection_vault, "MAX_BYTES", len(body.encode("utf-16-le")))
    assert sync_admin.issue(
        state, "https://sync.example.org", "workspace", "mac", output
    )["state"] == "enrolled"
    assert Connection.decoded(output.read_text(encoding="utf-8")).token == token
    assert sync_admin.issue(
        state, "https://sync.example.org", "workspace", "mac", output
    )["state"] == "already_enrolled"


def test_output_close_failure_does_not_leave_an_enrolled_device(tmp_path, monkeypatch):
    state, output = tmp_path / "service", tmp_path / "connection.json"
    sync_admin.initialize(state)
    original = sync_admin.os.fdopen

    class CloseFailure:
        def __init__(self, stream):
            self.stream = stream
            self.failed = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def close(self):
            self.stream.close()
            if not self.failed:
                self.failed = True
                raise OSError("fixture close failed")

    monkeypatch.setattr(sync_admin.os, "fdopen", lambda *a, **k: CloseFailure(original(*a, **k)))
    with pytest.raises(OSError):
        sync_admin.issue(state, "https://sync.example.org", "workspace", "mac", output)
    assert not output.exists()
    with sync_admin.authority(state)._transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sync_devices").fetchone()[0] == 0


def test_second_serve_is_actionable_and_preserves_existing_authority(tmp_path, capsys):
    from paper_daily.sync_http import make_server

    state = tmp_path / "service"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    before = service.path.read_bytes()
    with make_server(service):
        assert sync_admin.main(["serve", "--state", str(state), "--port", "0"]) == 2
        message = capsys.readouterr()
        assert not message.out
        assert "already active" in message.err and "Do not delete lock files" in message.err
        from paper_daily import sync_authority_backup

        backup = tmp_path / "online-backup"
        assert sync_authority_backup.export(state, backup)["state"] == "backed_up"
        sync_authority_backup.verify(backup)
        assert {item.name for item in backup.iterdir()} == {"manifest.json", "authority.sqlite"}
    assert service.path.read_bytes() == before
    with make_server(service):
        pass


def test_restarting_official_service_refuses_replaced_database_with_old_live_token(tmp_path):
    import sqlite3
    from contextlib import closing

    state = tmp_path / "service"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    token = service.enroll("workspace", "lost-device")
    old = tmp_path / "old.sqlite"
    with service._transaction() as source, closing(sqlite3.connect(old)) as target:
        source.backup(target)
    service.revoke(token)
    with pytest.raises(PermissionError):
        service.session_info(token)
    with pytest.raises(PermissionError):
        sync_admin.authority(state).session_info(token)
    old.replace(service.path)
    before = service.path.read_bytes()
    with pytest.raises(ValueError, match="identity|lifetime|recovery"):
        sync_admin.authority(state)
    assert service.path.read_bytes() == before


@pytest.mark.parametrize("legacy", ["v1", "v2"])
def test_legacy_marker_can_only_back_up_and_restore_with_fresh_credentials(
    tmp_path, capsys, legacy,
):
    from test_sync_service import operation

    from paper_daily import sync_authority_backup, sync_authority_restore

    state = tmp_path / "legacy"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    old = service.enroll("workspace-a", "device-a")
    service.push(old, operation())
    marker = state / sync_admin.MARKER
    record = sync_admin.LEGACY_FORMAT
    if legacy == "v2":
        record = {**sync_admin.LEGACY_PINNED_FORMAT,
                  "database_identity": list(service._database_identity)}
    marker.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(sync_admin.AuthorityMarkerError, match="Legacy"):
        sync_admin.authority(state)
    assert sync_admin.main(["init", "--state", str(state)]) == 2
    assert "restore-backup" in capsys.readouterr().err
    assert json.loads(marker.read_text()) == record
    snapshot = tmp_path / "snapshot"
    sync_authority_backup.export(state, snapshot)
    fresh = tmp_path / "fresh"
    sync_authority_restore.restore(snapshot, fresh, "workspace-a", "recovered-workspace")
    recovered = sync_admin.authority(fresh)
    with pytest.raises(PermissionError):
        recovered.session_info(old)
    new = recovered.enroll("recovered-workspace", "new-device")
    assert recovered.pull(new)[0]["operation"]["payload"]["body"] == "Research observation"
    assert json.loads((fresh / sync_admin.MARKER).read_text())["format"] == sync_admin.FORMAT[
        "format"
    ]


@pytest.mark.parametrize("mode", ["swap", "missing"])
def test_database_swap_after_marker_check_is_refused_before_schema_writes(
    tmp_path, monkeypatch, mode,
):
    import sqlite3
    from contextlib import closing

    state = tmp_path / "service"
    sync_admin.initialize(state)
    replacement = tmp_path / "replacement.sqlite"
    with closing(sqlite3.connect(replacement)) as connection, connection:
        connection.execute("CREATE TABLE sentinel(body TEXT)")
        connection.execute("INSERT INTO sentinel VALUES ('keep')")
    expected = replacement.read_bytes()
    actual = sync_admin.ReferenceService

    def swapped(database, **kwargs):
        if mode == "swap":
            replacement.replace(database)
        else:
            database.unlink()
        return actual(database, **kwargs)

    monkeypatch.setattr(sync_admin, "ReferenceService", swapped)
    with pytest.raises(ValueError, match="identity"):
        sync_admin.authority(state)
    if mode == "swap":
        assert (state / sync_admin.DATABASE).read_bytes() == expected
    else:
        assert not (state / sync_admin.DATABASE).exists()


@pytest.mark.parametrize("damage", ["identity", "extra-field", "float", "duplicate"])
def test_invalid_lifetime_marker_never_opens_or_repins_authority(tmp_path, monkeypatch, damage):
    state = tmp_path / "service"
    sync_admin.initialize(state)
    marker = state / sync_admin.MARKER
    record = json.loads(marker.read_text())
    if damage == "identity":
        record["database_identity"][1] += 1
    elif damage == "extra-field":
        record["unexpected"] = True
    elif damage == "float":
        record["database_identity"][0] = float(record["database_identity"][0])
    raw = json.dumps(record)
    if damage == "duplicate":
        raw = raw[:-1] + ',"format":"' + sync_admin.FORMAT["format"] + '"}'
    marker.write_text(raw, encoding="utf-8")
    before = (state / sync_admin.DATABASE).read_bytes()
    monkeypatch.setattr(sync_admin, "ReferenceService",
                        lambda *_a, **_k: pytest.fail("Must refuse before opening"))
    with pytest.raises(ValueError):
        sync_admin.authority(state)
    assert marker.read_text() == raw
    assert (state / sync_admin.DATABASE).read_bytes() == before


def test_same_file_revocation_rollback_is_refused_after_restart(tmp_path):
    import sqlite3
    from contextlib import closing

    state = tmp_path / "service"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    token = service.enroll("workspace", "lost-device")
    service.revoke(token)
    before = service.path.stat()
    with closing(sqlite3.connect(service.path)) as connection, connection:
        connection.execute("UPDATE sync_devices SET revoked=0")
    after = service.path.stat()
    assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
    with pytest.raises(ValueError, match="control|recovery"):
        sync_admin.authority(state).session_info(token)
