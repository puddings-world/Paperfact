"""User-selected accounts stay isolated through login, switching and long jobs."""

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_daily import ai_accounts, llm
from paper_daily.ai_types import Settings


@pytest.fixture
def clean(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith(("PAPERFACT_", "PAPER_DAILY_", "ANTHROPIC_", "OPENAI_")):
            monkeypatch.delenv(key)
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    return tmp_path


def test_desktop_selection_wins_over_environment_but_keeps_task_routes(clean, monkeypatch):
    for name in ("a", "b", "c"):
        llm.save_settings(profile=name, backend="openai", model=name, isolated=True)
    monkeypatch.setenv("PAPERFACT_PROFILE", "c")
    monkeypatch.setenv("PAPERFACT_MODEL", "unwanted-model")
    monkeypatch.setenv("PAPERFACT_LLM", "anthropic")
    llm.use_profile("a", desktop=True)
    llm.use_profile("b", task="slides", desktop=True)
    assert llm.settings().profile == "a"
    assert llm.settings(task="slides").model == "b"
    assert llm.settings(task="slides").backend == "openai"


def test_api_accounts_do_not_inherit_a_different_key_or_endpoint(clean, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "another-person")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unwanted.example/v1")
    llm.save_settings(profile="mine", backend="openai", api_key="mine", isolated=True)
    cfg = llm.settings()
    assert cfg.api_key == "mine" and cfg.base_url is None
    llm.save_settings(profile="empty", backend="openai", isolated=True)
    assert llm.settings(profile="empty").api_key is None


def test_explicit_environment_key_never_falls_back_to_a_stored_account(clean, monkeypatch):
    llm.save_settings(
        profile="mine", backend="openai", api_key="old", api_key_env="MY_KEY", isolated=True
    )
    monkeypatch.delenv("MY_KEY", raising=False)
    assert llm.settings().api_key is None
    monkeypatch.setenv("MY_KEY", "new")
    assert llm.settings().api_key == "new"


def test_job_keeps_routes_models_and_credentials_until_the_next_job(clean, monkeypatch):
    llm.save_settings(
        profile="a", backend="openai", model="before", api_key_env="MY_KEY", isolated=True
    )
    llm.save_settings(profile="b", backend="openai", model="other", isolated=True)
    monkeypatch.setenv("MY_KEY", "before-key")
    with llm.connection_scope():
        llm.use_profile("b", desktop=True)
        llm.save_settings(profile="a", model="after")
        monkeypatch.setenv("MY_KEY", "after-key")
        assert llm.settings().model == "before"
        assert llm.settings().api_key == "before-key"
        with llm.connection_scope():
            assert llm.settings().model == "before"
    assert llm.settings().model == "other"


def test_snapshot_restores_after_failure(clean):
    llm.save_settings(profile="a", backend="cli")
    with pytest.raises(RuntimeError), llm.connection_scope():
        llm.save_settings(profile="b", backend="codex")
        llm.use_profile("b")
        raise RuntimeError("job failed")
    assert llm.settings().profile == "b"


def test_bad_ai_config_does_not_prevent_a_non_ai_job(clean):
    llm.SETTINGS_PATH.write_text("{broken")
    with llm.connection_scope():
        result = "local work finished"
        with pytest.raises(ValueError, match="invalid JSON"):
            llm.settings()
    assert result == "local work finished"


def test_invalid_route_does_not_partially_replace_working_routes(clean):
    llm.save_settings(profile="a", backend="cli")
    llm.save_routes({"ask": "a"})
    before = llm.SETTINGS_PATH.read_bytes()
    with pytest.raises(ValueError, match="Unknown AI profile"):
        llm.save_routes({"slides": "a", "ask": "missing"})
    assert llm.SETTINGS_PATH.read_bytes() == before


def test_accounts_have_distinct_homes_and_no_inherited_auth(clean, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "other-person")
    monkeypatch.setenv("CODEX_ACCESS_TOKEN", "other-token")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "other-home")
    for name, account in (("a", "a" * 32), ("b", "b" * 32)):
        llm.save_settings(profile=name, backend="cli", account_id=account, isolated=True)
    env_a = ai_accounts.environment(llm.settings(profile="a"))
    env_b = ai_accounts.environment(llm.settings(profile="b"))
    assert env_a["CLAUDE_CONFIG_DIR"] != env_b["CLAUDE_CONFIG_DIR"]
    assert "ANTHROPIC_API_KEY" not in env_a and "CODEX_ACCESS_TOKEN" not in env_b
    assert os.environ["ANTHROPIC_API_KEY"] == "other-person"


def test_account_path_traversal_is_rejected(clean):
    with pytest.raises(ValueError, match="account ID"):
        llm.save_settings(profile="a", backend="cli", account_id="../../outside")


@pytest.mark.parametrize("account", [123, [], False])
def test_invalid_account_types_are_rejected_without_overwriting_settings(clean, account):
    llm.save_settings(profile="a", backend="cli")
    before = llm.SETTINGS_PATH.read_bytes()
    with pytest.raises(ValueError, match="account ID"):
        llm.save_settings(profile="a", account_id=account)
    assert llm.SETTINGS_PATH.read_bytes() == before


@pytest.mark.parametrize("backend", ["cli", "codex"])
def test_login_uses_official_cli_and_the_selected_isolated_account(clean, monkeypatch, backend):
    llm.save_settings(profile="a", backend=backend, account_id="a" * 32, isolated=True)
    cfg = llm.settings()
    monkeypatch.setattr(ai_accounts, "command", lambda _backend: ["official-cli"])
    seen = {}

    def run(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return SimpleNamespace(returncode=0, stdout="never-display-token", stderr="")

    monkeypatch.setattr(ai_accounts.subprocess, "run", run)
    text, _ = ai_accounts.auth(cfg, "login")
    assert "登入完成" in text and "token" not in text
    key = "CLAUDE_CONFIG_DIR" if backend == "cli" else "CODEX_HOME"
    assert seen["env"][key] == cfg.cli_home
    assert "login" in seen["argv"]
    if backend == "cli":
        assert "--claudeai" in seen["argv"]


def test_logout_cannot_change_the_users_shared_terminal_login(clean, monkeypatch):
    monkeypatch.setattr(
        ai_accounts.subprocess, "run", lambda *a, **k: pytest.fail("must not launch")
    )
    answer, reason = ai_accounts.auth(Settings("cli"), "logout")
    assert answer is None and "獨立帳號" in reason


def test_login_timeout_and_failure_do_not_expose_process_output(clean, monkeypatch):
    monkeypatch.setattr(ai_accounts, "command", lambda _backend: ["claude"])
    cfg = Settings("cli", account_id="a" * 32, cli_home=str(clean / "account"))
    monkeypatch.setattr(
        ai_accounts.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="secret", stderr="secret"),
    )
    assert "secret" not in str(ai_accounts.auth(cfg, "login"))

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired("cli", 240)

    monkeypatch.setattr(ai_accounts.subprocess, "run", timeout)
    assert "逾時" in ai_accounts.auth(cfg, "login")[1]


def test_claude_status_reports_identity_without_tokens(clean, monkeypatch):
    monkeypatch.setattr(ai_accounts, "command", lambda _backend: ["claude"])
    monkeypatch.setattr(
        ai_accounts.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"loggedIn": True, "email": "me@example.org", "token": "secret"}),
            stderr="",
        ),
    )
    answer, _ = ai_accounts.auth(Settings("cli"), "status")
    assert "me@example.org" in answer and "secret" not in answer


def test_codex_completion_uses_final_answer_and_preserves_prompt_and_model(clean, monkeypatch):
    monkeypatch.setattr(ai_accounts, "command", lambda _backend: ["codex"])
    seen = {}

    def run(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        Path(argv[argv.index("--output-last-message") + 1]).write_text(
            "research answer", encoding="utf-8"
        )
        return SimpleNamespace(returncode=0, stdout="events and diagnostics", stderr="")

    monkeypatch.setattr(ai_accounts.subprocess, "run", run)
    cfg = Settings("codex", model="chosen-model", isolated=True)
    result = llm.complete_result("paper text", system="research rules", cfg=cfg)
    assert result.text == "research answer"
    assert "chosen-model" in seen["argv"] and "read-only" in seen["argv"]
    assert "research rules" in seen["input"] and "paper text" in seen["input"]
    assert seen["cwd"] != str(Path.cwd())


def test_failed_codex_does_not_apply_partial_output(clean, monkeypatch):
    monkeypatch.setattr(ai_accounts, "command", lambda _backend: ["codex"])

    def run(argv, **kwargs):
        Path(argv[argv.index("--output-last-message") + 1]).write_text("partial")
        return SimpleNamespace(returncode=1, stdout="secret", stderr="secret")

    monkeypatch.setattr(ai_accounts.subprocess, "run", run)
    result = llm.complete_result("paper", cfg=Settings("codex"))
    assert result.text is None and "secret" not in result.reason
