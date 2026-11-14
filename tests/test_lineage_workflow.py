"""The application coordinator performs real local/native publication without hidden AI retries."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_lineage_jobs import routes, work
from test_research_lineage import corpus as corpus
from test_research_lineage import proposals

from paper_daily import lineage_sets, llm, research_lineage
from paper_daily import research_generation as generation
from paper_daily.lineage_workflow import LineageWorkflow
from paper_daily.manual_highlight_ops import observe_owner


def prepare(corpus, **options):
    owner = observe_owner(corpus[0], "focal", expected_native=generation._identity(corpus[0]))
    return work(
        LineageWorkflow.prepare,
        owner,
        ["prior", "later"],
        connections=routes(),
        legacy_root=corpus[1],
        **options,
    )


def completion(workflow, monkeypatch, effect=lambda: None):
    calls = []

    def complete(*_args, **_kwargs):
        calls.append(True)
        effect()
        return llm.Completion(json.dumps(proposals(workflow._job._corpus)))

    monkeypatch.setattr(llm, "complete_result", complete)
    return calls


def test_explicit_local_workflow_publishes_sources_once_and_rechecks_retry(corpus, monkeypatch):
    workflow = prepare(corpus)
    calls = completion(workflow, monkeypatch)
    outcome = work(workflow.run)
    assert outcome.state == "saved_local" and outcome.operation_id is None
    assert len(lineage_sets.saved(corpus[0], "focal")) == 1
    assert work(workflow.run) is outcome and len(calls) == 1
    with generation._connect(corpus[0]) as conn:
        conn.execute("UPDATE paper_lineage_sets SET written_at='2026-11-20T00:00:00+00:00'")
        conn.commit()
    with pytest.raises(research_lineage.LineageError, match="lineage_publication_changed"):
        work(workflow.run)
    assert len(calls) == 1


def test_changed_view_after_completion_retains_candidate_without_canonical_install(
    corpus, monkeypatch
):
    current = [True]
    workflow = prepare(corpus, current=lambda: current[0])
    calls = completion(workflow, monkeypatch, lambda: current.__setitem__(0, False))
    outcome = work(workflow.run, current=lambda: current[0])
    assert outcome.state == "retained" and outcome.result.retention_reason is not None
    assert lineage_sets.saved(corpus[0], "focal") == [] and len(calls) == 1
    assert workflow._job._state.candidate is not None


def test_cancel_before_preparation_or_run_spends_no_model_and_saves_no_report(corpus, monkeypatch):
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No model call"))
    with pytest.raises(research_lineage.LineageError, match="cancelled"):
        prepare(corpus, cancelled=lambda: True)
    workflow = prepare(corpus)
    with pytest.raises(research_lineage.LineageError, match="cancelled"):
        work(workflow.run, cancelled=lambda: True)
    assert lineage_sets.saved(corpus[0], "focal") == []


def test_concurrent_activation_uses_one_workflow_and_one_completion(corpus, monkeypatch):
    import threading

    workflow = prepare(corpus)
    entered, release = threading.Event(), threading.Event()

    def hold():
        entered.set()
        assert release.wait(10)

    calls = completion(workflow, monkeypatch, hold)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(workflow.run)
        assert entered.wait(10)
        try:
            with pytest.raises(research_lineage.LineageError, match="already_running"):
                work(workflow.run)
        finally:
            release.set()
        outcome = pending.result(timeout=10)
    assert outcome.state == "saved_local" and len(calls) == 1
    assert len(lineage_sets.saved(corpus[0], "focal")) == 1
