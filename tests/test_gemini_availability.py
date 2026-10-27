"""Saved credentials and model names do not promise consumer CLI access."""

import pytest

from paper_daily import ai_choices, ai_usage, gemini_cli
from paper_daily.llm import Settings


@pytest.mark.parametrize("model", ["", "gemini-2.5-pro", "custom-model"])
def test_gemini_picker_explains_consumer_access_even_for_default(model):
    hint = ai_choices.model_hint("gemini", model)
    assert "個人 Google 帳號已無法使用 Gemini CLI" in hint
    # The way forward is named, now that personal accounts connect with a key.
    assert "API 金鑰" in hint
    assert "不代表帳號已獲授權" in hint


def test_working_quota_response_is_not_treated_as_consumer_rejection(monkeypatch):
    monkeypatch.setattr(gemini_cli, "usage", lambda cfg: {
        "plan": "Licensed account",
        "buckets": [{"modelId": "example-model", "remainingFraction": 0.5}],
    })
    result = ai_usage.subscription(Settings("gemini"))
    assert result["plan"] == "Licensed account"
    assert result["windows"][0]["used"] == 50
    assert "服務已停止" not in result["message"]
