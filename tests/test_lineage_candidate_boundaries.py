"""Candidate persistence keeps private paths, retries and bounded reads isolated."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace

import pytest
from test_lineage_candidates import completed
from test_lineage_jobs import work
from test_research_lineage import corpus as corpus

from paper_daily import lineage_candidates, llm, source_snapshots, sync_capture, sync_recovery
from paper_daily import research_generation as generation


def test_native_candidate_cannot_be_retargeted_using_serialized_private_paths(corpus, monkeypatch):
    job, _result, _calls = completed(corpus, monkeypatch)
    prepared = job._state.candidate
    record = prepared.record
    foreign = corpus[0].parent / "foreign.sqlite"
    with closing(sqlite3.connect(foreign)) as conn, conn:
        conn.execute("CREATE TABLE untouched(value TEXT)")
        conn.execute("INSERT INTO untouched VALUES('keep')")
    before = foreign.read_bytes()
    context = json.loads(record["context_json"])
    context["db_path"] = str(foreign)
    record["context_json"] = json.dumps(context)
    record["candidate_id"] = generation._digest(
        {"context": context, "row": json.loads(record["row_json"])}
    )
    tampered = replace(prepared, _json=generation._json(record))
    with pytest.raises(ValueError, match="native"):
        work(lineage_candidates.persist, tampered)
    assert foreign.read_bytes() == before


def test_concurrent_native_retries_keep_one_exact_receipt(corpus, monkeypatch):
    job, _result, calls = completed(corpus, monkeypatch)
    prepared = job._state.candidate
    with closing(sqlite3.connect(corpus[0])) as conn, conn:
        conn.execute("DELETE FROM research_generation_requests")
    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = [
            future.result(timeout=10)
            for future in [
                pool.submit(lineage_candidates.persist, prepared),
                pool.submit(lineage_candidates.persist, prepared),
            ]
        ]
    assert one == two and calls == [True]
    assert work(lineage_candidates.saved, corpus[0], "focal") == [prepared.record]


def test_commit_acknowledgement_loss_probes_success_without_duplicate_sidecar(corpus, monkeypatch):
    lost = []

    class LostAck(sync_capture.CaptureConnection):
        def commit(self):
            super().commit()
            if not lost:
                lost.append(True)
                raise OSError("fixture committed acknowledgement lost")

    def connect(path):
        conn = sqlite3.connect(str(path), factory=LostAck, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(generation, "_connect", connect)
    job, result, calls = completed(corpus, monkeypatch)
    assert calls == [True] and result.execution["persistence"] == "candidate"
    assert len(work(lineage_candidates.saved, corpus[0], "focal")) == 1
    assert generation.list_recovery_requests(corpus[0]) == []
    assert work(job.run) is result


def test_saved_reader_does_not_parse_unrelated_invalid_context(corpus, monkeypatch):
    job, _result, _calls = completed(corpus, monkeypatch)
    with closing(sqlite3.connect(corpus[0])) as conn, conn:
        conn.execute(
            "INSERT INTO research_generation_requests VALUES(?,?,?,?,?,?)",
            ("unrelated", "not-json", "not-json", "candidate", "invalid", "invalid"),
        )
    records = work(lineage_candidates.saved, corpus[0], "focal")
    assert len(records) == 1 and records[0]["request_id"] == job.request_id


def test_missing_private_original_blocks_backup_without_partial_output(corpus, monkeypatch):
    completed(corpus, monkeypatch)
    rows = source_snapshots.list_owned(corpus[0])
    source_snapshots.source_path(corpus[0], rows[0]).unlink()
    destination = corpus[0].parent / "incomplete.zip"
    with pytest.raises(ValueError):
        sync_recovery.create(corpus[0], destination)
    assert not destination.exists()


def test_saved_limit_refuses_without_truncating_or_running_model(corpus, monkeypatch):
    completed(corpus, monkeypatch)
    completed(corpus, monkeypatch)
    monkeypatch.setattr(lineage_candidates.lineage_sets, "MAX_SETS", 1)
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("Saved read"))
    before = corpus[0].read_bytes()
    with pytest.raises(ValueError, match="bounded"):
        work(lineage_candidates.saved, corpus[0], "focal")
    assert corpus[0].read_bytes() == before
