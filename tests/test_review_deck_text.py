"""Plain-text summaries avoid exposing transport manifests as editable content."""

from copy import deepcopy

import pytest

from paper_daily.desktop.review_deck_text import MAX_PREVIEW, deck_text


@pytest.mark.parametrize("chinese", [False, True])
def test_deck_preview_is_readable_plain_text_and_does_not_mutate(chinese):
    value = {"title": "Retained title", "paper_title": "Paper", "slides": [
        {"title": "Result", "takeaway": "Main finding", "bullets": ["A point"],
         "speaker_notes": "A careful explanation", "sources": ["s1"],
         "elements": [{"kind": "text", "text": "private-layout-serialization"}]}],
         "sources": [{"id": "s1", "label": "Figure 2"}]}
    before = deepcopy(value)
    text = deck_text(value, chinese=chinese)
    assert "1. Result" in text and "A careful explanation" in text
    assert "Figure 2" in text and "Main finding" in text
    assert "private-layout-serialization" not in text
    assert value == before


def test_unverified_manifest_prompts_explicit_verification_without_raw_paths():
    text = deck_text({"body": {"sha256": "a" * 64}, "path": "/private/file"})
    assert "Verify retained slides" in text
    assert "private" not in text and "sha256" not in text
    assert deck_text(None) == "Absent or unavailable"


def test_large_preview_is_bounded_and_saved_deck_remains_complete():
    value = {"title": "Large", "slides": [{"title": "Long",
             "speaker_notes": "x" * (MAX_PREVIEW + 10)}]}
    before = deepcopy(value)
    text = deck_text(value)
    assert len(text) < MAX_PREVIEW + 100
    assert "Preview shortened" in text
    assert value == before
