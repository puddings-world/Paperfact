"""Editable retry must journal its deletion and new question in one commit."""

import sqlite3

import pytest
from test_research_chat import messages, start
from test_sync_capture import bound as _bound
from test_sync_capture import seed

from paper_daily import research_chat as chat
from paper_daily.desktop.main import Data

bound = _bound


def original():
    seed()
    request, _ = chat.prepare_chat(start("Original question"))
    row = messages()[0]
    return request, Data().chat_snapshot("local-paper", [row["id"]])


def test_retry_journals_exact_old_delete_and_new_question(bound):
    old, expected = original()
    before = len(bound.journal.pending())
    new, _ = chat.prepare_chat(start("Edited question"), replacement=expected)
    assert [(r["role"], r["body"]) for r in messages()] == [("user", "Edited question")]
    ops = bound.journal.pending()[before:]
    assert len(ops) == 2
    assert {o["action"] for o in ops} == {"delete", "put"}
    assert chat.publish_answer(new, "Edited answer").status == "accepted"
    assert chat.publish_answer(old, "Late old answer").status == "candidate"
    assert [r["body"] for r in messages()] == ["Edited question", "Edited answer"]


def test_failed_retry_commit_keeps_question_and_outbox(bound, monkeypatch):
    _old, expected = original()
    rows, operations = messages(), bound.journal.pending()
    def broken(conn):
        raise sqlite3.OperationalError("fixture commit failure")
    monkeypatch.setattr(chat, "_commit", broken)
    with pytest.raises(sqlite3.OperationalError):
        chat.prepare_chat(start("Edited question"), replacement=expected)
    assert messages() == rows and bound.journal.pending() == operations
