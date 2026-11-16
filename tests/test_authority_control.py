"""Official control checkpoints with synthetic credentials and owned file state."""

import json
import os
import secrets
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

from paper_daily import sync_admin, sync_authority_backup
from paper_daily import sync_authority_control as control


def test_guarded_pairing_and_concurrent_enrollment_survive_restart(tmp_path):
    state = tmp_path / "service"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    admin = service.enroll("workspace", "admin")
    code, credential = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    service.create_pairing(admin, code)
    service.redeem_pairing(code, "workspace", "mac", credential, "Mac")
    service.rename_device(admin, "mac", "Laptop")
    with ThreadPoolExecutor(max_workers=2) as workers:
        tokens = list(workers.map(lambda number: service.enroll("workspace", f"extra-{number}"),
                                 range(2)))
    reopened = sync_admin.authority(state)
    devices = reopened.device_catalog(admin)["devices"]
    assert {item["device_id"] for item in devices} == {"admin", "mac", "extra-0", "extra-1"}
    assert next(item["label"] for item in devices if item["device_id"] == "mac") == "Laptop"
    assert reopened.session_info(credential)["device_id"] == "mac"
    assert [reopened.session_info(token)["device_id"] for token in tokens] == ["extra-0", "extra-1"]
    with (pytest.raises(ValueError, match="control"),
          reopened._transaction(write=True) as connection):
        connection.execute("DROP TABLE sync_pairings")
    assert reopened.session_info(credential)["device_id"] == "mac"
    with closing(sqlite3.connect(service.path)) as connection, connection:
        connection.execute("UPDATE sync_pairings SET expires_at=expires_at+3600")
    with pytest.raises(ValueError, match="control"):
        sync_admin.authority(state).session_info(admin)


@pytest.mark.parametrize("phase", ["before", "crash-after"])
def test_interrupted_control_write_preserves_or_pauses_authority(
    tmp_path, monkeypatch, phase, capsys
):
    state = tmp_path / "service"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    token = service.enroll("workspace", "lost-device")
    if phase == "before":
        def failed(*_args):
            raise OSError("Synthetic checkpoint failure")

        with monkeypatch.context() as patch:
            patch.setattr(control, "publish", failed)
            with pytest.raises(OSError):
                service.revoke(token)
        assert sync_admin.authority(state).session_info(token)["device_id"] == "lost-device"
        service.revoke(token)
        with pytest.raises(PermissionError):
            sync_admin.authority(state).session_info(token)
        return
    code = """
import json,os,sys
from pathlib import Path
from paper_daily import sync_admin
from paper_daily import sync_authority_control as control
state, token = json.load(sys.stdin)
original = control.publish
def crash(*args):
    original(*args)
    os._exit(73)
control.publish = crash
sync_admin.authority(Path(state)).revoke(token)
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    child = subprocess.run([sys.executable, "-c", code], input=json.dumps([str(state), token]),
                           encoding="utf-8", capture_output=True, timeout=15, env=env)
    assert child.returncode == 73
    with closing(sqlite3.connect(service.path)) as connection:
        assert connection.execute("SELECT revoked FROM sync_devices").fetchone() == (0,)
    with pytest.raises(ValueError, match="control"):
        sync_admin.authority(state).session_info(token)
    output = tmp_path / "blocked-backup"
    with pytest.raises(ValueError, match="control"):
        sync_authority_backup.export(state, output)
    assert not (output / "manifest.json").exists()
    assert sync_admin.main(["serve", "--state", str(state)]) == 2
    error = capsys.readouterr().err
    assert "control/history" in error and token not in error
