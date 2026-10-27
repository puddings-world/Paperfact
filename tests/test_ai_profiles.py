"""Profile isolation, legacy migration, and explicit task selection."""

import json
import os

import pytest

from paper_daily import llm
from paper_daily.cli import build_parser, cmd_llm


@pytest.fixture
def clean(monkeypatch, tmp_path):
    for key in list(os.environ):
        if key.startswith(("PAPERFACT_", "PAPER_DAILY_")) or key in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "MY_GATEWAY_TOKEN",
        ):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(llm.shutil, "which", lambda _name: None)
    return llm.SETTINGS_PATH


def test_legacy_profile_migration_preserves_the_original_connection(clean):
    legacy = {"backend": "anthropic", "api_key": "old-secret", "model": "original"}
    clean.write_text(json.dumps(legacy), encoding="utf-8")
    llm.save_settings(
        profile="local",
        backend="openai",
        model="local-model",
        base_url="http://localhost:11434/v1",
        requires_key=False,
    )
    data = json.loads(clean.read_text(encoding="utf-8"))
    assert data["profiles"]["default"] == legacy
    assert data["active_profile"] == "default"
    assert llm.settings().api_key == "old-secret"
    llm.use_profile("local")
    cfg = llm.settings()
    assert cfg.profile == "local" and cfg.model == "local-model"
    assert cfg.api_key is None and not cfg.requires_key


def test_backend_switch_drops_previous_credentials_endpoint_and_model(clean):
    llm.save_settings(
        profile="one",
        backend="anthropic",
        api_key="old-secret",
        model="old-model",
        base_url="https://old.example",
    )
    llm.save_settings(profile="one", backend="openai")
    cfg = llm.settings()
    assert cfg.backend == "openai"
    assert cfg.api_key is None and cfg.base_url is None and cfg.model is None


def test_endpoint_switch_does_not_forward_a_stored_key(clean):
    llm.save_settings(
        profile="one",
        backend="openai",
        api_key="old-secret",
        api_key_env="MY_GATEWAY_TOKEN",
        base_url="https://old.example/v1",
    )
    llm.save_settings(profile="one", base_url="https://new.example/v1")
    raw = json.loads(clean.read_text(encoding="utf-8"))["profiles"]["one"]
    assert "api_key" not in raw and "api_key_env" not in raw


def test_env_backend_override_cannot_reuse_another_vendors_configuration(clean, monkeypatch):
    llm.save_settings(
        backend="anthropic", api_key="old-secret", base_url="https://old.example", model="old-model"
    )
    monkeypatch.setenv("PAPERFACT_LLM", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "new-secret")
    cfg = llm.settings()
    assert cfg.api_key == "new-secret" and cfg.model is None and cfg.base_url is None


def test_task_routes_do_not_change_default_and_can_follow_it_again(clean):
    llm.save_settings(profile="main", backend="cli")
    llm.save_settings(profile="fast", backend="openai", model="small", requires_key=False)
    llm.use_profile("fast", task="translate")
    assert llm.settings().profile == "main"
    assert llm.settings(task="translate").profile == "fast"
    llm.clear_route("translate")
    assert llm.settings(task="translate").profile == "main"


def test_new_environment_names_win_and_an_explicit_profile_can_override_them(clean, monkeypatch):
    llm.save_settings(profile="one", backend="cli")
    llm.save_settings(profile="two", backend="openai", requires_key=False)
    monkeypatch.setenv("PAPER_DAILY_PROFILE", "one")
    monkeypatch.setenv("PAPERFACT_PROFILE", "two")
    assert llm.settings().profile == "two"
    assert llm.settings(profile="one").profile == "one"


def test_gateway_uses_its_own_token_not_a_vendor_key(clean, monkeypatch):
    llm.save_settings(
        profile="service",
        backend="gateway",
        model="research",
        base_url="https://service.example/v1",
        api_key_env="MY_GATEWAY_TOKEN",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "vendor-secret")
    assert llm.settings().api_key is None
    monkeypatch.setenv("MY_GATEWAY_TOKEN", "account-token")
    cfg = llm.settings()
    assert cfg.api_key == "account-token"
    assert "account-token" not in repr(cfg)
    assert "api_key" not in llm.profile_fields("service")


def test_unknown_profile_fails_instead_of_sending_to_a_default(clean, monkeypatch):
    llm.save_settings(profile="one", backend="cli")
    monkeypatch.setenv("PAPERFACT_PROFILE", "missing")
    result = llm.complete_result("private paper")
    assert result.text is None and "Unknown AI profile" in result.reason


def test_bad_json_is_not_silently_overwritten(clean):
    clean.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        llm.save_settings(profile="one", backend="cli")
    assert clean.read_text(encoding="utf-8") == "{broken"


@pytest.mark.parametrize(
    "fields",
    [
        {"max_tokens": 0},
        {"max_tokens": True},
        {"token_parameter": "arbitrary"},
        {"api_key_env": "not a variable"},
        {"requires_key": "false"},
    ],
)
def test_invalid_settings_are_rejected_before_writing(clean, fields):
    with pytest.raises(ValueError):
        llm.save_settings(profile="one", backend="openai", **fields)
    assert not clean.exists()


def test_cli_creates_selects_and_routes_profiles_without_touching_the_paper_db(clean, capsys):
    parser = build_parser()
    assert (
        cmd_llm(
            parser.parse_args(
                [
                    "llm",
                    "--profile",
                    "local",
                    "--backend",
                    "openai",
                    "--model",
                    "local-model",
                    "--base-url",
                    "http://localhost:11434/v1",
                    "--no-requires-key",
                ]
            )
        )
        == 0
    )
    assert cmd_llm(parser.parse_args(["llm", "--use", "local", "--for-task", "ask"])) == 0
    assert llm.settings(task="ask").profile == "local"
    assert cmd_llm(parser.parse_args(["llm", "--for-task", "ask", "--follow-default"])) == 0
    assert llm.task_routes() == {}
    assert cmd_llm(parser.parse_args(["llm", "--list"])) == 0
    assert "local-model" in capsys.readouterr().out


def test_ai_can_be_disabled_without_removing_the_saved_profiles(clean):
    llm.save_settings(profile="main", backend="cli")
    llm.save_settings(profile="disabled", backend="none")
    llm.use_profile("disabled")
    assert not llm.available()
    assert llm.complete_result("paper").text is None
    llm.use_profile("main")
    assert llm.available()


def test_auto_backend_asks_for_the_claude_cli_at_most_every_30_seconds(clean, monkeypatch):
    # Settings are read several times a second while the window is open; walking PATH
    # each time froze it on Windows.
    calls = []
    monkeypatch.setattr(llm.shutil, "which", lambda name: calls.append(name) or "/bin/claude")
    llm.save_settings(profile="default", backend="auto")
    assert llm.settings().backend == "cli"
    assert llm.settings().backend == "cli"
    assert calls == ["claude"]
    monkeypatch.setenv("PATH", os.environ.get("PATH", "") + os.pathsep + "elsewhere")
    llm.settings()
    assert calls == ["claude", "claude"]
    from paper_daily import ai_profiles

    monkeypatch.setattr(ai_profiles, "CLAUDE_RECHECK", -1.0)
    monkeypatch.setattr(llm.shutil, "which", lambda name: calls.append(name))
    assert llm.settings().backend == "none"
