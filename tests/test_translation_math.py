"""A translation prompt must match the existing plain-text overlay renderer."""

from test_managed_reader_ui import wait_for
from test_translation_scope import translating as _translating
from test_translation_scope import workspace as _workspace

from paper_daily import llm

translating = _translating
workspace = _workspace
INSTRUCTION = (
    "把下面這段論文原文翻成繁體中文。技術名詞、模型名稱、資料集名稱保留英文,"
    "數學用 Unicode 純文字,絕不使用 LaTeX。只輸出譯文,不要前言。\n\n"
)


def test_actual_model_call_preserves_unicode_math_text_cfg_and_timeout(translating, monkeypatch):
    t = translating
    selected = t.selection.selected_text()
    seen = []

    def model(prompt, **kwargs):
        seen.append((prompt, kwargs))
        return "x\u00b2 \u2264 y", "ok"

    monkeypatch.setattr(llm, "complete", model)
    monkeypatch.setattr(t.w.widget.refine_runner, "start", t.real_starts[1])
    t.w.widget._translate_with_model(selected)
    wait_for(t.w.app, lambda: not t.w.widget.refine_runner.busy)
    assert len(seen) == 1
    prompt, options = seen[0]
    assert prompt == INSTRUCTION + selected
    assert prompt.endswith("\n\n" + selected)
    assert "Unicode" in prompt and "\u7d55\u4e0d\u4f7f\u7528 LaTeX" in prompt
    assert options["cfg"] is t.cfg
    assert options["timeout"] == 300 and options["task"] == "translate"
    assert t.selection.result.body.text() == "x\u00b2 \u2264 y"
