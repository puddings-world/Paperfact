"""Work started for one paper or selection lands there, never on what is open now."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_pdf_highlights import reader as _reader  # noqa: E402
from test_reader_prepare import _settle  # noqa: E402
from test_reader_prepare import window as _window  # noqa: E402

from paper_daily import llm  # noqa: E402
from paper_daily.desktop import ai_access  # noqa: E402
from paper_daily.desktop.ask import AskRunner  # noqa: E402

reader = _reader
window = _window


@pytest.fixture
def asking(window, monkeypatch):
    win, app = window
    monkeypatch.setattr(ai_access, "_bridge", None)
    monkeypatch.setattr(llm, "available", lambda **kw: True)
    calls = []
    monkeypatch.setattr(
        AskRunner, "start", lambda self, prompt, done, failed, **kw: calls.append(
            (prompt, done, failed)
        )
    )
    return win, app, calls


def _bodies(win, paper_id):
    return [(r["role"], r["body"]) for r in win.data.chat(paper_id)]


def _chat(win, app):
    _settle(win.reader_page.prepare, app)
    return win.reader_page.chat_view._body


def test_an_answer_is_saved_to_the_paper_it_was_asked_about(asking):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    reader._ask("What does A assume?")
    win.open_paper("b")
    calls[0][1]("Answer about A")
    assert _bodies(win, "a") == [("user", "What does A assume?"), ("assistant", "Answer about A")]
    assert _bodies(win, "b") == []
    assert "Answer about A" not in _chat(win, app)
    win.open_paper("a")
    assert "Answer about A" in _chat(win, app)


def test_a_failed_question_is_retryable_and_left_out_of_later_prompts(asking):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    reader._ask("Lost question")
    assert "思考中" in _chat(win, app)
    calls[0][2]("timed out after 900s")
    shown = _chat(win, app)
    assert "思考中" not in shown and "未完成，可重試" in shown
    assert "timed out" in reader.ask_status.text()
    reader._ask("Second question")
    assert "Lost question" not in calls[1][0]
    calls[1][1]("Second answer")
    reader._ask("Third question")
    assert "Second question" in calls[2][0] and "Lost question" not in calls[2][0]


def test_retrying_an_unanswered_question_replaces_it_when_sent(asking):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    reader._ask("Lost question")
    calls[0][2]("unavailable")
    question_id = win.data.chat("a")[0]["id"]
    reader._retry_question(question_id)
    assert reader.ask_box.text() == "Lost question" and not calls[1:]
    reader._ask_from_box(reader.ask_box.text())
    assert _bodies(win, "a") == [("user", "Lost question")]
    assert win.data.chat("a")[0]["id"] != question_id


def test_a_failure_for_a_paper_left_behind_does_not_touch_the_open_one(asking):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    reader._ask("Question on A")
    win.open_paper("b")
    calls[0][2]("HTTP 503: AI request rejected")
    assert "先前論文" in reader.ask_status.text()
    assert reader.ask_btn.isEnabled()
    assert "未完成" not in _chat(win, app)


def test_page_and_passage_context_do_not_follow_the_reader_to_another_paper(asking):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    reader._page_context = ("a", 0, "PAGE TEXT FROM PAPER A")
    reader._ask_selection("A passage that only paper A contains")
    assert not reader.passage_chip.isHidden()
    win.open_paper("b")
    assert reader.passage_chip.isHidden()
    reader._ask_from_box("What is this?")
    prompt = calls[0][0]
    assert "PAGE TEXT FROM PAPER A" not in prompt
    assert "only paper A contains" not in prompt
    assert _bodies(win, "b") == [("user", "What is this?")]


def test_a_page_context_is_used_only_for_its_own_paper(asking):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("b")
    reader._page_context = ("a", 0, "PAGE TEXT FROM PAPER A")
    reader._ask("Explain")
    assert "PAGE TEXT FROM PAPER A" not in calls[0][0]


def _translation_calls(widget, monkeypatch):
    shown, started = [], []
    monkeypatch.setattr(widget.pdf.selection, "show_result",
                        lambda title, text, **kw: shown.append((title, text)))
    for runner in (widget.translate_runner, widget.refine_runner):
        monkeypatch.setattr(runner, "start",
                            lambda prompt, done, failed, **kw: started.append((done, failed)))
    return shown, started


def test_a_translation_for_an_abandoned_selection_is_not_drawn(reader, monkeypatch):
    widget, app, _path = reader
    selection = widget.pdf.selection
    shown, started = _translation_calls(widget, monkeypatch)
    selection.focus(selection.find(0, "Alpha beta"))
    widget._translate_selection("Alpha beta")
    selection.focus(selection.find(1, "gamma evidence"))
    started[0][0]("舊的譯文")
    assert ("Google 翻譯", "舊的譯文") not in shown
    started[0][1]("Google down")
    assert len(started) == 1


def test_a_translation_lands_when_the_selection_is_unchanged(reader, monkeypatch):
    widget, app, _path = reader
    selection = widget.pdf.selection
    shown, started = _translation_calls(widget, monkeypatch)
    selection.focus(selection.find(0, "Alpha beta"))
    widget._translate_selection("Alpha beta")
    started[0][1]("Google down")
    started[1][0]("AI 譯文")
    assert shown[-1] == ("AI 精譯", "AI 譯文")


def test_a_refined_translation_is_dropped_after_switching_paper(reader, monkeypatch):
    from types import SimpleNamespace

    widget, app, path = reader
    selection = widget.pdf.selection
    shown, started = _translation_calls(widget, monkeypatch)
    selection.focus(selection.find(0, "Alpha beta"))
    widget._translate_with_model("Alpha beta")
    widget.paper = SimpleNamespace(id="another:paper", pdf_path=path)
    started[0][0]("AI 譯文")
    assert ("AI 精譯", "AI 譯文") not in shown


def test_prepared_highlights_are_not_analysed_again_on_open(reader, monkeypatch):
    from paper_daily import paper_highlights

    widget, app, _path = reader
    pane = widget.presentation_pane
    pane.paper_id = widget.paper.id
    monkeypatch.setattr(paper_highlights, "is_prepared", lambda conn, pid: True)
    monkeypatch.setattr(pane, "_analyze_highlights",
                        lambda **kw: pytest.fail("prepared paper re-analysed"))
    widget._prepare_reading_highlights()


def test_cached_analysis_does_not_claim_the_ai_is_reading_the_paper(reader, monkeypatch):
    from paper_daily import paper_highlights

    widget, app, _path = reader
    pane = widget.presentation_pane
    pane.paper_id = widget.paper.id
    monkeypatch.setattr(paper_highlights, "is_prepared", lambda conn, pid: False)
    monkeypatch.setattr(paper_highlights, "cached", lambda *a: {"items": []})

    def start(**kw):
        pane._highlight_status("AI 正在讀取原文、比較研究重要性並核對引句；舊結果暫時保留。")
        pane._highlights_busy = True

    monkeypatch.setattr(pane, "_analyze_highlights", start)
    widget._prepare_reading_highlights()
    assert "AI 正在讀取原文" not in widget.highlight_status.text()
    assert "沿用" in widget.highlight_status.text()
    pane._highlights_busy = False


def test_missing_ai_prompts_for_login_once_per_session(reader, monkeypatch):
    from types import SimpleNamespace

    from paper_daily import paper_highlights

    widget, app, path = reader
    pane = widget.presentation_pane
    monkeypatch.setattr(paper_highlights, "is_prepared", lambda conn, pid: False)
    monkeypatch.setattr(paper_highlights, "cached", lambda *a: None)
    monkeypatch.setattr(llm, "available", lambda **kw: False)
    prompts = []
    monkeypatch.setattr(ai_access, "login", lambda *a: prompts.append(a))
    for pid in ("test:paper", "test:other", "test:third"):
        widget.paper = SimpleNamespace(id=pid, pdf_path=path)
        pane.paper_id = pid
        widget._prepare_reading_highlights()
        widget._prepare_reading_highlights()
    assert len(prompts) == 1
    assert "AI 設定" in widget.highlight_status.text()
    widget.prepare_highlights.click()
    assert len(prompts) == 2
