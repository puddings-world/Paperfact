"""Remembered workspace routing is device-local and cannot override explicit choices."""

import sqlite3
from pathlib import Path

from paper_daily import runtime
from paper_daily.workspace_preferences import remember_workspace, remembered_workspace


def test_installed_launch_remembers_existing_profile_and_keeps_explicit_overrides(
    tmp_path, monkeypatch
):
    default = tmp_path / "default"
    profile = tmp_path / "sync-profile"
    profile.mkdir()
    sqlite3.connect(profile / "papers.db").close()
    record = default / "active-workspace.json"
    remember_workspace(profile, record=record)
    monkeypatch.setattr(runtime, "user_data_dir", lambda **_: default)
    assert remembered_workspace(record) == profile
    assert runtime.data_dir({}, frozen=True) == profile
    explicit = tmp_path / "explicit"
    assert runtime.data_dir({"PAPERFACT_DATA": str(explicit)}, frozen=True) == explicit
    assert runtime.data_dir({}, frozen=False) == runtime.bundle_root() / "data"
    assert set(__import__("json").loads(record.read_text())) == {
        "format",
        "root",
        "database_identity",
    }


def test_replaced_or_invalid_workspace_never_becomes_a_new_implicit_target(tmp_path):
    profile = tmp_path / "sync-profile"
    profile.mkdir()
    database = profile / "papers.db"
    sqlite3.connect(database).close()
    record = tmp_path / "active-workspace.json"
    remember_workspace(profile, record=record)
    other = profile / "different.db"
    sqlite3.connect(other).close()
    other.replace(database)
    assert remembered_workspace(record) is None
    record.write_text('{"format":1,"root":"relative","database_identity":[0,1]}')
    assert remembered_workspace(record) is None
    assert Path(database).exists()
