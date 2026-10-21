"""Rewriting one slide by an instruction: its sources follow, the rest of the deck stays."""

from __future__ import annotations

import json

import pytest

from paper_daily import presentations, slide_revise
from paper_daily.ai_types import Completion


def _deck(tmp_path, monkeypatch) -> presentations.Deck:
    monkeypatch.setattr(presentations, "DECK_DIR", tmp_path / "decks")
    slides = [
        presentations.Slide(
            f"Slide {i + 1}", "Paper order", "Point", ["A claim."], "Say it.", ["original"]
        )
        for i in range(3)
    ]
    sources = [
        {"id": "original", "label": "Original", "kind": "original", "page": None},
        {"id": "page:4", "label": "原文第 4 頁", "kind": "original", "page": 4},
        {"id": "figure:2", "label": "Table 2", "kind": "figure"},
    ]
    deck = presentations.Deck(
        "ref:x",
        "X",
        "X explained",
        "guide",
        "Newcomers",
        10,
        slides,
        sources,
        [{"id": "figure:2", "label": "Table 2", "caption": "Main results.", "file": "t2.png"}],
        [],
        "2026-10-14",
        source_hash="abc",
    )
    snapshot = presentations._folder("ref:x") / "evidence" / "abc.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(
        json.dumps(
            {
                "sources": [
                    {**sources[0], "text": "Whole paper text."},
                    {**sources[1], "text": "Table 2 reports a Dice of 0.754 on Cholec80."},
                    {**sources[2], "text": "Table 2: Main results."},
                ],
                "figures": [],
            }
        ),
        encoding="utf-8",
    )
    return deck


def _new(**over):
    s = {
        "title": "Main result: 0.754 Dice",
        "section": "Evidence",
        "takeaway": "The gain shows on Cholec80.",
        "bullets": ["Dice 0.754 (Table 2)."],
        "speaker_notes": "Walk through Table 2.",
        "sources": ["page:4", "figure:2"],
        "figure": "figure:2",
    }
    s.update(over)
    return s


def test_the_slide_and_its_sources_change_together(tmp_path, monkeypatch):
    deck = _deck(tmp_path, monkeypatch)
    seen = {}

    def model(prompt, **kwargs):
        seen.update(json.loads(prompt), task=kwargs["task"])
        return Completion(json.dumps({"slide": _new(), "summary": "換成 Table 2 的數字"}))

    monkeypatch.setattr(slide_revise.llm, "complete_result", model)
    slide, summary = slide_revise.revise(deck, 1, "換成 Table 2 的數字")
    assert summary == "換成 Table 2 的數字" and seen["task"] == "slides"
    assert slide.sources == ["figure:2", "page:4"] and slide.figure == "figure:2"
    # The neighbours travel along so the story still reads in order.
    assert seen["previous_title"] == "Slide 1" and seen["next_title"] == "Slide 3"
    # Cited sources go in full, others by label so the model can choose them.
    by_id = {s["id"]: s for s in seen["sources"]}
    assert by_id["original"]["text"] == "Whole paper text."
    assert "0.754" in by_id["page:4"]["text"]
    assert deck.slides[1].title == "Slide 2"  # the caller decides whether to keep it


def test_an_unknown_source_is_dropped_and_a_failing_slide_is_repaired(tmp_path, monkeypatch):
    deck = _deck(tmp_path, monkeypatch)
    calls = []

    def model(prompt, **kwargs):
        calls.append(kwargs["system"])
        if kwargs["system"] == slide_revise.REVISE_INSTRUCTIONS:
            too_long = _new(bullets=["字" * 130], sources=["page:4", "page:99", "figure:2"])
            return Completion(json.dumps({"slide": too_long, "summary": "x"}))
        fixed = _new(bullets=["字" * 60], speaker_notes="moved the rest here")
        return Completion(json.dumps({"slides": [{"index": 0, "slide": fixed}]}))

    monkeypatch.setattr(slide_revise.llm, "complete_result", model)
    slide, _summary = slide_revise.revise(deck, 0, "多放一點數字")
    assert len(calls) == 2 and slide.speaker_notes == "moved the rest here"
    assert "page:99" not in slide.sources


@pytest.mark.parametrize("instruction,reason", [("", "請先寫下"), ("x" * 2001, "太長")])
def test_an_empty_or_huge_instruction_is_refused(tmp_path, monkeypatch, instruction, reason):
    deck = _deck(tmp_path, monkeypatch)
    slide, why = slide_revise.revise(deck, 0, instruction)
    assert slide is None and reason in why


def test_a_reply_that_is_not_a_slide_leaves_it_unchanged(tmp_path, monkeypatch):
    deck = _deck(tmp_path, monkeypatch)
    monkeypatch.setattr(
        slide_revise.llm, "complete_result", lambda *a, **k: Completion("I cannot.")
    )
    slide, why = slide_revise.revise(deck, 0, "改短一點")
    assert slide is None and "原頁未變動" in why
