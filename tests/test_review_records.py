"""Read-only adapters and recovery preserve grouped research and provenance."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_research_review import candidate, context, output, query
from test_research_review import workspace as workspace  # noqa: F401
from test_sync_files import PAPER
from test_sync_files import codec as codec  # noqa: F401

from paper_daily import research_generation as generation
from paper_daily import sync_capture, sync_recovery
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.research_review import Preview, ResearchReview, validate_receipt
from paper_daily.sync_files import file_id


def test_capture_group_has_original_current_retained_and_no_generic_apply(workspace):
    path, client = workspace
    candidate(path)
    with closing(generation._connect(path)) as conn:
        row = dict(conn.execute("SELECT * FROM close_readings").fetchone())
        retained = {**row, "body": "Grouped retained text"}
        value = {
            "observations": [],
            "mutations": [
                {
                    "table_name": "close_readings",
                    "row_key": '["paper"]',
                    "before_json": json.dumps({**row, "body": "Original text"}),
                    "after_json": json.dumps(retained),
                }
            ],
        }
        with sync_capture.suppress_capture(conn):
            conn.execute(
                "INSERT INTO research_capture_candidates VALUES(?,?)",
                ("grouped", json.dumps(value)),
            )
            conn.commit()
    review = ResearchReview(path)
    before = client.journal.pending()
    preview = review.preview("capture", "grouped")
    assert preview.data["original"][0]["row"]["body"] == "Original text"
    assert preview.data["current"][0]["row"]["body"] == "Current saved analysis"
    assert preview.data["retained"][0]["row"]["body"] == "Grouped retained text"
    assert not preview.data["apply"]
    with pytest.raises(ValueError, match="grouped"):
        review.decide(preview)
    assert "Grouped retained text" in review.export_text(preview)
    review.decide(preview, keep=True, request_id="keep-group")
    assert client.journal.pending() == before


def test_malformed_capture_never_queries_retained_table_name(workspace):
    path, _ = workspace
    with closing(generation._connect(path)) as conn, sync_capture.suppress_capture(conn):
        conn.execute(
            "INSERT INTO research_capture_candidates VALUES(?,?)",
            (
                "bad",
                json.dumps(
                    {
                        "observations": [],
                        "mutations": [
                            {
                                "table_name": "papers; DELETE FROM papers;",
                                "row_key": "[]",
                                "before_json": None,
                                "after_json": "{}",
                            }
                        ],
                    }
                ),
            ),
        )
        conn.commit()
    review = ResearchReview(path)
    with pytest.raises(ValueError, match="Unsupported"):
        review.preview("capture", "bad")
    assert query(path, "SELECT title FROM papers") == [("Paper",)]


def test_file_candidate_validated_metadata_preview_does_not_load_assets(
    workspace, codec, monkeypatch
):
    path, client = workspace
    _deck, payload, _blobs = codec
    identity = file_id(PAPER, "deck", "guide")
    with closing(generation._connect(path)) as conn, sync_capture.suppress_capture(conn):
        conn.execute(
            "INSERT INTO research_file_candidates VALUES(?,?,?,?)",
            (
                "file-candidate",
                identity,
                json.dumps(payload),
                "{}",
            ),
        )
        conn.commit()
    from paper_daily import sync_artifacts

    monkeypatch.setattr(sync_artifacts, "materialize", lambda *a: pytest.fail("asset execution"))
    review = ResearchReview(path)
    before = client.journal.pending()
    preview = review.preview("file", "file-candidate")
    assert preview.data["retained"] == payload
    assert not preview.data["apply"]
    with pytest.raises(ValueError, match="verified assets"):
        review.decide(preview)
    review.decide(preview, keep=True, request_id="keep-file")
    assert client.journal.pending() == before


def test_owned_sidecar_read_and_explicit_target_choice(workspace):
    path, _ = workspace
    original = context(path)
    generation._retain_outside_database(
        original, output("Recovered sidecar text"), "Fixture lost binding"
    )
    review = ResearchReview(path)
    item = next(item for item in review.page()["items"] if item["origin"] == "sidecar")
    preview = review.preview("sidecar", item["id"])
    assert not preview.data["apply"]
    assert "Recovered sidecar text" in review.export_text(preview)
    chosen = review.target_preview(preview, "paper")
    review.decide(chosen, confirm_target=True, request_id="sidecar-choice")
    assert query(path, "SELECT body FROM close_readings") == [("Recovered sidecar text",)]


def test_preview_integrity_prevents_modified_target_or_capability(workspace):
    path, _ = workspace
    review = ResearchReview(path)
    preview = review.preview("generation", candidate(path))
    data = preview.data
    data["retained"]["body"] = "Forged candidate"
    altered = Preview(json.dumps(data), preview.seal)
    with pytest.raises(ValueError, match="modified"):
        review.decide(altered)
    assert query(path, "SELECT body FROM close_readings") == [("Current saved analysis",)]


def test_backup_preserves_receipts_source_and_epochs_as_detached_provenance(workspace, tmp_path):
    path, client = workspace
    review = ResearchReview(path)
    preview = review.preview("generation", candidate(path))
    review.decide(preview, request_id="backup-review")
    with closing(generation._connect(path)) as conn:
        old_epoch = parent_lifecycle(conn, "paper", "paper")
        receipt = dict(conn.execute("SELECT * FROM research_review_receipts").fetchone())
        validate_receipt(receipt)
    archive = tmp_path / "backup.zip"
    sync_recovery.create(path, archive)
    sync_recovery.restore_detached(archive, tmp_path / "restored")
    restored = tmp_path / "restored" / "papers.db"
    with closing(sqlite3.connect(restored)) as conn:
        saved = json.loads(
            conn.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_review_receipts'"
            ).fetchone()[0]
        )
        assert saved == receipt
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='research_parent_lifecycle'"
        ).fetchone()
    detached = ResearchReview(restored)
    pages = detached.page(limit=100)["items"]
    assert all(item["origin"] == "recovery" for item in pages)
    previews = [detached.preview(item["origin"], item["id"]) for item in pages]
    assert not any(item.data["apply"] for item in previews)
    with closing(generation._connect(restored)) as conn:
        assert parent_lifecycle(conn, "paper", "paper") != old_epoch
    assert query(restored, "SELECT body FROM close_readings") == [("Retained generated analysis",)]
    assert client.journal.pending()


def test_kept_offline_source_provenance_is_persistent(tmp_path):
    from test_research_lifecycle import legacy

    path = tmp_path / "legacy.db"
    legacy(path)
    review = ResearchReview(path)
    selected = review.target_preview(
        review.preview("generation", candidate(path, source_hash="c" * 64)), "paper"
    )
    review.decide(selected, confirm_target=True, request_id="source-proof")
    provenance = json.loads(query(path, "SELECT provenance FROM research_review_receipts")[0][0])
    assert provenance["source_document_hash"] == "c" * 64
    assert provenance["target_kind"] == "paper" and provenance["target_id"] == "paper"
    assert provenance["parent_token"] == selected.data["parent_token"]
