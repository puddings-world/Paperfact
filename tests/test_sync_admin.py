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
