"""Human highlight proposals retain coverage and require exact, selectable original quotes."""

import copy
import hashlib
import json
import sqlite3
from pathlib import Path

import pymupdf
import pytest
from test_research_evidence import CONTROL, REPEATED, UNIQUE, pdf
from test_research_evidence import source as source

from paper_daily import annotation_content, paper_highlights
from paper_daily import research_evidence as evidence


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def baseline_for(source):
    snapshot = evidence.capture(source)
    pages = evidence.snapshot_pages(snapshot)
    row = dict(
        paper_id=source.local_id,
        body_json=encoded(
            dict(
                items=[
                    dict(
                        text=UNIQUE,
                        page=2,
                        kind="evidence",
                        reason="Original appraisal.",
                        source="page:2",
                    )
                ],
                coverage=dict(
                    pages=len(pages),
                    empty_pages=[page["page"] for page in pages if not page["text"]],
                    chunks=1,
                    has_page_numbers=True,
                ),
            )
        ),
        source_hash=paper_highlights._hash(pages),
        document_hash=source.sha256,
        written_at="2026-11-02T00:00:00+00:00",
    )
    annotation_content.validate_row("highlight_analysis", row)
    return snapshot, row


@pytest.fixture
def draft(source):
    from paper_daily import highlight_draft_revision as revision

    snapshot, row = baseline_for(source)
    return snapshot, row, revision.editable(row)


def test_human_edits_preserve_coverage_and_rebuild_exact_mark_proposals(draft):
    from paper_daily import highlight_draft_revision as revision

    snapshot, row, changes = draft
    before = copy.deepcopy(row)
    changes["items"][0]["kind"] = "limitation"
    changes["items"][0]["reason"] = "Cohort size does not establish external validity."
    changes["items"][0]["page"] = None
    result = revision.revise(snapshot, row, encoded(changes))
    assert result["all_quotes_located"] and result["analysis"]["items"][0]["page"] == 2
    item = result["analysis"]["items"][0]
    assert item == dict(
        text=UNIQUE,
        page=2,
        kind="limitation",
        reason=changes["items"][0]["reason"],
        source="page:2",
    )
    assert result["analysis"]["coverage"] == json.loads(row["body_json"])["coverage"]
    annotation_content.validate("highlight_analysis", result["analysis"])
    mark = result["marks"][0]
    assert mark["source_key"] == hashlib.sha256(f"2:{UNIQUE}".encode()).hexdigest()
    assert mark["anchor"]["p0"] == mark["anchor"]["p1"] == 1 and mark["item_index"] == 0
    assert result["generation"] == dict(
        task="highlight_analysis", backend="manual", requested_model=None, returned_model=None
    )
    assert result["semantic_validation"] == "not_performed" and row == before
    assert revision.revise(snapshot, row, encoded(changes)) == result


@pytest.mark.parametrize(
    "case,state",
    [
        ("missing", "missing"),
        ("ambiguous", "ambiguous"),
        ("wrong-page", "invalid_page"),
        ("old-anchor", "invalid_anchor"),
    ],
)
def test_changed_or_uncertain_quotes_never_inherit_previous_highlight_positions(draft, case, state):
    from paper_daily import highlight_draft_revision as revision

    snapshot, row, changes = draft
    item = changes["items"][0]
    if case == "missing":
        item.update(text="An absent but plausible result.", page=None)
    elif case == "ambiguous":
        item.update(text=REPEATED, page=1)
    elif case == "wrong-page":
        item.update(page=99)
    else:
        first = revision.revise(snapshot, row, encoded(changes))["marks"][0]["anchor"]
        item.update(text=CONTROL, page=2, anchor=first)
    result = revision.revise(snapshot, row, encoded(changes))
    assert not result["all_quotes_located"] and result["analysis"] is None and result["marks"] == []
    assert result["items"][0]["location"]["state"] == state
    assert result["items"][0]["location"]["anchor"] is None
    assert result["draft_digest"] and result["semantic_validation"] == "not_performed"


def test_explicit_occurrence_can_resolve_ambiguity_without_selecting_first_automatically(draft):
    from paper_daily import highlight_draft_revision as revision

    snapshot, row, changes = draft
    changes["items"][0].update(text=REPEATED, page=1)
    result = revision.revise(snapshot, row, encoded(changes))
    choices = result["items"][0]["location"]["candidates"]
    assert len(choices) == 2
    changes["items"][0]["anchor"] = choices[1]
    resolved = revision.revise(snapshot, row, encoded(changes))
    assert resolved["all_quotes_located"] and resolved["marks"][0]["anchor"] == choices[1]


def test_whole_saved_baseline_identity_cannot_be_replaced_under_the_same_draft(draft):
    from paper_daily import highlight_draft_revision as revision

    snapshot, row, changes = draft
    for field, value in (
        ("paper_id", "other"),
        ("source_hash", "f" * 64),
        ("written_at", "2026-11-03T00:00:00+00:00"),
    ):
        changed = dict(row)
        changed[field] = value
        with pytest.raises(ValueError, match="baseline"):
            revision.revise(snapshot, changed, encoded(changes))
    changed = dict(row)
    body = json.loads(row["body_json"])
    body["items"][0]["reason"] = "A different saved interpretation."
    changed["body_json"] = encoded(body)
    with pytest.raises(ValueError, match="baseline"):
        revision.revise(snapshot, changed, encoded(changes))


def test_closed_highlight_draft_refuses_authority_coverage_overrides_empty_duplicates_and_limits(
    draft,
):
    from paper_daily import highlight_draft_revision as revision

    snapshot, row, changes = draft
    invalid = []
    for field, value in (
        ("format", "future"),
        ("permission", True),
        ("coverage", {}),
        ("source", dict(changes["source"], document_hash="f" * 64)),
        ("items", []),
        ("items", changes["items"] * 33),
    ):
        changed = copy.deepcopy(changes)
        changed[field] = value
        invalid.append(changed)
    for field, value in (
        ("reason", ""),
        ("kind", "verified"),
        ("location", {"state": "located"}),
        ("page", True),
        ("text", "short"),
        ("anchor", dict(p0=0, o0=False, p1=0, o1=1)),
    ):
        changed = copy.deepcopy(changes)
        changed["items"][0][field] = value
        invalid.append(changed)
    invalid.append(dict(changes, items=changes["items"] * 2))
    for changed in invalid:
        before = copy.deepcopy(changed)
        with pytest.raises(ValueError):
            revision.revise(snapshot, row, encoded(changed))
        assert changed == before


def test_wire_draft_rejects_duplicate_nonfinite_nonobject_and_oversized_inputs(draft):
    from paper_daily import highlight_draft_revision as revision

    snapshot, row, _changes = draft
    for raw in (
        '{"format":1,"format":2}',
        '{"value":NaN}',
        "[]",
        "{",
        b"\xff",
        " " * (220 * 1024 + 1),
    ):
        with pytest.raises(ValueError):
            revision.revise(snapshot, row, raw)


def test_new_pdf_cannot_verify_the_old_highlight_draft(draft, source):
    from paper_daily import highlight_draft_revision as revision

    _snapshot, row, changes = draft
    source.path.unlink()
    pdf(source.path, [["A new current B contains another result."]])
    newer = source._owner.resolve(source.local_id)
    with pytest.raises(ValueError):
        revision.revise(evidence.capture(newer), row, encoded(changes))


def test_original_snapshot_can_propose_edits_after_b_is_current_without_a_write_grant(
    draft, source
):
    from paper_daily import highlight_draft_revision as revision

    snapshot, row, changes = draft
    source.path.unlink()
    pdf(source.path, [["A new current B remains selected."]])
    result = revision.revise(snapshot, row, encoded(changes))
    assert result["source"]["document_hash"] == source.sha256 and result["all_quotes_located"]
    assert source._owner.resolve(source.local_id).sha256 != result["source"]["document_hash"]
    assert not {"can_apply", "prepared_source", "owner", "permission"} & result.keys()


def test_maximum_group_is_bounded_and_empty_old_coverage_is_not_rewritten(draft):
    from paper_daily import highlight_draft_revision as revision

    snapshot, row, changes = draft
    changes["items"] = [
        dict(
            text=f"An absent experimental quotation number {i}.",
            page=None,
            anchor=None,
            kind="method",
            reason="Needs original-source inspection.",
        )
        for i in range(32)
    ]
    assert revision.parse(row, encoded(changes)) == changes
    result = revision.revise(snapshot, row, encoded(changes))
    assert (
        len(result["items"]) == 32
        and result["analysis"] is None
        and not result["all_quotes_located"]
    )
    assert result["coverage"] == json.loads(row["body_json"])["coverage"]


def test_rotated_words_that_the_reader_cannot_select_never_become_highlight_marks(source):
    from paper_daily import highlight_draft_revision as revision

    source.path.unlink()
    with pymupdf.open() as pdf_file:
        page = pdf_file.new_page()
        page.insert_text((200, 500), UNIQUE, rotate=90)
        pdf_file.new_page()
        pdf_file.save(source.path)
    rotated = source._owner.resolve(source.local_id)
    snapshot, row = baseline_for(rotated)
    changes = revision.editable(row)
    changes["items"][0]["page"] = 1
    result = revision.revise(snapshot, row, encoded(changes))
    assert result["items"][0]["location"]["state"] == "invalid_anchor"
    assert result["items"][0]["location"]["reason"] == "not_selectable_in_reader"
    assert result["analysis"] is None and result["marks"] == []


def test_snapshot_revision_reads_no_database_or_old_path_after_capture(draft, monkeypatch):
    from paper_daily import highlight_draft_revision as revision

    snapshot, row, changes = draft

    def forbidden(*args, **kwargs):
        raise AssertionError("Content revision accessed disk or SQL")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    assert revision.revise(snapshot, row, encoded(changes))["all_quotes_located"]


@pytest.mark.parametrize("after", [1, 4])
def test_cancelled_highlight_revision_preserves_original_and_draft(draft, after):
    from paper_daily import highlight_draft_revision as revision

    snapshot, row, changes = draft
    before = copy.deepcopy((row, changes))
    calls = []

    def cancelled():
        calls.append(1)
        return len(calls) >= after

    with pytest.raises(ValueError, match="cancel"):
        revision.revise(snapshot, row, encoded(changes), cancelled=cancelled)
    assert (row, changes) == before


def test_receiver_mapping_is_explicit_and_cannot_change_original_bytes(draft):
    from paper_daily import highlight_draft_revision as revision

    snapshot, row, _changes = draft
    historical = dict(row, paper_id="old-local-paper")
    draft = revision.editable(historical)
    with pytest.raises(ValueError, match="another paper"):
        revision.revise(snapshot, historical, encoded(draft))
    mapped = revision.revise_for_receiver(snapshot, historical, encoded(draft))
    assert mapped["source"] == snapshot.source and mapped["all_quotes_located"]
    assert mapped["baseline_digest"] == draft["baseline_digest"]
    assert (
        historical["paper_id"] == "old-local-paper"
        and mapped["semantic_validation"] == "not_performed"
    )


def test_inconsistent_saved_page_coverage_does_not_become_a_verified_group(draft):
    from paper_daily import highlight_draft_revision as revision

    snapshot, row, _changes = draft
    for coverage in (
        dict(pages=1, empty_pages=[], chunks=1, has_page_numbers=True),
        dict(pages=2, empty_pages=[1], chunks=1, has_page_numbers=True),
    ):
        wrong = dict(row)
        body = json.loads(row["body_json"])
        body["coverage"] = coverage
        wrong["body_json"] = encoded(body)
        changes = revision.editable(wrong)
        before = copy.deepcopy((wrong, changes))
        with pytest.raises(ValueError, match="coverage"):
            revision.revise(snapshot, wrong, encoded(changes))
        assert (wrong, changes) == before
