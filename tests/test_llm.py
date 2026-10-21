"""Backend resolution. No network: what is tested is which backend gets chosen.

This is the part that decides whether a fresh clone on someone else's machine works
at all, and it is pure logic, so it is worth pinning down.
"""

from __future__ import annotations

import json

import pytest

from paper_daily import llm

ENV_KEYS = (
    "PAPER_DAILY_LLM",
    "PAPER_DAILY_MODEL",
    "PAPER_DAILY_BASE_URL",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
)


@pytest.fixture
def clean(monkeypatch, tmp_path):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(llm.shutil, "which", lambda _name: None)
    return tmp_path / "llm.json"


def test_no_backend_is_reported_not_guessed(clean):
    cfg = llm.settings()
    assert cfg.backend == "none"
    body, reason = llm.complete("hello", cfg=cfg)
    assert body is None
    assert "no LLM backend configured" in reason


def test_cli_wins_when_present(clean, monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda _name: "/usr/bin/claude")
    assert llm.settings().backend == "cli"


def test_anthropic_key_is_enough(clean, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cfg = llm.settings()
    assert cfg.backend == "anthropic"
    assert cfg.api_key == "sk-ant-test"
    assert cfg.effective_model == llm.DEFAULT_MODELS["anthropic"]


def test_openai_key_is_the_last_resort(clean, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    # Anthropic first: the dive prompt is written and tuned against Claude.
    assert llm.settings().backend == "anthropic"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert llm.settings().backend == "openai"


def test_env_overrides_the_saved_file(clean, monkeypatch):
    clean.write_text(json.dumps({"backend": "openai", "api_key": "stored"}), encoding="utf-8")
    monkeypatch.setenv("PAPER_DAILY_LLM", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    cfg = llm.settings()
    assert cfg.backend == "anthropic"
    assert cfg.api_key == "from-env"


def test_saved_file_is_used_when_the_env_is_empty(clean):
    clean.write_text(
        json.dumps({"backend": "openai", "api_key": "stored", "model": "local-llama"}),
        encoding="utf-8",
    )
    cfg = llm.settings()
    assert (cfg.backend, cfg.api_key, cfg.model) == ("openai", "stored", "local-llama")


def test_save_settings_keeps_the_other_fields(clean):
    llm.save_settings(backend="openai", api_key="one")
    llm.save_settings(model="gpt-5")
    data = json.loads(clean.read_text(encoding="utf-8"))
    assert data == {"backend": "openai", "api_key": "one", "model": "gpt-5"}


def test_openai_base_url_can_point_at_a_local_server(clean, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "none-needed")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    cfg = llm.settings()
    assert cfg.base_url == "http://localhost:11434/v1"
    assert "localhost:11434" in llm.describe(cfg)


def test_missing_key_does_not_reach_the_network(clean, monkeypatch):
    monkeypatch.setenv("PAPER_DAILY_LLM", "anthropic")
    called = False

    def explode(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("should not POST without a key")

    monkeypatch.setattr(llm, "_post", explode)
    body, reason = llm.complete("hello")
    assert body is None and not called
    assert "ANTHROPIC_API_KEY" in reason


def test_anthropic_request_shape(clean, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    seen = {}

    def fake_post(url, headers, payload, timeout):
        seen.update(url=url, headers=headers, payload=payload, timeout=timeout)
        return {"content": [{"type": "text", "text": "hi"}]}, "ok"

    monkeypatch.setattr(llm, "_post", fake_post)
    body, reason = llm.complete("the pack", system="the rules", timeout=42)
    assert (body, reason) == ("hi", "ok")
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-ant-test"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert seen["payload"]["system"] == "the rules"
    assert seen["payload"]["messages"] == [{"role": "user", "content": "the pack"}]
    assert seen["timeout"] == 42


def test_openai_request_shape_puts_the_system_message_first(clean, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1/")
    seen = {}

    def fake_post(url, headers, payload, timeout):
        seen.update(url=url, payload=payload)
        return {"choices": [{"message": {"content": "hi"}}]}, "ok"

    monkeypatch.setattr(llm, "_post", fake_post)
    body, _ = llm.complete("the pack", system="the rules")
    assert body == "hi"
    # A trailing slash on the base URL must not produce a doubled path.
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert [m["role"] for m in seen["payload"]["messages"]] == ["system", "user"]
