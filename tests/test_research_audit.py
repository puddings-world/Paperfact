"""Fixture-PDF behavior checks for the advisory, read-only audit boundary."""

import copy
import json
from dataclasses import replace

import pytest
from test_research_evidence import source as source_fixture

from paper_daily import research_audit as audit
from paper_daily import research_evidence as evidence

source = source_fixture


def item(source, **changes):
    result = dict(
        id="claim:1",
        feature="claims",
        text="A cohort of 50 participants.",
        document_hash=source.sha256,
        passages=[],
        reference=None,
    )
    result.update(changes)
    return result


def passage(source, text, *, page=None, anchor=None):
    return dict(quote=text, page=page, anchor=anchor, document_hash=source.sha256)


def test_locates_exact_quotes_without_certifying_support_or_mutating_inputs(source):
    values = [
        item(source, passages=[passage(source, "Controls were assigned independently.", page=2)])
    ]
    before = copy.deepcopy(values)
    report = audit.run(evidence.capture(source), values)
    found = report["checks"][0]
    assert found["state"] == "located" and found["location"]["page"] == 2
    assert report["semantics"] == "not_checked"
    assert "semantic_support" in report["not_checked"]
    assert report["counts"] == {"located": 1, "observed": 1}
    assert values == before and audit.run(evidence.capture(source), values) == report
    assert str(source.path) not in json.dumps(report)


@pytest.mark.parametrize(
    "quote,page,anchor,state",
    [
        ("Not actually stated by the authors", None, None, "missing"),
        ("Controls were assigned independently.", None, None, "ambiguous"),
        ("Controls were assigned independently.", 90, None, "invalid_page"),
        (
            "Controls were assigned independently.",
            1,
            dict(p0=0, o0=999, p1=0, o1=999),
            "invalid_anchor",
        ),
    ],
)
def test_reports_missing_ambiguous_and_invalid_sources_honestly(source, quote, page, anchor, state):
    report = audit.run(
        evidence.capture(source),
        [item(source, text="", passages=[passage(source, quote, page=page, anchor=anchor)])],
    )
    assert report["checks"][0]["state"] == state
    assert report["checks"][0]["location"]["anchor"] is None


@pytest.mark.parametrize("digest,state", [(None, "source_unknown"), ("f" * 64, "source_mismatch")])
def test_unknown_or_other_version_never_receives_this_pdf_location(source, digest, state):
    quote = passage(source, "Controls were assigned independently.", page=2)
    quote["document_hash"] = digest
    report = audit.run(
        evidence.capture(source), [item(source, document_hash=digest, passages=[quote])]
    )
    assert {entry["state"] for entry in report["checks"]} == {state}
    assert report["checks"][0]["location"] is None


def test_quantities_match_whole_number_and_unit_occurrence_not_semantics(source):
    report = audit.run(
        evidence.capture(source), [item(source, text="50 participants; 10%; 10 mg; 5; 150.")]
    )
    results = {
        (entry["quantity"]["value"], entry["quantity"]["unit"]): entry["state"]
        for entry in report["checks"]
    }
    assert results == {
        ("50", ""): "observed",
        ("10", "%"): "observed",
        ("10", "mg"): "not_observed",
        ("5", ""): "not_observed",
        ("150", ""): "not_observed",
    }
    assert report["semantics"] == "not_checked"


def test_reference_disagreement_and_title_only_basis_do_not_invent_identity(source):
    reference = dict(
        basis="title",
        contexts=[],
        proposed_title="Study A",
        resolved_title="Study B",
        proposed_doi="https://doi.org/10.1234/a",
        resolved_doi="10.1234/b",
        relation="Used as a baseline",
    )
    report = audit.run(evidence.capture(source), [item(source, text="", reference=reference)])
    assert [c["state"] for c in report["checks"]] == ["doi_mismatch", "title_only"]
    reference.update(proposed_doi=None, resolved_doi=None, resolved_title="Study A")
    report = audit.run(evidence.capture(source), [item(source, text="", reference=reference)])
    assert [c["state"] for c in report["checks"]] == ["title_similar", "title_only"]
    assert report["semantics"] == "not_checked"


def test_later_relation_needs_its_own_citing_context(source):
    reference = dict(
        basis="unknown",
        contexts=[],
        proposed_title=None,
        resolved_title=None,
        proposed_doi=None,
        resolved_doi=None,
        relation="Extends this method",
    )
    report = audit.run(evidence.capture(source), [item(source, text="", reference=reference)])
    assert [c["state"] for c in report["checks"]] == [
        "identity_not_checked",
        "citing_context_missing",
    ]


def test_empty_corpus_is_empty_check_scope_not_all_pass(source):
    report = audit.run(evidence.capture(source), [])
    assert report["items"] == [] and report["checks"] == [] and report["counts"] == {}
    assert report["semantics"] == "not_checked"


@pytest.mark.parametrize(
    "change,code",
    [
        (lambda x: x.append(copy.deepcopy(x[0])), "duplicate_item"),
        (lambda x: x[0].update(extra=True), "invalid_input"),
        (lambda x: x[0].update(document_hash=True), "invalid_input"),
        (lambda x: x[0].update(text="x" * (audit.MAX_TEXT + 1)), "invalid_input"),
        (lambda x: x.extend([dict(x[0], id=str(i)) for i in range(audit.MAX_ITEMS)]), "item_limit"),
        (
            lambda x: x[0]["passages"].append(
                dict(quote="quote", page=True, anchor=None, document_hash=None)
            ),
            "invalid_input",
        ),
        (
            lambda x: x[0].update(text=" ".join(str(i) for i in range(audit.MAX_QUANTITIES + 1))),
            "quantity_limit",
        ),
    ],
)
def test_invalid_or_overbudget_input_returns_no_partial_report(source, change, code):
    values = [item(source)]
    change(values)
    with pytest.raises(audit.AuditError) as error:
        audit.run(evidence.capture(source), values)
    assert error.value.code == code


def test_cancellation_during_work_returns_no_partial_report(source):
    stopped = [False]
    progress = []

    def step(done, total):
        progress.append((done, total))
        stopped[0] = True

    with pytest.raises(audit.AuditError, match="cancelled"):
        audit.run(
            evidence.capture(source),
            [item(source), item(source, id="claim:2")],
            cancelled=lambda: stopped[0],
            progress=step,
        )
    assert progress == [(1, 2)]


def test_forged_snapshot_is_rejected(source):
    snapshot = replace(evidence.capture(source), _bytes=b"forged")
    with pytest.raises(evidence.EvidenceError, match="invalid_snapshot"):
        audit.run(snapshot, [item(source)])


def test_equal_bytes_with_an_explicit_other_paper_owner_cannot_locate_or_verify_quantities(source):
    snapshot = evidence.capture(source)
    foreign = item(
        source,
        source_paper_id="another-paper",
        passages=[passage(source, "Controls were assigned independently.", page=2)],
    )
    report = audit.run(snapshot, [foreign])
    assert {check["state"] for check in report["checks"]} == {"source_owner_mismatch"}
    assert report["checks"][1]["location"] is None
    assert {check["rule"] for check in report["checks"]} == {
        "source_owner",
        "quote_location",
        "quantity_occurrence",
    }
    same = copy.deepcopy(foreign)
    same["source_paper_id"] = snapshot.source["paper_id"]
    assert audit.run(snapshot, [same])["counts"] == {"located": 1, "observed": 1}
    for invalid in (None, True, ""):
        with pytest.raises(audit.AuditError, match="invalid_input"):
            audit.validate([{**same, "source_paper_id": invalid}])
