"""Accepted claims and their immutable originals share one publication boundary."""

import sqlite3
from contextlib import closing

import pytest
from test_claim_jobs import claims as claims_fixture
from test_claim_jobs import job
from test_claim_jobs import ready as ready_fixture
from test_claim_jobs import workspace as workspace_fixture
from test_research_generation import rows
from test_sync_source_files import pdf

from paper_daily import research_generation as generation
from paper_daily import source_snapshots, sync_capture, sync_source_files

claims = claims_fixture
ready = ready_fixture
workspace = workspace_fixture


def originals(claims):
    client = claims[0][1]
    return (
        []
        if client is None
        else [
            op
            for op in client.journal.pending(1000)
            if op.get("payload", {}).get("feature") == "original_source"
        ]
    )


def test_atomic_failure_rolls_back_source_claim_and_receipt_then_retry_preserves_bytes(claims):
    db = claims[0][0]
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute(
            "CREATE TRIGGER source_claim_failure BEFORE INSERT ON paper_claim_sets "
            "BEGIN SELECT RAISE(ABORT,'stop'); END"
        )
    current = job(claims)
    result = current.run()
    assert result.status == "candidate"
    assert originals(claims) == []
    assert rows(db, "SELECT * FROM paper_claim_sets") == []
    assert source_snapshots.list_owned(db)
    if claims[0][1]:
        assert rows(db, "SELECT * FROM research_file_versions") == []
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("DROP TRIGGER source_claim_failure")
    accepted = generation.publish_generated(current.context, row=current.result)
    assert accepted.status == "accepted"
    assert generation.publish_generated(current.context, row=current.result) == accepted
    assert len(claims[2]) == 1
    assert len(originals(claims)) == (1 if claims[0][1] else 0)


def test_lost_commit_acknowledgement_does_not_duplicate_original_or_repeat_AI(claims, monkeypatch):
    current = job(claims)
    state = {"lost": False}

    class LostAck(sync_capture.CaptureConnection):
        def commit(self):
            accepted = self.execute(
                "SELECT 1 FROM research_generation_requests "
                "WHERE request_id=? AND status='accepted'",
                (current.context.request_id,),
            ).fetchone()
            super().commit()
            if accepted and not state["lost"]:
                state["lost"] = True
                raise OSError("commit acknowledgement lost")

    def connect(path):
        conn = sqlite3.connect(path, factory=LostAck)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(generation, "_connect", connect)
    assert current.run().status == "accepted"
    assert state["lost"] and current.run().status == "accepted"
    assert len(claims[2]) == 1
    assert len(originals(claims)) == (1 if claims[0][1] else 0)


@pytest.mark.parametrize("change", ["pdf", "parent"])
def test_late_source_or_parent_change_leaves_no_shared_original_candidate(
    claims, monkeypatch, change
):
    current = job(claims)
    stage = sync_source_files.stage_claim_source

    def changed(context, row):
        prepared = stage(context, row)
        if change == "pdf":
            claims[0][2].path.write_bytes(pdf("A newer current source B"))
        else:
            with closing(sqlite3.connect(context.db_path)) as conn, conn:
                conn.execute("DELETE FROM papers WHERE id='paper'")
                conn.execute(
                    "INSERT INTO papers(id,title,title_key,venue,year,source) "
                    "VALUES('paper','Replacement','replacement','Fixture',2026,'fixture')"
                )
        return prepared

    monkeypatch.setattr(sync_source_files, "stage_claim_source", changed)
    assert current.run().status == "candidate"
    assert originals(claims) == []
    assert rows(claims[0][0], "SELECT * FROM paper_claim_sets") == []
    assert source_snapshots.list_owned(claims[0][0])


def test_real_generation_history_remains_an_explicit_enrollment_blocker(claims):
    from paper_daily.workspace_enrollment import EnrollmentService

    assert job(claims).run().status == "accepted"
    report = EnrollmentService(claims[0][0]).plan(pdfs={"paper": claims[0][2].path})
    assert not report["supported"] and not report["runtime_enrollment_complete"]
    assert report["archived_source_receipts"] == 1
    assert report["original_source_count"] == 1
    assert any("research_generation_requests" in item for item in report["blockers"])
    assert any("research_parent_lifecycle" in item for item in report["blockers"])
