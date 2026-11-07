"""Exact original A stays separate from current B and from highlight Apply authority."""

import json
import pickle
from contextlib import closing
from uuid import uuid4

import pytest
from test_highlight_draft_storage import ready as ready
from test_highlight_draft_storage import scene as scene
from test_highlight_draft_storage import selected, state
from test_highlight_draft_storage import workspace as workspace
from test_research_generation import rows
from test_sync_source_files import pdf

from paper_daily import research_generation as generation
from paper_daily import sync_capture, sync_source_files
from paper_daily.document_reader import DocumentReader, register_document_paths
from paper_daily.research_review import ResearchReview, encode
from paper_daily.sync_artifacts import paths
from paper_daily.sync_blobs import BlobStore

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


@pytest.fixture
def source_pair(scene):
    original = scene["document"]
    original_bytes = original.path.read_bytes()
    client = scene["client"]
    with client.journal.transaction() as conn:
        portable = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id='paper'"
        ).fetchone()[0]
        parent = client._optimistic_graph(conn)[0][("paper", portable)]["incarnation"]
    blobs = BlobStore(scene["path"].parent / "blobs")
    sync_source_files.publish(
        client,
        portable,
        original.path,
        document_hash=original.sha256,
        parent_incarnation=parent,
        store=blobs,
        version_root=scene["path"].parent / "research-versions",
        request_id=str(uuid4()),
    )
    original.path.write_bytes(pdf("Current original B must remain selected while A is inspected."))
    with client.journal.transaction() as conn:
        registered, _versions = paths(conn)
        register_document_paths(
            conn,
            workspace_id=client.journal.workspace_id,
            blob_root=registered.root,
            projection_root=scene["path"].parent / "managed-pdfs",
            legacy_root=original.path.parent,
        )
    from paper_daily import legacy_primary_migration as migration
    from paper_daily.sync_file_transfers import FileTransfers
    from paper_daily.sync_operations import ResearchOperations

    class NoTransport:
        def __getattr__(self, name):
            if name == "base_url":
                raise AttributeError(name)
            raise AssertionError("Original verification attempted a network request")

    transfers = FileTransfers(
        client,
        blobs,
        NoTransport(),
        origin="https://fixture.invalid",
        token=None,
        version_root=_versions,
    )
    transfers.close()
    legacy = DocumentReader.from_workspace(scene["path"]).resolve("paper")
    outcome = migration.run(
        migration.prepare(ResearchOperations(client), legacy, blobs, request_id=str(uuid4()))
    )
    assert outcome["status"] == "migrated"
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
        original_bytes=original_bytes,
    )


def unchanged(value, before, pending):
    assert state(value["path"]) == before
    assert value["client"].journal.pending(1000) == pending
    assert value["current"].path.read_bytes() == value["current_bytes"]
    assert (
        DocumentReader.from_workspace(value["path"]).resolve("paper").sha256
        == value["current"].sha256
    )


def test_verification_rebuilds_the_whole_group_from_a_without_publishing_or_selecting_a(
    source_pair,
):
    value = source_pair
    before, pending = state(value["path"]), value["client"].journal.pending(1000)
    checked = value["review"].verify_highlight_draft(value["preview"], value["body"])
    report = value["review"].highlight_draft_report(checked)
    assert report["all_quotes_located"] and len(report["marks"]) == len(
        json.loads(value["body"])["items"]
    )
    assert (
        report["analysis"]["items"][0]["reason"] == json.loads(value["body"])["items"][0]["reason"]
    )
    assert (
        report["generation"]["backend"] == "manual"
        and report["semantic_validation"] == "not_performed"
    )
    assert checked.data["resume_state"] == "verified" and not checked.data["apply"]
    proof = value["review"].prepare_verified_highlight_original(checked)
    assert (
        proof.data == value["original_bytes"]
        and proof.document_hash == value["preview"].data["source_hash"]
    )
    with pytest.raises(ValueError, match="typed highlight"):
        value["review"].decide(checked, body=value["body"], confirm_target=True)
    unchanged(value, before, pending)


@pytest.mark.parametrize("change", ["missing", "wrong_page", "old_anchor"])
def test_unresolved_group_keeps_a_inspectable_but_produces_no_partial_marks(source_pair, change):
    value = source_pair
    draft = json.loads(value["body"])
    if change == "missing":
        draft["items"][0]["text"] = "A plausible conclusion absent from the exact original."
    elif change == "wrong_page":
        draft["items"][0]["page"] = 2
    else:
        draft["items"][0]["anchor"] = dict(p0=0, o0=10000, p1=0, o1=10001)
    before, pending = state(value["path"]), value["client"].journal.pending(1000)
    checked = value["review"].verify_highlight_draft(value["preview"], encode(draft))
    report = value["review"].highlight_draft_report(checked)
    assert not report["all_quotes_located"] and report["analysis"] is None and report["marks"] == []
    assert checked.data["resume_state"] == "needs_location" and not checked.data["apply"]
    assert (
        value["review"].prepare_verified_highlight_original(checked).data == value["original_bytes"]
    )
    unchanged(value, before, pending)


def test_saved_verified_preview_restores_private_only_and_requires_new_verification(source_pair):
    value = source_pair
    checked = value["review"].verify_highlight_draft(value["preview"], value["body"])
    saved = value["review"].save_highlight_draft(
        checked, value["body"], str(uuid4()), draft_id=str(uuid4())
    )
    row = rows(value["path"], "SELECT * FROM research_review_drafts")[0]
    assert not json.loads(row["preview_json"])["apply"]
    value["review"].close()
    receiver = ResearchReview(value["path"])
    try:
        loaded = receiver.load_highlight_draft(checked.data["id"], draft_id=saved["draft_id"])
        assert loaded["body"] == value["body"] and loaded["state"] == "verification_required"
        with pytest.raises(ValueError, match="verif"):
            receiver.highlight_draft_report(loaded["preview"])
        fresh = receiver.verify_highlight_draft(loaded["preview"], loaded["body"])
        assert receiver.highlight_draft_report(fresh)["all_quotes_located"]
    finally:
        receiver.close()


def test_reverification_of_a_different_body_revokes_the_old_runtime_result(source_pair):
    value = source_pair
    first = value["review"].verify_highlight_draft(value["preview"], value["body"])
    body = json.loads(value["body"])
    body["items"][0]["reason"] = "A different human reason after verification."
    second = value["review"].verify_highlight_draft(value["preview"], encode(body))
    with pytest.raises(ValueError, match="verif"):
        value["review"].highlight_draft_report(first)
    assert (
        value["review"].highlight_draft_report(second)["analysis"]["items"][0]["reason"]
        == body["items"][0]["reason"]
    )


@pytest.mark.parametrize("after", [1, 4, 10])
def test_cancelled_verification_leaves_no_runtime_result_or_research_change(source_pair, after):
    value = source_pair
    before, pending = state(value["path"]), value["client"].journal.pending(1000)
    calls = []

    def cancelled():
        calls.append(1)
        return len(calls) >= after

    with pytest.raises(ValueError, match="cancel"):
        value["review"].verify_highlight_draft(value["preview"], value["body"], cancelled=cancelled)
    with pytest.raises(ValueError, match="verif"):
        value["review"].highlight_draft_report(value["preview"])
    assert not value["review"]._resume_sources and not value["review"]._resume_documents
    unchanged(value, before, pending)


def test_independent_original_read_survives_new_analysis_without_creating_a_grant(source_pair):
    value = source_pair
    proof = value["review"].prepare_highlight_original(value["preview"])
    assert proof.data == value["original_bytes"]
    with (
        closing(generation._connect(value["path"])) as conn,
        conn,
        sync_capture.suppress_capture(conn),
    ):
        conn.execute("UPDATE paper_highlight_analysis SET written_at='2026-11-02T15:00:00+00:00'")
        conn.execute("UPDATE pdf_ai_highlights SET hidden=0")
    from paper_daily import highlight_draft_originals as originals

    refreshed = originals.revalidate(proof)
    assert refreshed.data == proof.data and originals.gui_status(refreshed) == "ready"
    assert not value["review"]._highlight_verifications and not value["review"]._resume_sources
    with pytest.raises(TypeError, match="process-only"):
        pickle.dumps(refreshed)
    assert value["current"].path.read_bytes() == value["current_bytes"]


def test_exact_saved_reference_cannot_follow_a_new_private_revision(source_pair):
    value = source_pair
    saved = value["review"].save_highlight_draft(
        value["preview"], value["body"], str(uuid4()), draft_id=str(uuid4())
    )
    proof = value["review"].prepare_highlight_original(
        value["preview"], reference=(saved["draft_id"], 1)
    )
    body = json.loads(value["body"])
    body["items"][0]["reason"] = "New saved private reason."
    value["review"].save_highlight_draft(
        value["preview"], encode(body), str(uuid4()), draft_id=saved["draft_id"], revision=1
    )
    from paper_daily import highlight_draft_originals as originals

    with pytest.raises(ValueError, match="draft changed"):
        originals.revalidate(proof)
    fresh = value["review"].prepare_highlight_original(
        value["preview"], reference=(saved["draft_id"], 2)
    )
    assert fresh.data == proof.data


def test_retired_original_never_falls_back_to_current_b_or_cached_bytes(source_pair):
    value = source_pair
    proof = value["review"].prepare_highlight_original(value["preview"])
    from paper_daily.sync_files import file_id

    identity = file_id(
        value["preview"].data["expected"]["paper_sync_id"],
        sync_source_files.FEATURE,
        proof.document_hash,
    )
    value["client"].save(
        value["client"].new_graph_operation("research_file", identity, {}, action="delete")
    )
    from paper_daily import highlight_draft_originals as originals

    with pytest.raises(ValueError, match="deleted or retired"):
        originals.revalidate(proof)
    with pytest.raises(ValueError, match="restoration"):
        value["review"].verify_highlight_draft(value["preview"], value["body"])
    assert value["current"].path.read_bytes() == value["current_bytes"]


def test_false_retained_page_digest_cannot_become_verified_against_real_a(source_pair):
    from dataclasses import replace

    value = source_pair
    request = value["preview"].data["id"].split(":", 1)[1]
    record = rows(value["path"], "SELECT * FROM research_generation_requests")
    record = next(row for row in record if row["request_id"] == request)
    context = generation.GenerationContext(record["context_json"])
    data = context.data
    data["request_id"] = str(uuid4())
    row = json.loads(record["row_json"])
    row["source_hash"] = "f" * 64
    for mark in data["highlight_plan"]["marks"]:
        mark["analysis_hash"] = row["source_hash"]
    retained = generation.publish_generated(
        replace(context, _json=generation._context_json(data)), row=row
    )
    assert retained.status == "candidate"
    original = value["review"].preview("generation", retained.request_id)
    view, body = value["review"].select_highlight_draft(original, "paper")
    before, pending = state(value["path"]), value["client"].journal.pending(1000)
    with pytest.raises(ValueError, match="source text"):
        value["review"].verify_highlight_draft(view, body)
    assert not value["review"]._highlight_verifications and not value["review"]._resume_sources
    unchanged(value, before, pending)


def test_highlight_read_gui_admission_is_cheap_and_cannot_be_reused_as_a_claim(
    source_pair, monkeypatch
):
    import hashlib
    import sqlite3

    import pymupdf

    from paper_daily import claim_draft_originals, highlight_draft_originals

    proof = source_pair["review"].prepare_highlight_original(source_pair["preview"])

    def forbidden(*args, **kwargs):
        raise AssertionError("GUI source admission performed expensive work")

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", forbidden)
        patch.setattr(hashlib, "sha256", forbidden)
        patch.setattr(pymupdf, "open", forbidden)
        assert highlight_draft_originals.gui_status(proof) == "ready"
        assert claim_draft_originals.gui_status(proof) == "revoked"
    with pytest.raises(ValueError, match="claim"):
        claim_draft_originals.revalidate(proof)
    source_pair["review"].close()
    assert highlight_draft_originals.gui_status(proof) == "revoked"


def test_explicit_demotion_revokes_the_verified_result_without_blocking_owned_a_reading(
    source_pair,
):
    value = source_pair
    checked = value["review"].verify_highlight_draft(value["preview"], value["body"])
    demoted = value["review"].require_draft_verification(checked)
    assert demoted.data["resume_state"] == "verification_required" and not demoted.data["apply"]
    with pytest.raises(ValueError, match="verif"):
        value["review"].highlight_draft_report(checked)
    assert value["review"].prepare_highlight_original(demoted).data == value["original_bytes"]


def test_curated_change_revokes_verified_group_but_not_the_independent_original(source_pair):
    value = source_pair
    checked = value["review"].verify_highlight_draft(value["preview"], value["body"])
    with (
        closing(generation._connect(value["path"])) as conn,
        conn,
        sync_capture.suppress_capture(conn),
    ):
        conn.execute("UPDATE pdf_ai_highlights SET hidden=0")
    before, pending = state(value["path"]), value["client"].journal.pending(1000)
    with pytest.raises(ValueError, match="changed"):
        value["review"].highlight_draft_report(checked)
    assert value["review"].prepare_highlight_original(checked).data == value["original_bytes"]
    unchanged(value, before, pending)
