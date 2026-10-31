"""Only explicit comparable proposals get deterministic value comparisons."""

import copy
import json
import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest
from test_audit_facts import atom, batch
from test_audit_facts import captured as captured_fixture
from test_audit_facts import source as source_fixture

from paper_daily import audit_inputs

source = source_fixture
captured = captured_fixture


def test_numeric_disagreement_preserves_both_source_and_output_locations(captured):
    from paper_daily import audit_consistency, audit_facts

    one, two = atom("one"), atom("two", value="60")
    # Source-only facts can disagree without any automatic semantic adjudication.
    report = audit_consistency.compare(audit_facts.prepare(captured, batch(captured, [one, two])))
    check = report["comparisons"][0]
    assert check["state"] == "numeric_disagreement" and check["review_required"]
    assert check["left"] == dict(fact_id="one", location=one["location"])
    assert check["right"] == dict(fact_id="two", location=two["location"])
    assert report["semantic_validation"] == "not_performed"
    assert "score" not in report and "contradiction" not in check




def bound(capture, hashes=None):
    with closing(sqlite3.connect(capture.database)) as conn, conn:
        for index, digest in enumerate(hashes or [capture.snapshot.source["document_hash"]] * 2, 1):
            anchor = dict(p0=1, o0=0, p1=1, o1=8, document_hash=digest)
            conn.execute(
                "UPDATE notes SET anchor=?, page=2 WHERE id=?", (json.dumps(anchor), index)
            )
    return audit_inputs.AuditCapture.capture(
        capture.database, capture.paper_id, document=capture.snapshot._origin
    )


def pair(capture, left=None, right=None, study_type=None):
    from paper_daily import audit_consistency, audit_facts

    proposal = batch(capture, [left or atom("one"), right or atom("two")])
    if study_type is not None:
        proposal["study_type"] = study_type
    return audit_consistency.compare(audit_facts.prepare(capture, proposal))


def test_actual_saved_outputs_report_both_exact_offsets_and_preserve_rows(captured):
    captured = bound(captured)
    first = atom("one", location=dict(kind="output", item_id="notes:1", start=0, end=15))
    second = atom(
        "two", value="60", location=dict(kind="output", item_id="notes:2", start=0, end=15)
    )
    before = captured.database.read_bytes()
    result = pair(captured, first, second)
    check = result["comparisons"][0]
    assert check["state"] == "numeric_disagreement"
    assert check["left"]["location"] == first["location"]
    assert check["right"]["location"] == second["location"]
    assert captured.database.read_bytes() == before
    assert len(result["facts"]) == 2 and result["persistence"] == "none"


@pytest.mark.parametrize(
    "field",
    [
        "construct",
        "outcome",
        "comparator",
        "population",
        "time",
        "unit",
        "statistic",
        "conditions",
    ],
)
def test_explicit_scope_differences_never_become_false_contradictions(captured, field):
    right = atom("two", value="60")
    right["scope"][field] = "A different declared condition"
    check = pair(captured, right=right)["comparisons"][0]
    assert check["state"] == "not_comparable" and check["reason"] == "different_scope"


def test_two_unknown_scope_fields_are_not_treated_as_equal_scope(captured):
    first, second = atom("one"), atom("two", value="60")
    first["scope"]["population"] = second["scope"]["population"] = None
    assert pair(captured, first, second)["comparisons"][0]["reason"] == "scope_unknown"


@pytest.mark.parametrize(
    "origin", ["reviewer_inferred", "not_reported", "not_applicable", "unknown"]
)
def test_absence_inference_and_applicability_are_not_zero_or_numeric_error(captured, origin):
    right = atom("two", value="0")
    right["origin"] = origin
    if origin != "reviewer_inferred":
        right["value"] = None
        right["passages"] = []
    check = pair(captured, right=right)["comparisons"][0]
    assert check["state"] == "not_comparable" and check["reason"] == origin


@pytest.mark.parametrize(
    "value,places,state",
    [
        ("50.004", None, "rounding_compatible"),
        ("50.006", None, "rounding_disagreement"),
        ("50", 2, "rounding_compatible"),
    ],
)
def test_rounding_has_a_distinct_explicit_interval_not_a_contradiction(
    captured, value, places, state
):
    first, second = atom("one"), atom("two", value=value)
    first["value"]["rounded_places"] = 2
    second["value"]["rounded_places"] = places
    assert pair(captured, first, second)["comparisons"][0]["state"] == state


def test_derived_numbers_stay_separate_without_recomputing_or_certifying_them(captured):
    second = atom("two", value="60")
    second["value"]["derived"] = True
    assert pair(captured, right=second)["comparisons"][0]["state"] == "derived_value"


@pytest.mark.parametrize("study", ["theoretical", "qualitative", "review", "mixed"])
def test_nonexperimental_materials_and_proofs_do_not_require_samples_or_experiments(
    captured, study
):
    first, second = atom("one"), atom("two")
    for fact in (first, second):
        fact["category"] = "method"
        fact["value"] = dict(kind="text", text="Proof under the stated assumptions")
    assert pair(captured, first, second, study)["comparisons"][0]["state"] == "same_text"


def test_text_difference_is_lexical_only_and_unknown_study_prevents_comparison(captured):
    first, second = atom("one"), atom("two")
    first["value"] = dict(kind="text", text="Interpretive analysis")
    second["value"] = dict(kind="text", text="Thematic analysis")
    assert pair(captured, first, second)["comparisons"][0]["state"] == "text_difference"
    assert (
        pair(captured, first, second, "unknown")["comparisons"][0]["reason"] == "study_type_unknown"
    )


@pytest.mark.parametrize(
    "digest,reason", [(None, "source_unknown"), ("b" * 64, "source_different_original")]
)
def test_versionless_and_old_a_output_is_not_compared_as_current_b(captured, digest, reason):
    if digest:
        captured = bound(captured, [digest, digest])
    right = atom("two", location=dict(kind="output", item_id="notes:1", start=0, end=15))
    check = pair(captured, right=right)["comparisons"][0]
    assert check["state"] == "not_comparable" and check["reason"] == reason


@pytest.mark.parametrize(
    "quote",
    [
        "No such original passage exists",
        "The intervention improved accuracy by 10% under the matched budget.",
    ],
)
def test_missing_or_ambiguous_evidence_excludes_numeric_disagreement(captured, quote):
    second = atom("two", value="60", quote=quote)
    check = pair(captured, right=second)["comparisons"][0]
    assert check["state"] == "not_comparable" and check["reason"] == "evidence_unverified"


def test_zero_is_a_reported_number_not_missing(captured):
    first, second = atom("one", value="0"), atom("two", value="-0.0")
    check = pair(captured, first, second)["comparisons"][0]
    assert check["state"] == "same_value"


def test_decimal_interval_uses_full_bounded_precision(captured):
    first = atom("one", value="999999999999999999.123456789012")
    second = atom("two", value="999999999999999999.123456789013")
    first["value"]["rounded_places"] = second["value"]["rounded_places"] = 12
    # Closed interval boundaries touch: preserve possible rounding compatibility.
    assert pair(captured, first, second)["comparisons"][0]["state"] == "rounding_compatible"


def test_full_32_fact_batch_returns_all_496_pairs_and_never_changes_caller_data(captured):
    from paper_daily import audit_consistency, audit_facts

    request = batch(captured, [atom(str(n)) for n in range(32)])
    original = copy.deepcopy(request)
    result = audit_consistency.compare(audit_facts.prepare(captured, request))
    assert len(result["comparisons"]) == 496 and result["covered_facts"] == 32
    assert request == original


@pytest.mark.parametrize("mode", ["cancelled", "stale"])
def test_cancelled_or_stale_comparison_discards_whole_batch(captured, mode):
    from paper_daily import audit_consistency, audit_facts, research_audit

    sheet = audit_facts.prepare(captured, batch(captured, [atom(str(n)) for n in range(4)]))
    calls = [0]

    def admitted():
        calls[0] += 1
        return calls[0] < 4

    with pytest.raises(research_audit.AuditError, match="cancelled|stale_context"):
        audit_consistency.compare(
            sheet,
            current=admitted if mode == "stale" else lambda: True,
            cancelled=lambda: not admitted() if mode == "cancelled" else False,
        )


def test_serialized_or_tampered_sheet_cannot_become_source_authority(captured):
    from paper_daily import audit_consistency, audit_facts, research_audit

    sheet = audit_facts.prepare(captured, batch(captured))
    changed = sheet.report
    changed["facts"][0]["value"]["decimal"] = "999"
    with pytest.raises(research_audit.AuditError):
        audit_consistency.compare(replace(sheet, _report_json=json.dumps(changed)))
    with pytest.raises(research_audit.AuditError):
        audit_consistency.compare(sheet.report)
