"""Actual generated history remains observations, with strict original-input validation."""

import hashlib
import json
import sqlite3
from contextlib import closing

import pytest
from test_claim_jobs import claims as claims_fixture
from test_claim_jobs import job
from test_claim_jobs import ready as ready_fixture
from test_claim_jobs import workspace as workspace_fixture
from test_recovery_adoption import prepared
from test_sync_recovery import archive_rows, rewrite

from paper_daily import llm, sync_recovery
from paper_daily.recovery_adoption import RecoveryAdoptionService
from paper_daily.sync_artifacts import paths

claims = claims_fixture
ready = ready_fixture
workspace = workspace_fixture


def generated_backup(claims, tmp_path):
    assert job(claims).run().status == "accepted"
    database = claims[0][0]
    if claims[0][1] is None:
        blobs = None
    else:
        with closing(sqlite3.connect(database)) as conn:
            blobs = paths(conn)[0]
            portable = conn.execute(
                "SELECT sync_id FROM research_paper_identity WHERE local_id='paper'"
            ).fetchone()[0]
        # This enrolled fixture starts from a legacy loaded PDF. Explicitly bind
        # that current PDF rather than weakening backup's untracked-file guard.
        from paper_daily.sync_document_actions import stage_file
        from paper_daily.sync_documents import (
            bind_verified_document,
            desired_document,
            verify_document,
        )
        from paper_daily.sync_operations import ResearchOperations

        manifest = stage_file(blobs, claims[0][2].path)
        client = claims[0][1]
        ResearchOperations(client).attach_document(
            portable, manifest, store=blobs, request_id="fixture-current-primary"
        )
        with client.journal.transaction() as conn:
            target = desired_document(conn, portable)
        proof = verify_document(blobs, target)
        with client.journal.transaction() as conn:
            assert bind_verified_document(conn, target, proof)
    package = tmp_path / "generated.zip"
    sync_recovery.create(database, package, blob_store=blobs, pdf_roots=[claims[0][2].path.parent])
    return package


def test_actual_generated_jobs_and_source_receipts_are_archived_without_replay(
    claims, tmp_path, monkeypatch
):
    package = generated_backup(claims, tmp_path)
    old = archive_rows(package, "research_generation_requests")
    folder = tmp_path / "generated-detached"
    sync_recovery.restore_detached(package, folder)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Recovery adoption invoked AI/provider settings")

    monkeypatch.setattr(llm, "complete_result", forbidden)
    monkeypatch.setattr(llm, "settings", forbidden)
    service = RecoveryAdoptionService(folder / "papers.db")
    result = prepared(service, service.inspect(), tmp_path, "-generated")
    with closing(sqlite3.connect(result["database"])) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_generation_requests'"
        ).fetchone()
    second = tmp_path / "generated-again"
    sync_recovery.restore_detached(result["backup"], second)
    service = RecoveryAdoptionService(second / "papers.db")
    assert service.inspect().report["supported"]
    assert len(claims[2]) == 1
    assert old[0]["status"] == "accepted"


def test_nested_original_generation_input_is_not_accepted_by_weaker_outer_recovery_parser(
    claims, tmp_path
):
    package = generated_backup(claims, tmp_path)

    def mutate(manifest, files):
        filename = "tables/research_generation_requests.jsonl"
        rows = [json.loads(line) for line in files[filename].splitlines()]
        context = json.loads(rows[0]["context_json"])
        context["inputs"]["unknown_future_authority"] = {"execute": True}
        rows[0]["context_json"] = json.dumps(context, sort_keys=True, separators=(",", ":"))
        data = b"".join((sync_recovery._json(row) + "\n").encode() for row in rows)
        files[filename] = data
        table = next(
            item for item in manifest["tables"] if item["name"] == "research_generation_requests"
        )
        table.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())

    changed = rewrite(package, tmp_path / "unknown-input.zip", mutate)
    # Old recovery can preserve this observation, but it must not gain adoption authority.
    sync_recovery.inspect(changed)
    folder = tmp_path / "unknown-input-detached"
    sync_recovery.restore_detached(changed, folder)
    with pytest.raises(ValueError):
        RecoveryAdoptionService(folder / "papers.db").inspect()
    assert not (tmp_path / "editable-generated").exists()
