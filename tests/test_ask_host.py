"""An agent host answers a question about a paper; Paperfact keeps it in the Q&A."""

import pytest
from test_research_chat import legacy as legacy
from test_research_chat import messages

from paper_daily import ask_host, llm, local_operations
from paper_daily.desktop.ask import ANSWER_RULE


@pytest.fixture
def host(legacy, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("Paperfact called a model"))
    return legacy


def op(name, **arguments):
    return local_operations.dispatch(name, arguments)


def turns():
    return [(row["role"], row["body"]) for row in messages()]


def test_the_question_is_stored_before_any_answer_and_the_task_carries_the_prompt(host):
    task = op("research.ask.task", paper_id="local-paper", question=" Why does it work? ")
    assert task["ok"]
    result = task["result"]
    assert result["question"] == "Why does it work?" and result["paper_id"] == "local-paper"
    assert ANSWER_RULE in result["material"]
    assert result["material"].endswith("讀者的問題:Why does it work?")
    assert turns() == [("user", "Why does it work?")]


def test_a_saved_answer_becomes_the_reply_without_text_outside_the_tags(host):
    request_id = op("research.ask.task", paper_id="local-paper", question="Q?")["result"][
        "request_id"
    ]
    saved = op(
        "research.ask.save",
        request_id=request_id,
        answer="plan first<answer>\n結論:有效。</answer>",
    )
    assert saved == {"ok": True, "result": {"status": "accepted", "reason": "ok", "chars": 6}}
    assert turns() == [("user", "Q?"), ("assistant", "結論:有效。")]


def test_a_question_is_answered_once(host):
    request_id = ask_host.task("local-paper", "Q?")["request_id"]
    ask_host.save(request_id, "First")
    again = op("research.ask.save", request_id=request_id, answer="Second")
    assert again["error"]["code"] == "ask_answer_rejected"
    reopened = op("research.ask.task", request_id=request_id)
    assert reopened["error"]["code"] == "ask_task_unavailable"
    assert turns() == [("user", "Q?"), ("assistant", "First")]


def test_an_unanswered_question_can_be_reopened_by_its_request(host):
    first = ask_host.task("local-paper", "Q?")
    again = op("research.ask.task", request_id=first["request_id"])["result"]
    assert again["request_id"] == first["request_id"]
    assert again["material"] == first["material"]
    assert turns() == [("user", "Q?")]
    assert ask_host.save(first["request_id"], "Answer")["status"] == "accepted"


@pytest.mark.parametrize("answer", ["", "   ", "<answer> </answer>"])
def test_an_empty_answer_is_rejected_and_the_question_stays_open(host, answer):
    request_id = ask_host.task("local-paper", "Q?")["request_id"]
    rejected = op("research.ask.save", request_id=request_id, answer=answer)
    assert rejected["error"]["code"] == "ask_answer_rejected"
    assert turns() == [("user", "Q?")]


def test_bad_input_and_unknown_targets_store_nothing(host):
    for arguments in (
        {},
        {"paper_id": "local-paper"},
        {"paper_id": "local-paper", "question": "  "},
        {"paper_id": "local-paper", "question": "x" * 4001},
        {"paper_id": "../etc", "question": "Q?"},
        {"paper_id": "local-paper", "question": "Q?", "request_id": "r"},
        {"request_id": 5},
    ):
        assert op("research.ask.task", **arguments)["error"]["code"] == "invalid_input"
    for arguments in ({"request_id": 5, "answer": "A"}, {"request_id": "r", "answer": 5}):
        assert op("research.ask.save", **arguments)["error"]["code"] == "invalid_input"
    absent = op("research.ask.task", paper_id="absent", question="Q?")
    assert absent["error"]["code"] == "ask_task_unavailable"
    unknown = op("research.ask.save", request_id="not-a-request", answer="A")
    assert unknown["error"]["code"] == "ask_answer_rejected"
    assert turns() == []
