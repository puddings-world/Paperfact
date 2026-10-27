"""A personal Gemini account connects with an AI Studio key, not the retired CLI login."""

import pytest
from PySide6.QtWidgets import QInputDialog
from test_ai_picker import picker as _picker

from paper_daily import ai_choices, ai_providers, llm
from paper_daily.desktop.ai_dialog import AIStatusButton

picker = _picker
MODELS = ["models/gemini-3-flash", "models/gemini-4-argon", "models/gemini-4-argon-preview"]


@pytest.fixture
def listed(monkeypatch):
    seen = []

    def list_models(cfg):
        seen.append(cfg)
        return (
            (MODELS, "ok") if cfg.api_key == "AIza-good" else ([], "無法取得模型清單（HTTP 400）")
        )

    monkeypatch.setattr(ai_providers, "list_models", list_models)
    return seen


def test_gemini_asks_for_a_key_and_cannot_be_used_without_one(picker, listed):
    widget, _app = picker
    before = llm.SETTINGS_PATH.read_bytes()
    widget.providers["gemini"].click()
    assert widget.login_button.text() == "輸入 API 金鑰…"
    assert "aistudio.google.com" in widget.account_status.text()
    assert "訂閱額度不適用" in widget.model_hint.text()
    widget.use_button.click()
    assert widget.notice.text() == "請先輸入 API 金鑰。"
    assert llm.SETTINGS_PATH.read_bytes() == before and not listed


def test_entering_a_key_lists_models_and_using_it_switches_the_default(picker, listed, monkeypatch):
    widget, _app = picker
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (" AIza-good ", True))
    widget.providers["gemini"].click()
    widget.login_button.click()
    saved = llm.settings(profile=ai_choices.GEMINI_API_PROFILE)
    assert saved.backend == "openai" and saved.api_key == "AIza-good"
    assert saved.base_url == ai_choices.GEMINI_API_URL
    # Saving the key does not switch the default; "use" does.
    assert llm.settings().profile == "old"
    assert widget.login_button.text() == "更換 API 金鑰…"
    assert widget._model() == "models/gemini-4-argon"
    assert widget.model.findData("") < 0
    widget.use_button.click()
    active = llm.settings()
    assert active.profile == ai_choices.GEMINI_API_PROFILE
    assert active.model == "models/gemini-4-argon"
    assert AIStatusButton().text().startswith("全域 AI：Gemini")


def test_a_rejected_key_says_why_and_is_not_used(picker, listed, monkeypatch):
    widget, _app = picker
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("AIza-bad", True))
    widget.providers["gemini"].click()
    widget.login_button.click()
    assert "HTTP 400" in widget.account_status.text()
    widget.use_button.click()
    assert widget.notice.text() == "請選擇要使用的模型。"
    assert llm.settings().profile == "old"


def test_replacing_a_key_keeps_the_connection_and_its_assignments(picker, listed):
    first = ai_choices.save_gemini_key("AIza-old", "models/gemini-3-flash")
    llm.use_profile(first.profile, task="slides")
    second = ai_choices.save_gemini_key("AIza-good", "", profile=first.profile)
    assert second.profile == first.profile and second.api_key == "AIza-good"
    assert llm.settings(task="slides").api_key == "AIza-good"
    with pytest.raises(ValueError):
        ai_choices.save_gemini_key("  ", "")


def test_a_workspace_cli_login_is_still_offered_after_the_key(picker):
    llm.save_settings(profile="work-gemini", backend="gemini", isolated=True)
    options = ai_choices.choices("gemini")
    assert ai_choices.is_gemini_api(options[0]) and not options[0].api_key
    assert [cfg.profile for cfg in options[1:]] == ["work-gemini"]
