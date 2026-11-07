"""Prompt context excludes unfinished typed turns without rewriting raw history."""

from copy import deepcopy

import pytest

from paper_daily.research_chat import _prompt_history


def row(role, message, *, exchange="e", reply=None, paper="p", source="a" * 64):
    return dict(role=role, body=message, message_id=message, exchange_id=exchange,
                reply_to=reply, paper_id=paper, source_hash=source)


@pytest.mark.parametrize("source", [None, "a" * 64])
def test_exact_completed_typed_pair_is_prompt_context_and_raw_inputs_are_unchanged(source):
    rows = [row("user", "question", source=source),
            row("assistant", "answer", reply="question", source=source),
            row("user", "unfinished", exchange="next")]
    original = deepcopy(rows)
    assert _prompt_history(rows) == [("user", "question"), ("assistant", "answer")]
    assert rows == original


@pytest.mark.parametrize("change", [
    {"reply_to": "unknown"}, {"exchange_id": "other"}, {"paper_id": "other"},
    {"source_hash": "b" * 64}, {"source_hash": None}, {"message_id": None},
])
def test_mismatched_or_unknown_typed_answer_never_completes_a_question(change):
    question = row("user", "question")
    answer = {**row("assistant", "answer", reply="question"), **change}
    assert _prompt_history([question, answer]) == []


def test_orphan_or_ambiguous_typed_turns_do_not_gain_pairing_from_order():
    question = row("user", "question")
    answer = row("assistant", "answer", reply="question")
    assert _prompt_history([question]) == []
    assert _prompt_history([answer]) == []
    assert _prompt_history([question, dict(question), answer]) == []


def test_interleaved_distinct_typed_exchanges_keep_actual_captured_order():
    rows = [row("user", "one", exchange="1"), row("user", "two", exchange="2"),
            row("assistant", "second", exchange="2", reply="two"),
            row("assistant", "first", exchange="1", reply="one")]
    assert _prompt_history(rows) == [(r["role"], r["body"]) for r in rows]


def test_unlinked_legacy_context_retains_existing_behavior_without_typed_pairing():
    legacy = [dict(role="user", body="Legacy unfinished", paper_id="p"),
              dict(role="assistant", body="Historical standalone", paper_id="p")]
    assert _prompt_history(legacy) == [
        ("user", "Legacy unfinished"), ("assistant", "Historical standalone")
    ]
    assert _prompt_history(legacy + [row("user", "New unfinished")]) == _prompt_history(legacy)
