"""Real scoped citation publication with explicit bounded additional calls."""

import json

import pytest
from test_citation_coverage import answers, read_coverage
from test_research_compound import driver as driver
from test_research_compound import workspace as workspace
from test_research_generation import rows

from paper_daily import cites, llm
from paper_daily.sources import crossref


@pytest.mark.parametrize("mode", ["manual", "complete", "bounded", "invalid", "no_progress"])
def test_partial_answers_survive_bounded_continuation(driver, monkeypatch, mode):
    path, _client, _document, _calls, install, _invoke = driver
    install("citations")
    monkeypatch.setattr(
        crossref,
        "reference_list",
        lambda _: {str(i): {"title": f"Reference {i}"} for i in range(1, 6)},
    )
    outputs = [answers([1])]
    if mode == "complete":
        outputs.append(answers(range(2, 6)))
    elif mode == "bounded":
        outputs.extend([answers([2]), answers([3])])
    elif mode == "invalid":
        outputs.append("invalid")
    elif mode == "no_progress":
        outputs.append(answers([1]))
    calls = []

    def complete(prompt, **kwargs):
        calls.append(prompt)
        reply = outputs.pop(0)
        return (reply if isinstance(reply, str) else json.dumps(reply)), "ok"

    monkeypatch.setattr(llm, "complete", complete)
    count, reason = cites.analyse_result(
        "paper", database=path, max_additional_calls=0 if mode == "manual" else 2
    )
    expected = 5 if mode == "complete" else 3 if mode == "bounded" else 1
    assert count == expected
    assert len(rows(path, "SELECT * FROM cites")) == expected
    assert len(calls) == (1 if mode == "manual" else 3 if mode == "bounded" else 2)
    assert read_coverage(path)["state"] == ("complete" if mode == "complete" else "partial")
    assert bool(reason) == (mode != "complete")
    if len(calls) > 1:
        assert '["2", "3", "4", "5"]' in calls[1]


@pytest.mark.parametrize("invalid", [True, -1, 3, "2"])
def test_invalid_budget_never_calls_provider(driver, monkeypatch, invalid):
    path, *_ = driver
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("Invalid budget called AI"))
    with pytest.raises(ValueError, match="integer"):
        cites.analyse_result("paper", database=path, max_additional_calls=invalid)
