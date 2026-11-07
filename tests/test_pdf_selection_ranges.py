"""Selection ranges use actual selectable PDF words, including cross-page endpoints."""

import pymupdf
import pytest

from paper_daily import pdf_selection_text as selection


@pytest.fixture
def document():
    with pymupdf.open() as pdf:
        first = pdf.new_page()
        first.insert_text((50, 50), "alpha beta gamma")
        first.insert_text((400, 400), "rotated axis", rotate=90)
        pdf.new_page().insert_text((50, 50), "delta epsilon zeta")
        yield pdf


@pytest.mark.parametrize(
    "anchor",
    [
        dict(p0=0, o0=0, p1=1, o1=2),
        dict(p0=0, o0=2, p1=0, o1=2),
        dict(p0=1, o0=0, p1=1, o1=0),
    ],
)
def test_valid_single_word_and_cross_page_positions_are_accepted(document, anchor):
    assert selection.validate_range(document, anchor) is None
    assert [word[4] for _index, word in selection.level_words(document[0])] == [
        "alpha",
        "beta",
        "gamma",
    ]


@pytest.mark.parametrize(
    "anchor",
    [
        dict(p0=0, o0=3, p1=0, o1=4),
        dict(p0=0, o0=0, p1=0, o1=8),
        dict(p0=0, o0=0, p1=2, o1=0),
        dict(p0=1, o0=0, p1=0, o1=2),
    ],
)
def test_rotated_missing_and_reversed_endpoints_cannot_claim_a_selectable_location(
    document, anchor
):
    # Rotated words really exist in the PDF but cannot be selected by the app.
    assert document[0].get_text("words")[3][4] == "rotated"
    with pytest.raises(ValueError):
        selection.validate_range(document, anchor)


def test_verifying_a_range_extracts_only_its_two_endpoint_pages(document, monkeypatch):
    extracted = []
    original = selection.level_words

    def words(page):
        extracted.append(page.number)
        return original(page)

    monkeypatch.setattr(selection, "level_words", words)
    selection.validate_range(document, dict(p0=0, o0=0, p1=1, o1=2))
    assert extracted == [0, 1]
    extracted.clear()
    selection.validate_range(document, dict(p0=0, o0=0, p1=0, o1=2))
    assert extracted == [0]
