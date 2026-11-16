"""Device-held authority knowledge stays separate from research recovery counts."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_sync_device_recovery import dump
from test_sync_device_recovery import prepared as prepared
from test_sync_recovery import research as research_fixture

from paper_daily import sync_authority_backup as backup
from paper_daily import sync_device_recovery as recovery
from paper_daily.workspace_control import ControlKnowledge

research = research_fixture


def remember(prepared, point=None):
    device, service, token, _snapshot = prepared
    with closing(sqlite3.connect(device.journal.path)) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY,value TEXT)")
    store = ControlKnowledge(device.journal.path,
                             dict(workspace_id="workspace", device_id="a"), lambda: None)
    point = point or service.control_session(token)["checkpoint"]
    store.remember(point, store.load())
    return store, point


@pytest.mark.parametrize("relation", ["included", "newer", "different", "legacy"])
def test_backup_review_reports_control_relation_without_rebinding_or_disclosing_hashes(
    prepared, tmp_path, relation,
):
    device, service, token, snapshot = prepared
    if relation == "newer":
        service.rename_device(token, "a", "Changed after backup")
    point = service.control_session(token)["checkpoint"]
    if relation == "different":
        point = dict(point, authority_id="11111111-1111-4111-8111-111111111111")
    store, point = remember(prepared, point)
    if relation == "legacy":
        # A verified historical backup can lack the newer control journal.
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        with closing(sqlite3.connect(legacy / "authority.sqlite")) as conn:
            source = sqlite3.connect(service.path)
            try:
                source.backup(conn)
            finally:
                source.close()
            conn.execute("DROP TABLE sync_control_history")
            conn.commit()
        # Mark only this synthetic copied state as a historical authority.
        from paper_daily import sync_admin
        (legacy / sync_admin.MARKER).write_text(
            json.dumps(sync_admin.LEGACY_FORMAT), encoding="utf-8")
        backup.export(legacy, tmp_path / "legacy-backup")
        snapshot = tmp_path / "legacy-backup"
    before = dump(device.journal.path)
    result = recovery.review(device.journal.path, snapshot, "workspace")
    expected = {"included": "included", "newer": "backup_older",
                "different": "different_authority", "legacy": "unavailable"}[relation]
    assert result["control_history"]["state"] == expected
    assert result["control_history"]["device_sequence"] == point["sequence"]
    assert not result["requires_preservation"] and not result["replayed"]
    assert dump(device.journal.path) == before and store.load() == point
    assert point["sha256"] not in json.dumps(result)
    assert point["authority_id"] not in json.dumps(result)


@pytest.mark.parametrize("damage", ["malformed", "fork"])
def test_invalid_or_divergent_device_knowledge_cannot_be_reported_as_backed_up(prepared, damage):
    store, point = remember(prepared)
    if damage == "malformed":
        value = "{invalid JSON"
    else:
        value = json.dumps(dict(format="paperfact.device-control-knowledge.v1",
                                workspace="workspace", device="a",
                                checkpoint=dict(point, sha256="0" * 64)))
    with closing(sqlite3.connect(prepared[0].journal.path)) as conn, conn:
        conn.execute("UPDATE kv SET value=? WHERE key=?", (value, store.key))
    before = dump(prepared[0].journal.path)
    with pytest.raises(ValueError):
        recovery.review(prepared[0].journal.path, prepared[3], "workspace")
    assert dump(prepared[0].journal.path) == before


def test_fresh_authority_restore_and_http_join_keep_old_trust_and_unsent_work(research, tmp_path):
    from test_sync_http import running

    from paper_daily import sync_admin, sync_authority_restore, sync_bootstrap
    from paper_daily.sync_http import HttpTransport, make_server
    from paper_daily.workspace_service import Ticket
    from paper_daily.workspace_sync import EnrollmentRequired, SyncSession

    database, client, *_ = research
    old_identity = dict(workspace_id="workspace", device_id="origin-device")
    root = tmp_path / "original-authority"
    sync_admin.initialize(root)
    authority = sync_admin.authority(root)
    token = authority.enroll(**old_identity)
    client.sync_once(authority, token)
    old = ControlKnowledge(database, old_identity, lambda: None)
    old.remember(authority.control_session(token)["checkpoint"], None)
    snapshot = tmp_path / "safe-backup"
    backup.export(root, snapshot)
    authority.rename_device(token, "origin-device", "Changed after backup")
    old.remember(authority.control_session(token)["checkpoint"], old.load())
    retained = old.load()
    client.save(client.new_graph_operation(
        "list", "after-backup", dict(name="Unsent work", note="")))
    pending = client.journal.pending()
    assert pending
    state = tmp_path / "fresh-authority"
    sync_authority_restore.restore(snapshot, state, "workspace", "fresh-workspace")
    restored = sync_admin.authority(state)
    fresh_identity = dict(workspace_id="fresh-workspace", device_id="fresh-mac")
    fresh_token = restored.enroll(**fresh_identity)
    destination = tmp_path / "fresh-device"
    with running(make_server(restored)) as endpoint:
        with HttpTransport(endpoint) as raw, pytest.raises(PermissionError):
            raw.session_info(token)
        session = SyncSession(database)
        session.connect(endpoint, **fresh_identity, token=fresh_token, ticket=Ticket())
        with pytest.raises(EnrollmentRequired):
            session.sync(Ticket())
        result = sync_bootstrap.join(session, destination, Ticket())
        assert result["state"] == "metadata_ready"
        joined = SyncSession(destination / "papers.db")
        joined.connect(endpoint, **fresh_identity, token=fresh_token, ticket=Ticket())
        point = ControlKnowledge(destination / "papers.db", fresh_identity, lambda: None).load()
        assert point["authority_id"] != retained["authority_id"]
        assert joined.summary()["authenticated"]
    assert old.load() == retained and client.journal.pending() == pending
    with closing(sqlite3.connect(destination / "papers.db")) as conn:
        assert conn.execute("SELECT count(*) FROM notes").fetchone()[0] > 0
        assert not conn.execute("SELECT 1 FROM lists WHERE name='Unsent work'").fetchone()
