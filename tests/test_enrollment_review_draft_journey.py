"""Saved human draft variants remain readable across first enrollment and recovery."""

import json
import zipfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_enrollment_review_decisions import decision as decision
from test_enrollment_review_decisions import source as source

from paper_daily import enrollment_history, sync_recovery
from paper_daily import research_generation as generation
from paper_daily.research_review import ResearchReview
from paper_daily.workspace_enrollment import EnrollmentService

PROTOCOL = "research_review_drafts"


@pytest.fixture
def draft_variants(decision):
    value = decision
    review = ResearchReview(value["database"])
    original_id = value["receipt"]["origin_id"]
    preview = review.target_preview(review.preview("generation", original_id), "paper")
    request_id = str(uuid4())
    one = review.save_draft(preview, "First saved human interpretation", request_id)
    two = review.save_draft(preview, "Second independent draft", request_id)
    assert one["draft_id"] != two["draft_id"]
    review.close()
    reopened = ResearchReview(value["database"])
    assert {
        row["draft_id"] for row in reopened.list_drafts("generation", original_id)["items"]
    } == {
        one["draft_id"],
        two["draft_id"],
    }
    reopened.close()
    with closing(generation._connect(value["database"])) as conn:
        records = [
            dict(row)
            for row in conn.execute("SELECT * FROM research_review_drafts ORDER BY save_order")
        ]
    assert [row["request_id"] for row in records] == [request_id, request_id]
    assert [row["body"] for row in records] == [
        "First saved human interpretation",
        "Second independent draft",
    ]
    return {**value, "drafts": records, "draft_request": request_id}


def prepare(value, tmp_path):
    return EnrollmentService(value["database"]).prepare(
        tmp_path / "candidate",
        backup_output=tmp_path / "backup.zip",
        request_id=str(uuid4()),
        pdfs={"paper": value["primary"]},
    )


def test_two_real_draft_variants_sharing_request_survive_copy_and_independent_backup(
    draft_variants, tmp_path
):
    value = draft_variants
    before = value["database"].read_bytes()
    plan = EnrollmentService(value["database"]).plan(pdfs={"paper": value["primary"]})
    assert plan["supported"], plan["blockers"]
    assert plan["archived_history_by_protocol"][PROTOCOL] == 2
    result = prepare(value, tmp_path)
    with closing(generation._connect(result["database"])) as conn:
        rows = [
            enrollment_history.validate(row)[0]
            for row in enrollment_history.archived(conn)
            if row["protocol"] == PROTOCOL
        ]
        assert sorted(rows, key=lambda row: row["save_order"]) == value["drafts"]
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (PROTOCOL,)).fetchone()
        wire = "\n".join(
            row[0] for row in conn.execute("SELECT envelope FROM paperfact_sync_operations")
        )
        assert value["draft_request"] not in wire and PROTOCOL not in wire
    with zipfile.ZipFile(result["backup"]) as bundle:
        assert bundle.read("objects/" + value["source_hash"]) == value["original_bytes"]
    detached = tmp_path / "detached"
    sync_recovery.restore_detached(result["backup"], detached)
    with closing(generation._connect(detached / "papers.db")) as conn:
        wrappers = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_history_archive'"
            )
        ]
        rows = [
            enrollment_history.validate(row)[0] for row in wrappers if row["protocol"] == PROTOCOL
        ]
        assert sorted(rows, key=lambda row: row["save_order"]) == value["drafts"]
    assert value["database"].read_bytes() == before
    assert value["primary"].read_bytes() == value["original_bytes"]


def test_copied_draft_variants_are_inspectable_as_separate_private_research(
    draft_variants, tmp_path
):
    value = draft_variants
    result = prepare(value, tmp_path)
    review = ResearchReview(Path(result["database"]))
    try:
        items = [
            row for row in review.page(limit=100)["items"] if row["origin"] == "archived_draft"
        ]
        assert len(items) == 2
        exports = []
        for item in items:
            preview = review.preview(item["origin"], item["id"])
            assert not preview.data["apply"] and not preview.data["editable"]
            text = review.export_text(preview)
            assert str(value["database"]) not in text and "database_identity" not in text
            exports.append(text)
        assert any("First saved human interpretation" in text for text in exports)
        assert any("Second independent draft" in text for text in exports)
    finally:
        review.close()
