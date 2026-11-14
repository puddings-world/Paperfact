"""Staged local compound publication is atomic and never bypasses sync capture."""

import json
import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest
from test_lineage_jobs import routes, work
from test_lineage_target_jobs import job_for, observed, write_target
from test_research_lineage import corpus as corpus
from test_research_lineage import proposals

from paper_daily import lineage_candidates, lineage_sets, llm, local_source_owners, research_lineage
from paper_daily import lineage_publication as publication
from paper_daily import research_generation as generation
from paper_daily.ai_types import Completion
from paper_daily.lineage_jobs import LineageJob


def prepared(corpus, monkeypatch):
    observation = observed(corpus)
    response = json.dumps(proposals(corpus[2]))
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: Completion(response))
    job = job_for(corpus, observation)
    work(job.run)
    return job, work(publication.prepare, job._state.candidate)


def publish(database, staged, *, rollback=False):
    with closing(generation._connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        result = publication.publish_in(conn, staged)
        if rollback:
            conn.rollback()
        else:
            conn.commit()
        return result


def count(database, table):
    with closing(sqlite3.connect(database)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
            return 0
        return conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]


def test_caller_commit_publishes_exact_row_all_originals_and_one_retry_receipt(corpus, monkeypatch):
    job, staged = prepared(corpus, monkeypatch)
    expected = json.loads(job._state.candidate.record["row_json"])
    first = work(publish, corpus[0], staged)
    assert first["state"] == "published"
    assert work(publish, corpus[0], staged) == first
    assert count(corpus[0], "paper_lineage_sets") == 1
    assert count(corpus[0], local_source_owners.TABLE) == 3
    assert count(corpus[0], publication.TABLE) == 1
    with closing(sqlite3.connect(corpus[0])) as conn:
        assert tuple(conn.execute("SELECT * FROM paper_lineage_sets").fetchone()) == tuple(
            expected[k] for k in lineage_sets.COLUMNS.split()
        )
        original_formats = [
            json.loads(r[0])["format"]
            for r in conn.execute("SELECT owner_json FROM " + local_source_owners.TABLE)
        ]
    assert set(original_formats) == {"paperfact.lineage-source-observation.v1"}
    assert len(work(lineage_candidates.saved, corpus[0], "focal")) == 1


def test_caller_rollback_removes_all_compound_writes_and_retry_can_commit(corpus, monkeypatch):
    _job, staged = prepared(corpus, monkeypatch)
    work(publish, corpus[0], staged, rollback=True)
    assert count(corpus[0], "paper_lineage_sets") == 0
    assert count(corpus[0], local_source_owners.TABLE) == 0
    assert count(corpus[0], publication.TABLE) == 0
    work(publish, corpus[0], staged)
    assert count(corpus[0], local_source_owners.TABLE) == 3


def test_mid_original_failure_rolls_back_earlier_row_and_preserves_caller_work(corpus, monkeypatch):
    _job, staged = prepared(corpus, monkeypatch)

    def fail_in_transaction():
        with closing(generation._connect(corpus[0])) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(local_source_owners.SCHEMA)
            conn.execute("UPDATE papers SET venue='caller change' WHERE id='missing'")
            conn.execute(
                "CREATE TRIGGER fail_second BEFORE INSERT ON research_local_source_owners "
                "WHEN (SELECT count(*) FROM research_local_source_owners)>=1 "
                "BEGIN SELECT RAISE(ABORT, 'fixture association failure'); END"
            )
            with pytest.raises(sqlite3.IntegrityError, match="fixture association failure"):
                publication.publish_in(conn, staged)
            conn.commit()

    work(fail_in_transaction)
    assert count(corpus[0], "paper_lineage_sets") == 0
    assert count(corpus[0], local_source_owners.TABLE) == 0
    assert count(corpus[0], publication.TABLE) == 0
    with closing(sqlite3.connect(corpus[0])) as conn:
        assert (
            conn.execute("SELECT venue FROM papers WHERE id='missing'").fetchone()[0]
            == "caller change"
        )


@pytest.mark.parametrize("changed", ["target", "original", "receipt"])
def test_changes_after_staging_refuse_without_installation(corpus, monkeypatch, changed):
    job, staged = prepared(corpus, monkeypatch)
    if changed == "target":
        write_target(corpus, job._target._observation)
    else:
        path = staged._files[1 if changed == "original" else 0][0]
        path.write_bytes(b"changed staged data")
    with pytest.raises(research_lineage.LineageError):
        work(publish, corpus[0], staged)
    assert count(corpus[0], "paper_lineage_sets") == (1 if changed == "target" else 0)
    assert count(corpus[0], local_source_owners.TABLE) == 0
    assert count(corpus[0], publication.TABLE) == 0


def test_retry_refuses_missing_original_association(corpus, monkeypatch):
    _job, staged = prepared(corpus, monkeypatch)
    work(publish, corpus[0], staged)
    with closing(sqlite3.connect(corpus[0])) as conn, conn:
        conn.execute(
            "DELETE FROM research_local_source_owners WHERE rowid=("
            "SELECT min(rowid) FROM research_local_source_owners)"
        )
    with pytest.raises(research_lineage.LineageError, match="lineage_original_association_changed"):
        work(publish, corpus[0], staged)
    assert count(corpus[0], local_source_owners.TABLE) == 2


def test_unobserved_or_forged_candidate_cannot_publish(corpus, monkeypatch):
    _job, staged = prepared(corpus, monkeypatch)
    with pytest.raises(research_lineage.LineageError, match="invalid_lineage_publication"):
        work(publish, corpus[0], replace(staged, _files=()))
    job = work(LineageJob.prepare, corpus[2], connections=routes())
    work(job.run)
    with pytest.raises(
        research_lineage.LineageError, match="lineage_observed_publication_required"
    ):
        work(publication.prepare, job._state.candidate)


def test_worker_and_caller_transaction_are_required(corpus, monkeypatch):
    _job, staged = prepared(corpus, monkeypatch)
    with pytest.raises(research_lineage.LineageError, match="worker_required"):
        publication.prepare(staged._candidate)

    def missing_transaction():
        with closing(generation._connect(corpus[0])) as conn:
            return publication.publish_in(conn, staged)

    with pytest.raises(research_lineage.LineageError, match="lineage_transaction_required"):
        work(missing_transaction)
    assert count(corpus[0], publication.TABLE) == 0


def test_publish_never_hashes_or_parses_originals_under_the_sql_lock(corpus, monkeypatch):
    _job, staged = prepared(corpus, monkeypatch)

    def forbidden(*_a, **_k):
        pytest.fail("Publication must use off-lock verified bytes and metadata guards")

    monkeypatch.setattr(publication.atomic_sources, "verify", forbidden)
    monkeypatch.setattr(research_lineage, "current", forbidden)
    work(publish, corpus[0], staged)
    work(publish, corpus[0], staged)
    assert count(corpus[0], local_source_owners.TABLE) == 3


def test_concurrent_publication_retries_install_one_row_and_receipt(corpus, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    _job, staged = prepared(corpus, monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(publish, corpus[0], staged) for _ in range(2)]
        results = [f.result(timeout=15) for f in futures]
    assert results[0] == results[1]
    assert count(corpus[0], publication.TABLE) == 1
    assert count(corpus[0], local_source_owners.TABLE) == 3


def test_unavailable_peer_has_no_invented_original_association(corpus, monkeypatch):
    expanded = research_lineage.capture(
        corpus[0],
        "focal",
        ["prior", "later", "missing"],
        legacy_root=corpus[1],
    )
    chosen = (corpus[0], corpus[1], expanded)
    observation = observed(chosen)
    response = json.dumps(
        dict(format=research_lineage.PROPOSALS, focal=expanded.focal, statements=[])
    )
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: Completion(response))
    job = job_for(chosen, observation)
    work(job.run)
    staged = work(publication.prepare, job._state.candidate)
    work(publish, corpus[0], staged)
    assert count(corpus[0], local_source_owners.TABLE) == 3
    with closing(sqlite3.connect(corpus[0])) as conn:
        row = conn.execute("SELECT body_json FROM paper_lineage_sets").fetchone()[0]
    assert len(json.loads(row)["bindings"]) == 4


def test_prepare_cancellation_never_grants_local_associations(corpus, monkeypatch):
    job, _staged = prepared(corpus, monkeypatch)
    with pytest.raises(research_lineage.LineageError, match="cancelled"):
        work(publication.prepare, job._state.candidate, cancelled=lambda: True)
    assert count(corpus[0], publication.TABLE) == 0
    assert count(corpus[0], local_source_owners.TABLE) == 0
