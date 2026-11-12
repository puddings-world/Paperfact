"""A manual first-enrollment copy survives another independent full recovery."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from test_manual_current_first_enrollment import tree
from test_manual_deck_enrollment import baseline, native, prepare
from test_manual_deck_enrollment import no_external as no_external
from test_manual_deck_enrollment import scientific as scientific
from test_manual_deck_enrollment import source as source

from paper_daily import enrolled_deck_proposals as catalog
from paper_daily import enrollment_history, presentations, recovery_provenance, retained_originals
from paper_daily import proposal_recovery_current as observed
from paper_daily.document_reader import from_workspace
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.research_file_review import _storage
from paper_daily.research_review import ResearchReview
from paper_daily.sync_artifacts import desired_file, verify_closure
from paper_daily.sync_blobs import BlobManifest
from paper_daily.sync_deck_publication import publication_scope, runtime
from paper_daily.sync_files import file_id
from paper_daily.workspace_service import Ticket, WorkspaceService


def test_manual_first_enrollment_backup_fresh_recovery_is_self_contained(
    source, tmp_path, monkeypatch
):
    initial_before = baseline(source)
    saved_bytes = source["saved"].read_bytes()
    saved_json = json.loads(saved_bytes)
    primary_bytes = source["primary"].read_bytes()
    first = prepare(source)
    first_database = Path(first["database"])
    service = WorkspaceService(first_database)
    service.status()
    first_before = tree(source["output"])
    archive, detached, output = (
        tmp_path / "second-complete.zip", tmp_path / "detached", tmp_path / "fresh-editable"
    )
    made = service.backup(archive, Ticket())
    checked = service.inspect(archive, Ticket())
    assert checked == made["manifest"]
    service.restore(archive, detached, checked["backup_id"], Ticket())
    adopter = RecoveryAdoptionService(detached / "papers.db")
    inspection = adopter.inspect()
    assert inspection.report["supported"], inspection.report["blockers"]
    result = adopter.prepare(
        inspection, output, backup_output=tmp_path / "fresh-editable.zip",
        request_id=str(uuid4()),
    )
    assert result["editable_copy"] and not result["adopted"] and not result["uploaded"]
    assert baseline(source) == initial_before and tree(source["output"]) == first_before
    client = runtime(database=Path(result["database"]))
    original_open = Path.open
    old_roots = (source["root"].resolve(), source["output"].resolve(), detached.resolve())

    def independent(path, *args, **kwargs):
        if any(path.resolve().is_relative_to(root) for root in old_roots):
            pytest.fail("Recovered workspace tried to open an old source/restore file")
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", independent)
        with client.journal.transaction() as conn:
            records = [
                enrollment_history.validate(row)[0]
                for row in enrollment_history.archived(conn)
                if row["protocol"] == observed.TABLE
            ]
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
            if recovery_provenance.TABLE in tables:
                archive_rows = [
                    dict(zip(recovery_provenance.COLUMNS.split(), row, strict=True))
                    for row in conn.execute(
                        "SELECT record_id,body_json FROM research_recovery_provenance"
                    )
                ]

                def archived_manual(group):
                    found = list(group.archived_observed_currents.values())
                    for child in getattr(group, "_recovered_groups", ()):
                        found.extend(archived_manual(child))
                    return found

                for group in recovery_provenance.validate_groups(archive_rows):
                    records.extend(archived_manual(group))
            cache = _storage(conn)[0]
            portable = conn.execute(
                "SELECT sync_id FROM research_paper_identity WHERE local_id=?", ("local-paper",)
            ).fetchone()[0]
            operation = desired_file(conn, file_id(portable, "deck", "guide"))
        retained_manual = [
            observed.read(
                row,
                lambda item: cache.verified_path(
                    BlobManifest(item["sha256"], item["size"])
                ).read_bytes(),
            )
            for row in records
        ]
        assert any(value["raw"] == saved_json for value in retained_manual)
        assert any(
            cache.verified_path(
                BlobManifest(
                    observed.validate(row)["body"]["sha256"],
                    observed.validate(row)["body"]["size"],
                )
            ).read_bytes() == saved_bytes
            for row in records
        )
        assert all(value["publish"] is False for value in retained_manual)
        assert verify_closure(cache, operation)[1]["deck"]["title"] == "Prior manual current"
        with publication_scope(client):
            loaded = presentations.load_deck("local-paper", "guide")
            assert loaded.title == "Prior manual current"
            for figure in loaded.figures:
                assert presentations.figure_bytes(loaded, figure["id"])
            loaded.title = "Explicit edit after independent recovery"
            presentations.save_deck(loaded, request_id="second-recovery-manual-edit")
            assert presentations.load_deck("local-paper", "guide").title == loaded.title
        reader = from_workspace(Path(result["database"]))
        try:
            assert reader.resolve("local-paper").path.read_bytes() == primary_bytes
        finally:
            reader.close()
        review = ResearchReview(Path(result["database"]))
        try:
            items = [
                row for row in review.page(limit=100)["items"]
                if row["origin"] == "enrolled_deck"
            ]
            assert len(items) == 1
            view = review.prepare_file(review.preview("enrolled_deck", items[0]["id"]))
            assert view.data["retained"] == source["expected"]["deck"]
            assert view.data["retained_evidence"] == source["expected"]["evidence"]
            assert len(view.data["image_manifest"]) == 4
            assert view.data["current"]["title"] == "Explicit edit after independent recovery"
            sha = source["expected"]["source_document_hash"]
            proof = retained_originals.prepare(review, view, sha)
            assert proof.data == source["expected"]["original_bytes"][sha]
            full = catalog.read(
                client, cache, view.data["id"],
                expected_native=native(Path(result["database"])),
            )
            assert full.content == source["expected"]
        finally:
            review.close()
    assert baseline(source) == initial_before and tree(source["output"]) == first_before
