"""Requested compatibility models are distinct from provider-reported identities."""

import pytest

from paper_daily import llm
from paper_daily.ai_types import Completion, Settings


@pytest.mark.parametrize("backend", ["openai", "anthropic"])
@pytest.mark.parametrize("model", [None, "actual-version"])
def test_api_reported_model_never_infers_requested_default(tmp_path, monkeypatch, backend, model):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(llm, "ACCESS_CHECK", None)
    payload = (
        {"choices": [{"message": {"content": "answer"}}]}
        if backend == "openai"
        else {"content": [{"type": "text", "text": "answer"}]}
    )
    if model is not None:
        payload["model"] = model
    monkeypatch.setattr(llm, "_post", lambda *args: (payload, "ok"))
    reply = llm.complete_result(
        "fixture", cfg=Settings(backend, model="requested", api_key="fixture")
    )
    assert reply.text == "answer"
    assert reply.model == (model or "requested")
    assert reply.reported_model == model
    assert reply.model_reported is bool(model)


def test_extension_provider_without_model_keeps_reported_identity_unknown(tmp_path, monkeypatch):
    class Provider:
        def complete(self, request, cfg, post):
            return Completion("answer")

    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(llm, "ACCESS_CHECK", None)
    monkeypatch.setitem(llm._PROVIDERS, "openai", Provider())
    reply = llm.complete_result("fixture", cfg=Settings("openai", model="requested"))
    assert reply.model == "requested" and reply.reported_model is None


def test_plain_cli_text_does_not_report_the_requested_model(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from paper_daily import ai_accounts, ai_providers

    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(llm, "ACCESS_CHECK", None)
    monkeypatch.setattr(ai_accounts, "command", lambda backend: ["fixture-cli"])
    monkeypatch.setattr(ai_accounts, "environment", lambda cfg: {})
    monkeypatch.setattr(ai_providers.shutil, "which", lambda command: command)
    monkeypatch.setattr(
        ai_providers.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="fixture answer", stderr=""),
    )
    reply = llm.complete_result("fixture", cfg=Settings("cli", model="requested-alias"))
    assert reply.text == "fixture answer" and reply.model == "requested-alias"
    assert reply.reported_model is None
