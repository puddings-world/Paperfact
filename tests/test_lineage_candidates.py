"""Completed proposals survive restart, stale owners and private recovery channels."""

import copy
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from contextlib import closing
from pathlib import Path

import pytest
from test_lineage_jobs import routes, work
from test_research_lineage import corpus as corpus
from test_research_lineage import proposals

from paper_daily import lineage_candidates, llm, source_snapshots, store, sync_recovery
from paper_daily import research_generation as generation
from paper_daily.ai_types import Completion
from paper_daily.lineage_jobs import LineageJob
from paper_daily.research_review import ResearchReview


def completed(corpus, monkeypatch, action=lambda: None):
    with closing(sqlite3.connect(corpus[0])) as conn, conn:
        store._migrate(conn)
    calls = []

    def complete(*_a, **_k):
        calls.append(True)
        action()
        return Completion(json.dumps(proposals(corpus[2])))

    monkeypatch.setattr(llm, "complete_result", complete)
    job = work(LineageJob.prepare, corpus[2], connections=routes())
    return job, work(job.run), calls


def test_saved_proposal_is_exact_read_only_and_reopens_in_another_process(corpus, monkeypatch):
    job, result, calls = completed(corpus, monkeypatch)
    assert result.execution["persistence"] == "candidate"
    before = corpus[0].read_bytes()
    records = work(lineage_candidates.saved, corpus[0], "focal")
    assert len(records) == 1 and records[0]["request_id"] == job.request_id
    body = json.loads(json.loads(records[0]["row_json"])["body_json"])
    assert body["report"] == result.report and records[0]["status"] == "candidate"
    assert len(lineage_candidates.originals(records[0])) == 3
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("Saved-only read"))
    assert work(lineage_candidates.saved, corpus[0], "focal") == records
    assert work(job.run) is result and calls == [True]
    script = """import json,sys
from concurrent.futures import ThreadPoolExecutor
from paper_daily.lineage_candidates import saved
with ThreadPoolExecutor(max_workers=1) as pool:
    records=pool.submit(saved,sys.argv[1],'focal').result(timeout=10)
print(json.dumps(records))
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(corpus[0])],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    assert child.returncode == 0, child.stderr
    assert json.loads(child.stdout) == records and corpus[0].read_bytes() == before


def test_stale_source_result_remains_saved_but_generic_review_cannot_apply(corpus, monkeypatch):
    job, result, _calls = completed(
        corpus,
        monkeypatch,
        lambda: (corpus[1] / "focal.pdf").write_bytes(b"changed source after call began"),
    )
    records = work(lineage_candidates.saved, corpus[0], "focal")
    assert records[0]["reason"] == result.retention_reason == "source_or_owner_changed"
    review = ResearchReview(corpus[0])
    preview = review.preview("generation", job.request_id)
    assert preview.data["apply"] is False and preview.data["editable"] is False
    assert json.loads(preview.data["retained"]["body_json"])["report"] == result.report
    assert "corpus" in preview.data["reason"]
    selected = review.target_preview(preview, "prior")
    assert not selected.data["apply"] and selected.data["scope"] == preview.data["scope"]
    with pytest.raises(ValueError):
        review.decide(preview)
    exported = json.loads(review.export_text(preview))
    assert exported["content"]["statements"][0]["text"] == result.report["statements"][0]["text"]
    assert str(corpus[0]) not in json.dumps(exported) and job.corpus_id not in json.dumps(exported)
    with closing(sqlite3.connect(corpus[0])) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='paper_lineage_sets'"
        ).fetchone()


def test_actual_backup_and_detached_restore_preserve_report_and_all_originals(corpus, monkeypatch):
    job, _result, _calls = completed(corpus, monkeypatch)
    records = work(lineage_candidates.saved, corpus[0], "focal")
    output = corpus[0].parent / "candidate.zip"
    sync_recovery.create(corpus[0], output)
    with zipfile.ZipFile(output) as archive:
        assert all(
            archive.read("objects/" + r["sha256"])
            == source_snapshots.source_path(corpus[0], r).read_bytes()
            for r in source_snapshots.list_owned(corpus[0])
        )
    destination = corpus[0].parent / "detached"
    sync_recovery.restore_detached(output, destination)
    with closing(sqlite3.connect(destination / "papers.db")) as conn:
        recovered = [
            json.loads(r[0])
            for r in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_generation_requests'"
            )
        ]
        assert recovered == records and recovered[0]["request_id"] == job.request_id
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='paperfact_sync_identity'"
        ).fetchone()
    assert work(lineage_candidates.saved, destination / "papers.db", "focal") == []


def test_replaced_database_keeps_proposal_outside_foreign_sql_and_backups_exact_originals(
    corpus, monkeypatch
):
    replacement = corpus[0].with_suffix(".new")

    def replace():
        shutil.copyfile(corpus[0], replacement)
        os.replace(replacement, corpus[0])

    job, result, _calls = completed(corpus, monkeypatch, replace)
    records = work(lineage_candidates.saved, corpus[0], "focal")
    assert len(records) == 1 and result.execution["persistence"] == "candidate"
    assert records[0]["request_id"] == job.request_id
    with closing(sqlite3.connect(corpus[0])) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_generation_requests'"
        ).fetchone()
    output = corpus[0].parent / "replaced-candidate.zip"
    sync_recovery.create(corpus[0], output)
    manifest = sync_recovery.inspect(output)
    assert any(
        t["name"] == "research_generation_recovery" and t["count"] == 1 for t in manifest["tables"]
    )
    with zipfile.ZipFile(output) as archive:
        assert all(
            archive.getinfo("objects/" + d["sha256"]).file_size == d["size"]
            for d in lineage_candidates.originals(records[0])
        )


def test_save_failure_retries_completed_response_without_another_call(corpus, monkeypatch):
    calls, attempts = [], []
    monkeypatch.setattr(
        llm,
        "complete_result",
        lambda *_a, **_k: calls.append(True) or Completion(json.dumps(proposals(corpus[2]))),
    )
    job = work(LineageJob.prepare, corpus[2], connections=routes())
    persist = lineage_candidates.persist

    def fail(candidate):
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("fixture unavailable retention")
        return persist(candidate)

    monkeypatch.setattr(lineage_candidates, "persist", fail)
    with pytest.raises(OSError, match="unavailable"):
        work(job.run)
    assert job.result.report["statements"] and calls == [True]
    result = work(job.run)
    assert result.execution["persistence"] == "candidate" and calls == [True]
    assert len(work(lineage_candidates.saved, corpus[0], "focal")) == 1


@pytest.mark.parametrize("change", ["status", "reason", "missing-original", "foreign-parent"])
def test_archive_validation_rejects_forged_acceptance_or_broken_original_closure(
    corpus, monkeypatch, change
):
    completed(corpus, monkeypatch)
    record = copy.deepcopy(work(lineage_candidates.saved, corpus[0], "focal")[0])
    if change == "status":
        record["status"] = "accepted"
    elif change == "reason":
        record["reason"] = []
    else:
        context = json.loads(record["context_json"])
        if change == "missing-original":
            context["inputs"]["originals"].pop()
        else:
            context["inputs"]["parents"][1]["paper_id"] = "focal"
        record["context_json"] = json.dumps(context)
        record["candidate_id"] = generation._digest(
            {"context": context, "row": json.loads(record["row_json"])}
        )
    with pytest.raises(ValueError):
        generation.validate_request_record(record)
