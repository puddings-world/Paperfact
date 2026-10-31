"""Remembered connections use a fake vault and isolated authority exclusively."""

import json
import shutil
import sqlite3
import sys
from contextlib import closing
from types import ModuleType

import pytest
from test_workspace_sync import Native, connect

from paper_daily.connection_vault import (
    Connection,
    ConnectionVault,
    VaultUnavailable,
    native_backend,
)
from paper_daily.store import SCHEMA
from paper_daily.sync_capture import CaptureConnection, install
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare, research_writer
from paper_daily.sync_service import ReferenceService
from paper_daily.workspace_service import Cancelled, Ticket, WorkspaceChanged, WorkspaceService
from paper_daily.workspace_sync import SyncSession


@pytest.fixture
def service(tmp_path):
    path = tmp_path / "research.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(SCHEMA)
    prepare(path, workspace_id="workspace", device_id="origin-device")
    SyncClient(
        Journal(path, workspace_id="workspace", device_id="origin-device"), research_writer
    )
    with closing(sqlite3.connect(path, factory=CaptureConnection)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="origin-device")
        conn.commit()
    authority = ReferenceService(tmp_path / "authority.db")
    token = authority.enroll("workspace", "origin-device")
    calls = []
    session = SyncSession(path, transport_factory=lambda url: Native(url, authority, calls))
    return session, authority, token, calls


class FakeVault:
    def __init__(self):
        self.rows, self.calls = {}, []
        self.after_write = lambda: None

    def get_password(self, service, account):
        self.calls.append("get")
        return self.rows.get((service, account))

    def set_password(self, service, account, body):
        self.calls.append("set")
        self.rows[service, account] = body
        self.after_write()

    def delete_password(self, service, account):
        self.calls.append("delete")
        self.rows.pop((service, account), None)


@pytest.fixture
def saved(service):
    session = service[0]
    backend = FakeVault()
    vault = ConnectionVault(session.workspace, backend=lambda: backend)
    connection = Connection("http://127.0.0.1:8765", "workspace", "origin-device", service[2])
    return vault, backend, connection


def test_constructor_and_empty_load_never_connect_or_write_research(saved, service):
    vault, backend, _ = saved
    assert not backend.calls
    before = service[0].workspace.path.read_bytes()
    assert vault.load() is None
    assert backend.calls == ["get"]
    assert service[3] == []
    assert service[0].workspace.path.read_bytes() == before
    assert not service[0].summary()["authenticated"]


def test_verified_round_trip_and_forget_preserve_research(saved, service):
    vault, backend, connection = saved
    connect(service)
    before = service[0].workspace.path.read_bytes()
    vault.remember(service[0], connection)
    service[0].disconnect()
    assert vault.load() == connection
    assert connection.token not in repr(vault.load())
    assert connection.token not in vault.account
    assert str(service[0].workspace.path) not in next(iter(backend.rows.values()))
    assert service[3] == ["session_info"]
    assert not service[0].summary()["authenticated"]
    assert service[0].workspace.path.read_bytes() == before
    vault.forget()
    vault.forget()
    assert vault.load() is None


@pytest.mark.parametrize("variant", ["unverified", "token", "device", "endpoint"])
def test_only_exact_verified_connection_is_remembered(saved, service, variant):
    vault, backend, connection = saved
    if variant != "unverified":
        connect(service)
    values = dict(endpoint=connection.endpoint, workspace_id=connection.workspace_id,
                  device_id=connection.device_id, token=connection.token)
    if variant == "token":
        values["token"] = "other-device-token"
    elif variant == "device":
        values["device_id"] = "another-device"
    elif variant == "endpoint":
        values["endpoint"] = "https://other.example.org"
    with pytest.raises(ValueError, match="verified"):
        vault.remember(service[0], Connection(**values))
    assert not backend.rows
    assert not backend.calls


def test_copied_workspace_never_inherits_credentials(saved, service, tmp_path):
    vault, backend, connection = saved
    connect(service)
    vault.remember(service[0], connection)
    copied = tmp_path / "copied.db"
    shutil.copyfile(service[0].workspace.path, copied)
    other = ConnectionVault(WorkspaceService(copied), backend=lambda: backend)
    assert other.account != vault.account
    assert other.load() is None
    assert vault.load() == connection


@pytest.mark.parametrize("change", ["replacement", "binding", "active_path"])
def test_scope_change_fails_before_vault_access(saved, service, tmp_path, change):
    vault, backend, connection = saved
    connect(service)
    vault.remember(service[0], connection)
    backend.calls.clear()
    path = service[0].workspace.path
    if change == "replacement":
        copied = tmp_path / "new.db"
        shutil.copyfile(path, copied)
        copied.replace(path)
    elif change == "binding":
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("UPDATE paperfact_sync_identity SET device='changed-device'")
            conn.commit()
    else:
        service[0].workspace.current_path = lambda: tmp_path / "another.db"
    with pytest.raises(WorkspaceChanged):
        vault.load()
    assert backend.calls == []


@pytest.mark.parametrize("previous", [None, "old connection record"])
def test_cancel_during_write_restores_previous_record(saved, service, previous):
    vault, backend, connection = saved
    connect(service)
    if previous is not None:
        backend.rows["io.github.puddings-world.paperfact.sync", vault.account] = previous
    before = dict(backend.rows)
    ticket = Ticket()
    backend.after_write = ticket.cancel
    with pytest.raises(Cancelled):
        vault.remember(service[0], connection, ticket)
    assert backend.rows == before


def test_cancel_before_load_or_save_never_opens_vault(saved, service):
    vault, backend, connection = saved
    ticket = Ticket()
    ticket.cancel()
    with pytest.raises(Cancelled):
        vault.load(ticket)
    with pytest.raises(Cancelled):
        vault.remember(service[0], connection, ticket)
    assert not backend.calls


def test_native_error_does_not_echo_secret_or_fall_back_to_file(saved, service):
    vault, backend, connection = saved

    def unavailable():
        raise RuntimeError(connection.token)

    vault._backend = unavailable
    with pytest.raises(VaultUnavailable) as caught:
        vault.load()
    assert connection.token not in str(caught.value)
    assert not backend.rows
    assert not list(service[0].workspace.path.parent.glob("*credential*"))


@pytest.mark.parametrize("body", [
    "{}", "[]", "null", "invalid", '{"format":1,"format":1}', "a" * 1300,
])
def test_malformed_native_records_are_rejected(body):
    with pytest.raises(ValueError):
        Connection.decoded(body)


@pytest.mark.parametrize("change", ["unknown", "format", "url", "token", "workspace"])
def test_closed_stored_schema(change):
    connection = Connection("https://sync.example.org", "workspace", "device", "token")
    value = json.loads(connection.encoded())
    if change == "unknown":
        value["extra"] = "ignored?"
    elif change == "format":
        value["format"] = True
    elif change == "url":
        value["endpoint"] = "http://remote.example.org"
    elif change == "token":
        value["token"] = "secret\nheader"
    else:
        value["workspace_id"] = "../escape"
    with pytest.raises(ValueError):
        Connection.decoded(json.dumps(value))


def test_native_selection_requires_exact_backend_and_local_persistence(monkeypatch):
    keyring = ModuleType("keyring")
    module = ModuleType("keyring.backends.Windows")
    module.WinVaultKeyring = FakeVault
    selected = FakeVault()
    keyring.get_keyring = lambda: selected
    monkeypatch.setitem(sys.modules, "keyring", keyring)
    monkeypatch.setitem(sys.modules, "keyring.backends.Windows", module)
    monkeypatch.setattr(sys, "platform", "win32")
    assert native_backend() is selected
    assert selected.persist == 2
    selected = object()
    with pytest.raises(VaultUnavailable):
        native_backend()


@pytest.mark.parametrize("platform,module_name", [
    ("darwin", "macOS"), ("linux", "SecretService"),
])
def test_other_native_backends_are_selected_without_opening_store(
    monkeypatch, platform, module_name
):
    keyring = ModuleType("keyring")
    module = ModuleType("keyring.backends." + module_name)
    module.Keyring = FakeVault
    backend = FakeVault()
    keyring.get_keyring = lambda: backend
    monkeypatch.setitem(sys.modules, "keyring", keyring)
    monkeypatch.setitem(sys.modules, "keyring.backends." + module_name, module)
    monkeypatch.setattr(sys, "platform", platform)
    assert native_backend() is backend
    assert not backend.calls


def test_missing_optional_package_preserves_sanitized_manual_fallback(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)
    with pytest.raises(VaultUnavailable, match="unavailable"):
        native_backend()


def test_oversized_valid_memory_credential_is_not_remembered(saved, service):
    vault, backend, connection = saved
    large = Connection(
        connection.endpoint, connection.workspace_id, connection.device_id, "a" * 2000
    )
    with pytest.raises(ValueError, match="too large"):
        vault.remember(service[0], large)
    assert not backend.rows and not backend.calls


def test_final_context_guard_reads_no_vault_and_rejects_changed_binding(saved, service):
    vault, backend, _connection = saved
    assert vault.current()
    assert backend.calls == []
    with closing(sqlite3.connect(service[0].workspace.path)) as conn:
        conn.execute("UPDATE paperfact_sync_identity SET device='different-device'")
        conn.commit()
    assert not vault.current()
    assert backend.calls == []
