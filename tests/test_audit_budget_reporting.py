"""AI disclosures distinguish configured intent from provider-reported facts."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_daily import ai_accounts, gemini_cli, llm
from paper_daily.ai_types import Settings
from paper_daily.desktop.source_fact_dialog import TEXT


@pytest.fixture(autouse=True)
def actual_candidate_source():
    expected = Path(__file__).resolve().parents[1] / "src/paper_daily"
    assert Path(gemini_cli.__file__).resolve() == expected / "gemini_cli.py"
    assert Path(llm.__file__).resolve() == expected / "llm.py"


@pytest.mark.parametrize("model", [None, "requested-alias"])
def test_gemini_cli_without_reported_identity_never_reports_requested_alias(
    tmp_path, monkeypatch, model
):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "ai.json")
    monkeypatch.setattr(llm, "ACCESS_CHECK", None)
    monkeypatch.setattr(gemini_cli, "status", lambda cfg: (True, "fixture"))
    monkeypatch.setattr(gemini_cli, "prepare_workspace", lambda folder: None)
    monkeypatch.setattr(ai_accounts, "command", lambda backend: ["fixture-gemini"])
    monkeypatch.setattr(ai_accounts, "environment", lambda cfg: {})
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(
            returncode=0, stdout=json.dumps({"response": "Fixture answer"}), stderr=""
        )

    monkeypatch.setattr(gemini_cli.subprocess, "run", run)
    reply = llm.complete_result(
        "Fixture prompt", cfg=Settings("gemini", model=model), task="audit", max_tokens=4000
    )
    assert reply.text == "Fixture answer" and reply.model == model
    assert reply.reported_model is None
    assert len(calls) == 1
    if model:
        assert calls[0][0][-2:] == ["--model", model]


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_audit_output_budget_copy_is_a_setting_with_service_controlled_limits(language):
    text = TEXT[language]["budget"].format(tokens=4000)
    assert "4000" in text
    if language == "en":
        assert "budget setting" in text.lower() and "AI service" in text
        assert "output cap" not in text.lower()
    else:
        assert "\u9810\u7b97\u8a2d\u5b9a" in text and "\u5be6\u969b" in text
