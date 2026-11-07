"""Real cancelled-result and remote-conflict claim edits survive offline return."""

import json
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_claim_draft_application import claims as claims
from test_claim_draft_application import ready as ready
from test_claim_draft_application import receiver as receiver
from test_claim_draft_application import scene as scene
from test_claim_draft_application import source_pair as source_pair
from test_claim_draft_application import workspace as workspace
from test_claim_draft_storage import rows
from test_claim_jobs import job
from test_claim_review_operations import invoke
from test_enrollment_history_peer import peer
from test_note_review_continuity import backup, live_count

from paper_daily import claim_content, store, sync_content, sync_recovery
from paper_daily import research_generation as generation
from paper_daily.document_reader import DocumentReader
from paper_daily.research_review import encode
from paper_daily.sync_client import SyncClient
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import research_writer

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


def scientific(value):
    return json.loads(rows(value, "SELECT body_json FROM paper_claim_sets")[0]["body_json"])


def typed_edit(value, text):
    review = value["review"]
    origin = value["preview"].data["id"]
    target = value["preview"].data["expected"]["paper_id"]
    preview, raw = review.select_claim_draft(review.preview("archived_draft", origin), target)
    draft = json.loads(raw)
    draft["claims"][0]["text"] = text
    checked = review.verify_claim_draft(preview, encode(draft))
    body = review.claim_draft_report(checked)
    row = dict(
        paper_id=target,
        body_json=encode(body),
        document_hash=value["source_hash"],
        source_hash=claim_content.source_digest(body["inputs"], value["source_hash"]),
        written_at="2026-11-02T01:00:00+00:00",
    )
    with closing(generation._connect(value["path"])) as conn:
        return sync_content.content_payload(conn, "paper_claim_sets", row)


def test_cancelled_completed_claim_sidecar_can_be_privately_edited_and_applied(claims):
    assert job(claims).run().status == "accepted"
    current = job(claims)
    calls = len(claims[2])
    outcome = current.run(cancelled=lambda: len(claims[2]) > calls)
    assert outcome.status == "candidate"
    before = scientific(claims[0][0])
    listed = invoke("list")
    origins = [
        item["origin_id"] for item in listed["items"] if item["origin_id"].startswith("sidecar:")
    ]
    assert len(origins) == 1
    origin = origins[0]
    inspected = invoke("inspect", origin_id=origin)
    assert not inspected["can_apply"]
    opened = invoke("open", origin_id=origin, target_id="paper", operation_id="sidecar-open")
    draft = invoke("read", draft_id=opened["draft_id"])["draft"]
    draft["claims"][0]["text"] = "Manual interpretation of a completed cancelled analysis."
    saved = invoke(
        "save", draft_id=opened["draft_id"], revision=1, draft=draft, operation_id="sidecar-save"
    )
    assert scientific(claims[0][0]) == before
    result = invoke(
        "apply",
        draft_id=opened["draft_id"],
        revision=saved["revision"],
        operation_id="sidecar-apply",
        confirm=True,
    )
    assert result["status"] == "applied"
    actual = scientific(claims[0][0])
    assert actual["report"]["claims"][0]["text"] == draft["claims"][0]["text"]
    assert actual["generation"]["backend"] == "manual" and len(claims[2]) == calls + 1
    assert generation._recovery_path(current.context).is_file()


def test_remote_claim_review_offline_restart_return_resolution_and_backup(receiver, monkeypatch):
    value = receiver
    review = value["review"]
    verified = review.verify_claim_draft(value["preview"], value["body"])
    review.apply_claim_draft(verified, value["body"], request_id=str(uuid4()), confirm_target=True)
    desktop_payload = typed_edit(value, "Desktop interpretation before the laptop returns.")
    laptop_payload = typed_edit(value, "Laptop interpretation retained by a real sync conflict.")
    journey = value["path"].parent.parent / "offline-claim-journey"
    journey.mkdir()
    a, b, service, ta, tb, portable, local, files = peer(value["adopted"], journey)
    identity = sync_content.content_id(dict(kind="paper", id=portable), "claims", "main")
    try:
        a.save(a.new_graph_operation("research_content", identity, desktop_payload))
        incoming = b.new_graph_operation("research_content", identity, laptop_payload)
        b.save(incoming)
        a.sync_once(service, ta, limit=1000)
        b.sync_once(service, tb, limit=1000)
        a.sync_once(service, ta, limit=1000)
        assert (
            scientific(b.journal.path)["report"]["claims"][0]["text"]
            == desktop_payload["data"]["body_json"]["report"]["claims"][0]["text"]
        )
        monkeypatch.setattr(store, "DB_PATH", b.journal.path)
        origins = [
            item["origin_id"]
            for item in invoke("list")["items"]
            if item["origin_id"].startswith("remote:")
        ]
        assert len(origins) == 1
        with monkeypatch.context() as offline:
            for method in ("push", "pull", "session_info"):
                offline.setattr(
                    service,
                    method,
                    lambda *a, **k: (_ for _ in ()).throw(
                        AssertionError("Offline review contacted the service")
                    ),
                )
            opened = invoke(
                "open", origin_id=origins[0], target_id=local, operation_id="offline-remote-open"
            )
            draft = invoke("read", draft_id=opened["draft_id"])["draft"]
            draft["claims"][0]["text"] = "Offline laptop review of both interpretations."
            saved = invoke(
                "save",
                draft_id=opened["draft_id"],
                revision=1,
                draft=draft,
                operation_id="offline-remote-save",
            )
            checked = invoke("verify", draft_id=opened["draft_id"], revision=saved["revision"])
            assert checked["source_document_hash"] == value["source_hash"]
            request = dict(
                draft_id=opened["draft_id"],
                revision=saved["revision"],
                operation_id="offline-remote-apply",
                confirm=True,
            )
            accepted = invoke("apply", **request)
            assert invoke("apply", **request) == accepted
            assert (
                DocumentReader.from_workspace(b.journal.path).resolve(local).sha256
                == value["current"].sha256
            )
        queued = b.journal.pending(1000)
        assert len(queued) == 1 and queued[0]["resolution_of"] == incoming["operation_id"]
        restarted = SyncClient(
            Journal(b.journal.path, workspace_id=a.journal.workspace_id, device_id="peer"),
            research_writer,
        )
        assert restarted.journal.pending(1000) == queued
        restarted.sync_once(service, tb, limit=1000)
        a.sync_once(service, ta, limit=1000)
        assert not restarted.journal.pending(1000)
        assert scientific(a.journal.path) == scientific(b.journal.path)
        assert (
            scientific(a.journal.path)["report"]["claims"][0]["text"] == draft["claims"][0]["text"]
        )
        for client in (a, restarted):
            assert rows(
                client.journal.path, "SELECT resolved_by FROM paperfact_sync_conflicts"
            ) == [dict(resolved_by=queued[0]["operation_id"])]
        newer = scientific(b.journal.path)
        assert invoke("apply", **request) == accepted and scientific(b.journal.path) == newer
        independent = journey.parent / "claim-return-independent"
        independent.mkdir()
        output = independent / "returned-claim.zip"
        backup(b.journal.path, output)
        files.close()
        journey.rename(journey.with_name(journey.name + "-unavailable-" + uuid4().hex))
        detached = independent / "returned-detached"
        sync_recovery.restore_detached(output, detached)
        detached_path = detached / "papers.db"
        assert scientific(detached_path) == newer
        assert live_count(detached_path, "integration_operations") == 0
        assert live_count(detached_path, "research_review_drafts") == 0
        from paper_daily.recovery_adoption import RecoveryAdoptionService

        adoption = RecoveryAdoptionService(detached_path)
        inspection = adoption.inspect()
        assert inspection.report["supported"], inspection.report
        adopted = adoption.prepare(
            inspection,
            independent / "editable",
            backup_output=independent / "adopted.zip",
            request_id=str(uuid4()),
        )
        adopted_path = Path(adopted["database"])
        actual = scientific(adopted_path)
        assert actual["report"]["claims"][0]["text"] == draft["claims"][0]["text"]
        assert actual["report"]["source"]["document_hash"] == value["source_hash"]
        target = rows(adopted_path, "SELECT local_id FROM research_paper_identity")[0]["local_id"]
        active = DocumentReader.from_workspace(adopted_path).resolve(target)
        assert active.sha256 == value["current"].sha256
        assert active.path.is_relative_to(independent)
    finally:
        files.close()
