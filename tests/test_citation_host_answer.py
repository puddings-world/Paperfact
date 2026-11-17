"""An agent host answers the reference analysis with its own account; Paperfact stores it."""

import pytest
from test_research_compound import driver as driver
from test_research_compound import seed
from test_research_compound import workspace as workspace
from test_research_generation import rows

from paper_daily import cites, followups, llm, local_operations, store


def answer(key, title="First"):
    return {
        "key": key,
        "title": title,
        "purpose": "Evidence",
        "gist": "Method",
        "verdict": followups.VERDICTS[0],
        "why": "Core",
    }


@pytest.fixture
def no_model(monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("Paperfact called a model"))


def test_the_task_carries_instructions_material_and_keys(driver, no_model):
    path, *_ = driver
    task = cites.task("paper", database=path)
    assert task["instructions"] == cites.INSTRUCTIONS
    assert task["keys"] == ["1", "2"]
    assert "[1] First" in task["material"] and "[2] Second" in task["material"]
    assert task["spec"] == cites.CITE_SPEC
    assert rows(path, "SELECT * FROM cites") == []


def test_a_saved_answer_is_stored_as_the_models_would_be(driver, no_model):
    path, *_ = driver
    saved, reason = cites.save("paper", [answer("1"), answer("2", "Second")], database=path)
    assert (saved, reason) == (2, "")
    stored = rows(path, "SELECT ref_key, title, verdict, spec FROM cites ORDER BY ref_key")
    assert [(r["ref_key"], r["title"]) for r in stored] == [("1", "First"), ("2", "Second")]
    assert {r["spec"] for r in stored} == {cites.CITE_SPEC}


def test_keys_the_paper_does_not_have_and_unanswered_entries_are_dropped(driver, no_model):
    path, *_ = driver
    invented = answer("99", "Invented")
    empty = {**answer("2", "Second"), "why": ""}
    saved, reason = cites.save("paper", [answer("1"), invented, empty], database=path)
    assert saved == 1 and "1/2" in reason
    assert [r["ref_key"] for r in rows(path, "SELECT ref_key FROM cites")] == ["1"]


def test_a_row_the_reader_edited_survives_a_host_answer(driver, no_model):
    path, *_ = driver
    seed(path, "citations", "1", edited=1)
    cites.save("paper", [answer("1", "Overwritten"), answer("2", "Second")], database=path)
    kept = rows(path, "SELECT title, edited FROM cites WHERE ref_key='1'")[0]
    assert (kept["title"], kept["edited"]) == ("Original", 1)


def test_a_reply_that_is_not_a_list_of_objects_saves_nothing(driver, no_model):
    path, *_ = driver
    assert cites.save("paper", {"key": "1"}, database=path)[0] == 0
    assert cites.save("paper", ["1"], database=path)[0] == 0
    assert rows(path, "SELECT * FROM cites") == []


def test_operations_share_the_envelope_and_reject_bad_input(driver, no_model, monkeypatch):
    path, *_ = driver
    monkeypatch.setattr(store, "DB_PATH", path)
    task = local_operations.dispatch("research.citations.task", {"paper_id": "paper"})
    assert task["ok"] and task["result"]["keys"] == ["1", "2"]
    saved = local_operations.dispatch(
        "research.citations.save",
        {"paper_id": "paper", "entries": [answer("1"), answer("2", "Second")]},
    )
    assert saved == {"ok": True, "result": {"saved": 2, "complete": True, "reason": ""}}
    for operation, args in [
        ("research.citations.task", {"paper_id": "../etc"}),
        ("research.citations.task", {"paper_id": "paper", "limit": 0}),
        ("research.citations.save", {"paper_id": "paper", "entries": [], "limit": True}),
    ]:
        assert local_operations.dispatch(operation, args)["error"]["code"] == "invalid_input"
    nothing = local_operations.dispatch(
        "research.citations.save", {"paper_id": "paper", "entries": []}
    )
    assert nothing["error"]["code"] == "citation_answer_rejected"
    missing = local_operations.dispatch("research.citations.task", {"paper_id": "absent"})
    assert missing["error"]["code"] == "citation_task_unavailable"
