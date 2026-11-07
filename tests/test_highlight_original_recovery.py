"""Read and verify adopted private original A with the old folder unavailable."""

from contextlib import closing
from uuid import uuid4

import pytest
from test_highlight_draft_storage import ready as ready
from test_highlight_draft_storage import scene as scene
from test_highlight_draft_storage import selected, state
from test_highlight_draft_storage import workspace as workspace
from test_research_generation import rows

from paper_daily import research_generation as generation
from paper_daily.research_review import ResearchReview

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


def test_independently_recovered_highlight_original_can_be_read_and_verified_without_old_paths(
    scene, tmp_path
):
    from paper_daily import sync_recovery
    from paper_daily.recovery_adoption import RecoveryAdoptionService
    from paper_daily.sync_artifacts import paths

    view, raw = selected(scene)
    original_bytes = scene["document"].path.read_bytes()
    scene["review"].save_highlight_draft(view, raw, str(uuid4()), draft_id=str(uuid4()))
    source_hash = view.data["source_hash"]
    independent = tmp_path.parent / (tmp_path.name + "-independent")
    independent.mkdir()
    with closing(generation._connect(scene["path"])) as conn:
        registered = paths(conn)
        store = registered[0] if registered else None
    backup = independent / "private-highlights.zip"
    sync_recovery.create(
        scene["path"], backup, blob_store=store, pdf_roots=[scene["path"].parent / "pdf"]
    )
    detached = independent / "detached"
    sync_recovery.restore_detached(backup, detached)
    scene["review"].close()
    tmp_path.rename(tmp_path.with_name(tmp_path.name + "-unavailable"))
    assert not scene["path"].exists()
    detached_bytes = (detached / "papers.db").read_bytes()
    detached_schema = rows(detached / "papers.db", "SELECT name FROM sqlite_master ORDER BY name")
    archived_reader = ResearchReview(detached / "papers.db")
    try:
        items = [
            item
            for item in archived_reader.page(limit=100)["items"]
            if item["origin"] == "archived_draft"
        ]
        assert len(items) == 1
        original = archived_reader.preview("archived_draft", items[0]["id"])
        assert original.data["retained"]["body"] == raw
        assert (detached / "papers.db").read_bytes() == detached_bytes
        assert (
            rows(detached / "papers.db", "SELECT name FROM sqlite_master ORDER BY name")
            == detached_schema
        )
        with pytest.raises(ValueError, match="editable"):
            archived_reader.highlight_draft_targets(original)
    finally:
        archived_reader.close()
    adoption = RecoveryAdoptionService(detached / "papers.db")
    inspection = adoption.inspect()
    assert inspection.report["supported"], inspection.report
    result = adoption.prepare(
        inspection,
        independent / "receiver",
        backup_output=independent / "receiver.zip",
        request_id=str(uuid4()),
    )
    receiver = ResearchReview(result["database"])
    try:
        items = [
            item for item in receiver.page(limit=100)["items"] if item["origin"] == "archived_draft"
        ]
        assert len(items) == 1
        archived = receiver.preview("archived_draft", items[0]["id"])
        target = receiver.highlight_draft_targets(archived)["items"][0]
        fresh, restored = receiver.select_highlight_draft(archived, target["id"])
        assert restored == raw and fresh.data["source_hash"] == source_hash
        assert fresh.data["expected"]["database_identity"] == receiver.identity
        assert fresh.data["expected"]["binding"] == receiver.binding
        assert fresh.data["apply"] is False
        before = state(result["database"])
        with closing(receiver._connect()) as conn:
            client = conn._capture_client
        pending = client.journal.pending(1000)
        proof = receiver.prepare_highlight_original(fresh)
        assert proof.data == original_bytes and proof.document_hash == source_hash
        assert not receiver._highlight_verifications and not receiver._resume_sources
        checked = receiver.verify_highlight_draft(fresh, restored)
        assert receiver.highlight_draft_report(checked)["all_quotes_located"]
        assert receiver.prepare_verified_highlight_original(checked).data == original_bytes
        assert state(result["database"]) == before and client.journal.pending(1000) == pending
        saved = receiver.save_highlight_draft(fresh, restored, str(uuid4()), draft_id=str(uuid4()))
        assert (
            receiver.load_highlight_draft(fresh.data["id"], draft_id=saved["draft_id"])["body"]
            == raw
        )
    finally:
        receiver.close()
