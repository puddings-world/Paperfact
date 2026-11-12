"""Editable retries preserve the original until the new question is safely prepared."""

import pytest
from test_reader_ai_scope import _bodies, _chat, _until
from test_reader_ai_scope import asking as _asking
from test_reader_ai_scope import window as _window

from paper_daily import research_chat

asking = _asking
window = _window


def failed(asking):
    win, app, calls = asking
    win.open_paper("a")
    win.reader_page._ask("Original question")
    calls[0][2]("unavailable")
    _chat(win, app)
    original = win.data.chat("a")[0]
    win.reader_page._retry_question(original["id"])
    assert win.reader_page.ask_box.text() == "Original question"
    return original


def test_edit_retry_is_a_draft_until_sent_and_does_not_follow_another_paper(asking):
    original = failed(asking)
    win, app, calls = asking
    reader = win.reader_page
    reader.ask_box.setText("Edited question")
    assert win.data.chat("a") == [original] and len(calls) == 1
    win.open_paper("b")
    reader._ask("New paper question")
    reader._ask("New paper question")
    assert len(calls) == 2
    calls[1][1]("Answer B")
    assert win.data.chat("a") == [original]
    assert _bodies(win, "b") == [("user", "New paper question"), ("assistant", "Answer B")]


def test_edit_retry_commits_one_edited_question_and_answer(asking):
    original = failed(asking)
    win, app, calls = asking
    reader = win.reader_page
    reader.ask_box.setText("Edited question")
    reader._ask_from_box(reader.ask_box.text())
    reader._ask_from_box(reader.ask_box.text())
    assert len(calls) == 2
    calls[1][1]("Edited answer")
    assert _bodies(win, "a") == [("user", "Edited question"), ("assistant", "Edited answer")]
    assert win.data.chat("a")[0]["id"] != original["id"]


@pytest.mark.parametrize("failure", ["append", "changed"])
def test_failed_retry_preparation_rolls_back_old_question_without_an_ai_call(
    asking, monkeypatch, failure
):
    original = failed(asking)
    win, app, calls = asking
    reader = win.reader_page
    # The normal fixture waits for a model invocation. This path must fail before one.
    monkeypatch.setattr(reader.runner, "start", type(reader.runner).start.__get__(reader.runner))
    if failure == "append":
        def broken(*args, **kwargs):
            raise OSError("fixture storage failure")
        monkeypatch.setattr(research_chat, "_append", broken)
    else:
        win.data.delete_chat([original["id"]])
    reader._ask_from_box("Edited question")
    _until(app, lambda: not reader.runner.busy)
    assert len(calls) == 1
    assert win.data.chat("a") == ([original] if failure == "append" else [])
    assert reader.ask_btn.isEnabled()
