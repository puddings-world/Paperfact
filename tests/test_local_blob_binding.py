"""Actual local store binding: explicit empty admission, no remote/source authority."""

import hashlib
import os
import shutil
import socket
import sqlite3
import subprocess
from contextlib import closing

import pytest

from paper_daily import llm, store
from paper_daily import local_blob_binding as binding
from paper_daily.sync_artifacts import stage_bytes
from paper_daily.sync_blobs import BlobManifest, BlobStore
from paper_daily.sync_client import SyncClient
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare, research_writer


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("No remote, account or model work")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(llm, "complete_result", deny)


def make(path, *, workspace="workspace", device="device"):
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(store.SCHEMA)
    prepare(path, workspace_id=workspace, device_id=device)
    return SyncClient(Journal(path, workspace_id=workspace, device_id=device), research_writer)


@pytest.fixture
def actual(tmp_path):
    return make(tmp_path / "research.sqlite"), BlobStore(tmp_path / "blobs")


def native(path):
    value = path.stat()
    return value.st_dev, value.st_ino


def row(store):
    with closing(sqlite3.connect(store.root / "index.sqlite")) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='transfer_binding'").fetchone():
            return None
        return conn.execute(
            "SELECT id,workspace,device,research_path FROM transfer_binding"
        ).fetchall()


def install(store, sql, rows):
    with closing(sqlite3.connect(store.root / "index.sqlite")) as conn, conn:
        conn.execute(sql)
        for value in rows:
            conn.execute("INSERT INTO transfer_binding VALUES(?,?,?,?)", value)


def test_empty_store_binds_once_with_strict_schema_and_no_research_changes(actual):
    client, blobs = actual
    before = client.journal.path.read_bytes()
    pending = client.journal.pending()
    index = blobs.root / "index.sqlite"
    identity = binding.bind(client, blobs)
    assert identity == native(index)
    assert row(blobs) == [(1, "workspace", "device", str(client.journal.path.resolve()))]
    with closing(sqlite3.connect(index)) as conn:
        columns = conn.execute("PRAGMA table_info(transfer_binding)").fetchall()
    assert columns == [
        (0, "id", "INTEGER", 0, None, 1),
        (1, "workspace", "TEXT", 1, None, 0),
        (2, "device", "TEXT", 1, None, 0),
        (3, "research_path", "TEXT", 1, None, 0),
    ]
    after = index.read_bytes()
    assert binding.bind(client, blobs) == identity and index.read_bytes() == after
    assert client.journal.path.read_bytes() == before and client.journal.pending() == pending


@pytest.mark.parametrize(
    "schema", [binding.LEGACY_SCHEMA, binding.SCHEMA], ids=["legacy", "strict"]
)
def test_exact_existing_binding_is_readonly_and_schema_is_preserved(actual, schema, monkeypatch):
    client, blobs = actual
    install(blobs, schema, [(1, "workspace", "device", str(client.journal.path.resolve()))])
    before = (blobs.root / "index.sqlite").read_bytes()
    research = client.journal.path.read_bytes()
    statements = []
    real = binding.sqlite3.connect

    def connection(*args, **kwargs):
        conn = real(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(binding.sqlite3, "connect", connection)
    assert binding.bind(client, blobs) == native(blobs.root / "index.sqlite")
    assert not any(
        sql.lstrip().upper().startswith(("CREATE", "INSERT", "UPDATE", "DELETE", "REPLACE"))
        for sql in statements
    )
    assert (
        blobs.root / "index.sqlite"
    ).read_bytes() == before and client.journal.path.read_bytes() == research


def test_real_file_transfers_legacy_binding_remains_usable_without_transport_calls(actual):
    client, blobs = actual

    class Inert:
        def __getattr__(self, name):
            if name == "base_url":
                raise AttributeError(name)
            raise AssertionError("Transport must not be used")

    transfers = FileTransfers(client, blobs, Inert(), origin="https://fixture.invalid", token=None)
    before = (blobs.root / "index.sqlite").read_bytes()
    research = client.journal.path.read_bytes()
    assert binding.bind(client, blobs) == native(blobs.root / "index.sqlite")
    assert (
        blobs.root / "index.sqlite"
    ).read_bytes() == before and client.journal.path.read_bytes() == research
    transfers.close()


@pytest.mark.parametrize(
    "mode",
    [
        "workspace",
        "device",
        "path",
        "id-two",
        "empty",
        "multiple",
        "null",
        "extra-column",
        "wrong-type",
        "default",
        "ifnotexists-name",
        "view",
        "trigger",
    ],
)
def test_foreign_or_damaged_present_binding_refuses_without_modifying_index(actual, mode):
    client, blobs = actual
    expected = (1, "workspace", "device", str(client.journal.path.resolve()))
    sql = binding.LEGACY_SCHEMA
    rows = [expected]
    if mode == "workspace":
        rows = [(1, "foreign", *expected[2:])]
    elif mode == "device":
        rows = [(1, "workspace", "foreign", expected[3])]
    elif mode == "path":
        rows = [(*expected[:3], str(client.journal.path.parent / "other.sqlite"))]
    elif mode == "id-two":
        rows = [(2, *expected[1:])]
    elif mode == "empty":
        rows = []
    elif mode == "multiple":
        rows = [expected, (2, *expected[1:])]
    elif mode == "null":
        rows = [(1, None, *expected[2:])]
    elif mode == "extra-column":
        sql = sql[:-1] + ",future TEXT)"
        rows = []
    elif mode == "wrong-type":
        sql = sql.replace("workspace TEXT", "workspace BLOB")
    elif mode == "default":
        sql = sql.replace("workspace TEXT", "workspace TEXT DEFAULT 'workspace'")
    elif mode == "ifnotexists-name":
        sql = sql.replace("workspace TEXT", "workspaceIFNOTEXISTS TEXT")
    elif mode == "view":
        sql = (
            "CREATE VIEW transfer_binding AS SELECT 1 AS id,'workspace' AS workspace,"
            "'device' AS device,'path' AS research_path"
        )
        rows = []
    install(blobs, sql, rows)
    if mode == "trigger":
        with closing(sqlite3.connect(blobs.root / "index.sqlite")) as conn, conn:
            conn.execute(
                "CREATE TRIGGER binding_writer AFTER INSERT ON transfer_binding "
                "BEGIN DELETE FROM blobs; END"
            )
    before = (blobs.root / "index.sqlite").read_bytes()
    with pytest.raises(ValueError):
        binding.bind(client, blobs, allow_existing=True)
    assert (blobs.root / "index.sqlite").read_bytes() == before


@pytest.mark.parametrize("state", ["complete", "partial", "stray-object", "stray-root"])
def test_nonempty_unbound_store_requires_explicit_legacy_choice(actual, state):
    client, blobs = actual
    data = b"Legitimate staged local artifact"
    sha = hashlib.sha256(data).hexdigest()
    if state == "complete":
        stage_bytes(blobs, {sha: data})
    elif state == "partial":
        blobs.begin(BlobManifest(sha, len(data)))
    elif state == "stray-object":
        (blobs.root / "objects/stray").write_bytes(data)
    else:
        (blobs.root / "unexpected-private-file").write_bytes(data)
    before = (blobs.root / "index.sqlite").read_bytes()
    with pytest.raises(ValueError):
        binding.bind(client, blobs)
    assert row(blobs) is None and (blobs.root / "index.sqlite").read_bytes() == before
    if state in {"complete", "partial"}:
        identity = binding.bind(client, blobs, allow_existing=True)
        assert identity == native(blobs.root / "index.sqlite")
        assert row(blobs) == [(1, "workspace", "device", str(client.journal.path.resolve()))]
        if state == "complete":
            assert blobs.verified_path(BlobManifest(sha, len(data))).read_bytes() == data
        else:
            assert blobs.begin(BlobManifest(sha, len(data)))["offset"] == 0


@pytest.mark.parametrize(
    "mode",
    [
        "research-binding",
        "journal-binding",
        "missing-binding",
        "optional-empty",
        "optional-foreign",
    ],
)
def test_actual_research_binding_must_match_client_without_adopting_rows(actual, mode):
    client, blobs = actual
    with closing(sqlite3.connect(client.journal.path)) as conn, conn:
        if mode == "research-binding":
            conn.execute("UPDATE research_sync_binding SET origin='foreign'")
        elif mode == "journal-binding":
            conn.execute("UPDATE paperfact_sync_identity SET device='foreign'")
        elif mode == "missing-binding":
            conn.execute("DELETE FROM research_sync_binding")
        else:
            conn.execute(
                "CREATE TABLE research_capture_binding("
                "id INTEGER PRIMARY KEY,workspace TEXT,device TEXT)"
            )
            if mode == "optional-foreign":
                conn.execute("INSERT INTO research_capture_binding VALUES(1,'workspace','foreign')")
    before = client.journal.path.read_bytes()
    index = (blobs.root / "index.sqlite").read_bytes()
    with pytest.raises(ValueError):
        binding.bind(client, blobs)
    assert (
        client.journal.path.read_bytes() == before
        and (blobs.root / "index.sqlite").read_bytes() == index
    )
    assert row(blobs) is None


@pytest.mark.parametrize("when", [2, 3], ids=["before-DDL", "before-commit"])
def test_binding_change_during_admission_rolls_back_all_new_metadata(actual, monkeypatch, when):
    client, blobs = actual
    real = binding._owner_current
    calls = []

    def changed(owner):
        calls.append(True)
        if len(calls) == when:
            with closing(sqlite3.connect(client.journal.path)) as conn, conn:
                conn.execute("UPDATE research_sync_binding SET origin='changed-before-publication'")
        return real(owner)

    monkeypatch.setattr(binding, "_owner_current", changed)
    before = (blobs.root / "index.sqlite").read_bytes()
    with pytest.raises(ValueError):
        binding.bind(client, blobs)
    assert row(blobs) is None and (blobs.root / "index.sqlite").read_bytes() == before


def test_actual_native_research_replacement_before_commit_is_not_recaptured(actual, monkeypatch):
    client, blobs = actual
    real = binding._owner_current
    calls = []
    old = native(client.journal.path)
    replacement = client.journal.path.with_name("replacement.sqlite")
    shutil.copyfile(client.journal.path, replacement)

    def changed(owner):
        calls.append(True)
        if len(calls) == 3:
            os.replace(replacement, client.journal.path)
            assert native(client.journal.path) != old
        return real(owner)

    monkeypatch.setattr(binding, "_owner_current", changed)
    before = (blobs.root / "index.sqlite").read_bytes()
    with pytest.raises(ValueError):
        binding.bind(client, blobs)
    assert len(calls) == 3 and row(blobs) is None
    assert (blobs.root / "index.sqlite").read_bytes() == before


def test_actual_native_index_replacement_before_open_refuses_without_binding_new_index(
    actual, monkeypatch
):
    client, blobs = actual
    index = blobs.root / "index.sqlite"
    old = native(index)
    replacement = blobs.root / "replacement.sqlite"
    shutil.copyfile(index, replacement)
    before = replacement.read_bytes()
    real = binding.sqlite3.connect
    acted = []

    def changed(path, *args, **kwargs):
        if str(path).startswith(index.as_uri() + "?mode=rw") and not acted:
            acted.append(True)
            os.replace(replacement, index)
            assert native(index) != old
        return real(path, *args, **kwargs)

    monkeypatch.setattr(binding.sqlite3, "connect", changed)
    with pytest.raises(ValueError):
        binding.bind(client, blobs)
    assert acted and row(blobs) is None and index.read_bytes() == before


def test_client_path_change_to_another_actual_same_binding_database_is_refused(
    actual, tmp_path, monkeypatch
):
    client, blobs = actual
    other = make(tmp_path / "other.sqlite")
    real = binding._store

    def changed(store):
        result = real(store)
        client.journal.path = other.journal.path
        return result

    monkeypatch.setattr(binding, "_store", changed)
    before = (blobs.root / "index.sqlite").read_bytes()
    with pytest.raises(ValueError):
        binding.bind(client, blobs)
    assert row(blobs) is None and (blobs.root / "index.sqlite").read_bytes() == before


@pytest.mark.parametrize("where", ["root", "sidecar"])
def test_actual_reparse_path_is_never_followed(actual, tmp_path, where):
    client, blobs = actual
    target = blobs.root if where == "root" else tmp_path / "sidecar-target"
    target.mkdir(exist_ok=True)
    link = tmp_path / "linked-root" if where == "root" else blobs.root / "index.sqlite-wal"
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)
    before = (blobs.root / "index.sqlite").read_bytes()
    if where == "root":
        blobs.root = link
    with pytest.raises(ValueError):
        binding.bind(client, blobs)
    assert (
        target / "index.sqlite" if where == "root" else blobs.root / "index.sqlite"
    ).read_bytes() == before


@pytest.mark.parametrize("value", [None, 1, "yes"])
def test_legacy_override_requires_explicit_boolean_without_initialization(actual, value):
    client, blobs = actual
    before = (blobs.root / "index.sqlite").read_bytes()
    with pytest.raises(ValueError):
        binding.bind(client, blobs, allow_existing=value)
    assert row(blobs) is None and (blobs.root / "index.sqlite").read_bytes() == before


def test_strict_fresh_binding_interoperates_with_maintained_transfer_and_scope_readers(actual):
    from paper_daily import raw_deck_closure
    from paper_daily.legacy_primary_migration import _store_scope

    client, blobs = actual
    identity = binding.bind(client, blobs)

    class Inert:
        def __getattr__(self, name):
            if name == "base_url":
                raise AttributeError(name)
            raise AssertionError("No transport or credential operation")

    transfer = FileTransfers(client, blobs, Inert(), origin="https://fixture.invalid", token=None)
    assert _store_scope(blobs, client.journal.path.resolve(), "workspace", "device") == identity
    with client.journal.transaction() as conn:
        admitted = raw_deck_closure._owned_store(conn, blobs)
        assert admitted.root == blobs.root
    assert binding.bind(client, blobs) == identity
    with closing(sqlite3.connect(blobs.root / "index.sqlite")) as conn:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='transfer_binding'"
        ).fetchone()[0]
    assert "CHECK(id=1)" in sql and "NOT NULL" in sql
    transfer.close()
