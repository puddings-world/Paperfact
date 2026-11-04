import json
import os
from contextlib import nullcontext

import pytest
from PySide6.QtWidgets import QApplication

from paper_daily import paper_highlights
from paper_daily import research_questions as rq
from paper_daily.ai_types import Completion
from paper_daily.desktop.ask import AskRunner
from paper_daily.desktop.research_questions import ResearchQuestions

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QUOTE = "The sparse mechanism reduces memory but assumes independent observations."
ITEM = {"question": "獨立觀測假設如何限制稀疏機制？", "why": "判斷適用範圍。", "evidence": QUOTE}


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr(rq, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(paper_highlights, "_reading_lock", lambda pid: nullcontext())
    source = {"pages": [{"page": 3, "text": QUOTE}], "explanation": "講解", "close_reading": "精讀"}
    monkeypatch.setattr(rq, "context", lambda pid: source)
    calls = []

    def complete(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return Completion(json.dumps({"questions": [ITEM]}))

    monkeypatch.setattr(rq.llm, "complete_result", complete)
    return source, calls


def test_questions_use_full_analysis_and_cache_without_repeated_calls(context):
    source, calls = context
    value, _ = rq.ensure("p")
    assert value["items"][0]["page"] == 3
    assert json.loads(calls[0][0]) == source and calls[0][1]["task"] == "ask"
    assert rq.ensure("p")[0] == value and len(calls) == 1
    source["close_reading"] = "更新後的精讀"
    assert rq.ensure("p")[0]["items"] and len(calls) == 2


@pytest.mark.parametrize(
    "items",
    [
        [],
        [{**ITEM, "evidence": "fabricated evidence is not in this paper"}],
        [{**ITEM, "why": ""}],
        ["invalid"],
    ],
)
def test_ungrounded_or_malformed_questions_are_rejected(items):
    with pytest.raises(ValueError):
        rq.validate(items, [{"page": 3, "text": QUOTE}])


def test_failed_auto_generation_is_not_retried_on_every_open(context, monkeypatch):
    calls = []
    monkeypatch.setattr(
        rq.llm,
        "complete_result",
        lambda *a, **kw: calls.append(1) or Completion(None, "unavailable"),
    )
    assert rq.ensure("p") == (None, "unavailable")
    assert rq.ensure("p") == (None, "unavailable") and len(calls) == 1
    rq.ensure("p", force=True)
    assert len(calls) == 2


def test_failed_refresh_preserves_saved_questions_and_does_not_loop(context, monkeypatch):
    source, _calls = context
    old = rq.ensure("p")[0]
    source["explanation"] = "changed"
    calls = []
    monkeypatch.setattr(
        rq.llm,
        "complete_result",
        lambda *a, **kw: calls.append(1) or Completion(None, "unavailable"),
    )
    assert rq.ensure("p")[0] is None
    assert rq.cached("p")["items"] == old["items"]
    assert rq.ensure("p")[0] is None and len(calls) == 1


def test_missing_full_analysis_does_not_call_model(context, monkeypatch):
    _source, calls = context
    monkeypatch.setattr(rq, "context", lambda pid: None)
    assert rq.ensure("p")[0] is None and not calls


def test_question_choice_drafts_only_and_source_points_into_original(context, monkeypatch):
    app = QApplication.instance() or QApplication([])
    rq.ensure("p")
    widget = ResearchQuestions()
    chosen, sources = [], []
    widget.chosen.connect(chosen.append)
    widget.source_requested.connect(sources.append)
    widget.load("p")
    widget.insert.click()
    widget.source.click()
    assert chosen == [ITEM["question"]]
    assert sources == [{"kind": "original", "page": 3, "text": QUOTE}]
    assert not widget.runner.busy
    widget.deleteLater()
    app.processEvents()


def test_late_questions_cannot_replace_a_different_paper(context, monkeypatch):
    app = QApplication.instance() or QApplication([])
    callbacks = []
    monkeypatch.setattr(AskRunner, "start", lambda self, *args, **kw: callbacks.append(args[1]))
    widget = ResearchQuestions()
    widget.load("a")
    widget.generate()
    widget.load("b")
    callbacks[0](json.dumps({"items": [{**ITEM, "page": 3}]}))
    assert widget.picker.count() == 0 and widget.paper_id == "b"
    widget.deleteLater()
    app.processEvents()


def test_showing_the_tab_or_switching_papers_starts_no_ai(tmp_path, monkeypatch):
    """Showing the tab started an AI job by itself: a model call nobody asked for, and
    a failed job in the tray on every paper not yet analysed."""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(rq, "CACHE_DIR", tmp_path)
    started = []
    monkeypatch.setattr(AskRunner, "start", lambda self, *a, **k: started.append(a))
    widget = ResearchQuestions()
    widget.load("a")
    widget.show()
    widget.load("b")
    for _ in range(5):
        app.processEvents()
    assert started == []
    assert "AI 更新建議" in widget.status.text()
    widget.refresh_button.click()  # Asking for it is what starts the job.
    assert len(started) == 1
    widget.deleteLater()
    app.processEvents()


def test_asking_before_the_paper_is_analysed_says_what_to_do_first(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(rq, "CACHE_DIR", tmp_path)

    def refuse(pid, force=False):
        raise ValueError("Complete the deep explanation and close reading first")

    monkeypatch.setattr(rq, "ensure", refuse)

    def run_now(self, prompt, done, fail, call=None, **kwargs):
        answer, reason = call(prompt)
        return done(answer) if answer else fail(reason)

    monkeypatch.setattr(AskRunner, "start", run_now)
    widget = ResearchQuestions()
    widget.load("a")
    widget.refresh_button.click()
    assert "先完成深入分析" in widget.status.text()
    assert "ValueError" not in widget.status.text()
    widget.deleteLater()
    app.processEvents()
