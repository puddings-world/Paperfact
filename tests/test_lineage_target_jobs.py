"""AI work is bound to the exact target observed before its single completion."""

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from uuid import uuid4

import pytest
from test_lineage_jobs import routes, work
from test_lineage_observation import initialized, make_row
from test_research_lineage import corpus as corpus
from test_research_lineage import proposals

from paper_daily import lineage_candidates, lineage_observation, llm, research_lineage
from paper_daily import research_generation as generation
from paper_daily.ai_types import Completion
from paper_daily.lineage_jobs import LineageJob


def observed(corpus):
    initialized(corpus)
    return work(lineage_observation.observe, corpus[2], str(uuid4()), str(uuid4()))


def write_target(corpus, observation):
    row = make_row(corpus[2], observation.data["corpus_id"])
    with closing(sqlite3.connect(corpus[0])) as conn, conn:
        conn.execute("INSERT INTO paper_lineage_sets VALUES(?,?,?,?,?,?)", tuple(row.values()))
    return row


def job_for(corpus, observation):
    return work(
        LineageJob.prepare, corpus[2], connections=routes(), publication_observation=observation
    )


def test_changed_target_before_completion_does_not_spend_or_overwrite(corpus, monkeypatch):
    observation = observed(corpus)
    job = job_for(corpus, observation)
    row = write_target(corpus, observation)
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No model call"))
    with pytest.raises(research_lineage.LineageError, match="lineage_target_changed"):
        work(job.run)
    with closing(sqlite3.connect(corpus[0])) as conn:
        assert (
            conn.execute("SELECT body_json FROM paper_lineage_sets").fetchone()[0]
            == row["body_json"]
        )
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_generation_requests'"
        ).fetchone()


def test_change_during_completion_retains_exact_original_base_and_cannot_retarget(
    corpus, monkeypatch
):
    observation = observed(corpus)
    job = job_for(corpus, observation)
    calls = []

    def complete(*_a, **_k):
        calls.append(True)
        write_target(corpus, observation)
        return Completion(json.dumps(proposals(corpus[2])))

    monkeypatch.setattr(llm, "complete_result", complete)
    result = work(job.run)
    assert result.retention_reason == "lineage_target_changed"
    assert work(job.run) is result and calls == [True]
    records = work(lineage_candidates.saved, corpus[0], "focal")
    base = json.loads(records[0]["context_json"])["publication_base"]
    assert base == dict(
        format="paperfact.lineage-target-base.v1",
        request_id=observation.data["request_id"],
        corpus_id=observation.data["corpus_id"],
        target_hash=None,
        observation_hash=generation._digest(observation.data),
    )
    assert records[0]["reason"] == "lineage_target_changed"
    assert len(work(lineage_candidates.saved, corpus[0], "focal")) == 1
    with pytest.raises(research_lineage.LineageError, match="lineage_observation_changed"):
        job_for(corpus, observation)


def test_existing_target_exact_bytes_are_recorded_and_never_replaced(corpus, monkeypatch):
    original = observed(corpus)
    row = write_target(corpus, original)
    observation = work(
        lineage_observation.observe, corpus[2], original.data["corpus_id"], str(uuid4())
    )
    monkeypatch.setattr(
        llm, "complete_result", lambda *_a, **_k: Completion(json.dumps(proposals(corpus[2])))
    )
    result = work(job_for(corpus, observation).run)
    assert result.retention_reason is None
    record = work(lineage_candidates.saved, corpus[0], "focal")[0]
    assert json.loads(record["context_json"])["publication_base"][
        "target_hash"
    ] == generation._digest(row)
    with closing(sqlite3.connect(corpus[0])) as conn:
        assert (
            conn.execute("SELECT body_json FROM paper_lineage_sets").fetchone()[0]
            == row["body_json"]
        )


def test_original_lease_remains_readable_after_source_changes_but_cannot_authorize(corpus):
    observation = observed(corpus)
    lease = work(lineage_observation.target_lease, observation)
    (corpus[1] / "prior.pdf").write_bytes(b"source replaced")
    assert lineage_observation.lease_data(lease) == observation.data
    with pytest.raises(research_lineage.LineageError):
        work(lineage_observation.check_target, lease)
    with pytest.raises(research_lineage.LineageError):
        work(lineage_observation.target_lease, observation)


def test_forged_lease_or_candidate_target_is_rejected(corpus, monkeypatch):
    observation = observed(corpus)
    lease = work(lineage_observation.target_lease, observation)
    other = work(lineage_observation.observe, corpus[2], str(uuid4()), str(uuid4()))
    with pytest.raises(research_lineage.LineageError, match="invalid_lineage_target_lease"):
        lineage_observation.lease_data(replace(lease, _observation=other))
    monkeypatch.setattr(
        llm, "complete_result", lambda *_a, **_k: Completion(json.dumps(proposals(corpus[2])))
    )
    job = job_for(corpus, observation)
    work(job.run)
    forged = replace(job._state.candidate, _target=work(lineage_observation.target_lease, other))
    with pytest.raises(ValueError, match="native prepared candidate"):
        work(lineage_candidates.persist, forged)


@pytest.mark.parametrize("kind", ["wrong-key", "invalid-observer"])
def test_prepare_rejects_mismatched_observation(corpus, kind):
    observation = observed(corpus)
    kwargs = dict(publication_observation=observation)
    if kind == "wrong-key":
        kwargs["corpus_id"] = str(uuid4())
    else:
        kwargs["publication_observation"] = object()
    with pytest.raises(research_lineage.LineageError, match="lineage_observation_corpus_mismatch"):
        work(LineageJob.prepare, corpus[2], connections=routes(), **kwargs)


def test_target_checks_require_worker_and_archive_metadata_is_defensive(corpus):
    observation = observed(corpus)
    with pytest.raises(research_lineage.LineageError, match="worker_required"):
        lineage_observation.target_lease(observation)
    lease = work(lineage_observation.target_lease, observation)
    with pytest.raises(research_lineage.LineageError, match="worker_required"):
        lineage_observation.check_target(lease)
    data = lineage_observation.lease_data(lease)
    data["corpus_id"] = str(uuid4())
    assert lineage_observation.lease_data(lease) == observation.data


def test_closed_reader_retains_original_base_and_result_without_new_authority(corpus, monkeypatch):
    observation = observed(corpus)
    job = job_for(corpus, observation)
    response = json.dumps(proposals(corpus[2]))

    def complete(*_a, **_k):
        corpus[2]._documents[0]._owner.close()
        return Completion(response)

    monkeypatch.setattr(llm, "complete_result", complete)
    result = work(job.run)
    assert result.retention_reason == "source_or_owner_changed"
    record = work(lineage_candidates.saved, corpus[0], "focal")[0]
    base = json.loads(record["context_json"])["publication_base"]
    assert base["observation_hash"] == generation._digest(observation.data)
    assert len(lineage_candidates.originals(record)) == 3
    assert lineage_observation.lease_data(job._target) == observation.data
    with pytest.raises(research_lineage.LineageError):
        work(lineage_observation.check_target, job._target)


@pytest.mark.parametrize(
    "field,value",
    [
        ("corpus_id", "not-original-key"),
        ("request_id", "not-original-request"),
        ("format", "wrong"),
        ("target_hash", "bad-digest"),
        ("observation_hash", None),
    ],
)
def test_archive_base_rejects_corruption_even_if_candidate_digest_is_recomputed(
    corpus, monkeypatch, field, value
):
    observation = observed(corpus)
    response = json.dumps(proposals(corpus[2]))
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: Completion(response))
    work(job_for(corpus, observation).run)
    record = work(lineage_candidates.saved, corpus[0], "focal")[0]
    context = json.loads(record["context_json"])
    context["publication_base"][field] = value
    record["context_json"] = generation._context_json(context)
    record["candidate_id"] = generation._digest(
        {
            "context": context,
            "row": json.loads(record["row_json"]),
        }
    )
    with pytest.raises(ValueError):
        lineage_candidates.validate(record)


@pytest.mark.parametrize("context", [None, [], "publication_base", 1])
def test_non_object_archive_context_fails_as_validation_error(context):
    record = dict(
        request_id=str(uuid4()),
        context_json=json.dumps(context),
        row_json="{}",
        status="candidate",
        candidate_id="0" * 64,
        reason="pending_lineage_publication",
    )
    with pytest.raises(ValueError):
        lineage_candidates.validate(record)
