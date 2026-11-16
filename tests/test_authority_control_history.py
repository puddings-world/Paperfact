"""Transactional authority controls, private history and explicit legacy recovery."""

import json
import secrets
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from paper_daily import sync_admin, sync_authority_backup, sync_authority_restore
from paper_daily import sync_authority_control as control


def rows(database):
    with closing(sqlite3.connect(database)) as conn:
        return conn.execute("SELECT sequence,record,sha256 FROM sync_control_history "
                            "ORDER BY sequence").fetchall()


def test_actual_controls_have_dense_private_history_and_noop_reads_do_not_append(tmp_path):
    state = tmp_path / "service"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    assert len(rows(service.path)) == 1
    admin = service.enroll("workspace", "admin")
    code, credential = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    service.create_pairing(admin, code)
    service.redeem_pairing(code, "workspace", "mac", credential, "Mac")
    service.rename_device(admin, "mac", "Laptop")
    with ThreadPoolExecutor(max_workers=2) as pool:
        tokens = list(pool.map(lambda n: service.enroll("workspace", f"peer-{n}"), range(2)))
    service.revoke(credential)
    captured = rows(service.path)
    assert [row[0] for row in captured] == list(range(1, len(captured) + 1))
    text = json.dumps(captured)
    assert all(secret not in text for secret in [admin, code, credential, *tokens])
    reopened = sync_admin.authority(state)
    reopened.device_catalog(admin)
    reopened.rename_device(admin, "mac", "Laptop")
    reopened.revoke(credential)
    assert rows(service.path) == captured
    from paper_daily import sync_authority_history as history

    with closing(sqlite3.connect(service.path)) as conn:
        checked = history.read(conn)
    assert checked["sequence"] == len(captured)
    with closing(sqlite3.connect(service.path)) as conn:
        assert checked["state"] == history.snapshot(conn)


@pytest.mark.parametrize("damage", ["record", "truncate", "revocation", "rewrite", "schema"])
def test_corrupt_history_or_reverted_control_refuses_access_and_backup(tmp_path, damage):
    state = tmp_path / "service"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    token = service.enroll("workspace", "mac")
    service.revoke(token)
    with closing(sqlite3.connect(service.path)) as conn, conn:
        if damage == "record":
            conn.execute("UPDATE sync_control_history SET record='{}' WHERE sequence=1")
        elif damage == "truncate":
            conn.execute("DELETE FROM sync_control_history WHERE sequence="
                         "(SELECT MAX(sequence) FROM sync_control_history)")
        elif damage == "revocation":
            conn.execute("UPDATE sync_devices SET revoked=0")
        elif damage == "schema":
            conn.execute("DROP TABLE sync_pairings")
        else:
            from paper_daily import sync_authority_history as history

            previous = history.ZERO
            for sequence, raw, _digest in rows(service.path):
                value = json.loads(raw)
                if sequence == 1:
                    value["recorded_at"] = "2020-01-01T00:00:00+00:00"
                value["previous"] = previous
                previous = history._hash(value)
                conn.execute("UPDATE sync_control_history SET record=?,sha256=? WHERE sequence=?",
                             (history._encode(value), previous, sequence))
            assert history.read(conn)["sequence"] == 3
        before = tuple(conn.iterdump())
    marker = (state / sync_admin.MARKER).read_bytes()
    with pytest.raises(ValueError, match="control"):
        sync_admin.authority(state).session_info(token)
    output = tmp_path / "blocked-backup"
    with pytest.raises(ValueError, match="control"):
        sync_authority_backup.export(state, output)
    assert not (output / "manifest.json").exists()
    with closing(sqlite3.connect(service.path)) as conn:
        assert tuple(conn.iterdump()) == before
    assert (state / sync_admin.MARKER).read_bytes() == marker


def test_failed_checkpoint_rolls_back_history_and_controls_then_retry_appends_once(
    tmp_path, monkeypatch,
):
    state = tmp_path / "service"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    token = service.enroll("workspace", "mac")
    before = rows(service.path)
    marker = (state / sync_admin.MARKER).read_bytes()

    def failed(*args):
        raise OSError("Synthetic checkpoint failure")

    with monkeypatch.context() as patch:
        patch.setattr(control, "publish", failed)
        with pytest.raises(OSError):
            service.revoke(token)
    assert rows(service.path) == before and (state / sync_admin.MARKER).read_bytes() == marker
    assert sync_admin.authority(state).session_info(token)["device_id"] == "mac"
    service.revoke(token)
    assert len(rows(service.path)) == len(before) + 1
    with pytest.raises(PermissionError):
        sync_admin.authority(state).session_info(token)


def test_verified_backup_keeps_history_and_recovery_uses_new_authority_identity(tmp_path):
    from paper_daily import sync_authority_history as history

    state = tmp_path / "service"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    old = service.enroll("workspace", "mac")
    service.rename_device(old, "mac", "Laptop")
    captured = rows(service.path)
    snapshot = tmp_path / "backup"
    sync_authority_backup.export(state, snapshot)
    assert rows(snapshot / sync_admin.DATABASE) == captured
    restored = tmp_path / "restored"
    sync_authority_restore.restore(snapshot, restored, "workspace", "fresh-workspace")
    reopened = sync_admin.authority(restored)
    with pytest.raises(PermissionError):
        reopened.session_info(old)
    with closing(sqlite3.connect(service.path)) as source, closing(
        sqlite3.connect(reopened.path)
    ) as fresh:
        assert history.read(source)["authority_id"] != history.read(fresh)["authority_id"]
    assert rows(snapshot / sync_admin.DATABASE) == captured


@pytest.mark.parametrize("stale", [False, True])
def test_v3_is_backup_only_and_stale_legacy_checkpoint_is_not_blessed(tmp_path, stale):
    state = tmp_path / "legacy"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    service.enroll("workspace", "mac")
    with closing(sqlite3.connect(service.path)) as conn, conn:
        conn.execute("DROP TABLE sync_control_history")
        digest = control.state_fingerprint(conn)
        if stale:
            conn.execute("UPDATE sync_devices SET revoked=1")
    marker = sync_admin.file_marker(service.path)
    marker.update(format="paperfact-reference-service-v3", control_sha256=digest)
    (state / sync_admin.MARKER).write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(ValueError, match="Legacy"):
        sync_admin.authority(state)
    output = tmp_path / "backup"
    if stale:
        with pytest.raises(ValueError, match="control"):
            sync_authority_backup.export(state, output)
        assert not (output / "manifest.json").exists()
    else:
        sync_authority_backup.export(state, output)
        sync_authority_restore.restore(output, tmp_path / "fresh", "workspace", "recovered")
        assert sync_admin.authority(tmp_path / "fresh")


def test_control_history_budget_rejects_new_mutation_without_losing_existing_access(
    tmp_path, monkeypatch,
):
    from paper_daily import sync_authority_history as history

    state = tmp_path / "service"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    token = service.enroll("workspace", "mac")
    before = rows(service.path)
    monkeypatch.setattr(history, "MAX_RECORDS", len(before))
    with pytest.raises(ValueError, match="control"):
        service.rename_device(token, "mac", "Must not save")
    assert rows(service.path) == before
    reopened = sync_admin.authority(state)
    assert reopened.session_info(token)["device_id"] == "mac"
    assert reopened.device_catalog(token)["devices"][0]["label"] is None
    stopped = sync_authority_backup.BackupCancelled("Synthetic cancellation")

    def cancelled():
        raise stopped

    with (closing(sqlite3.connect(service.path)) as conn,
          pytest.raises(sync_authority_backup.BackupCancelled) as caught):
        history.read(conn, check=cancelled)
    assert caught.value is stopped and rows(service.path) == before



def test_control_history_does_not_coerce_prior_integer_fields(tmp_path):
    from paper_daily import sync_authority_history as history

    state = tmp_path / "service"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    token = service.enroll("workspace", "mac")
    service.rename_device(token, "mac", "Laptop")
    sequence, original, _digest = rows(service.path)[-1]
    for invalid in (False, 0.0):
        value = json.loads(original)
        value["changes"][0]["before"][3] = invalid
        with closing(sqlite3.connect(service.path)) as conn, conn:
            conn.execute("UPDATE sync_control_history SET record=?,sha256=? WHERE sequence=?",
                         (history._encode(value), history._hash(value), sequence))
            with pytest.raises(ValueError, match="control"):
                history.read(conn)


def test_official_transaction_cannot_rewrite_previously_observed_history(tmp_path):
    from paper_daily import sync_authority_history as history

    state = tmp_path / "service"
    sync_admin.initialize(state)
    service = sync_admin.authority(state)
    token = service.enroll("workspace", "mac")
    before = rows(service.path)
    marker = (state / sync_admin.MARKER).read_bytes()
    with pytest.raises(ValueError, match="control"), service._transaction(write=True) as conn:
        previous = history.ZERO
        for sequence, raw, _digest in before:
            value = json.loads(raw)
            if sequence == 1:
                value["recorded_at"] = "2020-01-01T00:00:00+00:00"
            value["previous"] = previous
            previous = history._hash(value)
            conn.execute("UPDATE sync_control_history SET record=?,sha256=? WHERE sequence=?",
                         (history._encode(value), previous, sequence))
        assert history.read(conn)["sequence"] == len(before)
    assert rows(service.path) == before
    assert (state / sync_admin.MARKER).read_bytes() == marker
    assert service.session_info(token)["device_id"] == "mac"
