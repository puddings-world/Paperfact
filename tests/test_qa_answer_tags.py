"""A Q&A reply keeps only the answer, not planning the model wrote ahead of it."""

import json

import pytest
from test_research_chat import legacy as legacy
from test_research_chat import messages, start

from paper_daily import llm
from paper_daily.answer_content import tagged_answer
from paper_daily.desktop.ask import ANSWER_RULE, build_prompt

# Observed 2026-11-19 from claude -p (Opus 5.5) on a 精要 question, before the tags.
LEAKED = (
    "</reasoning_effort>\n\nThe user asks to explain online RL. Keep ~250 chars."
    "<answer>\n結論:online RL 是 LLM post-training 的核心。\n</answer>"
)


def test_the_answer_inside_the_tags_is_kept_and_leaked_planning_dropped():
    assert tagged_answer(LEAKED) == "結論:online RL 是 LLM post-training 的核心。"


def test_a_reply_without_tags_is_kept_whole():
    assert tagged_answer("  結論:沒有標籤的回答。\n") == "結論:沒有標籤的回答。"


def test_a_cut_off_closing_tag_keeps_what_follows_the_last_opening():
    reply = "plan <answer>草稿</answer> more <answer>\n結論:最後一版"
    assert tagged_answer(reply) == "結論:最後一版"


@pytest.mark.parametrize("empty", [None, "", "<answer>  </answer>"])
def test_an_empty_answer_is_no_answer(empty):
    assert tagged_answer(empty) is None


@pytest.mark.parametrize("concise", [True, False])
def test_every_question_asks_for_the_answer_in_tags(concise):
    prompt = build_prompt("T", "ICLR", 2026, None, "text", [], "Q?", concise=concise)
    assert ANSWER_RULE in prompt.split("論文:")[0] and "<answer>" in ANSWER_RULE
    assert prompt.endswith("讀者的問題:Q?")


def test_a_stored_answer_has_no_leaked_planning(legacy, monkeypatch):
    from paper_daily.desktop.qa_job import ChatJob

    monkeypatch.setattr(llm, "ACCESS_CHECK", None)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (LEAKED, "ok"))
    job = ChatJob(start(), {}, None)
    response, _ = job("")
    assert json.loads(response)["status"] == "accepted"
    assert [r["body"] for r in messages()][-1] == "結論:online RL 是 LLM post-training 的核心。"
