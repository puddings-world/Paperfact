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


def test_one_unverifiable_question_costs_only_itself(context, monkeypatch):
    fabricated = {**ITEM, "question": "另一題？", "evidence": "fabricated evidence is not here"}
    monkeypatch.setattr(
        rq.llm,
        "complete_result",
        lambda *a, **kw: Completion(
            "以下是問題（共 [2] 題）：\n```\n"
            + json.dumps({"questions": [fabricated, ITEM]}, ensure_ascii=False)
            + "\n```"
        ),
    )
    value, _ = rq.ensure("p")
    assert [item["question"] for item in value["items"]] == [ITEM["question"]]


def test_failed_questions_show_their_reason_and_the_retry_button(context, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        rq.llm, "complete_result", lambda *a, **kw: Completion("Sorry, I cannot help.")
    )
    assert rq.ensure("p")[0] is None
    widget = ResearchQuestions()
    widget.load("p")
    text = widget.status.text()
    assert "格式無法解析" in text and "AI 更新建議" in text
    assert "完成深入分析後" not in text
    widget.deleteLater()
    app.processEvents()


def test_a_refresh_that_fails_says_the_previous_questions_were_kept(context, monkeypatch):
    app = QApplication.instance() or QApplication([])
    rq.ensure("p")
    monkeypatch.setattr(
        rq.llm, "complete_result", lambda *a, **kw: Completion(None, "timed out after 240s")
    )
    widget = ResearchQuestions()
    widget.load("p")
    monkeypatch.setattr(
        AskRunner,
        "start",
        lambda self, prompt, done, failed, call=None, **kw: failed(call("")[1]),
    )
    widget.generate(force=True)
    text = widget.status.text()
    assert "保留先前建議" in text and "timed out" in text and "AI 更新建議" in text
    assert widget.picker.count() == 1
    widget.deleteLater()
    app.processEvents()
