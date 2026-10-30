"""Only an explicit observed source-bound restore creates a new incarnation."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_claim_jobs import claims as _claims
from test_claim_jobs import job
from test_claim_jobs import ready as _ready
from test_claim_jobs import workspace as _workspace
from test_research_generation import rows

from paper_daily import annotation_reader, claim_jobs, llm, sync_capture
from paper_daily import research_generation as generation
from paper_daily.ai_types import Completion
from paper_daily.claim_jobs import ClaimJob
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare, research_writer
from paper_daily.sync_service import ReferenceService

claims = _claims
ready = _ready
workspace = _workspace


def deleted(claims):
    assert job(claims).run().status == "accepted"
    with closing(generation._connect(claims[0][0])) as conn:
        observed = sync_capture.observe_target(conn, "paper", "paper", "claims", "main")
        with sync_capture.expecting(conn, [observed]):
            conn.execute("DELETE FROM paper_claim_sets WHERE paper_id='paper'")
            conn.commit()


def restore_job(claims):
    return ClaimJob.capture(
        claims[0][0], "paper", legacy_root=claims[0][2].path.parent, restore_deleted=True
    )


def peer(claims, tmp_path):
    client = claims[0][1]
    path = tmp_path / "peer.sqlite"
    from paper_daily.store import SCHEMA

    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
    prepare(path, workspace_id="workspace", device_id="peer")
    receiver = SyncClient(
        Journal(path, workspace_id="workspace", device_id="peer"), research_writer
    )
    service = ReferenceService(
        tmp_path / "authority.sqlite", blob_root=tmp_path / "authority-blobs")
    token = service.enroll("workspace", "device")
    peer_token = service.enroll("workspace", "peer")
    from paper_daily.sync_blobs import BlobStore
    from paper_daily.sync_file_transfers import FileTransfers

    sender = FileTransfers(client, BlobStore(client.journal.path.parent / "blobs"), service,
                           origin="https://fixture.invalid", token=token)
    for operation in client.journal.pending():
        if operation["entity_type"] == "research_file":
            for _ in range(20):
                if sender.upload(operation)["state"] == "uploaded":
                    break
            else:
                pytest.fail("Source transfer did not finish")
    client.sync_once(service, token, prepare_push=sender.ready_to_push)
    receiver.sync_once(service, peer_token)
    with closing(generation._connect(path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="peer")
        conn.commit()
    return receiver, service, token, peer_token


def test_default_and_force_without_restore_never_spend_or_resurrect(claims):
    deleted(claims)
    for force in (False, True):
        value, reason = claim_jobs.ensure(
            claims[0][0], "paper", legacy_root=claims[0][2].path.parent, force=force
        )
        assert value == {"claims": [], "known": True} and "deleted" in reason
    with pytest.raises(ValueError, match="explicit restoration"):
        job(claims)
    assert len(claims[2]) == 1
    assert rows(claims[0][0], "SELECT * FROM paper_claim_sets") == []


def test_explicit_restore_retry_and_real_peer_convergence(claims, tmp_path):
    deleted(claims)
    receiver = service = token = peer_token = None
    if claims[0][1]:
        receiver, service, token, peer_token = peer(claims, tmp_path)
        before = claims[0][1].journal.pending()
        with closing(generation._connect(claims[0][0])) as conn:
            tombstone = sync_capture.observe_target(conn, "paper", "paper", "claims", "main")
    current = restore_job(claims)
    result = current.run()
    assert result.status == "accepted" and current.run() == result
    assert len(claims[2]) == 2
    saved = rows(claims[0][0], "SELECT * FROM paper_claim_sets")
    assert len(saved) == 1
    if claims[0][1]:
        pending = claims[0][1].journal.pending()
        assert len(pending) == len(before) + 1
        operation = pending[-1]
        assert operation["incarnation"] != tombstone["incarnation"]
        claims[0][1].sync_once(service, token)
        receiver.sync_once(service, peer_token)
        remote = rows(
            receiver.journal.path,
            "SELECT body_json,source_hash,document_hash,written_at FROM paper_claim_sets",
        )
        assert remote == [{key: value for key, value in saved[0].items() if key != "paper_id"}]


@pytest.mark.parametrize("change", ["source", "inputs", "tombstone"])
def test_restore_never_overwrites_changes_during_model_work(claims, monkeypatch, change):
    deleted(claims)
    current = restore_job(claims)
    complete = llm.complete_result

    def changed(*args, **kwargs):
        response = complete(*args, **kwargs)
        if change == "source":
            claims[0][2].path.write_bytes(b"replacement original")
        else:
            with (
                closing(generation._connect(claims[0][0])) as conn,
                conn,
                sync_capture.suppress_capture(conn),
            ):
                if change == "inputs":
                    conn.execute(
                        "UPDATE dives SET body='Newer study analysis' WHERE paper_id='paper'"
                    )
                else:
                    conn.execute("DELETE FROM paper_annotation_known WHERE feature='claims'")
        return response

    monkeypatch.setattr(llm, "complete_result", changed)
    assert current.run().status == "candidate"
    assert rows(claims[0][0], "SELECT * FROM paper_claim_sets") == []
    assert current.result is not None and current.context.data["claim_restore"] is True


def test_restore_storage_failure_rolls_back_incarnation_sql_and_outbox(claims):
    deleted(claims)
    before = claims[0][1].journal.pending() if claims[0][1] else None
    with closing(sqlite3.connect(claims[0][0])) as conn, conn:
        conn.execute(
            "CREATE TRIGGER break_restore BEFORE INSERT ON paper_claim_sets "
            "BEGIN SELECT RAISE(ABORT,'fixture failure'); END"
        )
    current = restore_job(claims)
    assert current.run().status == "candidate"
    assert rows(claims[0][0], "SELECT * FROM paper_claim_sets") == []
    if claims[0][1]:
        assert claims[0][1].journal.pending() == before
        with closing(generation._connect(claims[0][0])) as conn:
            assert not sync_capture.observe_target(conn, "paper", "paper", "claims", "main")[
                "active"
            ]
    assert generation.list_recovery_requests(claims[0][0])


def test_empty_model_result_is_failure_and_preserves_the_last_set(claims, monkeypatch):
    assert job(claims).run().status == "accepted"
    before = rows(claims[0][0], "SELECT * FROM paper_claim_sets")
    calls = []

    def empty(*args, **kwargs):
        calls.append(True)
        return Completion(json.dumps({"claims": []}))

    monkeypatch.setattr(llm, "complete_result", empty)
    with pytest.raises(ValueError, match="no usable claims"):
        job(claims).run()
    assert rows(claims[0][0], "SELECT * FROM paper_claim_sets") == before
    assert calls == [True]


def test_explicit_restore_refuses_a_newer_already_present_set_before_ai(claims):
    assert job(claims).run().status == "accepted"
    with pytest.raises(ValueError, match="Claims changed since deletion"):
        restore_job(claims)
    assert len(claims[2]) == 1


def test_concurrent_peer_restore_wins_without_overwrite_from_older_completion(
    claims, monkeypatch, tmp_path
):
    deleted(claims)
    if claims[0][1] is None:
        # The corresponding unbound absence-to-presence CAS is exercised by a
        # second explicitly captured result; no remote state exists in this mode.
        first = restore_job(claims)
        other = restore_job(claims)
        assert other.run().status == "accepted"
        before = rows(claims[0][0], "SELECT * FROM paper_claim_sets")
        with pytest.raises(ValueError, match="changed before AI"):
            first.run()
        assert rows(claims[0][0], "SELECT * FROM paper_claim_sets") == before
        return
    receiver, service, token, peer_token = peer(claims, tmp_path)
    with (
        closing(generation._connect(receiver.journal.path)) as conn,
        conn,
        sync_capture.suppress_capture(conn),
    ):
        local = conn.execute("SELECT id FROM papers").fetchone()[0]
        for table in ("dives", "close_readings"):
            original = rows(claims[0][0], "SELECT * FROM " + table)[0]
            original["paper_id"] = local
            columns = list(original)
            conn.execute(
                "INSERT INTO "
                + table
                + "("
                + ",".join(columns)
                + ") VALUES("
                + ",".join("?" for _ in columns)
                + ")",
                tuple(original.values()),
            )
    from paper_daily.fetch import _safe_name

    root = tmp_path / "peer-pdf"
    root.mkdir()
    (root / (_safe_name(local) + ".pdf")).write_bytes(claims[0][2].path.read_bytes())
    other = ClaimJob.capture(receiver.journal.path, local, legacy_root=root, restore_deleted=True)
    first = restore_job(claims)
    complete = llm.complete_result
    entered = []

    def racing(*args, **kwargs):
        response = complete(*args, **kwargs)
        if not entered:
            entered.append(True)
            assert other.run().status == "accepted"
            receiver.sync_once(service, peer_token)
            claims[0][1].sync_once(service, token)
            return response
        payload = json.loads(response.text)
        payload["claims"][0]["text"] = "A newer peer appraisal of the same source."
        return Completion(json.dumps(payload), model="returned")

    monkeypatch.setattr(llm, "complete_result", racing)
    assert first.run().status == "candidate"
    saved = annotation_reader.saved(claims[0][0], "paper", "claims")
    assert saved["report"]["claims"][0]["text"] == "A newer peer appraisal of the same source."
    assert not claims[0][1].journal.pending()
