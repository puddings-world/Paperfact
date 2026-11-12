"""Source A, visible B and manual claims share a reviewed atomic publication."""

import json
from contextlib import closing
from uuid import uuid4

import pytest
from test_claim_draft_storage import claims as _claims
from test_claim_draft_storage import ready as _ready
from test_claim_draft_storage import rows, selected
from test_claim_draft_storage import workspace as _workspace
from test_claim_jobs import job
from test_sync_source_files import pdf

from paper_daily import claim_content, sync_recovery, sync_source_files
from paper_daily import research_generation as generation
from paper_daily.document_reader import DocumentReader, register_document_paths
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.research_review import ResearchReview, encode
from paper_daily.sync_artifacts import desired_file, paths
from paper_daily.sync_files import file_id

claims = _claims
ready = _ready
workspace = _workspace
pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


@pytest.fixture
def scene(claims, monkeypatch):
    import pymupdf

    from paper_daily import llm, sync_capture

    accepted = job(claims)
    source = accepted.snapshot.source
    parent = accepted.context.data["observation"]["parents"][0]["id"]
    assert source["paper_id"] == parent
    assert source["document_hash"] == accepted.context.data["document"]["sha256"]
    assert accepted.run().status == "accepted"
    primary = claims[0][2].path
    replacement = primary.with_suffix(".new.pdf")
    with pymupdf.open(primary) as document:
        document.set_metadata({"title": "Original A retained by a pending claim proposal"})
        document.save(replacement)
    replacement.replace(primary)
    claims[1]["claims"][0]["text"] = "Retained original-A proposal awaiting appraisal."
    pending = job(claims)
    assert pending.snapshot.source["document_hash"] != source["document_hash"]
    complete = llm.complete_result

    def during_work(*args, **kwargs):
        response = complete(*args, **kwargs)
        with (
            closing(generation._connect(claims[0][0])) as conn,
            conn,
            sync_capture.suppress_capture(conn),
        ):
            conn.execute("UPDATE dives SET body='Newer analysis during original-A extraction'")
        return response

    with monkeypatch.context() as patch:
        patch.setattr(llm, "complete_result", during_work)
        assert pending.run().status == "candidate"
    review = ResearchReview(claims[0][0])
    original = review.preview("generation", pending.context.request_id)
    assert original.data["apply"] is False
    yield dict(
        claims=claims, path=claims[0][0], client=claims[0][1], review=review, original=original
    )
    review.close()


@pytest.fixture
def source_pair(scene):
    primary = scene["claims"][0][2].path
    primary.write_bytes(pdf("Current version B is deliberately different from original A."))
    with scene["client"].journal.transaction() as conn:
        store, _versions = paths(conn)
        register_document_paths(
            conn,
            workspace_id=scene["client"].journal.workspace_id,
            blob_root=store.root,
            projection_root=scene["path"].parent / "managed-pdfs",
            legacy_root=primary.parent,
        )
    from paper_daily import legacy_primary_migration as migration
    from paper_daily.sync_file_transfers import FileTransfers
    from paper_daily.sync_operations import ResearchOperations

    class NoTransport:
        def __getattr__(self, name):
            if name == "base_url":
                raise AttributeError(name)
            raise AssertionError("Local claim migration attempted network transport")

    files = FileTransfers(
        scene["client"], store, NoTransport(), origin="https://fixture.invalid", token=None
    )
    files.close()
    legacy = DocumentReader.from_workspace(scene["path"]).resolve("paper")
    migrated = migration.run(
        migration.prepare(
            ResearchOperations(scene["client"]), legacy, store, request_id=str(uuid4())
        )
    )
    assert migrated["status"] == "migrated"
    preview, raw = selected(scene)
    current = DocumentReader.from_workspace(scene["path"]).resolve("paper")
    assert current.available and current.sha256 != preview.data["source_hash"]
    assert preview.data["expected"]["document"]["sha256"] == current.sha256
    return dict(
        scene,
        preview=preview,
        body=raw,
        current=current,
        current_bytes=current.path.read_bytes(),
        source_hash=preview.data["source_hash"],
    )


def test_exact_original_revision_apply_retry_and_later_research_leave_b_selected(source_pair):
    value = source_pair
    review, preview, raw = value["review"], value["preview"], value["body"]
    calls = len(value["claims"][2])
    draft_id, request = str(uuid4()), str(uuid4())
    review.save_claim_draft(preview, raw, request, draft_id=draft_id)
    before = rows(value["path"], "SELECT * FROM paper_claim_sets")
    pending = value["client"].journal.pending(1000)
    verified = review.verify_claim_draft(preview, raw)
    report = review.claim_draft_report(verified)
    claim = report["report"]["claims"][0]
    assert claim["text"] == json.loads(raw)["claims"][0]["text"]
    assert claim["passages"][0]["location"]["state"] == "located"
    assert claim["semantic_validation"] == "not_performed"
    assert report["generation"] == dict(
        task="claims", backend="manual", requested_model=None, returned_model=None
    )
    assert report["report"]["source"] == dict(
        paper_id=preview.data["expected"]["paper_sync_id"], document_hash=value["source_hash"]
    )
    assert report["inputs"] == json.loads(preview.data["retained"]["body_json"])["inputs"]
    assert rows(value["path"], "SELECT * FROM paper_claim_sets") == before
    assert value["client"].journal.pending(1000) == pending
    with pytest.raises(ValueError, match="Confirm"):
        review.apply_claim_draft(verified, raw, request_id=request)
    result = review.apply_claim_draft(verified, raw, request_id=request, confirm_target=True)
    assert result == dict(decision="applied", operation_id=request)
    assert (
        review.apply_claim_draft(verified, raw, request_id=request, confirm_target=True) == result
    )
    saved = rows(value["path"], "SELECT * FROM paper_claim_sets")[0]
    assert json.loads(saved["body_json"]) == report
    assert saved["document_hash"] == value["source_hash"]
    assert saved["source_hash"] == claim_content.source_digest(
        report["inputs"], value["source_hash"]
    )
    operations = [
        op for op in value["client"].journal.pending(1000) if op["operation_id"] == request
    ]
    assert (
        len(operations) == 1
        and operations[0]["payload"]["source_document_hash"] == value["source_hash"]
    )
    assert rows(value["path"], "SELECT body FROM research_review_drafts") == [dict(body=raw)]
    assert len(value["claims"][2]) == calls
    assert value["current"].path.read_bytes() == value["current_bytes"]
    assert (
        DocumentReader.from_workspace(value["path"]).resolve("paper").sha256
        == value["current"].sha256
    )
    assert job(value["claims"]).run().status == "accepted"
    later = rows(value["path"], "SELECT * FROM paper_claim_sets")
    assert (
        review.apply_claim_draft(verified, raw, request_id=request, confirm_target=True) == result
    )
    assert rows(value["path"], "SELECT * FROM paper_claim_sets") == later


def test_an_edit_after_verification_requires_its_own_revision_check(source_pair):
    value = source_pair
    review = value["review"]
    verified = review.verify_claim_draft(value["preview"], value["body"])
    changed = json.loads(value["body"])
    changed["claims"][0]["text"] = "A different human assertion after verification."
    changed = encode(changed)
    before = rows(value["path"], "SELECT * FROM paper_claim_sets")
    with pytest.raises(ValueError, match="verif"):
        review.apply_claim_draft(verified, changed, request_id=str(uuid4()), confirm_target=True)
    assert rows(value["path"], "SELECT * FROM paper_claim_sets") == before
    current = review.verify_claim_draft(verified, changed)
    review.apply_claim_draft(current, changed, request_id=str(uuid4()), confirm_target=True)
    assert (
        json.loads(rows(value["path"], "SELECT body_json FROM paper_claim_sets")[0]["body_json"])[
            "report"
        ]["claims"][0]["text"]
        == json.loads(changed)["claims"][0]["text"]
    )


def test_failed_reverification_revokes_the_older_claim_permission(source_pair):
    value = source_pair
    review = value["review"]
    verified = review.verify_claim_draft(value["preview"], value["body"])
    with pytest.raises(ValueError):
        review.verify_claim_draft(verified, "{invalid draft")
    before = rows(value["path"], "SELECT * FROM paper_claim_sets")
    with pytest.raises(ValueError, match="verif"):
        review.apply_claim_draft(
            verified, value["body"], request_id=str(uuid4()), confirm_target=True
        )
    assert rows(value["path"], "SELECT * FROM paper_claim_sets") == before


def test_unrelated_note_allows_the_same_verified_claim_revision(source_pair):
    value = source_pair
    review = value["review"]
    verified = review.verify_claim_draft(value["preview"], value["body"])
    with closing(generation._connect(value["path"])) as conn, conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) VALUES(?,?,?)",
            ("paper", "Keep this note", "2026-11-02T00:00:00+00:00"),
        )
    report = review.claim_draft_report(verified)
    review.apply_claim_draft(verified, value["body"], request_id=str(uuid4()), confirm_target=True)
    assert (
        json.loads(rows(value["path"], "SELECT body_json FROM paper_claim_sets")[0]["body_json"])
        == report
    )
    assert rows(value["path"], "SELECT body FROM notes") == [dict(body="Keep this note")]


@pytest.fixture
def receiver(source_pair, tmp_path):
    value = source_pair
    value["review"].save_claim_draft(
        value["preview"], value["body"], str(uuid4()), draft_id=str(uuid4())
    )
    second = json.loads(value["body"])
    second["claims"][0]["judgment"]["reason"] = "Second private interpretation remains separate."
    value["review"].save_claim_draft(
        value["preview"], encode(second), str(uuid4()), draft_id=str(uuid4())
    )
    independent = tmp_path.parent / (tmp_path.name + "-claim-receiver-" + uuid4().hex)
    independent.mkdir()
    with closing(generation._connect(value["path"])) as conn:
        store, _versions = paths(conn)
    backup = independent / "private.zip"
    sync_recovery.create(
        value["path"], backup, blob_store=store, pdf_roots=[value["path"].parent / "pdf"]
    )
    detached = independent / "detached"
    sync_recovery.restore_detached(backup, detached)
    value["review"].close()
    tmp_path.rename(tmp_path.with_name(tmp_path.name + "-unavailable-" + uuid4().hex))
    adoption = RecoveryAdoptionService(detached / "papers.db")
    inspection = adoption.inspect()
    assert inspection.report["supported"], inspection.report
    result = adoption.prepare(
        inspection,
        independent / "editable",
        backup_output=independent / "editable.zip",
        request_id=str(uuid4()),
    )
    review = ResearchReview(result["database"])
    items = [item for item in review.page(limit=100)["items"] if item["origin"] == "archived_draft"]
    assert len(items) == 2
    archived = next(
        preview
        for item in items
        if (preview := review.preview("archived_draft", item["id"])).data["retained"]["body"]
        == value["body"]
    )
    target = review.claim_draft_targets(archived)["items"][0]
    preview, raw = review.select_claim_draft(archived, target["id"])
    current = DocumentReader.from_workspace(review.path).resolve(target["id"])
    assert (
        current.sha256 == value["current"].sha256 and current.sha256 != preview.data["source_hash"]
    )
    yield dict(
        path=review.path,
        adopted=result,
        review=review,
        preview=preview,
        body=raw,
        current=current,
        source_hash=preview.data["source_hash"],
        current_bytes=current.path.read_bytes(),
    )
    review.close()


@pytest.mark.parametrize("fail_receipt", [False, True], ids=["apply", "rollback-retry"])
def test_independent_receiver_verifies_a_and_atomically_applies_without_old_paths(
    receiver, monkeypatch, fail_receipt
):
    value = receiver
    review, preview, raw = value["review"], value["preview"], value["body"]
    original = rows(value["path"], "SELECT * FROM paper_claim_sets")
    verified = review.verify_claim_draft(preview, raw)
    report = review.claim_draft_report(verified)
    paper = preview.data["expected"]["paper_sync_id"]
    assert report["report"]["source"] == dict(paper_id=paper, document_hash=value["source_hash"])
    with closing(generation._connect(value["path"])) as conn:
        identity = file_id(paper, sync_source_files.FEATURE, value["source_hash"])
        assert desired_file(conn, identity) is None
    pending = rows(value["path"], "SELECT * FROM paperfact_sync_operations ORDER BY sequence")
    request = str(uuid4())
    if fail_receipt:
        with monkeypatch.context() as patch:

            def fail(*args):
                raise OSError("receipt storage failure")

            patch.setattr(ResearchReview, "_receipt", staticmethod(fail))
            with pytest.raises(OSError, match="receipt storage"):
                review.apply_claim_draft(verified, raw, request_id=request, confirm_target=True)
        assert rows(value["path"], "SELECT * FROM paper_claim_sets") == original
        assert (
            rows(value["path"], "SELECT * FROM paperfact_sync_operations ORDER BY sequence")
            == pending
        )
        with closing(generation._connect(value["path"])) as conn:
            assert desired_file(conn, identity) is None
    result = review.apply_claim_draft(verified, raw, request_id=request, confirm_target=True)
    assert result["operation_id"] == request
    assert (
        json.loads(rows(value["path"], "SELECT body_json FROM paper_claim_sets")[0]["body_json"])
        == report
    )
    with closing(generation._connect(value["path"])) as conn:
        source = desired_file(conn, identity)
        assert source["payload"]["slot"] == value["source_hash"]
        original_path = sync_source_files.inspectable(conn, paper, value["source_hash"])
        assert original_path is not None
    assert value["current"].path.read_bytes() == value["current_bytes"]
    assert (
        DocumentReader.from_workspace(value["path"])
        .resolve(preview.data["expected"]["paper_id"])
        .sha256
        == value["current"].sha256
    )
    count = len(rows(value["path"], "SELECT * FROM paperfact_sync_operations"))
    assert (
        review.apply_claim_draft(verified, raw, request_id=request, confirm_target=True) == result
    )
    assert len(rows(value["path"], "SELECT * FROM paperfact_sync_operations")) == count


def test_concurrent_identical_application_has_one_shared_operation(source_pair):
    from concurrent.futures import ThreadPoolExecutor

    value = source_pair
    review = value["review"]
    verified = review.verify_claim_draft(value["preview"], value["body"])
    request = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: review.apply_claim_draft(
                    verified, value["body"], request_id=request, confirm_target=True
                ),
                range(8),
            )
        )
    assert results == [dict(decision="applied", operation_id=request)] * 8
    assert len(rows(value["path"], "SELECT * FROM research_review_receipts")) == 1
    operations = value["client"].journal.pending(1000)
    assert sum(op["operation_id"] == request for op in operations) == 1


def test_lost_commit_reply_is_recovered_from_the_same_decision_receipt(source_pair, monkeypatch):
    import sqlite3

    from paper_daily import sync_capture

    value = source_pair
    review = value["review"]
    verified = review.verify_claim_draft(value["preview"], value["body"])
    request = str(uuid4())
    lost = []

    class LostReply(sync_capture.CaptureConnection):
        def commit(self):
            accepted = self.execute(
                "SELECT 1 FROM research_review_receipts WHERE request_id=?", (request,)
            ).fetchone()
            super().commit()
            if accepted and not lost:
                lost.append(True)
                raise OSError("committed reply lost")

    def connect():
        conn = sqlite3.connect(review.path, factory=LostReply)
        conn.row_factory = sqlite3.Row
        review._check(conn)
        return conn

    monkeypatch.setattr(review, "_connect", connect)
    with pytest.raises(OSError, match="reply lost"):
        review.apply_claim_draft(verified, value["body"], request_id=request, confirm_target=True)
    committed = rows(value["path"], "SELECT * FROM paper_claim_sets")
    result = review.apply_claim_draft(
        verified, value["body"], request_id=request, confirm_target=True
    )
    assert result == dict(decision="applied", operation_id=request)
    assert rows(value["path"], "SELECT * FROM paper_claim_sets") == committed
    assert len(rows(value["path"], "SELECT * FROM research_review_receipts")) == 1


def test_changed_same_size_source_cannot_reuse_an_older_verification(source_pair):
    import os

    value = source_pair
    review = value["review"]
    verified = review.verify_claim_draft(value["preview"], value["body"])
    from paper_daily import resumed_draft_originals

    original_proof = resumed_draft_originals.prepare(review, verified, value["source_hash"])
    source = original_proof.source_path
    original = source.read_bytes()
    timestamp = source.stat()
    changed = bytearray(original)
    changed[len(changed) // 2] ^= 1
    source.write_bytes(changed)
    os.utime(source, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
    before = rows(value["path"], "SELECT * FROM paper_claim_sets")
    with pytest.raises(ValueError):
        review.apply_claim_draft(
            verified, value["body"], request_id=str(uuid4()), confirm_target=True
        )
    assert rows(value["path"], "SELECT * FROM paper_claim_sets") == before
    source.write_bytes(original)
    checked = review.verify_claim_draft(value["preview"], value["body"])
    review.apply_claim_draft(checked, value["body"], request_id=str(uuid4()), confirm_target=True)
    assert rows(value["path"], "SELECT document_hash FROM paper_claim_sets") == [
        dict(document_hash=value["source_hash"])
    ]


def test_source_retirement_after_verification_refuses_publication(source_pair):
    value = source_pair
    review = value["review"]
    verified = review.verify_claim_draft(value["preview"], value["body"])
    from paper_daily import resumed_draft_originals

    proof = resumed_draft_originals.prepare(review, verified, value["source_hash"])
    with value["client"].journal.transaction() as conn:
        sync_source_files.publish_source_in(conn, value["client"], proof.prepared)
    identity = file_id(
        value["preview"].data["expected"]["paper_sync_id"],
        sync_source_files.FEATURE,
        value["source_hash"],
    )
    value["client"].save(
        value["client"].new_graph_operation("research_file", identity, {}, action="delete")
    )
    before = rows(value["path"], "SELECT * FROM paper_claim_sets")
    pending = value["client"].journal.pending(1000)
    with pytest.raises(ValueError):
        review.apply_claim_draft(
            verified, value["body"], request_id=str(uuid4()), confirm_target=True
        )
    assert rows(value["path"], "SELECT * FROM paper_claim_sets") == before
    assert value["client"].journal.pending(1000) == pending


def test_deleted_claims_require_explicit_restoration_and_a_new_incarnation(source_pair):
    value = source_pair
    review = value["review"]
    old = value["preview"].data["expected"]["observation"]
    value["client"].save(
        value["client"].new_graph_operation(
            "research_content", old["entity_id"], {}, action="delete"
        )
    )
    preview, raw = review.select_claim_draft(value["preview"], "paper", body=value["body"])
    assert preview.data["current"] is None
    with pytest.raises(ValueError, match="restoration"):
        review.verify_claim_draft(preview, raw)
    verified = review.verify_claim_draft(preview, raw, restore_deleted=True)
    assert verified.data["claim_restore"] is True
    request = str(uuid4())
    review.apply_claim_draft(verified, raw, request_id=request, confirm_target=True)
    operation = next(
        op for op in value["client"].journal.pending(1000) if op["operation_id"] == request
    )
    assert operation["incarnation"] != old["incarnation"]
    assert rows(value["path"], "SELECT document_hash FROM paper_claim_sets") == [
        dict(document_hash=value["source_hash"])
    ]


def test_cancellation_revokes_previous_proof_without_publishing(source_pair):
    value = source_pair
    review = value["review"]
    verified = review.verify_claim_draft(value["preview"], value["body"])
    before = rows(value["path"], "SELECT * FROM paper_claim_sets")
    with pytest.raises(ValueError, match="cancel"):
        review.verify_claim_draft(verified, value["body"], cancelled=lambda: True)
    with pytest.raises(ValueError, match="verif"):
        review.apply_claim_draft(
            verified, value["body"], request_id=str(uuid4()), confirm_target=True
        )
    assert rows(value["path"], "SELECT * FROM paper_claim_sets") == before


def test_closing_during_revision_delivery_cannot_publish_a_ready_result(source_pair, monkeypatch):
    from paper_daily import claim_draft_revision

    value = source_pair
    review = value["review"]
    revise = claim_draft_revision.revise_for_receiver

    def close_after_revision(*args, **kwargs):
        result = revise(*args, **kwargs)
        review.close()
        return result

    monkeypatch.setattr(claim_draft_revision, "revise_for_receiver", close_after_revision)
    before = rows(value["path"], "SELECT * FROM paper_claim_sets")
    with pytest.raises(ValueError):
        review.verify_claim_draft(value["preview"], value["body"])
    assert rows(value["path"], "SELECT * FROM paper_claim_sets") == before
    assert not review._claim_revisions and not review._resume_sources


def test_restart_does_not_restore_runtime_claim_write_authority(source_pair):
    value = source_pair
    review = value["review"]
    request, draft_id = str(uuid4()), str(uuid4())
    verified = review.verify_claim_draft(value["preview"], value["body"])
    review.save_claim_draft(verified, value["body"], request, draft_id=draft_id)
    review.close()
    reopened = ResearchReview(value["path"])
    try:
        loaded = reopened.load_claim_draft(verified.data["id"])
        assert loaded["body"] == value["body"] and loaded["state"] == "verification_required"
        assert loaded["preview"].data["apply"] is False
        with pytest.raises(ValueError, match="verif"):
            reopened.apply_claim_draft(
                loaded["preview"], loaded["body"], request_id=request, confirm_target=True
            )
        ready = reopened.verify_claim_draft(loaded["preview"], loaded["body"])
        reopened.apply_claim_draft(ready, loaded["body"], request_id=request, confirm_target=True)
    finally:
        reopened.close()


@pytest.mark.parametrize("change", ["claims", "document", "parent", "native"])
def test_pending_application_cannot_write_after_its_actual_target_changed(
    source_pair, change, tmp_path
):
    import sqlite3

    from paper_daily import sync_document_actions
    from paper_daily.sync_operations import ResearchOperations

    value = source_pair
    review = value["review"]
    verified = review.verify_claim_draft(value["preview"], value["body"])
    paper = verified.data["expected"]["paper_sync_id"]
    if change == "claims":
        assert job(value["claims"]).run().status == "accepted"
    elif change == "document":
        next_pdf = tmp_path / "new-primary.pdf"
        next_pdf.write_bytes(pdf("New current primary chosen after verification."))
        with value["client"].journal.transaction() as conn:
            store, _versions = paths(conn)
        manifest = sync_document_actions.stage_file(store, next_pdf)
        ResearchOperations(value["client"]).attach_document(
            paper, manifest, store=store, request_id=str(uuid4())
        )
    elif change == "parent":
        from types import SimpleNamespace

        from test_legacy_primary_migration import recreate_parent

        recreate_parent(SimpleNamespace(database=value["path"]))
    else:
        replacement = value["path"].with_suffix(".next.sqlite")
        with (
            closing(sqlite3.connect(value["path"])) as old,
            closing(sqlite3.connect(replacement)) as new,
        ):
            old.backup(new)
        replacement.replace(value["path"])
    before = rows(value["path"], "SELECT * FROM paper_claim_sets")
    pending = rows(value["path"], "SELECT * FROM paperfact_sync_operations ORDER BY sequence")
    with pytest.raises(ValueError):
        review.apply_claim_draft(
            verified, value["body"], request_id=str(uuid4()), confirm_target=True
        )
    assert rows(value["path"], "SELECT * FROM paper_claim_sets") == before
    assert (
        rows(value["path"], "SELECT * FROM paperfact_sync_operations ORDER BY sequence") == pending
    )
    assert (
        rows(value["path"], "SELECT name FROM sqlite_master WHERE name='research_review_receipts'")
        == []
    )


def test_native_workspace_replacement_during_verification_discards_delivery(
    source_pair, monkeypatch
):
    import sqlite3

    from paper_daily import claim_draft_revision

    value = source_pair
    review = value["review"]
    revise = claim_draft_revision.revise_for_receiver

    def replace_after_revision(*args, **kwargs):
        result = revise(*args, **kwargs)
        replacement = value["path"].with_suffix(".next.sqlite")
        with (
            closing(sqlite3.connect(value["path"])) as old,
            closing(sqlite3.connect(replacement)) as new,
        ):
            old.backup(new)
        replacement.replace(value["path"])
        return result

    monkeypatch.setattr(claim_draft_revision, "revise_for_receiver", replace_after_revision)
    before = rows(value["path"], "SELECT * FROM paper_claim_sets")
    pending = rows(value["path"], "SELECT * FROM paperfact_sync_operations ORDER BY sequence")
    with pytest.raises(ValueError):
        review.verify_claim_draft(value["preview"], value["body"])
    assert rows(value["path"], "SELECT * FROM paper_claim_sets") == before
    assert (
        rows(value["path"], "SELECT * FROM paperfact_sync_operations ORDER BY sequence") == pending
    )
    assert not review._claim_revisions and not review._resume_sources


def test_recovered_claim_reaches_offline_peer_and_survives_return_and_new_backup(receiver):

    from test_enrollment_history_peer import peer

    from paper_daily.sync_client import SyncClient
    from paper_daily.sync_journal import Journal
    from paper_daily.sync_research import research_writer

    value = receiver
    journey = value["path"].parent.parent / "peer-journey"
    journey.mkdir()
    review = value["review"]
    verified = review.verify_claim_draft(value["preview"], value["body"])
    request = str(uuid4())
    accepted = review.apply_claim_draft(
        verified, value["body"], request_id=request, confirm_target=True
    )
    report = json.loads(
        rows(value["path"], "SELECT body_json FROM paper_claim_sets")[0]["body_json"]
    )
    peer_root = journey / "claim-peer"
    peer_root.mkdir()
    a, b, service, ta, tb, portable, local, files = peer(value["adopted"], peer_root)
    peer_report = json.loads(
        rows(b.journal.path, "SELECT body_json FROM paper_claim_sets")[0]["body_json"]
    )
    assert peer_report == report
    assert (
        DocumentReader.from_workspace(b.journal.path).resolve(local).sha256
        == value["current"].sha256
    )
    with b.journal.transaction() as conn:
        original = sync_source_files.inspectable(conn, portable, value["source_hash"])
        assert original is not None
        source_bytes = original.read_bytes()
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_review_drafts'"
        ).fetchone()
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_review_receipts'"
        ).fetchone()
    note = str(uuid4())
    offline_text = "Offline laptop appraisal of the retained original-A claim."
    b.save(
        b.new_graph_operation(
            "note",
            note,
            dict(
                paper_id=portable,
                body=offline_text,
                page=None,
                anchor=None,
                kind="note",
                created_at="2026-11-02T00:00:00+00:00",
            ),
        )
    )
    assert rows(value["path"], "SELECT body FROM notes") == []
    assert len(b.journal.pending(1000)) == 1
    restarted = SyncClient(
        Journal(b.journal.path, workspace_id=a.journal.workspace_id, device_id="peer"),
        research_writer,
    )
    assert len(restarted.journal.pending(1000)) == 1
    restarted.sync_once(service, tb, limit=1000)
    a.sync_once(service, ta, limit=1000)
    assert not restarted.journal.pending(1000)
    assert rows(value["path"], "SELECT body FROM notes") == [dict(body=offline_text)]
    assert (
        json.loads(rows(value["path"], "SELECT body_json FROM paper_claim_sets")[0]["body_json"])
        == report
    )
    pending = a.journal.pending(1000)
    assert (
        review.apply_claim_draft(verified, value["body"], request_id=request, confirm_target=True)
        == accepted
    )
    assert a.journal.pending(1000) == pending
    assert rows(value["path"], "SELECT body FROM notes") == [dict(body=offline_text)]
    with closing(generation._connect(value["path"])) as conn:
        store, _versions = paths(conn)
    archive = journey / "returned-claims.zip"
    sync_recovery.create(
        value["path"], archive, blob_store=store, pdf_roots=[value["path"].parent / "pdf"]
    )
    detached = journey / "returned-detached"
    sync_recovery.restore_detached(archive, detached)
    final = detached / "papers.db"
    assert rows(final, "SELECT body_json,source_hash,document_hash FROM paper_claim_sets") == rows(
        value["path"], "SELECT body_json,source_hash,document_hash FROM paper_claim_sets"
    )
    assert rows(final, "SELECT body FROM notes") == [dict(body=offline_text)]
    assert (detached / "objects" / value["source_hash"]).read_bytes() == source_bytes
    assert (detached / "objects" / value["current"].sha256).read_bytes() == value["current_bytes"]
    recovered = ResearchReview(final)
    try:
        drafts = [
            item
            for item in recovered.page(limit=100)["items"]
            if item["origin"] == "archived_draft"
        ]
        assert len(drafts) == 2
        bodies = [
            recovered.preview("archived_draft", item["id"]).data["retained"]["body"]
            for item in drafts
        ]
        assert value["body"] in bodies and len(set(bodies)) == 2
    finally:
        recovered.close()
        files.close()
