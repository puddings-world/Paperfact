"""Trusted-device pairing uses synthetic credentials and isolated authorities."""

import json
import secrets
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier

import pytest
from test_sync_http import endpoint as endpoint_fixture

from paper_daily.sync_device_management import MAX_PAIRINGS, PAIRING_SECONDS
from paper_daily.sync_http import HttpTransport
from paper_daily.sync_service import ReferenceService

endpoint = endpoint_fixture


@pytest.fixture
def grant(tmp_path, monkeypatch):
    service = ReferenceService(tmp_path / "authority.sqlite")
    owner = service.enroll("workspace", "desktop")
    code, credential = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    clock = [1_000_000]
    monkeypatch.setattr(service, "_pair_now", lambda: clock[0])
    return service, owner, code, credential, clock


def claim(grant, **changes):
    service, _owner, code, credential, _clock = grant
    values = dict(workspace_id="workspace", device_id="mac", credential=credential, label="Mac")
    values.update(changes)
    return service.redeem_pairing(code, **values)


def rows(service):
    with closing(sqlite3.connect(service.path)) as conn:
        return list(conn.iterdump())


def test_pairing_creates_independent_device_once_and_stores_no_raw_secrets(grant):
    service, owner, code, credential, clock = grant
    created = service.create_pairing(owner, code)
    clock[0] += 20
    assert service.create_pairing(owner, code) == created  # No expiry extension on retry.
    assert created == {"workspace_id": "workspace", "issuer_device_id": "desktop",
                       "expires_at": 1_000_000 + PAIRING_SECONDS}
    reserved = secrets.token_urlsafe(32)
    service.create_pairing(owner, reserved)
    before = rows(service)
    for changes in ({"device_id": "desktop"}, {"credential": code}, {"credential": reserved}):
        with pytest.raises(ValueError):
            claim(grant, **changes)
        assert rows(service) == before
    assert claim(grant) == {"workspace_id": "workspace", "device_id": "mac"}
    before = rows(service)
    assert claim(grant) == service.session_info(credential)
    assert rows(service) == before
    assert all(secret not in str(before) for secret in (owner, code, credential))
    catalog = service.device_catalog(owner)
    assert len(catalog["devices"]) == 2
    assert next(row for row in catalog["devices"] if row["device_id"] == "mac")["label"] == "Mac"
    service.rename_device(owner, "mac", "Later name")
    assert claim(grant)["device_id"] == "mac"
    assert service.device_catalog(owner)["devices"][1]["label"] == "Later name"


@pytest.mark.parametrize("reason", ["expired", "issuer_revoked", "wrong_workspace", "consumed"])
def test_pairing_refuses_changed_authority_without_creating_another_device(grant, reason):
    service, owner, code, credential, clock = grant
    service.create_pairing(owner, code)
    changes = {}
    if reason == "expired":
        clock[0] += PAIRING_SECONDS
    elif reason == "issuer_revoked":
        service.revoke(owner)
    elif reason == "wrong_workspace":
        changes["workspace_id"] = "someone-else"
    else:
        claim(grant)
        changes["credential"] = secrets.token_urlsafe(32)
    before = rows(service)
    with pytest.raises(PermissionError):
        claim(grant, **changes)
    assert rows(service) == before
    if reason == "expired":
        with pytest.raises(ValueError):
            service.create_pairing(owner, code)
        assert rows(service) == before
    if reason == "consumed":
        service.revoke_peer(owner, "mac")
        with pytest.raises(PermissionError):
            claim(grant)


def test_pairing_claim_rolls_back_device_and_consumption_together(grant):
    service, owner, code, _credential, _clock = grant
    service.create_pairing(owner, code)
    with closing(sqlite3.connect(service.path)) as conn, conn:
        conn.execute("CREATE TRIGGER stop_pair BEFORE UPDATE ON sync_pairings "
                     "BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    before = rows(service)
    with pytest.raises(sqlite3.IntegrityError):
        claim(grant)
    assert rows(service) == before
    with closing(sqlite3.connect(service.path)) as conn, conn:
        conn.execute("DROP TRIGGER stop_pair")
    assert claim(grant)["device_id"] == "mac"


def test_concurrent_claims_enroll_only_one_device(grant):
    service, owner, code, _credential, _clock = grant
    service.create_pairing(owner, code)
    ready = Barrier(2)

    def attempt(index):
        ready.wait(timeout=5)
        try:
            return claim(grant, device_id="receiver-" + str(index),
                         credential=secrets.token_urlsafe(32))
        except PermissionError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (0, 1)))
    assert sum(result is not None for result in results) == 1
    assert len(service.device_catalog(owner)["devices"]) == 2


def test_pairing_quota_and_restart_are_bounded(grant, monkeypatch):
    service, owner, code, _credential, clock = grant
    import paper_daily.sync_device_management as devices

    monkeypatch.setattr(devices, "MAX_PAIRINGS", 2)
    service.create_pairing(owner, code)
    service.create_pairing(owner, secrets.token_urlsafe(32))
    before = rows(service)
    with pytest.raises(ValueError, match="Too many"):
        service.create_pairing(owner, secrets.token_urlsafe(32))
    assert rows(service) == before
    clock[0] += PAIRING_SECONDS
    service.create_pairing(owner, secrets.token_urlsafe(32))
    assert ReferenceService(service.path).session_info(owner)["device_id"] == "desktop"
    assert MAX_PAIRINGS == 100


def test_actual_http_pairing_retries_and_revocation_keep_credentials_private(endpoint):
    service, owner, url = endpoint
    code, credential = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with HttpTransport(url) as transport:
        created = transport.create_pairing(owner, code)
        assert created["workspace_id"] == "workspace" and code not in json.dumps(created)
        assert transport.create_pairing(owner, code) == created
        received = transport.redeem_pairing(code, "workspace", "mac", credential, "Mac")
        assert received == {"workspace_id": "workspace", "device_id": "mac"}
        assert transport.redeem_pairing(code, "workspace", "mac", credential, "Mac") == received
        assert transport.session_info(credential) == received
        with pytest.raises(PermissionError):
            transport.redeem_pairing(code, "workspace", "another", secrets.token_urlsafe(32))
        transport.revoke_peer(owner, "mac")
        with pytest.raises(PermissionError):
            transport.session_info(credential)
