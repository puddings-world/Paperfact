"""Shared quote location is source-bound, bounded and independent of claim semantics."""

import copy
from dataclasses import replace

import pytest
from test_research_evidence import CONTROL, REPEATED, UNIQUE, pdf
from test_research_evidence import source as source

from paper_daily import research_evidence as evidence


def request(source, *quotes):
    return dict(
        format="paperfact.quote-locations.proposals.v1",
        source=dict(paper_id=source.paper_id or source.local_id, document_hash=source.sha256),
        passages=[dict(quote=quote, page=page, anchor=None) for quote, page in quotes],
    )


def test_shared_snapshot_locations_return_honest_states_without_claims_or_semantic_verdict(source):
    snapshot = evidence.capture(source)
    data = request(source, (UNIQUE, None), (REPEATED, 1), ("An absent but plausible result.", None))
    before = copy.deepcopy(data)
    result = evidence.locate_quotes_snapshot(snapshot, data)
    assert [item["location"]["state"] for item in result["passages"]] == [
        "located",
        "ambiguous",
        "missing",
    ]
    assert result["passages"][0]["location"]["page"] == 2
    assert result["passages"][1]["location"]["anchor"] is None
    assert len(result["passages"][1]["location"]["candidates"]) == 2
    assert result["source"] == data["source"] and result["page_count"] == 2
    assert result["semantic_validation"] == "not_performed"
    assert not {"claims", "judgment", "confidence", "can_apply", "permission"} & result.keys()
    assert data == before and evidence.locate_quotes_snapshot(snapshot, data) == result


def test_wrong_owner_or_hash_refuses_before_extracting_pdf(source, monkeypatch):
    snapshot = evidence.capture(source)

    def forbidden(*args):
        pytest.fail("A wrong source reached PDF extraction")

    monkeypatch.setattr(evidence, "_extract", forbidden)
    for field, value, code in (
        ("paper_id", "other", "source_identity_mismatch"),
        ("document_hash", "f" * 64, "source_hash_mismatch"),
    ):
        data = request(source, (UNIQUE, None))
        data["source"][field] = value
        with pytest.raises(evidence.EvidenceError) as caught:
            evidence.locate_quotes_snapshot(snapshot, data)
        assert caught.value.code == code and value not in str(caught.value)


def test_closed_bounded_quote_requests_refuse_unknown_or_untrusted_fields_before_pdf(
    source, monkeypatch
):
    snapshot = evidence.capture(source)
    good = request(source, (UNIQUE, None))
    invalid = []
    for field, value in (
        ("format", "future"),
        ("permission", True),
        ("source", {}),
        ("passages", []),
        ("passages", good["passages"] * 129),
    ):
        data = copy.deepcopy(good)
        data[field] = value
        invalid.append(data)
    for field, value in (
        ("page", True),
        ("anchor", {}),
        ("quote", ""),
        ("quote", "x" * 4001),
        ("location", {"state": "located"}),
        ("anchor", dict(p0=0, o0=False, p1=0, o1=4)),
    ):
        data = copy.deepcopy(good)
        data["passages"][0][field] = value
        invalid.append(data)
    invalid.append(dict(good, passages=good["passages"] * 2))
    invalid.append(
        dict(good, passages=[dict(quote="x" * 4000, page=i, anchor=None) for i in range(128)])
    )
    monkeypatch.setattr(
        evidence, "_extract", lambda *args: pytest.fail("Invalid request reached PDF")
    )
    for data in invalid:
        before = copy.deepcopy(data)
        with pytest.raises(evidence.EvidenceError):
            evidence.locate_quotes_snapshot(snapshot, data)
        assert data == before


def test_original_snapshot_locations_survive_current_pdf_change_but_remain_content_only(source):
    snapshot = evidence.capture(source)
    data = request(source, (UNIQUE, None))
    source.path.unlink()
    pdf(source.path, [["A new current B with different source text."]])
    result = evidence.locate_quotes_snapshot(snapshot, data)
    assert result["passages"][0]["location"]["state"] == "located"
    assert result["source"]["document_hash"] == source.sha256
    assert source._owner.resolve(source.local_id).sha256 != source.sha256
    assert "can_apply" not in result


@pytest.mark.parametrize("after", [1, 4])
def test_cancelled_quote_location_returns_no_partial_result_or_mutated_input(source, after):
    snapshot = evidence.capture(source)
    data = request(source, (UNIQUE, None), (CONTROL, 2))
    before = copy.deepcopy(data)
    calls = []

    def cancelled():
        calls.append(1)
        return len(calls) >= after

    with pytest.raises(evidence.EvidenceError, match="cancel"):
        evidence.locate_quotes_snapshot(snapshot, data, cancelled=cancelled)
    assert data == before


def test_changed_snapshot_bytes_cannot_mint_locations(source):
    snapshot = evidence.capture(source)
    forged = replace(snapshot, _bytes=snapshot._bytes + b"changed")
    with pytest.raises(evidence.EvidenceError, match="invalid_snapshot"):
        evidence.locate_quotes_snapshot(forged, request(source, (UNIQUE, None)))
