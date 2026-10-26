"""Progress describes the captured request, not mutable UI or returned-model guesses."""

from dataclasses import replace

import pytest

from paper_daily import feedback, llm, usage_cache
from paper_daily.ai_types import Completion, Settings
from paper_daily.work_progress import observe


@pytest.fixture
def calls(monkeypatch, tmp_path):
    result = []

    class Provider:
        def complete(self, request, cfg, post):
            result.append((request, cfg))
            return Completion("fixture answer", model="reported-model")

    providers = {key: Provider() for key in (*llm._PROVIDERS, "custom-service")}
    monkeypatch.setattr(llm, "_PROVIDERS", providers)
    monkeypatch.setattr(llm, "ACCESS_CHECK", None)
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(llm, "_stored", lambda: pytest.fail("Progress reread current settings"))
    monkeypatch.setattr(llm, "_record", lambda *args: None)
    monkeypatch.setattr(feedback, "safe_record", lambda *args, **kwargs: None)
    monkeypatch.setattr(usage_cache, "invalidate", lambda _cfg: None)
    return result


@pytest.mark.parametrize(
    "backend,brand",
    [
        ("cli", "Claude"),
        ("codex", "Codex"),
        ("gemini", "Gemini"),
        ("custom-service", "custom-service"),
    ],
)
def test_service_default_is_readable_and_not_a_claim_of_actual_model(calls, backend, brand):
    events = []
    cfg = Settings(backend)
    with observe(events.append):
        reply = llm.complete_result("private fixture prompt", cfg=cfg, task="ask")
    assert events[0]["stage"] == f"等待 {brand} / 服務預設模型（未指定） 回覆"
    assert "None" not in events[0]["stage"]
    assert "reported-model" not in events[0]["stage"]
    assert reply.model == "reported-model"
    assert calls[0][1] == cfg


@pytest.mark.parametrize(
    "backend,brand,model",
    [
        ("cli", "Claude", "fable"),
        ("codex", "Codex", "chosen-codex"),
        ("gemini", "Gemini", "chosen-gemini"),
        ("custom-service", "custom-service", "local-model"),
        ("gateway", "AI 閘道", "gateway-model"),
    ],
)
def test_explicit_requested_model_reaches_provider_and_progress_unchanged(
    calls, backend, brand, model
):
    events = []
    cfg = Settings(
        backend,
        model=model,
        api_key="private-fixture-secret",
        profile="private-profile",
        account_id="private-account",
    )
    with observe(events.append):
        llm.complete_result("private fixture prompt", cfg=cfg, task="slides")
    assert events[0]["stage"] == f"等待 {brand} / 指定模型：{model} 回覆"
    assert calls[0][0].task == "slides"
    assert calls[0][1] == cfg
    assert all("private-" not in event["stage"] for event in events)


@pytest.mark.parametrize(
    "backend,brand", [("anthropic", "Anthropic"), ("openai", "OpenAI 相容服務")]
)
def test_known_api_default_names_the_request_model(calls, backend, brand):
    cfg = Settings(backend)
    events = []
    with observe(events.append):
        llm.complete_result("fixture", cfg=cfg)
    assert events[0]["stage"] == f"等待 {brand} / 預設模型：{cfg.effective_model} 回覆"
    assert calls[0][1] == cfg


def test_label_and_dispatch_stay_on_captured_cfg_when_current_choice_changes(calls, monkeypatch):
    captured = Settings("cli", model="fable")
    events = []
    monkeypatch.setattr(
        llm, "settings", lambda **kw: replace(captured, backend="gemini", model="new")
    )
    with observe(events.append):
        llm.complete_result("fixture", cfg=captured)
    assert events[0]["stage"] == "等待 Claude / 指定模型：fable 回覆"
    assert calls[0][1] == captured


def test_captured_task_override_drives_both_label_and_dispatch(calls, tmp_path):
    snapshot = (
        {
            "active_profile": "global",
            "prefer_saved_profiles": True,
            "profiles": {
                "global": {"backend": "codex", "model": "global-model", "isolated": True},
                "qa": {"backend": "cli", "model": "fable", "isolated": True},
            },
            "routes": {"ask": "qa"},
            "route_models": {"ask": "opus"},
        },
        {},
        tmp_path,
    )
    events = []
    with llm.connection_scope(snapshot), observe(events.append):
        llm.complete_result("fixture", task="ask")
    assert events[0]["stage"] == "等待 Claude / 指定模型：opus 回覆"
    assert (calls[0][1].backend, calls[0][1].model, calls[0][1].profile) == ("cli", "opus", "qa")
