"""Native pairing state, lost replies and destination-only credential persistence."""

import secrets
import shutil
import sqlite3
from contextlib import closing

import pytest
from test_connection_vault import FakeVault
from test_workspace_sync import Native, connect
from test_workspace_sync import enrolled as enrolled_fixture
from test_workspace_sync import research as research_fixture
from test_workspace_sync import service as service_fixture

from paper_daily import sync_bootstrap
from paper_daily.connection_vault import ConnectionVault, PendingPairingExists, VaultUnavailable
from paper_daily.store import SCHEMA
from paper_daily.sync_pairing import Attempt, Invitation, remember_joined
from paper_daily.workspace_service import Cancelled, Ticket, WorkspaceChanged
from paper_daily.workspace_sync import EnrollmentRequired, SyncSession

research = research_fixture
enrolled = enrolled_fixture
service = service_fixture


@pytest.fixture
def receiver(service, tmp_path):
    path = tmp_path / "receiver-source" / "papers.db"
    path.parent.mkdir()
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(SCHEMA)
    backend, calls = FakeVault(), []

    def factory(url):
        return Native(url, service[1], calls)

    session = SyncSession(path, transport_factory=factory)
    vault = ConnectionVault(
        session.workspace, backend=lambda: backend, startup_dir=tmp_path / "local-settings"
    )
    code = secrets.token_urlsafe(32)
    result = service[1].create_pairing(service[2], code)
    invitation = Invitation("http://127.0.0.1:8765", code=code, **result)
    return session, vault, backend, invitation, factory, calls


def test_lost_claim_response_resumes_same_device_after_restart_and_expiry(
    receiver, service, monkeypatch
):
    session, vault, backend, invitation, factory, calls = receiver
    before = session.workspace.path.read_bytes()
    attempt = vault.prepare_pairing(invitation)
    assert vault.prepare_pairing(invitation) == attempt
    assert invitation.code not in repr(invitation) and attempt.credential not in repr(attempt)
    original = service[1].redeem_pairing

    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise ConnectionError("synthetic lost response")

    monkeypatch.setattr(service[1], "redeem_pairing", lost)
    with pytest.raises(ConnectionError):
        attempt.connect(session, Ticket())
    assert len(service[1].device_catalog(service[2])["devices"]) == 2
    fresh = SyncSession(session.workspace.path, transport_factory=factory)
    reopened = ConnectionVault(fresh.workspace, backend=lambda: backend)
    resumed = reopened.load_pairing()
    assert resumed == attempt
    monkeypatch.setattr(service[1], "_pair_now", lambda: invitation.expires_at + 1)
    resumed.connect(fresh, Ticket())  # Already-admitted credentials survive invite expiry.
    reopened.complete_pairing(fresh, resumed)
    reopened.complete_pairing(fresh, resumed)
    assert reopened.load() == resumed.connection and reopened.load_pairing() is None
    assert calls.count("redeem_pairing") == 1 and fresh.summary()["authenticated"]
    assert session.workspace.path.read_bytes() == before


def test_saved_attempt_refuses_replacement_and_never_follows_a_copied_database(receiver, tmp_path):
    session, vault, backend, invitation, _factory, _calls = receiver
    attempt = vault.prepare_pairing(invitation)
    other = Invitation(
        invitation.endpoint,
        invitation.workspace_id,
        invitation.issuer_device_id,
        invitation.expires_at,
        secrets.token_urlsafe(32),
    )
    with pytest.raises(PendingPairingExists):
        vault.prepare_pairing(other)
    copied = tmp_path / "copied.sqlite"
    shutil.copyfile(session.workspace.path, copied)
    clone = ConnectionVault(SyncSession(copied).workspace, backend=lambda: backend)
    assert clone.load_pairing() is None and clone.account != vault.account
    assert vault.load_pairing() == attempt
    vault.forget()
    assert vault.load_pairing() is None


def test_cancelled_native_save_has_no_pending_grant_or_enrollment(receiver, service):
    _session, vault, backend, invitation, _factory, _calls = receiver
    ticket = Ticket()
    backend.after_write = ticket.cancel
    with pytest.raises(Cancelled):
        vault.prepare_pairing(invitation, ticket)
    assert vault.load_pairing() is None
    assert len(service[1].device_catalog(service[2])["devices"]) == 1


def test_unavailable_native_store_does_not_enroll_a_device(receiver, service):
    _session, vault, _backend, invitation, _factory, calls = receiver
    vault._backend = lambda: (_ for _ in ()).throw(RuntimeError("synthetic unavailable"))
    with pytest.raises(VaultUnavailable):
        vault.prepare_pairing(invitation)
    assert not calls and len(service[1].device_catalog(service[2])["devices"]) == 1


def test_pairing_cannot_replace_the_identity_of_enrolled_local_research(receiver, service):
    _session, _vault, _backend, invitation, _factory, _calls = receiver
    connect(service)
    before = service[0].workspace.path.read_bytes()
    with pytest.raises(EnrollmentRequired):
        Attempt.start(invitation).connect(service[0], Ticket())
    assert len(service[1].device_catalog(service[2])["devices"]) == 1
    assert service[0].workspace.path.read_bytes() == before


def test_joined_workspace_gets_its_own_verified_vault_entry_without_rebinding_source(
    receiver, service, tmp_path, monkeypatch
):
    session, vault, backend, invitation, factory, _calls = receiver
    connect(service)
    service[0].sync(Ticket())
    attempt = vault.prepare_pairing(invitation)
    attempt.connect(session, Ticket())
    vault.complete_pairing(session, attempt)
    before = session.workspace.path.read_bytes()
    destination = tmp_path / "joined"
    assert sync_bootstrap.join(session, destination, Ticket())["state"] == "metadata_ready"
    remember_joined(
        session,
        destination,
        Ticket(),
        vault_factory=lambda workspace: ConnectionVault(workspace, backend=lambda: backend),
    )
    target = SyncSession(destination / "papers.db", transport_factory=factory)
    remembered = ConnectionVault(target.workspace, backend=lambda: backend)
    assert remembered.account != vault.account and remembered.load() == attempt.connection
    record = remembered.load()
    target.connect(record.endpoint, record.workspace_id, record.device_id, record.token, Ticket())
    assert target.summary()["authenticated"]
    assert session.workspace.path.read_bytes() == before
    assert not remembered.startup_record()  # Saving credentials is not startup upload consent.

    import os

    from paper_daily import workspace_sync

    saved_rows = dict(backend.rows)
    actual = SyncSession

    def replaced(database, **kwargs):
        replacement = database.with_name("replacement.sqlite")
        shutil.copyfile(database, replacement)
        os.replace(replacement, database)
        return actual(database, **kwargs)

    monkeypatch.setattr(workspace_sync, "SyncSession", replaced)
    with pytest.raises(WorkspaceChanged):
        remember_joined(
            session,
            destination,
            Ticket(),
            vault_factory=lambda workspace: ConnectionVault(workspace, backend=lambda: backend),
        )
    assert backend.rows == saved_rows
