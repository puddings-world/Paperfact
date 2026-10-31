"""Source fact proposals are bounded, read-only and never semantic certification."""

import copy
import json
import sqlite3
from contextlib import closing

import pytest
from test_research_evidence import REPEATED, UNIQUE
from test_research_evidence import source as source_fixture

from paper_daily import audit_inputs

source = source_fixture


@pytest.fixture
def captured(source):
    database = source._owner.db_path
    with closing(sqlite3.connect(database)) as conn, conn:
        for value in ("50 participants", "60 participants"):
            conn.execute(
                "INSERT INTO notes(paper_id,body,kind,created_at) VALUES('paper',?,'note','now')",
                (value,),
            )
    return audit_inputs.AuditCapture.capture(database, "paper", document=source)


def atom(identity="sample", *, value="50", location=None, quote=UNIQUE):
    return dict(
        id=identity,
        category="sample",
        statement=value + " participants",
        origin="author_stated",
        scope=dict(
            construct="participants",
            outcome="sample size",
            comparator="none",
            population="held-out cohort",
            time="replication",
            unit="participants",
            statistic="count",
            conditions="held-out",
        ),
        value=dict(kind="number", decimal=value, rounded_places=None, derived=False),
        location=location or dict(kind="source"),
        passages=[dict(quote=quote, page=None, anchor=None)],
    )


def batch(capture, facts=None):
    from paper_daily import audit_facts

    return dict(
        format=audit_facts.FORMAT,
        source=capture.snapshot.source,
        study_type="empirical",
        facts=facts if facts is not None else [atom()],
    )


def test_source_and_actual_saved_output_preserve_exact_locations_without_calls_or_writes(
    captured, monkeypatch
):
    from paper_daily import audit_facts, llm

    monkeypatch.setattr(llm, "complete_result", lambda *a, **kw: pytest.fail("implicit model"))
    monkeypatch.setattr(llm, "settings", lambda *a, **kw: pytest.fail("implicit route"))
    output = atom("note", location=dict(kind="output", item_id="notes:1", start=0, end=15))
    request = batch(captured, [atom(), output])
    original = copy.deepcopy(request)
    database = captured.database
    before = database.read_bytes()
    sheet = audit_facts.prepare(captured, request)
    report = sheet.report
    assert request == original and database.read_bytes() == before
    assert report["source"] == captured.snapshot.source
    assert report["semantic_validation"] == "researcher_review_proposal"
    assert report["facts"][0]["evidence"][0]["location"]["state"] == "located"
    assert report["facts"][1]["location"] == output["location"]
    assert report["facts"][1]["source_binding"] == "unknown"
    assert report["facts"][0]["source_binding"] == "exact"
    assert report["owner_observation"] and report["input_hash"]
    assert str(database) not in json.dumps(report)
    report["facts"].clear()
    assert len(sheet.report["facts"]) == 2 and sheet.current()


@pytest.mark.parametrize(
    "change",
    [
        lambda b: b.update(extra=True),
        lambda b: b.update(study_type="machine_learning_only"),
        lambda b: b.update(facts=None),
        lambda b: b["facts"][0].update(extra="ignored?"),
        lambda b: b["facts"][0].update(value=0),
        lambda b: b["facts"][0]["value"].update(decimal="NaN"),
        lambda b: b["facts"][0]["value"].update(decimal="1e20"),
        lambda b: b["facts"][0]["value"].update(decimal=50),
        lambda b: b["facts"][0]["value"].update(derived=1),
        lambda b: b["facts"][0]["value"].update(rounded_places=True),
        lambda b: b["facts"][0]["value"].update(decimal="1.23", rounded_places=1),
        lambda b: b["facts"][0].update(origin="unknown"),
        lambda b: b["facts"][0].update(category="quality_score"),
        lambda b: b["facts"][0]["scope"].update(unit=[]),
        lambda b: b["facts"][0]["passages"][0].update(page=True),
        lambda b: b["facts"][0]["passages"][0].update(page=0),
        lambda b: b["facts"][0]["passages"][0].update(anchor=dict(p0=1, o0=5, p1=1, o1=1)),
        lambda b: b["facts"][0]["location"].update(kind="global_path", path="ignored"),
    ],
)
def test_closed_malformed_batches_fail_without_mutation_or_partial_results(captured, change):
    from paper_daily import audit_facts, research_audit

    proposal = batch(captured)
    change(proposal)
    before = copy.deepcopy(proposal)
    with pytest.raises(research_audit.AuditError):
        audit_facts.prepare(captured, proposal)
    assert proposal == before


@pytest.mark.parametrize("field", ["paper_id", "document_hash"])
def test_different_source_never_relabels_facts_with_the_loaded_original(captured, field):
    from paper_daily import audit_facts, research_audit

    request = batch(captured)
    request["source"][field] = "other" if field == "paper_id" else "b" * 64
    with pytest.raises(research_audit.AuditError, match="source_identity_mismatch"):
        audit_facts.prepare(captured, request)


@pytest.mark.parametrize(
    "quote,state", [(REPEATED, "ambiguous"), ("Unreported invented text", "missing")]
)
def test_nonunique_or_missing_quote_never_gets_an_active_anchor(captured, quote, state):
    from paper_daily import audit_facts

    sheet = audit_facts.prepare(captured, batch(captured, [atom(quote=quote)]))
    location = sheet.report["facts"][0]["evidence"][0]["location"]
    assert location["state"] == state and location["anchor"] is None
    assert sheet.report["semantic_validation"] == "researcher_review_proposal"


def test_quote_and_requested_locator_remain_exact_not_normalized_display_rewrites(captured):
    from paper_daily import audit_facts

    fact = atom()
    fact["passages"][0].update(page=2, anchor=dict(p0=1, o0=0, p1=1, o1=7))
    report = audit_facts.prepare(captured, batch(captured, [fact])).report
    result = report["facts"][0]["evidence"][0]
    assert result["quote"] == UNIQUE
    assert result["requested_locator"] == dict(page=2, anchor=fact["passages"][0]["anchor"])
    assert result["location"]["state"] == "located"


@pytest.mark.parametrize("kind", ["unknown_item", "wrong_offsets", "wrong_statement"])
def test_output_location_must_name_actual_exact_captured_text(captured, kind):
    from paper_daily import audit_facts, research_audit

    fact = atom(location=dict(kind="output", item_id="notes:1", start=0, end=15))
    if kind == "unknown_item":
        fact["location"]["item_id"] = "notes:999"
    elif kind == "wrong_offsets":
        fact["location"]["start"] = 1
    else:
        fact["statement"] = "Unseen output"
    with pytest.raises(research_audit.AuditError, match="output_location_mismatch"):
        audit_facts.prepare(captured, batch(captured, [fact]))


def test_empty_valid_batch_has_zero_coverage_not_filled_quotas(captured):
    from paper_daily import audit_consistency, audit_facts

    sheet = audit_facts.prepare(captured, batch(captured, []))
    assert sheet.report["facts"] == []
    assert audit_consistency.compare(sheet)["covered_facts"] == 0


def test_count_passage_byte_and_duplicate_bounds_fail_whole_batch(captured):
    from paper_daily import audit_facts, research_audit

    cases = []
    cases.append(batch(captured, [atom(str(n)) for n in range(33)]))
    cases.append(batch(captured, [atom("same"), atom("same")]))
    many = [atom(str(n)) for n in range(17)]
    for fact in many:
        fact["passages"] = [
            dict(quote="Some quote " + str(n), page=None, anchor=None) for n in range(4)
        ]
    cases.append(batch(captured, many))
    huge = batch(captured)
    huge["facts"][0]["statement"] = "x" * (audit_facts.MAX_BYTES + 1)
    cases.append(huge)
    for proposal in cases:
        with pytest.raises(research_audit.AuditError):
            audit_facts.prepare(captured, proposal)


@pytest.mark.parametrize("mode", ["saved_row", "source", "database_replaced"])
def test_changed_saved_or_source_native_identity_rejects_old_sheet(captured, mode):
    from paper_daily import audit_consistency, audit_facts, research_audit

    sheet = audit_facts.prepare(captured, batch(captured))
    if mode == "saved_row":
        with closing(sqlite3.connect(captured.database)) as conn, conn:
            conn.execute("UPDATE notes SET body='new content' WHERE id=1")
    else:
        path = captured.snapshot._origin.path if mode == "source" else captured.database
        replacement = path.with_name("replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
    assert not sheet.current()
    with pytest.raises(research_audit.AuditError):
        audit_consistency.compare(sheet)
    with pytest.raises(research_audit.AuditError, match="saved_content_changed"):
        audit_facts.prepare(captured, batch(captured))


def test_same_pdf_same_paper_in_two_workspace_owners_cannot_rebind_sealed_result(
    captured, tmp_path
):
    from dataclasses import replace

    from paper_daily import audit_consistency, audit_facts, research_audit
    from paper_daily.document_reader import DocumentReader

    other = tmp_path / "other.sqlite"
    other.write_bytes(captured.database.read_bytes())
    original = captured.snapshot._origin
    reader = DocumentReader(other, projection_root=None, legacy_root=original.path.parent)
    doc = reader.resolve("paper")
    second = audit_inputs.AuditCapture.capture(other, "paper", document=doc)
    first_sheet = audit_facts.prepare(captured, batch(captured))
    second_sheet = audit_facts.prepare(second, batch(second))
    assert first_sheet.report["source"] == second_sheet.report["source"]
    assert first_sheet.report["owner_observation"] != second_sheet.report["owner_observation"]
    forged = replace(first_sheet, _capture=second)
    assert not forged.current()
    with pytest.raises(research_audit.AuditError, match="invalid_or_stale_fact_sheet"):
        audit_consistency.compare(forged)


@pytest.mark.parametrize("stage", ["before", "during", "after"])
def test_cancel_or_stale_supplied_guard_discards_complete_preparation(captured, monkeypatch, stage):
    from paper_daily import audit_facts, research_audit, research_evidence

    active = [stage != "before"]
    original = research_evidence.verify_snapshot

    def verify(*args, **kwargs):
        result = original(*args, **kwargs)
        if stage != "before":
            active[0] = False
        return result

    monkeypatch.setattr(research_evidence, "verify_snapshot", verify)
    with pytest.raises(research_audit.AuditError, match="cancelled|stale_context"):
        audit_facts.prepare(
            captured,
            batch(captured),
            cancelled=lambda: stage == "during" and not active[0],
            current=lambda: active[0],
        )


def test_mutating_caller_batch_during_source_work_does_not_change_copied_inputs(
    captured, monkeypatch
):
    from paper_daily import audit_facts, research_evidence

    proposal = batch(captured)
    original = research_evidence.verify_snapshot

    def verify(*args, **kwargs):
        proposal["facts"][0]["statement"] = "Changed caller data"
        return original(*args, **kwargs)

    monkeypatch.setattr(research_evidence, "verify_snapshot", verify)
    assert (
        audit_facts.prepare(captured, proposal).report["facts"][0]["statement"] == "50 participants"
    )


def test_pdf_extraction_runs_on_explicit_worker_with_no_implicit_capture_or_global_lookup(
    captured, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from paper_daily import audit_facts, research_evidence, store

    gui_thread = threading.get_ident()
    seen = []
    actual = research_evidence._extract

    def extract(*args, **kwargs):
        seen.append(threading.get_ident())
        assert threading.get_ident() != gui_thread
        return actual(*args, **kwargs)

    monkeypatch.setattr(research_evidence, "_extract", extract)
    monkeypatch.setattr(
        audit_inputs.AuditCapture, "capture", lambda *a, **kw: pytest.fail("implicit capture")
    )
    unrelated = captured.database.with_name("not-opened.sqlite")
    monkeypatch.setattr(store, "DB_PATH", unrelated)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(audit_facts.prepare, captured, batch(captured)).result(timeout=10)
    assert seen and result.report["facts"] and not unrelated.exists()
