"""Explicit bounded lineage over real synthetic originals, with fake completions."""

import copy
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from test_research_lineage import corpus as _corpus
from test_research_lineage import proposals

from paper_daily import lineage_sets, llm, research_lineage
from paper_daily.ai_job_intent import FrozenRoutes
from paper_daily.ai_types import Completion, Settings

corpus = _corpus


def work(call, *args, **kwargs):
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(call, *args, **kwargs).result(timeout=10)


def routes():
    return FrozenRoutes(Settings("none"), {
        "lineage": Settings("openai", model="lineage-selected", profile="selected",
                            account_id="a" * 32, api_key="fixture-key", max_tokens=6000),
        "ask": Settings("openai", model="unrelated-ask", profile="other"),
    })


def test_explicit_real_corpus_produces_closed_quote_report_once_on_captured_route(
    corpus, monkeypatch
):
    from paper_daily.lineage_jobs import LineageJob

    _database, _root, captured = corpus
    calls = []

    def complete(prompt, **kwargs):
        calls.append((json.loads(prompt), kwargs))
        assert llm.settings("lineage").model == "lineage-selected"
        return Completion(json.dumps(proposals(captured)), model="actually-reported")

    monkeypatch.setattr(llm, "complete_result", complete)
    job = work(LineageJob.prepare, captured, connections=routes(), max_tokens=4000)
    monkeypatch.setattr(llm, "capture_configured_connections", lambda: pytest.fail(
        "An admitted Lineage route must not reread live configuration"))
    result = work(job.run)
    assert work(job.run) is result and len(calls) == 1
    assert calls[0][1]["task"] == "lineage"
    assert calls[0][1]["cfg"].account_id == "a" * 32
    assert calls[0][1]["max_tokens"] == 4000
    assert len(calls[0][0]["sources"]) == 3
    assert all(source["pages"] for source in calls[0][0]["sources"])
    assert result.report["verification_scope"] == "original_snapshots"
    assert all(p["location"]["state"] == "located"
               for item in result.report["statements"] for p in item["passages"])
    assert all(item["requirements"]["semantic_validation"] == "not_performed"
               for item in result.report["statements"])
    assert result.report["statements"][0]["requirements"]["citation_identity"] == "unresolved"
    assert result.execution["requested_model"] == "lineage-selected"
    assert result.execution["returned_model"] == "actually-reported"
    assert result.retention_reason is None and work(result.current)


@pytest.mark.parametrize("options,code", [
    ({"max_calls": True}, "invalid_call_budget"),
    ({"max_calls": 2}, "invalid_call_budget"),
    ({"max_tokens": True}, "invalid_token_budget"),
    ({"max_tokens": 0}, "invalid_token_budget"),
    ({"max_tokens": 8001}, "invalid_token_budget"),
    ({"max_tokens": 6001}, "invalid_token_budget"),
    ({"max_prompt_bytes": 0}, "invalid_prompt_budget"),
    ({"max_prompt_bytes": 1}, "prompt_budget_exceeded"),
])
def test_invalid_or_insufficient_budget_refuses_without_truncation_or_call(corpus, monkeypatch,
                                                                        options, code):
    from paper_daily.lineage_jobs import LineageJob

    monkeypatch.setattr(llm, "complete_result", lambda *_, **__: pytest.fail("No model call"))
    with pytest.raises(research_lineage.LineageError, match=code):
        work(LineageJob.prepare, corpus[2], connections=routes(), **options)


@pytest.mark.parametrize("connections", [None, ({}, {}, None),
    FrozenRoutes(Settings("openai"), {"ask": Settings("openai")}),
    FrozenRoutes(Settings("openai"), {"lineage": Settings("none")}),
])
def test_explicit_lineage_route_is_required_without_ask_or_default_fallback(corpus, connections):
    from paper_daily.lineage_jobs import LineageJob

    code = "unsupported_lineage_route" if isinstance(connections, FrozenRoutes) and (
        "lineage" in connections.task_names) else "lineage_route_required"
    with pytest.raises(research_lineage.LineageError, match=code):
        work(LineageJob.prepare, corpus[2], connections=connections)


def test_prepare_and_run_refuse_gui_thread_and_saved_read_never_calls_model(corpus, monkeypatch):
    from paper_daily.lineage_jobs import LineageJob

    database, _root, captured = corpus
    monkeypatch.setattr(llm, "complete_result", lambda *_, **__: pytest.fail("Saved-only read"))
    assert lineage_sets.saved(database, "focal") == []
    with pytest.raises(research_lineage.LineageError, match="worker_required"):
        LineageJob.prepare(captured, connections=routes())
    job = work(LineageJob.prepare, captured, connections=routes())
    with pytest.raises(research_lineage.LineageError, match="worker_required"):
        job.run()


def test_missing_selected_original_is_included_and_evidence_stays_missing(corpus, monkeypatch):
    from paper_daily.lineage_jobs import LineageJob

    database, root, _captured = corpus
    captured = research_lineage.capture(database, "focal", ["missing"], legacy_root=root)
    missing = captured.sources[1]["id"]
    proposal = dict(format=research_lineage.PROPOSALS, focal=captured.focal, statements=[dict(
        stage="prior_gap", subject=missing, text="Unresolved prior gap", function="unresolved",
        judgment=dict(status="unresolved", reason="The selected prior original is unavailable."),
        passages=[dict(source_id=missing, role="own_characterization", cites=None,
                       quote="Unavailable words remain unverified.", page=None, anchor=None)],
    )])
    prompts = []

    def complete(prompt, **_kwargs):
        prompts.append(json.loads(prompt))
        return Completion(json.dumps(proposal), model=None)

    monkeypatch.setattr(llm, "complete_result", complete)
    result = work(work(LineageJob.prepare, captured, connections=routes()).run)
    assert len(prompts[0]["sources"]) == 2
    assert prompts[0]["sources"][1]["availability"] == "unavailable"
    assert prompts[0]["sources"][1]["pages"] == []
    item = result.report["statements"][0]
    assert item["passages"][0]["location"]["state"] == "source_unavailable"
    assert item["requirements"] == dict(own_source_passage="missing", citing_passage="missing",
                                        citation_identity="unresolved",
                                        semantic_validation="not_performed")
    assert result.execution["returned_model"] is None
    assert result.report["coverage"]["later_development"] == "no_statement"


@pytest.mark.parametrize("change", ["unknown_source", "bad_quote", "extra_quote_field",
                                    "wrong_focal", "duplicate_key", "nan"])
def test_closed_malformed_model_proposal_never_produces_partial_result(corpus, monkeypatch, change):
    from paper_daily.lineage_jobs import LineageJob

    captured = corpus[2]
    value = proposals(captured)
    if change == "unknown_source":
        value["statements"][0]["passages"][0]["source_id"] = "unknown-source"
    elif change == "bad_quote":
        value["statements"][0]["passages"][0]["quote"] = 123
    elif change == "extra_quote_field":
        value["statements"][0]["passages"][0]["certified"] = True
    elif change == "wrong_focal":
        value["focal"] = captured.sources[1]["id"]
    encoded = json.dumps(value)
    if change == "duplicate_key":
        encoded = encoded.replace('"format":', '"format":"duplicate","format":', 1)
    elif change == "nan":
        encoded = encoded.replace('"page": 1', '"page": NaN', 1)
    calls = []
    monkeypatch.setattr(llm, "complete_result", lambda *_, **__: (
        calls.append(True) or Completion(encoded)))
    job = work(LineageJob.prepare, captured, connections=routes())
    with pytest.raises(ValueError):
        work(job.run)
    with pytest.raises(research_lineage.LineageError, match="explicit_new_job_required"):
        work(job.run)
    assert calls == [True] and job.result is None


def test_unlocated_quote_is_honest_not_a_verified_support_claim(corpus, monkeypatch):
    from paper_daily.lineage_jobs import LineageJob

    value = proposals(corpus[2])
    value["statements"][0]["passages"][0]["quote"] = "Words not present in this original."
    monkeypatch.setattr(llm, "complete_result", lambda *_, **__: Completion(json.dumps(value)))
    result = work(work(LineageJob.prepare, corpus[2], connections=routes()).run)
    item = result.report["statements"][0]
    assert item["passages"][0]["location"]["state"] == "missing"
    assert item["requirements"]["own_source_passage"] == "missing"
    assert item["requirements"]["citation_identity"] == "unresolved"
    assert item["requirements"]["semantic_validation"] == "not_performed"


def test_concurrent_same_and_separate_jobs_make_one_call_and_reuse_actual_result(
    corpus, monkeypatch
):
    from paper_daily.lineage_jobs import LineageJob

    captured = corpus[2]
    entered, release = threading.Event(), threading.Event()
    calls = []

    def complete(*_args, **_kwargs):
        calls.append(True)
        entered.set()
        assert release.wait(10)
        return Completion(json.dumps(proposals(captured)))

    monkeypatch.setattr(llm, "complete_result", complete)
    job = work(LineageJob.prepare, captured, connections=routes())
    other = work(LineageJob.prepare, captured, connections=routes())
    with ThreadPoolExecutor(max_workers=2) as pool:
        active = pool.submit(job.run)
        try:
            assert entered.wait(5)
            for duplicate in (job, other):
                with pytest.raises(research_lineage.LineageError, match="already_running"):
                    pool.submit(duplicate.run).result(timeout=5)
        finally:
            release.set()
        result = active.result(timeout=10)
    assert work(job.run) is result and calls == [True]


def test_cancel_before_call_and_after_completion_never_spends_an_extra_call(corpus, monkeypatch):
    from paper_daily.lineage_jobs import LineageJob

    captured = corpus[2]
    stop = threading.Event()
    calls = []

    def complete(*_args, **_kwargs):
        calls.append(True)
        stop.set()
        return Completion(json.dumps(proposals(captured)))

    monkeypatch.setattr(llm, "complete_result", complete)
    job = work(LineageJob.prepare, captured, connections=routes())
    stop.set()
    with pytest.raises(research_lineage.LineageError, match="cancelled"):
        work(job.run, cancelled=stop.is_set)
    assert calls == []
    stop.clear()
    with pytest.raises(research_lineage.LineageError, match="cancelled"):
        work(job.run, cancelled=stop.is_set)
    assert calls == [True] and job.result is None
    stop.clear()
    result = work(job.run, cancelled=stop.is_set)
    assert result.retention_reason == "cancelled_after_completion"
    assert result.report["verification_scope"] == "original_snapshots"
    assert work(job.run) is result and calls == [True]


@pytest.mark.parametrize("mutation", ["source", "parent", "owner", "native_lease", "route"])
def test_completed_snapshot_stays_retained_after_source_owner_or_scope_changes(
    corpus, monkeypatch, mutation
):
    from paper_daily.lineage_jobs import LineageJob

    database, root, captured = corpus
    scope, route = threading.Event(), threading.Event()
    calls = []

    def complete(*_args, **_kwargs):
        calls.append(True)
        if mutation == "source":
            import pymupdf

            with pymupdf.open(root / "prior.pdf") as document:
                assert len(document) == 1
                document[0].insert_text((40, 260), "Changed same-page-count original")
                document.saveIncr()
        elif mutation == "parent":
            with closing(sqlite3.connect(database)) as conn, conn:
                conn.execute("DELETE FROM papers WHERE id='prior'")
        elif mutation == "owner":
            captured._documents[1]._owner.close()
        elif mutation == "native_lease":
            scope.set()
        else:
            route.set()
        return Completion(json.dumps(proposals(captured)))

    monkeypatch.setattr(llm, "complete_result", complete)
    job = work(LineageJob.prepare, captured, connections=routes(),
               route_current=lambda: not route.is_set())
    result = work(job.run, current=lambda: not scope.is_set())
    reason = ("caller_context_changed" if mutation == "native_lease" else
              "route_changed" if mutation == "route" else "source_or_owner_changed")
    assert result.retention_reason == reason and calls == [True]
    assert all(p["location"]["state"] == "located"
               for item in result.report["statements"] for p in item["passages"])
    assert result.report["verification_scope"] == "original_snapshots"
    assert work(job.run, current=lambda: True).retention_reason == reason
    assert calls == [True]


def test_source_change_before_call_refuses_and_future_route_does_not_rewrite_report(corpus,
                                                                                 monkeypatch):
    from paper_daily.lineage_jobs import LineageJob

    captured = corpus[2]
    route = threading.Event()
    calls = []
    monkeypatch.setattr(llm, "complete_result", lambda *_, **__: (
        calls.append(True) or Completion(json.dumps(proposals(captured)), model=None)))
    job = work(LineageJob.prepare, captured, connections=routes(),
               route_current=lambda: not route.is_set())
    route.set()
    with pytest.raises(research_lineage.LineageError, match="route_changed"):
        work(job.run)
    assert calls == []
    route.clear()
    accepted = work(job.run)
    before = copy.deepcopy((accepted.report, accepted.execution))
    route.set()
    retained = work(job.run)
    assert retained.retention_reason == "route_changed"
    assert (accepted.report, accepted.execution) == before
    assert accepted.retention_reason is None and work(accepted.current)
    assert accepted.execution["returned_model"] is None and calls == [True]


@pytest.mark.parametrize("change", ["source", "parent", "native_lease"])
def test_changed_capture_or_view_before_spending_call_refuses(corpus, monkeypatch, change):
    from paper_daily.lineage_jobs import LineageJob

    database, _root, captured = corpus
    monkeypatch.setattr(llm, "complete_result", lambda *_, **__: pytest.fail("No stale call"))
    job = work(LineageJob.prepare, captured, connections=routes())
    if change == "source":
        captured._documents[1].path.write_bytes(b"changed original")
    elif change == "parent":
        with closing(sqlite3.connect(database)) as conn, conn:
            conn.execute("DELETE FROM papers WHERE id='prior'")
    code = "caller_context_changed" if change == "native_lease" else "source_or_owner_changed"
    with pytest.raises(research_lineage.LineageError, match=code):
        work(job.run, current=lambda: change != "native_lease")
    assert job.result is None


def test_failed_completion_needs_explicit_new_job_and_never_retries_automatically(
    corpus, monkeypatch
):
    from paper_daily.lineage_jobs import LineageJob

    calls = []
    monkeypatch.setattr(llm, "complete_result", lambda *_, **__: (
        calls.append(True) or Completion(None, "Synthetic failure")))
    job = work(LineageJob.prepare, corpus[2], connections=routes())
    with pytest.raises(research_lineage.LineageError, match="lineage_generation_failed"):
        work(job.run)
    with pytest.raises(research_lineage.LineageError, match="explicit_new_job_required"):
        work(job.run)
    assert calls == [True] and job.result is None
    monkeypatch.setattr(llm, "complete_result", lambda *_, **__: (
        calls.append(True) or Completion(json.dumps(proposals(corpus[2])))))
    retry = work(LineageJob.prepare, corpus[2], connections=routes())
    assert retry.request_id != job.request_id
    assert work(retry.run).retention_reason is None and calls == [True, True]


def test_cancel_during_quote_verification_reuses_bounded_response_without_another_call(
    corpus, monkeypatch
):
    from paper_daily.lineage_jobs import LineageJob

    calls = []
    stop = threading.Event()
    monkeypatch.setattr(llm, "complete_result", lambda *_, **__: (
        calls.append(True) or Completion(json.dumps(proposals(corpus[2])))))
    job = work(LineageJob.prepare, corpus[2], connections=routes())

    def progress(stage):
        if stage == "quote_verification":
            stop.set()

    with pytest.raises(ValueError, match="cancelled"):
        work(job.run, progress=progress, cancelled=stop.is_set)
    assert job.result is None and calls == [True]
    stop.clear()
    result = work(job.run, cancelled=stop.is_set)
    assert result.retention_reason == "cancelled_after_completion"
    assert result.report["statements"] and calls == [True]
