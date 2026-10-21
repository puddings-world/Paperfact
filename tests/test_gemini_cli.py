import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_daily import ai_accounts, gemini_cli, llm
from paper_daily.ai_types import Settings


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(ai_accounts, "command", lambda backend: ["official-gemini"])
    return Settings(
        "gemini",
        model="chosen-model",
        isolated=True,
        account_id="a" * 32,
        cli_home=str(tmp_path / "account"),
    )


def test_gemini_account_isolation_does_not_inherit_api_keys(cfg, monkeypatch):
    for key in (
        "GEMINI_CLI_HOME",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
    ):
        monkeypatch.setenv(key, "other-account")
    env = ai_accounts.environment(cfg)
    assert env["GEMINI_CLI_HOME"] == cfg.cli_home
    assert env["GEMINI_FORCE_FILE_STORAGE"] == "true"
    assert env["GEMINI_CLI_NO_RELAUNCH"] == "true"
    assert "GEMINI_API_KEY" not in env and "GOOGLE_API_KEY" not in env
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in env


def test_google_login_uses_official_acp_auth_without_a_model_request(cfg, monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, argv, **kwargs):
            assert "--acp" in argv
            assert kwargs["env"]["GEMINI_CLI_HOME"] == cfg.cli_home
            settings = json.loads((Path(kwargs["cwd"]) / ".gemini" / "settings.json").read_text())
            assert settings["tools"] == {"core": [], "useRipgrep": False}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def request(self, method, params, **kwargs):
            calls.append((method, params))
            if method == "initialize":
                return json.loads(
                    (Path(__file__).parent / "fixtures/gemini-acp-discovery.json").read_text()
                )
            return {}

    monkeypatch.setattr(gemini_cli, "Client", FakeClient)
    assert ai_accounts.auth(cfg, "login")[0] == "Google 登入完成"
    assert [method for method, _ in calls] == ["initialize", "authenticate"]
    assert calls[1][1] == {"methodId": "oauth-personal"}


def test_logout_removes_only_selected_local_account(cfg):
    folder = gemini_cli.auth_dir(cfg)
    folder.mkdir(parents=True)
    for name in (
        "oauth_creds.json",
        "gemini-credentials.json",
        "google_accounts.json",
        "settings.json",
    ):
        (folder / name).write_text("{}")
    sibling = Path(cfg.cli_home).parent / "other-account.json"
    sibling.write_text("keep")
    assert ai_accounts.auth(cfg, "logout")[0]
    assert not (folder / "oauth_creds.json").exists()
    assert not (folder / "gemini-credentials.json").exists()
    assert (folder / "settings.json").exists() and sibling.read_text() == "keep"


def test_gemini_answer_uses_selected_model_and_never_tools(cfg, monkeypatch):
    monkeypatch.setattr(gemini_cli, "status", lambda cfg: ("cached", "ok"))

    def run(argv, **kwargs):
        settings = json.loads((Path(kwargs["cwd"]) / ".gemini" / "settings.json").read_text())
        assert settings["tools"] == {"core": [], "useRipgrep": False}
        assert argv[argv.index("--model") + 1] == "chosen-model"
        policy = Path(argv[argv.index("--policy") + 1]).read_text()
        assert 'toolName = "*"' in policy and 'decision = "deny"' in policy
        assert "paper text" in kwargs["input"] and "research rules" in kwargs["input"]
        return SimpleNamespace(
            returncode=0, stdout=json.dumps({"response": "answer"}), stderr="secret"
        )

    monkeypatch.setattr(gemini_cli.subprocess, "run", run)
    answer = llm.complete_result("paper text", system="research rules", cfg=cfg)
    assert answer.text == "answer" and answer.backend == "gemini"


@pytest.mark.parametrize(
    "data", [[], {}, {"error": "secret", "response": "partial"}, {"response": 1}]
)
def test_invalid_gemini_output_is_not_applied(cfg, monkeypatch, data):
    monkeypatch.setattr(gemini_cli, "status", lambda cfg: ("cached", "ok"))
    monkeypatch.setattr(
        gemini_cli.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(data), stderr="secret"),
    )
    result = llm.complete_result("paper text", cfg=cfg)
    assert result.text is None and "secret" not in result.reason


def test_missing_login_never_starts_generation(cfg, monkeypatch):
    monkeypatch.setattr(gemini_cli.subprocess, "run", lambda *a, **k: pytest.fail("not signed in"))
    assert llm.complete_result("paper", cfg=cfg).text is None


@pytest.mark.parametrize("filename", ["oauth_creds.json", "gemini-credentials.json"])
def test_local_cached_status_supports_official_storage_versions(cfg, filename):
    folder = gemini_cli.auth_dir(cfg)
    folder.mkdir(parents=True)
    (folder / filename).write_text("opaque-cli-owned-credentials")
    (folder / "google_accounts.json").write_text(json.dumps({"active": "researcher@example.org"}))
    label, reason = gemini_cli.status(cfg)
    assert "researcher@example.org" in label and reason == "ok"
    assert "opaque" not in label


def test_quota_resolves_active_bundle_not_stale_chunks(tmp_path):
    entry = tmp_path / "gemini.js"
    entry.write_text('import { other, getOauthClient } from "./chunk-current.js";')
    (tmp_path / "chunk-current.js").write_text("export {};")
    (tmp_path / "chunk-old.js").write_text("export {};")
    assert gemini_cli.quota_module(entry).name == "chunk-current.js"
    entry.write_text('import { getOauthClient } from "../outside.js";')
    with pytest.raises(ValueError):
        gemini_cli.quota_module(entry)


def test_quota_process_is_scoped_and_accepts_only_tagged_result(cfg, monkeypatch, tmp_path):
    entry = tmp_path / "gemini.js"
    entry.write_text('import { getOauthClient } from "./chunk-core.js";')
    (tmp_path / "chunk-core.js").write_text("export {};")
    monkeypatch.setattr(ai_accounts, "command", lambda backend: ["node", str(entry)])
    monkeypatch.setattr(gemini_cli, "status", lambda cfg: ("cached", "ok"))
    monkeypatch.setenv("GOOGLE_CLOUD_ACCESS_TOKEN", "other-account-token")

    def run(argv, **kwargs):
        assert argv[1].endswith("gemini_usage.mjs") and "-p" not in argv
        assert kwargs["env"]["GEMINI_CLI_HOME"] == cfg.cli_home
        assert kwargs["env"]["NO_BROWSER"] == "true"
        assert "GOOGLE_CLOUD_ACCESS_TOKEN" not in kwargs["env"]
        assert kwargs["timeout"] == 45
        assert Path(kwargs["cwd"]).is_dir()
        return SimpleNamespace(returncode=0, stdout='CLI notice\nPAPERFACT_QUOTA={"buckets":[]}\n')

    monkeypatch.setattr(gemini_cli.subprocess, "run", run)
    assert gemini_cli.usage(cfg) == {"buckets": []}
    monkeypatch.setattr(gemini_cli.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=1, stdout="secret credentials", stderr="private details"
    ))
    with pytest.raises(ValueError, match="無法讀取 Gemini"):
        gemini_cli.usage(cfg)


def test_missing_gemini_login_never_starts_quota_process(cfg, monkeypatch):
    monkeypatch.setattr(gemini_cli.subprocess, "run", lambda *a, **kw: pytest.fail("no login"))
    with pytest.raises(ValueError, match="尚未登入"):
        gemini_cli.usage(cfg)
