"""The picker's third source is any API endpoint; Gemini has no button of its own."""

import pytest
from test_ai_picker import picker as _picker

from paper_daily import ai_choices, ai_profiles, ai_providers, llm
from paper_daily.desktop import ai_dialog
from paper_daily.desktop.ai_access import readiness
from paper_daily.desktop.ai_dialog import AIStatusButton

picker = _picker
MODELS = ["small-model", "large-model"]


@pytest.fixture
def listed(monkeypatch):
    seen = []

    def list_models(cfg):
        seen.append(cfg)
        return (MODELS, "ok") if cfg.api_key != "bad" else ([], "無法取得模型清單（HTTP 400）")

    monkeypatch.setattr(ai_providers, "list_models", list_models)
    return seen


def endpoint(name="lab", **fields):
    values = dict(backend="openai", base_url="https://llm.example.org/v1", api_key="good")
    llm.save_settings(profile=name, **{**values, **fields})


def test_with_no_endpoint_the_button_offers_to_add_one_and_nothing_can_be_used(picker, listed):
    widget, _app = picker
    before = llm.SETTINGS_PATH.read_bytes()
    widget.providers["api"].click()
    assert widget.cfg is None
    assert widget.login_button.text() == "新增 API 端點…"
    assert "尚未新增 API 端點" in widget.account_status.text()
    assert not widget.use_button.isEnabled() and not widget.model_row.isVisible()
    assert llm.SETTINGS_PATH.read_bytes() == before and not listed


def test_adding_an_endpoint_opens_the_connection_form_and_selects_what_it_saved(
    picker, listed, monkeypatch
):
    widget, _app = picker
    opened = []

    class Form:
        def __init__(self, parent):
            opened.append(parent)

        def exec(self):
            endpoint()

    monkeypatch.setattr(ai_dialog, "AISettingsDialog", Form)
    widget.providers["api"].click()
    widget.login_button.click()
    assert opened == [widget]
    assert widget.cfg.profile == "lab" and widget.use_button.isEnabled()
    # Saving an endpoint does not switch the default; "use" does.
    assert llm.settings().profile == "old"
    assert widget._model() == "small-model" and widget.model.findData("") < 0
    assert "訂閱額度不適用" in widget.model_hint.text()
    widget.model.setCurrentIndex(widget.model.findData("large-model"))
    widget.use_button.click()
    active = llm.settings()
    assert (active.profile, active.model) == ("lab", "large-model")
    assert AIStatusButton().text().startswith("全域 AI：API")


def test_every_saved_endpoint_is_listed_whatever_service_it_points_at(picker, listed):
    widget, _app = picker
    endpoint("lab")
    endpoint("claude-key", backend="anthropic", base_url="")
    endpoint("google", base_url="https://generativelanguage.googleapis.com/v1beta/openai")
    widget.providers["api"].click()
    names = {widget.accounts.itemData(i).profile for i in range(widget.accounts.count())}
    assert names == {"lab", "claude-key", "google"}
    assert widget.accounts.isVisible()
    assert {cfg.profile for cfg in ai_choices.accounts() if ai_choices.uses_key(cfg)} == names


def test_an_endpoint_without_its_key_cannot_be_used_and_a_local_one_needs_none(picker, listed):
    widget, _app = picker
    endpoint("keyless", api_key="")
    widget.providers["api"].click()
    assert "尚未輸入金鑰" in widget.account_status.text() and not listed
    widget.use_button.click()
    assert widget.notice.text() == "請先輸入 API 金鑰。"
    endpoint("ollama", base_url="http://localhost:11434/v1", api_key="", requires_key=False)
    widget._select("api", selected="ollama")
    assert widget._model() == "small-model"
    widget.use_button.click()
    assert llm.settings().profile == "ollama"


def test_an_endpoint_that_lists_no_model_says_why_and_is_not_used(picker, listed):
    widget, _app = picker
    endpoint("broken", api_key="bad")
    widget.providers["api"].click()
    assert "HTTP 400" in widget.account_status.text()
    widget.use_button.click()
    assert widget.notice.text() == "請選擇要使用的模型。"
    assert llm.settings().profile == "old"


def test_a_saved_gemini_cli_login_is_retired_and_points_to_agy(picker):
    data = ai_profiles.load(llm.SETTINGS_PATH)
    data.setdefault("profiles", {})["work-gemini"] = {"backend": "gemini", "isolated": True}
    ai_profiles.write(llm.SETTINGS_PATH, data)
    assert ai_choices.choices("api") == []
    retired = llm.settings(profile="work-gemini")
    assert retired.backend == "gemini"
    reply = llm.complete_result("prompt", cfg=retired)
    assert reply.text is None and "agy" in reply.reason and "API 端點" in reply.reason
    assert readiness(retired) == ai_profiles.RETIRED["gemini"]
    with pytest.raises(ValueError, match="2026-06-18"):
        llm.save_settings(profile="new-gemini", backend="gemini", isolated=True)


def test_signing_in_to_a_retired_connection_explains_instead_of_starting_a_cli():
    from paper_daily import ai_accounts
    from paper_daily.ai_types import Settings

    retired = Settings("gemini", isolated=True)
    assert ai_accounts.auth(retired, "status") == (None, ai_profiles.RETIRED["gemini"])
    assert ai_accounts.auth(retired, "login")[0] is None
