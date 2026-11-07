"""Structured claim edits must be rebound to exact original bytes, never old anchors."""

import copy
import json

import pytest
from test_research_evidence import CONTROL, REPEATED, UNIQUE, pdf, proposal
from test_research_evidence import source as _source

from paper_daily import annotation_content, claim_content
from paper_daily import claim_draft_revision as revision
from paper_daily import research_evidence as evidence

source = _source


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


@pytest.fixture
def draft(source):
    snapshot = evidence.capture(source)
    body = dict(
        format=claim_content.FORMAT,
        recipe=claim_content.RECIPE,
        inputs=dict(dive="a" * 64, close_reading="b" * 64),
        generation=dict(
            task="claims", backend="fixture", requested_model="chosen", returned_model="returned"
        ),
        report=evidence.verify_snapshot(snapshot, proposal(source)),
    )
    annotation_content.validate("claims", body)
    baseline = encoded(body)
    return snapshot, body, baseline, revision.editable(baseline)


def test_human_revision_relocates_sources_rebuilds_ids_and_records_manual_origin(draft):
    snapshot, original, baseline, changes = draft
    assert revision.parse(baseline, encoded(changes)) == changes
    before = copy.deepcopy(original)
    claim = changes["claims"][0]
    claim["text"] = "The cohort is held out; generalization remains untested."
    claim["judgment"] = dict(
        status="inferred", reason="The quote gives cohort size, not external validation."
    )
    result = revision.revise(snapshot, baseline, encoded(changes))
    body = result["body"]
    annotation_content.validate("claims", body)
    assert body["inputs"] == original["inputs"]
    assert body["report"]["source"] == original["report"]["source"]
    assert body["generation"] == dict(
        task="claims", backend="manual", requested_model=None, returned_model=None
    )
    updated = body["report"]["claims"][0]
    assert updated["id"] != original["report"]["claims"][0]["id"]
    assert updated["text"] == claim["text"]
    assert updated["judgment"] == {**claim["judgment"], "authority": "caller"}
    assert updated["semantic_validation"] == "not_performed"
    assert updated["passages"][0]["location"]["state"] == "located"
    assert updated["passages"][0]["location"]["page"] == 2
    assert result["baseline_digest"] == changes["baseline_digest"]
    assert result["draft_digest"] == claim_content.hashed(changes)
    assert revision.revise(snapshot, baseline, encoded(changes)) == result
    assert original == before and encoded(before) == baseline


@pytest.mark.parametrize(
    "quote,state",
    [("This quotation is absent from the original.", "missing"), (REPEATED, "ambiguous")],
)
def test_changed_quote_never_keeps_the_previous_verified_anchor(draft, quote, state):
    snapshot, _body, baseline, changes = draft
    changes["claims"][0]["passages"][0] = dict(quote=quote, page=None, anchor=None)
    changes["claims"][0]["judgment"]["status"] = "supported"
    claim = revision.revise(snapshot, baseline, encoded(changes))["body"]["report"]["claims"][0]
    assert claim["passages"][0]["location"]["state"] == state
    assert claim["passages"][0]["location"]["anchor"] is None
    assert claim["judgment"]["authority"] == "caller"
    assert claim["semantic_validation"] == "not_performed"


def test_changed_quote_with_old_coordinates_is_not_presented_as_located(draft):
    snapshot, _body, baseline, changes = draft
    changes["claims"][0]["passages"][0]["quote"] = CONTROL
    passage = revision.revise(snapshot, baseline, encoded(changes))["body"]["report"]["claims"][0][
        "passages"
    ][0]
    assert passage["location"]["state"] == "invalid_anchor"
    assert passage["location"]["anchor"] is None


def test_edited_draft_belongs_to_the_whole_baseline_not_just_its_pdf(draft):
    snapshot, body, _baseline, changes = draft
    changed = copy.deepcopy(body)
    changed["generation"]["returned_model"] = "a different saved result"
    with pytest.raises(ValueError, match="baseline"):
        revision.revise(snapshot, encoded(changed), encoded(changes))


@pytest.mark.parametrize(
    "field", ["format", "source", "authority", "location", "empty", "claims", "passages"]
)
def test_closed_typed_draft_refuses_untrusted_or_oversized_content(draft, field):
    snapshot, _body, baseline, changes = draft
    if field == "format":
        changes["format"] = "future"
    elif field == "source":
        changes["source"]["document_hash"] = "c" * 64
    elif field == "authority":
        changes["claims"][0]["judgment"]["authority"] = "verified"
    elif field == "location":
        changes["claims"][0]["passages"][0]["location"] = {"state": "located"}
    elif field == "empty":
        changes["claims"] = []
    elif field == "claims":
        changes["claims"] = [
            {**copy.deepcopy(changes["claims"][0]), "text": "Claim " + str(i)} for i in range(17)
        ]
    else:
        changes["claims"][0]["passages"] = [
            copy.deepcopy(changes["claims"][0]["passages"][0]) for _ in range(49)
        ]
    before = copy.deepcopy(changes)
    with pytest.raises(ValueError):
        revision.revise(snapshot, baseline, encoded(changes))
    assert changes == before


@pytest.mark.parametrize(
    "raw",
    ['{"format":1,"format":2}', '{"value":NaN}', "[]", "{", " " * (220 * 1024 + 1)],
    ids=["duplicate-keys", "nonfinite", "nonobject", "broken-json", "oversized"],
)
def test_wire_draft_rejects_duplicate_keys_nonfinite_nonobject_and_oversize(draft, raw):
    snapshot, _body, baseline, _changes = draft
    with pytest.raises(ValueError):
        revision.revise(snapshot, baseline, raw)


def test_a_new_pdf_cannot_satisfy_an_old_source_draft(draft, source):
    _snapshot, _body, baseline, changes = draft
    source.path.unlink()
    pdf(source.path, [["A newer original containing different evidence."]])
    newer = source._owner.resolve(source.local_id)
    assert newer.available and newer.sha256 != changes["source"]["document_hash"]
    with pytest.raises(ValueError):
        revision.revise(evidence.capture(newer), baseline, encoded(changes))


def test_captured_original_remains_only_a_proposal_when_current_file_changes(draft, source):
    snapshot, original, baseline, changes = draft
    source.path.unlink()
    pdf(source.path, [["New current B must not replace original A."]])
    result = revision.revise(snapshot, baseline, encoded(changes))
    assert result["body"]["report"]["source"] == original["report"]["source"]
    assert result["body"]["report"]["claims"][0]["passages"][0]["quote"] == UNIQUE
    assert (
        source._owner.resolve(source.local_id).sha256
        != result["body"]["report"]["source"]["document_hash"]
    )
    assert set(result) == {"body", "baseline_digest", "draft_digest"}  # No publication grant.


@pytest.mark.parametrize("after", [1, 3])
def test_cancellation_returns_no_partial_revision_and_preserves_draft(draft, after):
    snapshot, body, baseline, changes = draft
    before = copy.deepcopy((body, changes))
    calls = []

    def cancelled():
        calls.append(True)
        return len(calls) >= after

    with pytest.raises(ValueError, match="cancel"):
        revision.revise(snapshot, baseline, encoded(changes), cancelled=cancelled)
    assert len(calls) >= after and (body, changes) == before


def test_proposed_external_identity_stays_unresolved_after_human_revision(draft):
    snapshot, _body, baseline, changes = draft
    changes["claims"][0]["passages"][0]["citation"] = dict(
        paper_id=None, doi="10.0000/example", title="Proposed reference"
    )
    passage = revision.revise(snapshot, baseline, encoded(changes))["body"]["report"]["claims"][0][
        "passages"
    ][0]
    assert passage["citation_identity"]["state"] == "unresolved"
    assert passage["citation_identity"]["reason"] == "no_trusted_citation_mapping"
