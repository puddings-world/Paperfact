"""Actual independent recovery, grouped conflict closure and offline peer data journeys."""

import copy
import json
from contextlib import closing
from uuid import uuid4

import pytest
from test_highlight_draft_application import apply, assert_b, snapshot
from test_highlight_draft_verification import ready as ready
from test_highlight_draft_verification import scene as scene
from test_highlight_draft_verification import source_pair as source_pair
from test_highlight_draft_verification import workspace as workspace
from test_research_generation import rows
from test_research_review import remote_graph as remote_graph

from paper_daily import (
    manual_highlight_ops,
    sync_content,
    sync_recovery,
    sync_source_files,
)
from paper_daily import research_generation as generation
from paper_daily.document_reader import DocumentReader
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.research_review import ResearchReview, encode
from paper_daily.sync_artifacts import desired_file, paths
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_files import file_id

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


@pytest.fixture
def recovered(scene, ready, monkeypatch, tmp_path):
    # A is private backup material, not an already published original-source artifact.
    # Keep it before replacing the selected primary, so recovery must own new A itself.
    import pymupdf
    from test_highlight_draft_storage import selected
    from test_sync_source_files import pdf

    from paper_daily import legacy_primary_migration as migration
    from paper_daily import llm, sync_capture
    from paper_daily.ai_types import Completion
    from paper_daily.document_reader import register_document_paths
    from paper_daily.highlight_jobs import HighlightJob
    from paper_daily.sync_file_transfers import FileTransfers
    from paper_daily.sync_operations import ResearchOperations

    source = scene["document"]
    canonical_bytes = source.path.read_bytes()
    (source.path.parent / "canonical-c.pdf").write_bytes(canonical_bytes)
    with pymupdf.open(stream=canonical_bytes, filetype="pdf") as pdf_document:
        pdf_document.set_metadata({"title": "Only the pending private proposal owns original A"})
        original_bytes = pdf_document.tobytes()
    source.path.write_bytes(original_bytes)
    canonical_hash = scene["original"].data["retained"]["analysis"]["document_hash"]
    pending = HighlightJob.capture(
        scene["path"], "paper", legacy_root=source.path.parent, connections={}
    )

    def complete(*a, **k):
        with closing(generation._connect(scene["path"])) as conn:
            mark = conn.execute(
                "SELECT document_hash,source_key FROM pdf_ai_highlights LIMIT 1"
            ).fetchone()
            observed = sync_capture.observe_target(
                conn, "paper", "paper", "ai_highlight", mark[0] + ":" + mark[1]
            )
            with sync_capture.expecting(conn, [observed]):
                conn.execute("UPDATE pdf_ai_highlights SET hidden=0")
                conn.commit()
        return Completion(
            json.dumps(
                dict(items=[dict(id=i, kind="evidence", reason="Fixed fixture") for i in (0, 1)])
            )
        )

    with monkeypatch.context() as patch:
        patch.setattr(llm, "complete_result", complete)
        assert pending.run().status == "candidate"
    from test_highlight_generation import change_mark

    change_mark(scene["path"])
    scene["original"] = scene["review"].preview("generation", pending.context.request_id)
    assert scene["original"].data["retained"]["analysis"]["document_hash"] != canonical_hash

    (source.path.parent / "retained-a.pdf").write_bytes(original_bytes)
    source.path.write_bytes(pdf("Current B remains selected while private A is recovered."))
    store = BlobStore(scene["path"].parent / "blobs")
    version_root = scene["path"].parent / "research-versions"

    class NoTransport:
        def __getattr__(self, name):
            if name == "base_url":
                raise AttributeError(name)
            raise AssertionError("Recovery preparation contacted a network transport")

    transfers = FileTransfers(
        scene["client"],
        store,
        NoTransport(),
        origin="https://fixture.invalid",
        token=None,
        version_root=version_root,
    )
    transfers.close()
    with scene["client"].journal.transaction() as conn:
        register_document_paths(
            conn,
            workspace_id=scene["client"].journal.workspace_id,
            blob_root=store.root,
            projection_root=scene["path"].parent / "managed",
            legacy_root=source.path.parent,
        )
    document = DocumentReader.from_workspace(scene["path"]).resolve("paper")
    migrated = migration.run(
        migration.prepare(
            ResearchOperations(scene["client"]), document, store, request_id=str(uuid4())
        )
    )
    assert migrated["status"] == "migrated"
    preview, raw = selected(scene)
    current = DocumentReader.from_workspace(scene["path"]).resolve("paper")
    assert current.available and current.sha256 != preview.data["source_hash"]
    value = dict(
        scene,
        preview=preview,
        body=raw,
        current=current,
        current_bytes=current.path.read_bytes(),
        original_bytes=original_bytes,
    )
    review = value["review"]
    second = json.loads(value["body"])
    second["items"][0]["reason"] = "An independent second human interpretation."
    for body in (value["body"], encode(second)):
        review.save_highlight_draft(value["preview"], body, str(uuid4()), draft_id=str(uuid4()))
    independent = tmp_path.parent / (tmp_path.name + "-recovered-" + uuid4().hex)
    independent.mkdir()
    with closing(generation._connect(value["path"])) as conn:
        store, _versions = paths(conn)
    backup = independent / "private.zip"
    sync_recovery.create(
        value["path"], backup, blob_store=store, pdf_roots=[value["path"].parent / "pdf"]
    )
    detached = independent / "detached"
    sync_recovery.restore_detached(backup, detached)
    review.close()
    old = value["path"]
    tmp_path.rename(tmp_path.with_name(tmp_path.name + "-unavailable-" + uuid4().hex))
    assert not old.exists()
    adoption = RecoveryAdoptionService(detached / "papers.db")
    inspection = adoption.inspect()
    assert inspection.report["supported"], inspection.report
    result = adoption.prepare(
        inspection,
        independent / "editable",
        backup_output=independent / "editable.zip",
        request_id=str(uuid4()),
    )
    receiver = ResearchReview(result["database"])
    try:
        previews = [
            receiver.preview(item["origin"], item["id"])
            for item in receiver.page(limit=100)["items"]
            if item["origin"] == "archived_draft"
        ]
        assert len(previews) == 2
        source = next(view for view in previews if view.data["retained"]["body"] == value["body"])
        target = receiver.highlight_draft_targets(source)["items"][0]
        selected, raw = receiver.select_highlight_draft(source, target["id"])
        current = DocumentReader.from_workspace(receiver.path).resolve(target["id"])
        assert current.available and current.sha256 == value["current"].sha256
        assert current.sha256 != selected.data["source_hash"]
        proof = receiver.prepare_highlight_original(selected)
        assert proof.data == value["original_bytes"]
        with closing(receiver._connect()) as conn:
            client = conn._capture_client
        yield dict(
            path=receiver.path,
            adopted=result,
            review=receiver,
            preview=selected,
            body=raw,
            client=client,
            current=current,
            current_bytes=current.path.read_bytes(),
            original_bytes=value["original_bytes"],
            independent=independent,
            old=old,
            variants={value["body"], encode(second)},
        )
    finally:
        receiver.close()


def test_recovered_source_ownership_and_private_group_roll_back_then_retry(recovered, monkeypatch):
    value = recovered
    checked = value["review"].verify_highlight_draft(value["preview"], value["body"])
    identity = file_id(
        checked.data["expected"]["paper_sync_id"],
        sync_source_files.FEATURE,
        checked.data["source_hash"],
    )
    with closing(value["review"]._connect()) as conn:
        assert desired_file(conn, identity) is None
    before = snapshot(value)
    request = str(uuid4())
    with monkeypatch.context() as patch:

        def failure(*a, **k):
            raise OSError("decision storage unavailable after source and marks")

        patch.setattr(ResearchReview, "_receipt", staticmethod(failure))
        with pytest.raises(OSError, match="decision storage"):
            apply(value, checked, request_id=request)
    assert snapshot(value) == before
    with closing(value["review"]._connect()) as conn:
        assert desired_file(conn, identity) is None
    result = apply(value, checked, request_id=request)
    assert result["decision"] == "applied"
    with closing(value["review"]._connect()) as conn:
        assert desired_file(conn, identity)["payload"]["slot"] == checked.data["source_hash"]
    assert_b(value)
    assert not value["old"].exists()


def test_recovered_group_peer_offline_hide_note_restart_return_and_second_backup(
    recovered, monkeypatch
):
    from test_enrollment_history_peer import peer

    from paper_daily.sync_client import SyncClient
    from paper_daily.sync_journal import Journal
    from paper_daily.sync_research import research_writer

    value = recovered
    checked = value["review"].verify_highlight_draft(value["preview"], value["body"])
    request = str(uuid4())
    outcome = apply(value, checked, request_id=request)
    journey = value["independent"] / "peer"
    journey.mkdir()
    a, b, service, ta, tb, portable, local, files = peer(value["adopted"], journey)
    try:
        assert rows(
            b.journal.path,
            "SELECT body_json,source_hash,document_hash FROM paper_highlight_analysis",
        ) == rows(
            value["path"],
            "SELECT body_json,source_hash,document_hash FROM paper_highlight_analysis",
        )
        with b.journal.transaction() as conn:
            original = sync_source_files.inspectable(conn, portable, checked.data["source_hash"])
            assert original is not None and original.read_bytes() == value["original_bytes"]
            assert not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='research_review_drafts'"
            ).fetchone()
        reader = DocumentReader.from_workspace(b.journal.path).resolve(local)
        assert reader.sha256 == value["current"].sha256
        owner = manual_highlight_ops.capture_owner(b.journal.path, local)
        view = manual_highlight_ops.load(owner, original, checked.data["source_hash"])
        visible = next(mark for mark in view.marks if mark["origin"] == "ai")
        fields = "document_hash,source_key,analysis_hash,anchor,quote,reason,hidden"
        peer_before = rows(
            b.journal.path,
            "SELECT " + fields + " FROM pdf_ai_highlights ORDER BY document_hash,source_key",
        )
        expected_marks = [
            dict(mark, hidden=1)
            if (
                mark["document_hash"] == checked.data["source_hash"]
                and mark["quote"] == visible["quote"]
            )
            else mark
            for mark in peer_before
        ]
        assert (
            sum(before != after for before, after in zip(peer_before, expected_marks, strict=True))
            == 1
        )

        with monkeypatch.context() as offline:
            for method in ("push", "pull", "session_info"):
                offline.setattr(
                    service, method, lambda *a, **k: pytest.fail("Offline edit contacted service")
                )
            manual_highlight_ops.remove(view, [visible["id"]])
            note = str(uuid4())
            b.save(
                b.new_graph_operation(
                    "note",
                    note,
                    dict(
                        paper_id=portable,
                        body="Offline appraisal of the revised source highlights.",
                        page=None,
                        anchor=None,
                        kind="note",
                        created_at="2026-11-02T00:00:00+00:00",
                    ),
                )
            )
        assert len(b.journal.pending(1000)) == 2
        restarted = SyncClient(
            Journal(b.journal.path, workspace_id=a.journal.workspace_id, device_id="peer"),
            research_writer,
        )
        assert len(restarted.journal.pending(1000)) == 2
        restarted.sync_once(service, tb, limit=1000)
        a.sync_once(service, ta, limit=1000)
        assert not restarted.journal.pending(1000)
        assert rows(value["path"], "SELECT body FROM notes") == [
            dict(body="Offline appraisal of the revised source highlights.")
        ]
        assert (
            rows(
                value["path"],
                "SELECT " + fields + " FROM pdf_ai_highlights ORDER BY document_hash,source_key",
            )
            == expected_marks
        )
        before = snapshot(value)
        assert apply(value, checked, request_id=request) == outcome
        assert snapshot(value) == before
        assert_b(value)
        with closing(value["review"]._connect()) as conn:
            store, _versions = paths(conn)
        archive = value["independent"] / "returned.zip"
        sync_recovery.create(
            value["path"], archive, blob_store=store, pdf_roots=[value["path"].parent / "pdf"]
        )
        detached = value["independent"] / "returned-detached"
        sync_recovery.restore_detached(archive, detached)
        final = detached / "papers.db"
        assert rows(
            final, "SELECT body_json,source_hash,document_hash FROM paper_highlight_analysis"
        ) == rows(
            value["path"],
            "SELECT body_json,source_hash,document_hash FROM paper_highlight_analysis",
        )
        assert rows(
            final, "SELECT quote,reason,hidden FROM pdf_ai_highlights ORDER BY source_key"
        ) == rows(
            value["path"], "SELECT quote,reason,hidden FROM pdf_ai_highlights ORDER BY source_key"
        )
        assert rows(final, "SELECT body FROM notes") == rows(
            value["path"], "SELECT body FROM notes"
        )
        assert (detached / "objects" / checked.data["source_hash"]).read_bytes() == value[
            "original_bytes"
        ]
        assert (detached / "objects" / value["current"].sha256).read_bytes() == value[
            "current_bytes"
        ]
        final_review = ResearchReview(final)
        try:
            previews = [
                final_review.preview(item["origin"], item["id"])
                for item in final_review.page(limit=100)["items"]
                if item["origin"] == "archived_draft"
            ]
            assert {preview.data["retained"]["body"] for preview in previews} == value["variants"]
            assert (
                len(previews) == 3
            )  # two original variants plus the newly accepted private revision
        finally:
            final_review.close()
        assert not value["old"].exists()
    finally:
        files.close()


def test_actual_remote_analysis_revision_resolves_one_conflict_and_syncs_whole_marks(
    scene, remote_graph, tmp_path
):
    from test_sync_files import drain

    from paper_daily.sync_file_transfers import FileTransfers

    a, b, service, ta, tb, _list = remote_graph
    from paper_daily.sync_service import ReferenceService

    # Reopen the same authority with explicit local attachment storage; device tokens persist.
    service = ReferenceService(service.path, blob_root=tmp_path / "remote-service-blobs")
    with b.journal.transaction() as conn:
        portable, local = conn.execute(
            "SELECT sync_id,local_id FROM research_paper_identity"
        ).fetchone()
        parent = b._optimistic_graph(conn)[0][("paper", portable)]["incarnation"]
    retained = scene["original"].data["retained"]["analysis"]
    scope = dict(kind="paper", id=portable)
    identity = sync_content.content_id(scope, "highlight_analysis", "main")
    baseline = dict(
        scope=scope,
        feature="highlight_analysis",
        key="main",
        source_document_hash=retained["document_hash"],
        data={
            key: (json.loads(value) if key == "body_json" else value)
            for key, value in retained.items()
            if key != "paper_id"
        },
    )

    def payload(reason):
        value = copy.deepcopy(baseline)
        value["data"]["body_json"]["items"][0]["reason"] = reason
        return value

    a.save(a.new_graph_operation("research_content", identity, payload("Initial")))
    a.sync_once(service, ta, limit=1000)
    b.sync_once(service, tb, limit=1000)
    a.save(a.new_graph_operation("research_content", identity, payload("Desktop")))
    b.save(b.new_graph_operation("research_content", identity, payload("Laptop")))
    a.sync_once(service, ta, limit=1000)
    b.sync_once(service, tb, limit=1000)
    a.sync_once(service, ta, limit=1000)
    store = BlobStore(tmp_path / "remote-blobs")
    root = tmp_path / "remote-versions"
    sync_source_files.publish(
        b,
        portable,
        scene["document"].path,
        document_hash=retained["document_hash"],
        parent_incarnation=parent,
        store=store,
        version_root=root,
        request_id=str(uuid4()),
    )
    review = ResearchReview(b.journal.path)
    try:
        source = next(
            view
            for item in review.page(limit=100)["items"]
            if item["origin"] == "remote"
            and (view := review.preview("remote", item["id"])).data["source_hash"]
            == retained["document_hash"]
        )
        preview, body = review.select_highlight_draft(source, local)
        draft = json.loads(body)
        draft["items"][0]["reason"] = "Human comparison of both competing interpretations."
        body = encode(draft)
        verified = review.verify_highlight_draft(preview, body)
        request = str(uuid4())
        result = review.apply_highlight_draft(
            verified, body, request_id=request, confirm_target=True
        )
        resolution = next(op for op in b.journal.pending(1000) if op["operation_id"] == request)
        assert (
            resolution["resolution_of"]
            == preview.data["expected"]["conflict"]["event"]["operation"]["operation_id"]
        )
        assert len(rows(b.journal.path, "SELECT * FROM pdf_ai_highlights")) == 2
        files = FileTransfers(
            b, store, service, origin="https://fixture.invalid", token=tb, version_root=root
        )
        try:

            def prepare(op):
                if op["entity_type"] == "research_file":
                    drain(lambda: files.upload(op), "uploaded")
                return True

            b.sync_once(service, tb, limit=1000, prepare_push=prepare)
            a.sync_once(service, ta, limit=1000)
            b.sync_once(service, tb, limit=1000)
            # remote_graph intentionally includes a separate unresolved list-survey conflict.
            with b.journal.transaction() as conn:
                state = b.conflict_observation_in(
                    conn, preview.data["expected"]["conflict"]["event"]["sequence"]
                )
                assert state["resolved_by"] == request
            assert rows(
                a.journal.path, "SELECT body_json,source_hash FROM paper_highlight_analysis"
            ) == rows(b.journal.path, "SELECT body_json,source_hash FROM paper_highlight_analysis")
            assert len(rows(a.journal.path, "SELECT * FROM pdf_ai_highlights")) == 2
            before = rows(b.journal.path, "SELECT * FROM pdf_ai_highlights")
            assert (
                review.apply_highlight_draft(
                    verified, body, request_id=request, confirm_target=True
                )
                == result
            )
            assert rows(b.journal.path, "SELECT * FROM pdf_ai_highlights") == before
        finally:
            files.close()
    finally:
        review.close()
