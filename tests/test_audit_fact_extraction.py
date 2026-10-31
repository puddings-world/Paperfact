"""Explicit extraction uses one captured Audit route and exact saved/PDF locations."""

import json

import pytest
from test_audit_facts import atom
from test_audit_facts import captured as captured_fixture
from test_audit_facts import source as source_fixture

from paper_daily.ai_types import Completion, Settings

source = source_fixture
captured = captured_fixture


def response(prompt):
    items = json.loads(prompt)["items"]
    target = next(item for item in items if item["id"] == "notes:1")
    span = next(span for span in target["spans"] if "50 participants" in span["text"])
    fact = atom()
    fact.pop("location")
    fact.pop("passages")
    fact["output"] = dict(item_id="notes:1", excerpt="50 participants")
    fact["evidence"] = [
        dict(
            item_id="notes:1",
            span_id=span["id"],
            quote="Replication used a held-out cohort of 50 participants.",
        )
    ]
    return dict(study_type="empirical", facts=[fact], empty_reason=None)


@pytest.fixture
def route(monkeypatch, captured):
    from paper_daily import llm

    cfg = Settings(backend="openai", model="chosen-alias", account_id="fake-account")
    connections = ({}, {}, captured.database.parent)
    calls = []
    monkeypatch.setattr(llm, "capture_connections", lambda: connections)
    monkeypatch.setattr(llm, "settings", lambda **kw: cfg)

    def complete(prompt, **kw):
        calls.append((prompt, kw))
        return Completion(json.dumps(response(prompt)), model="actually-reported")

    monkeypatch.setattr(llm, "complete_result", complete)
    return cfg, connections, calls


def test_success_is_one_captured_call_and_core_prepared_proposals_without_research_writes(
    captured, route, monkeypatch
):
    from paper_daily import audit_fact_extraction, llm

    cfg, connections, calls = route
    before = captured.database.read_bytes()
    job = audit_fact_extraction.ExtractionJob.prepare(captured, ["notes:1"])
    assert calls == []
    monkeypatch.setattr(llm, "settings", lambda **kw: pytest.fail("route was not captured"))
    result = job.run()
    assert job.run() is result and len(calls) == 1
    assert calls[0][1]["task"] == "audit" and calls[0][1]["cfg"] is cfg
    assert result.execution["requested_model"] == "chosen-alias"
    assert result.execution["reported_model"] == "actually-reported"
    assert result.sheet.report["semantic_validation"] == "researcher_review_proposal"
    fact = result.sheet.report["facts"][0]
    assert fact["location"] == dict(kind="output", item_id="notes:1", start=0, end=15)
    assert fact["evidence"][0]["location"]["state"] == "located"
    assert fact["source_binding"] == "unknown"
    assert result.consistency["covered_facts"] == 1
    assert captured.database.read_bytes() == before and result.current()


def complete_with(monkeypatch, route, transform):
    from paper_daily import llm

    calls = route[2]

    def complete(prompt, **kwargs):
        calls.append((prompt, kwargs))
        data = response(prompt)
        changed = transform(data)
        return Completion(json.dumps(data if changed is None else changed), model="returned")

    monkeypatch.setattr(llm, "complete_result", complete)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(source={"document_hash": "b" * 64}),
        lambda d: d.pop("facts"),
        lambda d: d.update(facts=None),
        lambda d: d.update(facts=0),
        lambda d: d.update(facts=[], empty_reason=None),
        lambda d: d.update(study_type="universal_ML_quality"),
        lambda d: d["facts"][0].update(start=0),
        lambda d: d["facts"][0]["output"].update(start=0),
        lambda d: d["facts"][0]["output"].update(item_id="notes:unselected"),
        lambda d: d["facts"][0]["output"].update(excerpt="invented output"),
        lambda d: d["facts"][0].update(statement="invented saved assertion"),
        lambda d: d["facts"][0]["evidence"][0].update(span_id="invented-span"),
        lambda d: d["facts"][0]["evidence"][0].update(item_id="notes:unselected"),
        lambda d: d["facts"][0]["evidence"][0].update(quote="Invented PDF text"),
        lambda d: d["facts"][0]["value"].update(decimal=0),
        lambda d: d["facts"][0].update(origin="unknown"),
        lambda d: d.update(facts=d["facts"] * 33),
    ],
)
def test_malformed_or_unmapped_batch_fails_whole_call_without_retry(
    captured, route, monkeypatch, change
):
    from paper_daily import audit_fact_extraction
    from paper_daily.research_audit import AuditError

    # Mutation return values (e.g. dict.pop) are not model responses.
    def transform(data):
        change(data)

    complete_with(monkeypatch, route, transform)
    job = audit_fact_extraction.ExtractionJob.prepare(captured, ["notes:1"])
    with pytest.raises(ValueError):
        job.run()
    assert job._result is None and len(route[2]) == 1
    with pytest.raises(AuditError, match="explicit_retry_required"):
        job.run()
    assert len(route[2]) == 1


@pytest.mark.parametrize(
    "text",
    [
        '{"study_type":"unknown","facts":[],"facts":[],"empty_reason":"none"}',
        '{"study_type":"unknown","facts":[],"empty_reason":NaN}',
        "not JSON",
        "x" * 128001,
    ],
    ids=["duplicate-keys", "nonfinite", "not-json", "oversize"],
)
def test_duplicate_keys_invalid_json_and_oversize_are_not_empty_success(
    captured, route, monkeypatch, text
):
    from paper_daily import audit_fact_extraction, llm

    calls = route[2]

    def complete(prompt, **kwargs):
        calls.append(prompt)
        return Completion(text)

    monkeypatch.setattr(llm, "complete_result", complete)
    job = audit_fact_extraction.ExtractionJob.prepare(captured, ["notes:1"])
    with pytest.raises(ValueError):
        job.run()
    assert len(calls) == 1 and job._result is None


def test_legitimate_empty_outcome_remains_empty_and_uses_one_call(captured, route, monkeypatch):
    from paper_daily import audit_fact_extraction

    complete_with(
        monkeypatch,
        route,
        lambda data: dict(
            study_type="unknown",
            facts=[],
            empty_reason="No supported facts in the bounded snippets.",
        ),
    )
    result = audit_fact_extraction.ExtractionJob.prepare(captured, ["notes:1"]).run()
    assert result.execution["outcome"] == "no_supported_facts"
    assert result.execution["empty_reason"]
    assert result.sheet.report["facts"] == [] and result.consistency["covered_facts"] == 0
    assert len(route[2]) == 1


@pytest.mark.parametrize(
    "origin,value",
    [
        ("not_reported", None),
        ("unknown", None),
        ("author_stated", dict(kind="number", decimal="0", rounded_places=None, derived=False)),
    ],
)
def test_null_unknown_and_reported_zero_remain_distinct(
    captured, route, monkeypatch, origin, value
):
    from paper_daily import audit_fact_extraction

    def transform(data):
        data["facts"][0].update(origin=origin, value=value)

    complete_with(monkeypatch, route, transform)
    result = audit_fact_extraction.ExtractionJob.prepare(captured, ["notes:1"]).run()
    fact = result.sheet.report["facts"][0]
    assert fact["origin"] == origin and fact["value"] == value
    assert result.sheet.report["semantic_validation"] == "researcher_review_proposal"


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(max_calls=0),
        dict(max_calls=2),
        dict(max_calls=True),
        dict(max_tokens=0),
        dict(max_tokens=True),
        dict(max_tokens=8001),
        dict(max_prompt_bytes=0),
        dict(max_prompt_bytes=96001),
    ],
)
def test_explicit_invalid_budgets_refuse_without_completion(captured, route, kwargs):
    from paper_daily import audit_fact_extraction

    with pytest.raises(ValueError):
        audit_fact_extraction.ExtractionJob.prepare(captured, ["notes:1"], **kwargs)
    assert route[2] == []


@pytest.mark.parametrize("backend", ["none", "unknown_vendor"])
def test_unsupported_route_has_no_global_fallback(captured, route, monkeypatch, backend):
    from paper_daily import audit_fact_extraction, llm

    monkeypatch.setattr(llm, "settings", lambda **kw: Settings(backend))
    with pytest.raises(ValueError, match="unsupported_audit_route"):
        audit_fact_extraction.ExtractionJob.prepare(captured, ["notes:1"])
    assert route[2] == []


def test_unavailable_selected_route_and_too_small_token_budget_do_not_fallback(
    captured, route, monkeypatch
):
    from paper_daily import audit_fact_extraction, llm

    def unavailable(**kwargs):
        raise ValueError("No such captured profile")

    monkeypatch.setattr(llm, "settings", unavailable)
    with pytest.raises(ValueError, match="audit_route_unavailable"):
        audit_fact_extraction.ExtractionJob.prepare(captured, ["notes:1"])
    monkeypatch.setattr(llm, "settings", lambda **kw: Settings("openai", max_tokens=10))
    with pytest.raises(ValueError, match="invalid_token_budget"):
        audit_fact_extraction.ExtractionJob.prepare(captured, ["notes:1"], max_tokens=11)
    assert route[2] == []


@pytest.mark.parametrize("selection", [[], ["missing"], ["notes:1", "notes:1"], ["notes:1"] * 9])
def test_invalid_selection_never_invokes_route_or_model(captured, route, monkeypatch, selection):
    from paper_daily import audit_fact_extraction, llm

    monkeypatch.setattr(llm, "settings", lambda **kw: pytest.fail("selection reached route"))
    with pytest.raises(ValueError, match="invalid_selection"):
        audit_fact_extraction.ExtractionJob.prepare(captured, selection)
    assert route[2] == []


def fresh(capture, sql, args=()):
    import sqlite3
    from contextlib import closing

    from paper_daily import audit_inputs

    with closing(sqlite3.connect(capture.database)) as conn, conn:
        conn.execute(sql, args)
    return audit_inputs.AuditCapture.capture(
        capture.database, capture.paper_id, document=capture.snapshot._origin
    )


def test_selected_output_and_prompt_bounds_do_not_truncate_or_call_model(captured, route):
    from paper_daily import audit_fact_extraction

    too_long = fresh(captured, "UPDATE notes SET body=? WHERE id=1", ("x" * 8001,))
    with pytest.raises(ValueError, match="selected_output_limit"):
        audit_fact_extraction.ExtractionJob.prepare(too_long, ["notes:1"])
    fresh_capture = fresh(too_long, "UPDATE notes SET body='50 participants' WHERE id=1")
    task = audit_fact_extraction.ExtractionJob.prepare(
        fresh_capture, ["notes:1"], max_prompt_bytes=1
    )
    with pytest.raises(ValueError, match="extraction_prompt_limit"):
        task.run()
    assert route[2] == []


def test_repeated_output_excerpt_is_explicit_failure_not_first_match(captured, route):
    from paper_daily import audit_fact_extraction

    captured = fresh(
        captured, "UPDATE notes SET body=? WHERE id=1", ("50 participants, then 50 participants",)
    )
    task = audit_fact_extraction.ExtractionJob.prepare(captured, ["notes:1"])
    with pytest.raises(ValueError, match="output_excerpt_ambiguous"):
        task.run()
    assert task._result is None and len(route[2]) == 1


def test_repeated_pdf_quote_inside_provided_span_is_not_assigned_an_invented_anchor(
    captured, route, monkeypatch
):
    from paper_daily import audit_fact_extraction, llm

    quote = "The intervention improved accuracy by 10% under the matched budget."
    captured = fresh(captured, "UPDATE notes SET body=? WHERE id=1", (quote,))

    def complete(prompt, **kwargs):
        route[2].append(prompt)
        item = json.loads(prompt)["items"][0]
        span = next(span for span in item["spans"] if span["text"].count(quote) == 2)
        fact = atom()
        fact.pop("location")
        fact.pop("passages")
        fact.update(
            output=None, evidence=[dict(item_id=item["id"], span_id=span["id"], quote=quote)]
        )
        return Completion(json.dumps(dict(study_type="empirical", facts=[fact], empty_reason=None)))

    monkeypatch.setattr(llm, "complete_result", complete)
    task = audit_fact_extraction.ExtractionJob.prepare(captured, ["notes:1"])
    with pytest.raises(ValueError, match="source_quote_ambiguous"):
        task.run()
    assert len(route[2]) == 1 and task._result is None


@pytest.mark.parametrize("kind", ["saved_row", "source", "workspace", "route", "cancel"])
def test_real_held_completion_discards_changed_source_saved_rows_route_or_cancel(
    captured, route, monkeypatch, kind
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from paper_daily import audit_fact_extraction, llm

    entered, release = threading.Event(), threading.Event()
    active, cancelled = [True], [False]

    def complete(prompt, **kwargs):
        route[2].append(prompt)
        entered.set()
        assert release.wait(10)
        return Completion(json.dumps(response(prompt)))

    monkeypatch.setattr(llm, "complete_result", complete)
    task = audit_fact_extraction.ExtractionJob.prepare(
        captured, ["notes:1"], route_current=lambda: active[0]
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(task.run, cancelled=lambda: cancelled[0])
        assert entered.wait(10)
        try:
            if kind == "saved_row":
                fresh(captured, "UPDATE notes SET body='Changed' WHERE id=1")
            elif kind in ("source", "workspace"):
                path = captured.database if kind == "workspace" else captured.snapshot._origin.path
                replacement = path.with_name("new-version")
                replacement.write_bytes(
                    path.read_bytes() + (b"\nnew version" if kind == "source" else b"")
                )
                replacement.replace(path)
            elif kind == "route":
                active[0] = False
            else:
                cancelled[0] = True
        finally:
            release.set()
        with pytest.raises(ValueError, match="saved_content_changed|stale_context|cancelled"):
            future.result(timeout=10)
    assert task._result is None and len(route[2]) == 1


def test_concurrent_repeated_run_owns_one_completion_until_drain(captured, route, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from paper_daily import audit_fact_extraction, llm

    entered, release = threading.Event(), threading.Event()

    def complete(prompt, **kwargs):
        route[2].append(prompt)
        entered.set()
        assert release.wait(10)
        return Completion(json.dumps(response(prompt)))

    monkeypatch.setattr(llm, "complete_result", complete)
    task = audit_fact_extraction.ExtractionJob.prepare(captured, ["notes:1"])
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(task.run)
        assert entered.wait(10)
        try:
            with pytest.raises(ValueError, match="already_running"):
                task.run()
        finally:
            release.set()
        result = future.result(timeout=10)
    assert task.run() is result and len(route[2]) == 1


def test_cancel_before_call_and_after_progress_never_spends_a_completion(captured, route):
    from paper_daily import audit_fact_extraction

    task = audit_fact_extraction.ExtractionJob.prepare(captured, ["notes:1"])
    with pytest.raises(ValueError, match="cancelled"):
        task.run(cancelled=lambda: True)
    active = [True]

    def progress(message):
        if message == "model":
            active[0] = False

    with pytest.raises(ValueError, match="stale_context"):
        task.run(current=lambda: active[0], progress=progress)
    assert route[2] == []


def test_actual_reported_model_is_never_requested_alias_fallback(captured, route, monkeypatch):
    from paper_daily import audit_fact_extraction, llm

    monkeypatch.setattr(
        llm,
        "complete_result",
        lambda prompt, **kw: Completion(
            json.dumps(response(prompt)), model="requested-compat-alias", model_reported=False
        ),
    )
    result = audit_fact_extraction.ExtractionJob.prepare(captured, ["notes:1"]).run()
    assert result.execution["reported_model"] is None
    assert result.execution["requested_model"] == "chosen-alias"
    text = json.dumps(result.execution)
    assert "fake-account" not in text and str(captured.database) not in text


def test_connection_snapshot_is_copied_and_cached_result_rejects_later_route_change(
    captured, route, monkeypatch
):
    from paper_daily import audit_fact_extraction, llm

    snapshot = (dict(marker="original"), {}, captured.database.parent)
    active = [True]
    task = audit_fact_extraction.ExtractionJob.prepare(
        captured, ["notes:1"], connections=snapshot, route_current=lambda: active[0]
    )
    snapshot[0]["marker"] = "different account"

    def complete(prompt, **kwargs):
        route[2].append(prompt)
        assert llm._CONNECTIONS.get()[0]["marker"] == "original"
        return Completion(json.dumps(response(prompt)))

    monkeypatch.setattr(llm, "complete_result", complete)
    result = task.run()
    copy = result.execution
    copy["reported_model"] = "tampered"
    assert result.execution["reported_model"] is None
    active[0] = False
    assert not result.current()
    with pytest.raises(ValueError, match="stale_context"):
        task.run()
    assert len(route[2]) == 1


@pytest.mark.parametrize("failure", ["none", "exception"])
def test_failed_completion_never_retries_same_job(captured, route, monkeypatch, failure):
    from paper_daily import audit_fact_extraction, llm

    def complete(prompt, **kwargs):
        route[2].append(prompt)
        if failure == "exception":
            raise RuntimeError("simulated transport failure")
        return Completion(None, reason="simulated refusal")

    monkeypatch.setattr(llm, "complete_result", complete)
    task = audit_fact_extraction.ExtractionJob.prepare(captured, ["notes:1"])
    with pytest.raises((ValueError, RuntimeError)):
        task.run()
    with pytest.raises(ValueError, match="explicit_retry_required"):
        task.run()
    assert len(route[2]) == 1 and task._result is None


def test_prepared_budget_and_selection_are_immutable_through_actual_call(
    captured, route
):
    from contextlib import suppress
    from dataclasses import FrozenInstanceError

    from paper_daily import audit_fact_extraction

    selection = ["notes:1"]
    job = audit_fact_extraction.ExtractionJob.prepare(captured, selection, max_tokens=4000)
    selection.clear()
    with suppress(FrozenInstanceError):
        job.max_tokens = 8001
    job.run()
    # Observe the actual completion arguments, not just a prepared field.
    assert route[2][0][1]["max_tokens"] == 4000
    assert job.selected == ("notes:1",)
    with pytest.raises(FrozenInstanceError):
        job.selected = ("notes:2",)
    with pytest.raises(FrozenInstanceError):
        job.max_prompt_bytes = 200000
    with pytest.raises(TypeError):
        job.selected[0] = "notes:2"
    assert len(route[2]) == 1


def test_completed_result_does_not_retain_dropped_job_without_gc(captured, route):
    import weakref

    from paper_daily import audit_fact_extraction

    active = [True]
    job = audit_fact_extraction.ExtractionJob.prepare(
        captured, ["notes:1"], route_current=lambda: active[0]
    )
    result = job.run()
    assert job.run() is result and len(route[2]) == 1
    reference = weakref.ref(job)
    del job
    assert reference() is None
    assert result.current()
    assert result.sheet.report["facts"][0]["location"]["item_id"] == "notes:1"
    assert result.execution["requested_model"] == "chosen-alias"
    active[0] = False
    assert not result.current()
    assert len(route[2]) == 1
