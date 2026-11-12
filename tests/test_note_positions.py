"""Reviewed quotations survive the note contract without widening other anchors."""

from copy import deepcopy
from uuid import uuid4

import pymupdf
import pytest

from paper_daily import note_positions
from paper_daily.sync_content import validate_anchor, validate_rich_note


def pdf():
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "A verified source paper")
    document.new_page().insert_text((72, 72), "Second page passage")
    return document


def test_reviewed_note_keeps_exact_quote_and_extractor_but_generic_anchor_stays_closed():
    with pdf() as document:
        anchor = note_positions.select(document, dict(p0=0, o0=0, p1=0, o1=3), "a" * 64)
        assert anchor["selection"]["quote"] == "A verified source paper"
        assert anchor["selection"]["extractor"]["version"] == pymupdf.VersionBind
        payload = dict(
            paper_id=str(uuid4()),
            body="Human interpretation",
            kind="note",
            created_at="2026-11-01T00:00:00+00:00",
            page=1,
            anchor=anchor,
        )
        validate_rich_note(payload)
        note_positions.verify(document, anchor)
        with pytest.raises(ValueError):
            validate_anchor(anchor)
        # Valid coordinates alone cannot conceal changed word ordering.
        changed = deepcopy(anchor)
        changed["selection"]["quote"] = "paper source verified A"
        with pytest.raises(ValueError, match="passage changed"):
            note_positions.verify(document, changed)


def test_multiline_cross_page_selection_is_bounded_and_uses_the_reader_word_order():
    with pdf() as document:
        anchor = note_positions.select(document, dict(p0=0, o0=2, p1=1, o1=1), "a" * 64)
        assert anchor["selection"]["quote"] == "source paper Second page"
        note_positions.verify(document, anchor)
        with pytest.raises(InterruptedError):
            note_positions.select(
                document, dict(p0=0, o0=0, p1=0, o1=1), "a" * 64, cancelled=lambda: True
            )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a.update(document_hash=None),
        lambda a: a["selection"].update(version=True),
        lambda a: a["selection"].update(quote=" "),
        lambda a: a["selection"].update(quote="字" * 11000),
        lambda a: a["selection"].update(unexpected=True),
        lambda a: a["selection"]["extractor"].update(engine="model"),
        lambda a: a["selection"]["extractor"].update(version="unsafe/path"),
        lambda a: a.update(p1=100),
    ],
)
def test_malformed_or_unbounded_reviewed_passage_is_refused(mutate):
    with pdf() as document:
        anchor = note_positions.select(document, dict(p0=0, o0=0, p1=0, o1=1), "a" * 64)
    mutate(anchor)
    with pytest.raises(ValueError):
        note_positions.validate(anchor)
