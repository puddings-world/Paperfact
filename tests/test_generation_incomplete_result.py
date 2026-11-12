"""A valid result is not downgraded to a generic parser/storage failure."""

import pytest
from test_presentations import reply
from test_presentations import research as _research

from paper_daily import llm, presentations
from paper_daily.ai_types import Completion
from paper_daily.sync_deck_publication import DraftRetention, IncompleteDraftRetention

research = _research


def test_actual_generate_propagates_actual_completed_unsaved_deck(research, monkeypatch):
    captured = []
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **kw: Completion(reply(), backend="fixture")
    )

    def fail(deck, **kwargs):
        result = DraftRetention("incomplete-generation", "incomplete", deck, kwargs["evidence"])
        captured.append(result)
        raise IncompleteDraftRetention(result)

    monkeypatch.setattr(presentations, "save_deck", fail)
    with pytest.raises(IncompleteDraftRetention) as error:
        presentations.generate(
            "ref:deck",
            mode="guide",
            audience="",
            minutes=10,
            slide_count=4,
            inputs={"original", "dive"},
        )
    assert error.value.retention is captured[0]
    assert error.value.retention.deck.slides[0].title == "Section 1"
    assert len(captured) == 1
