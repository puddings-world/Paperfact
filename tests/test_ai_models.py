"""Model discovery uses the selected connection and never changes its model."""

import json
from pathlib import Path

import httpx
import pytest

from paper_daily import ai_providers
from paper_daily.ai_types import Settings


@pytest.mark.parametrize(
    "backend,base,url,key_header",
    [
        ("anthropic", None, "https://api.anthropic.com/v1/models", "x-api-key"),
        ("openai", None, "https://api.openai.com/v1/models", "Authorization"),
        ("gateway", "https://mine.example/v1/", "https://mine.example/v1/models", "Authorization"),
    ],
)
def test_model_list_uses_the_selected_endpoint_and_key(monkeypatch, backend, base, url, key_header):
    seen = {}

    def get(address, **kwargs):
        seen.update(url=address, **kwargs)
        return httpx.Response(
            200,
            json={
                "data": [{"id": "z"}, {"id": "a"}, {"id": "z"}, {"id": None}, "invalid", {"id": ""}]
            },
        )

    monkeypatch.setattr(ai_providers.httpx, "get", get)
    models, reason = ai_providers.list_models(Settings(backend, api_key="selected", base_url=base))
    assert models == ["a", "z"] and reason == "ok"
    assert seen["url"] == url
    assert seen["headers"][key_header].endswith("selected")


def test_local_model_discovery_needs_no_credentials(monkeypatch):
    def get(url, **kwargs):
        assert url == "http://localhost:11434/v1/models"
        assert not kwargs["headers"]
        return httpx.Response(200, json={"data": [{"id": "local-model"}]})

    monkeypatch.setattr(ai_providers.httpx, "get", get)
    models, _ = ai_providers.list_models(
        Settings("openai", base_url="http://localhost:11434/v1", requires_key=False)
    )
    assert models == ["local-model"]


@pytest.mark.parametrize("base", ["http://remote.example/v1", "https://user:secret@host/v1"])
def test_invalid_endpoint_never_receives_credentials(monkeypatch, base):
    monkeypatch.setattr(ai_providers.httpx, "get", lambda *a, **k: pytest.fail("must not request"))
    models, reason = ai_providers.list_models(Settings("openai", base_url=base, api_key="secret"))
    assert not models and "secret" not in reason


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, text="secret"),
        httpx.Response(200, text="secret"),
        httpx.Response(200, json={"data": "secret"}),
        httpx.Response(200, json=[]),
    ],
)
def test_bad_model_responses_are_safe_and_allow_manual_entry(monkeypatch, response):
    monkeypatch.setattr(ai_providers.httpx, "get", lambda *a, **k: response)
    models, reason = ai_providers.list_models(Settings("openai", api_key="secret"))
    assert not models and "secret" not in reason and "ID" in reason


def test_missing_key_does_not_call_service(monkeypatch):
    monkeypatch.setattr(ai_providers.httpx, "get", lambda *a, **k: pytest.fail("must not request"))
    models, reason = ai_providers.list_models(Settings("openai"))
    assert not models and "金鑰" in reason


def test_codex_model_choices_come_from_official_service(monkeypatch):
    from paper_daily import ai_accounts, cli_rpc

    calls = []

    class Client:
        def __init__(self, argv, **kwargs):
            assert argv == ["official-codex", "app-server"]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send(self, message):
            calls.append(message["method"])

        def request(self, method, params):
            calls.append(method)
            return {"data": [{"model": "available"}, {"model": "hidden", "hidden": True}, {}]}

    monkeypatch.setattr(cli_rpc, "Client", Client)
    monkeypatch.setattr(ai_accounts, "command", lambda backend: ["official-codex"])
    assert ai_accounts.models(Settings("codex")) == ["available"]
    assert calls == ["initialize", "initialized", "model/list"]


def test_claude_discovery_reads_live_catalog_without_a_model_turn(monkeypatch, tmp_path):
    from paper_daily import ai_accounts, cli_rpc

    # Only model values retained from a metadata query to Claude Code 2.1.304.
    catalog = json.loads(
        (Path(__file__).parent / "fixtures/claude_models_2_1_304.json").read_text()
    )
    catalog["models"] += [
        {"value": "default"}, {"value": "fable"}, {}, None, {"value": 42}, {"value": " "},
    ]
    cfg = Settings("cli", account_id="a" * 32, cli_home=str(tmp_path / "account"), isolated=True)
    calls = []

    class Client:
        def __init__(self, argv, *, env, cwd):
            assert env["CLAUDE_CONFIG_DIR"] == str(Path(cfg.cli_home).resolve())
            assert "ANTHROPIC_API_KEY" not in env
            assert argv[0] == "official-claude"
            assert argv[argv.index("--tools") + 1] == ""
            assert argv[argv.index("--setting-sources") + 1] == ""
            assert json.loads(argv[argv.index("--settings") + 1])["disableAllHooks"]
            assert json.loads(argv[argv.index("--mcp-config") + 1]) == {"mcpServers": {}}
            assert "--strict-mcp-config" in argv and "--no-session-persistence" in argv
            assert list(Path(cwd).iterdir()) == []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def control(self, request):
            calls.append(request)
            return catalog

    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-use-other-credential")
    monkeypatch.setattr(cli_rpc, "Client", Client)
    monkeypatch.setattr(ai_accounts, "command", lambda backend: ["official-claude"])
    found = ai_accounts.models(cfg)
    assert "fable" in found and "claude-fable-5" in found
    assert found.count("fable") == 1 and "default" not in found
    assert calls == [{"subtype": "initialize", "hooks": {}}]


@pytest.mark.parametrize("catalog", [{}, {"models": None}, {"models": "invalid"}, []])
def test_invalid_claude_discovery_never_invents_fallback_models(monkeypatch, catalog):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from paper_daily import ai_accounts

    @contextmanager
    def client(_cfg):
        yield SimpleNamespace(control=lambda request: catalog)

    monkeypatch.setattr(ai_accounts, "_claude_client", client)
    with pytest.raises(ValueError, match="model list"):
        ai_accounts.models(Settings("cli"))


def test_shared_cli_discovery_keeps_selected_connection_and_errors_safe(monkeypatch):
    from paper_daily import ai_accounts

    cfg = Settings("cli", model="my-version")
    seen = []

    def discover(selected):
        seen.append(selected)
        return ["fable", "claude-fable-5"]

    monkeypatch.setattr(ai_accounts, "models", discover)
    assert ai_providers.list_models(cfg) == (["fable", "claude-fable-5"], "ok")
    assert seen == [cfg] and cfg.model == "my-version"

    def fail(_cfg):
        raise TimeoutError("private service details")

    monkeypatch.setattr(ai_accounts, "models", fail)
    models, reason = ai_providers.list_models(cfg)
    assert models == [] and "private" not in reason and "重試" in reason


@pytest.mark.parametrize("model", ["fable", "claude-fable-5"])
def test_discovered_fable_id_reaches_claude_unchanged(monkeypatch, model):
    from types import SimpleNamespace

    from paper_daily.ai_types import Request

    monkeypatch.setattr(ai_providers.shutil, "which", lambda name: "official-claude")
    commands = []

    def run(argv, **kwargs):
        commands.append(argv)
        return SimpleNamespace(returncode=0, stdout="fixture answer", stderr="")

    monkeypatch.setattr(ai_providers.subprocess, "run", run)
    result = ai_providers.ClaudeCLI().complete(
        Request("fixture", None, 30, 100, "ask", "fixture-request"),
        Settings("cli", model=model, isolated=True),
        lambda *args: pytest.fail("must not switch to API"),
    )
    assert result.text == "fixture answer"
    assert commands[0][commands[0].index("--model") + 1] == model
