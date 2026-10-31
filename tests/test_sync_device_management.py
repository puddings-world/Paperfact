"""Single-owner device management checks with synthetic workspaces and no network."""

import hashlib
import sqlite3
from contextlib import closing, contextmanager

import pytest

from paper_daily.sync_device_management import CurrentDeviceError, UnknownDeviceError
from paper_daily.sync_service import ReferenceService

OLD_DEVICE_SCHEMA = (
    "CREATE TABLE sync_devices ("
    "token_hash TEXT PRIMARY KEY, workspace TEXT NOT NULL, device TEXT NOT NULL, "
    "revoked INTEGER NOT NULL DEFAULT 0, UNIQUE(workspace,device))"
)


def operation(identity="op-1", *, device="device-a", body="Research observation"):
    return {
        "version": 1,
        "operation_id": identity,
        "workspace_id": "workspace-a",
        "device_id": device,
        "entity_type": "note",
        "entity_id": "note-" + identity,
        "action": "put",
        "base_revision": 0,
        "depends_on": None,
        "payload": {"paper_id": "paper-example", "body": body},
    }


class _Connection:
    def __init__(self, conn, owner):
        self._conn, self._owner = conn, owner

    def execute(self, sql, parameters=()):
        self._owner.statements.append((sql, parameters))
        cursor = self._conn.execute(sql, parameters)
        if self._owner.fail_after_update and sql.startswith("UPDATE sync_devices"):
            raise RuntimeError("Injected authority failure")
        return cursor


class InstrumentedService(ReferenceService):
    """Records statements and can fail after a device update, before commit."""

    statements = None
    fail_after_update = False

    @contextmanager
    def _transaction(self, *, write=False):
        with super()._transaction(write=write) as conn:
            yield conn if self.statements is None else _Connection(conn, self)


@pytest.fixture
def service(tmp_path):
    return ReferenceService(tmp_path / "service.sqlite")


def device_rows(path):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(
            "SELECT token_hash,workspace,device,revoked,label FROM sync_devices "
            "ORDER BY workspace,device"
        ).fetchall()


def research_snapshot(path):
    with closing(sqlite3.connect(path)) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name!='sync_devices' "
                "ORDER BY name"
            )
        ]
        return {table: sorted(conn.execute(f'SELECT * FROM "{table}"')) for table in tables}


def secrets_of(*tokens):
    return [
        value
        for token in tokens
        for value in (token, hashlib.sha256(token.encode()).hexdigest())
    ]


def test_catalog_is_closed_sorted_and_never_exposes_credentials(service):
    tokens = [service.enroll("workspace-a", device) for device in ("phone", "desktop", "laptop")]
    service.revoke(tokens[2])
    catalog = service.device_catalog(tokens[0])
    assert catalog == {
        "workspace_id": "workspace-a",
        "current_device_id": "phone",
        "devices": [
            {"device_id": "desktop", "label": None, "revoked": False},
            {"device_id": "laptop", "label": None, "revoked": True},
            {"device_id": "phone", "label": None, "revoked": False},
        ],
        "next_cursor": None,
    }
    assert all(type(device["revoked"]) is bool for device in catalog["devices"])
    for secret in secrets_of(*tokens):
        assert secret not in repr(catalog)


def test_catalog_pagination_uses_strict_cursor_and_reads_at_most_limit_plus_one(tmp_path):
    service = InstrumentedService(tmp_path / "service.sqlite")
    token = service.enroll("workspace-a", "device-c")
    for device in ("device-a", "device-b", "device-d", "device-e"):
        service.enroll("workspace-a", device)
    service.enroll("workspace-b", "device-aa")
    service.statements = []

    pages, after = [], None
    while True:
        page = service.device_catalog(token, after=after, limit=2)
        pages.append([device["device_id"] for device in page["devices"]])
        after = page["next_cursor"]
        if after is None:
            break
    assert pages == [["device-a", "device-b"], ["device-c", "device-d"], ["device-e"]]
    reads = [params for sql, params in service.statements if "ORDER BY device LIMIT" in sql]
    assert reads and all(params[-1] == 3 for params in reads)
    assert not any("SELECT token_hash" in sql or "SELECT *" in sql for sql, _ in service.statements)

    # Exactly-full final page has no cursor; cursors need not name an existing device.
    assert service.device_catalog(token, after="device-c", limit=2)["next_cursor"] is None
    tail = service.device_catalog(token, after="device-bb", limit=100)
    assert [d["device_id"] for d in tail["devices"]] == ["device-c", "device-d", "device-e"]
    assert service.device_catalog(token, after="device-e")["devices"] == []


@pytest.mark.parametrize("limit", [0, 101, -1, True, False, 1.0, "5", None])
def test_catalog_rejects_invalid_limits(service, limit):
    token = service.enroll("workspace-a", "device-a")
    with pytest.raises(ValueError):
        service.device_catalog(token, limit=limit)


@pytest.mark.parametrize("after", ["", "has space", "x" * 129, "new\nline", 5, b"device-a", True])
def test_catalog_rejects_invalid_cursors(service, after):
    token = service.enroll("workspace-a", "device-a")
    with pytest.raises(ValueError):
        service.device_catalog(token, after=after)


def test_management_is_scoped_to_caller_workspace(service):
    a = service.enroll("workspace-a", "device-a")
    a_peer = service.enroll("workspace-a", "device-b")
    b = service.enroll("workspace-b", "device-x")
    b_same_id = service.enroll("workspace-b", "device-a")

    assert [d["device_id"] for d in service.device_catalog(b)["devices"]] == [
        "device-a",
        "device-x",
    ]
    with pytest.raises(UnknownDeviceError) as foreign:
        service.revoke_peer(b, "device-b")
    with pytest.raises(UnknownDeviceError) as missing:
        service.revoke_peer(b, "never-enrolled")
    assert str(foreign.value) == str(missing.value)
    with pytest.raises(UnknownDeviceError):
        service.rename_device(b, "device-b", "Not yours")

    # A colliding device ID only ever resolves inside the caller's workspace.
    service.rename_device(b, "device-a", "Workspace B tablet")
    assert service.revoke_peer(b, "device-a")["changed"] is True
    with pytest.raises(PermissionError):
        service.session_info(b_same_id)
    assert service.session_info(a) == {"workspace_id": "workspace-a", "device_id": "device-a"}
    assert service.session_info(a_peer)["device_id"] == "device-b"
    assert service.device_catalog(a)["devices"] == [
        {"device_id": "device-a", "label": None, "revoked": False},
        {"device_id": "device-b", "label": None, "revoked": False},
    ]


@pytest.mark.parametrize("token", ["", "unknown", None, 123, "x" * 4097])
def test_wrong_credentials_cannot_query_or_manage(service, token):
    service.enroll("workspace-a", "device-a")
    before = device_rows(service.path)
    with pytest.raises(PermissionError):
        service.device_catalog(token)
    with pytest.raises(PermissionError):
        service.rename_device(token, "device-a", "Label")
    with pytest.raises(PermissionError):
        service.revoke_peer(token, "device-a")
    assert device_rows(service.path) == before


@pytest.mark.parametrize("revoke_with", ["admin", "peer"])
def test_revoked_callers_cannot_query_or_manage(service, revoke_with):
    caller = service.enroll("workspace-a", "device-a")
    peer = service.enroll("workspace-a", "device-b")
    if revoke_with == "admin":
        service.revoke(caller)
    else:
        service.revoke_peer(peer, "device-a")
    before = device_rows(service.path)
    with pytest.raises(PermissionError):
        service.device_catalog(caller)
    # Authentication precedes input validation, so invalid input still sees PermissionError.
    with pytest.raises(PermissionError):
        service.device_catalog(caller, limit=0)
    with pytest.raises(PermissionError):
        service.rename_device(caller, "device-b", "Label")
    with pytest.raises(PermissionError):
        service.rename_device(caller, "bad id", "\n")
    with pytest.raises(PermissionError):
        service.revoke_peer(caller, "device-b")
    assert device_rows(service.path) == before
    assert service.session_info(peer)["device_id"] == "device-b"


def test_current_device_cannot_revoke_itself(service):
    token = service.enroll("workspace-a", "device-a")
    service.enroll("workspace-a", "device-b")
    before = device_rows(service.path)
    with pytest.raises(CurrentDeviceError, match="Disconnect"):
        service.revoke_peer(token, "device-a")
    assert device_rows(service.path) == before
    assert service.session_info(token)["device_id"] == "device-a"
    # Labelling the current device is allowed.
    assert service.rename_device(token, "device-a", "This laptop")["changed"] is True


def test_revoke_peer_is_idempotent_and_preserves_research_and_cursors(service):
    a = service.enroll("workspace-a", "device-a")
    b = service.enroll("workspace-a", "device-b")
    service.push(a, operation("op-a"))
    service.push(b, operation("op-b", device="device-b", body="Phone observation"))
    events = service.pull(a)
    research = research_snapshot(service.path)

    first = service.revoke_peer(a, "device-b")
    second = service.revoke_peer(a, "device-b")
    assert first == {"device_id": "device-b", "revoked": True, "changed": True}
    assert second == {"device_id": "device-b", "revoked": True, "changed": False}
    for secret in secrets_of(a, b):
        assert secret not in repr((first, second))

    with pytest.raises(PermissionError):
        service.pull(b)
    with pytest.raises(PermissionError):
        service.push(b, operation("op-b2", device="device-b"))
    service.revoke(b)  # trusted admin revocation stays safe to repeat
    with pytest.raises(ValueError, match="already enrolled"):
        service.enroll("workspace-a", "device-b")

    assert research_snapshot(service.path) == research
    assert service.pull(a) == events
    assert service.pull(a, after=1) == events[1:]
    replacement = service.enroll("workspace-a", "device-b2")
    assert service.pull(replacement) == events


def test_unknown_or_invalid_targets_fail_without_changes(service):
    token = service.enroll("workspace-a", "device-a")
    before = device_rows(service.path)
    for target in ("missing", "", "has space", None, 7, "x" * 129):
        with pytest.raises(ValueError):
            service.revoke_peer(token, target)
        with pytest.raises(ValueError):
            service.rename_device(token, target, "Label")
    assert device_rows(service.path) == before


@pytest.mark.parametrize(
    "label",
    [
        "Lab desktop",
        "研究室のノート",
        "Café ☕ bench",
        "👩‍🔬 field tablet",
        "é" * 64,
        "a",
    ],
)
def test_unicode_labels_round_trip(service, label):
    token = service.enroll("workspace-a", "device-a")
    service.enroll("workspace-a", "device-b")
    assert service.rename_device(token, "device-b", label) == {
        "device_id": "device-b",
        "label": label,
        "changed": True,
    }
    assert service.rename_device(token, "device-b", label)["changed"] is False
    assert service.device_catalog(token)["devices"][1]["label"] == label
    assert service.rename_device(token, "device-b", None) == {
        "device_id": "device-b",
        "label": None,
        "changed": True,
    }
    assert service.device_catalog(token)["devices"][1]["label"] is None


@pytest.mark.parametrize(
    "label",
    [
        "",
        " leading",
        "trailing ",
        "x" * 65,
        "line\nbreak",
        "carriage\rreturn",
        "tab\tlabel",
        "nul\x00byte",
        "escape\x1b[31m",
        "delete\x7f",
        "next\x85line",
        "line separator",
        "paragraph separator",
        "spoof‮evil",
        "isolate⁦x⁩",
        "lone\ud800surrogate",
        123,
        b"bytes",
        ["list"],
    ],
)
def test_invalid_labels_are_rejected_without_changes(service, label):
    token = service.enroll("workspace-a", "device-a")
    service.rename_device(token, "device-a", "Original")
    before = device_rows(service.path)
    with pytest.raises(ValueError):
        service.rename_device(token, "device-a", label)
    assert device_rows(service.path) == before


@pytest.mark.parametrize("action", ["rename", "revoke"])
def test_injected_failure_rolls_back_device_changes(tmp_path, action):
    service = InstrumentedService(tmp_path / "service.sqlite")
    a = service.enroll("workspace-a", "device-a")
    b = service.enroll("workspace-a", "device-b")
    service.rename_device(a, "device-b", "Original")
    before = device_rows(service.path)
    service.statements, service.fail_after_update = [], True
    with pytest.raises(RuntimeError, match="Injected"):
        if action == "rename":
            service.rename_device(a, "device-b", "Changed")
        else:
            service.revoke_peer(a, "device-b")
    assert any(sql.startswith("UPDATE sync_devices") for sql, _ in service.statements)
    assert device_rows(service.path) == before
    restarted = ReferenceService(service.path)
    assert restarted.session_info(b)["device_id"] == "device-b"
    assert restarted.device_catalog(a)["devices"][1] == {
        "device_id": "device-b",
        "label": "Original",
        "revoked": False,
    }


def test_old_authority_schema_upgrades_lazily_and_keeps_credentials(tmp_path):
    path = tmp_path / "old-authority.sqlite"
    active, revoked = "old-active-credential", "old-revoked-credential"
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            conn.execute(OLD_DEVICE_SCHEMA)
            conn.executemany(
                "INSERT INTO sync_devices(token_hash,workspace,device,revoked) VALUES(?,?,?,?)",
                [
                    (hashlib.sha256(active.encode()).hexdigest(), "workspace-a", "desktop", 0),
                    (hashlib.sha256(revoked.encode()).hexdigest(), "workspace-a", "old-phone", 1),
                ],
            )
        before = conn.execute(
            "SELECT token_hash,workspace,device,revoked FROM sync_devices ORDER BY device"
        ).fetchall()

    service = ReferenceService(path)
    with closing(sqlite3.connect(path)) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(sync_devices)")]
        after = conn.execute(
            "SELECT token_hash,workspace,device,revoked FROM sync_devices ORDER BY device"
        ).fetchall()
        version = conn.execute("PRAGMA schema_version").fetchone()[0]
    assert columns == ["token_hash", "workspace", "device", "revoked", "label"]
    assert after == before

    ReferenceService(path)  # repeated initialization does not alter the schema again
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA schema_version").fetchone()[0] == version

    assert service.session_info(active) == {"workspace_id": "workspace-a", "device_id": "desktop"}
    with pytest.raises(PermissionError):
        service.session_info(revoked)
    assert service.device_catalog(active)["devices"] == [
        {"device_id": "desktop", "label": None, "revoked": False},
        {"device_id": "old-phone", "label": None, "revoked": True},
    ]
    assert service.revoke_peer(active, "old-phone")["changed"] is False

    # Trusted admin seams keep their original signatures and semantics.
    added = service.enroll("workspace-a", "new-tablet")
    assert service.device_catalog(added)["current_device_id"] == "new-tablet"
    service.revoke(added)
    service.revoke(added)
    with pytest.raises(PermissionError):
        service.device_catalog(added)
