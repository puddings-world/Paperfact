"""Official CLI authentication, isolated from the user's terminal sessions."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from paper_daily import model_catalog
from paper_daily.ai_types import Settings

CLI_NAMES = {"cli": "claude", "codex": "codex", "gemini": "gemini"}


@contextmanager
def _claude_client(cfg):
    """Metadata-only session in an empty directory, with tools and hooks disabled."""
    from paper_daily.cli_rpc import Client

    argv = [*command("cli"), "-p", "--input-format", "stream-json",
            "--output-format", "stream-json", "--verbose", "--setting-sources", "",
            "--settings", '{"disableAllHooks":true}', "--tools", "",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--no-session-persistence"]
    with (
        tempfile.TemporaryDirectory(prefix="paperfact-quota-") as folder,
        Client(argv, env=environment(cfg), cwd=folder) as client,
    ):
        yield client


def claude_usage(cfg):
    """Ask the official CLI for /usage, without reading credentials or transcripts."""
    with _claude_client(cfg) as client:
        initialized = client.control({"subtype": "initialize", "hooks": {}})
        if isinstance(initialized, dict) and isinstance(initialized.get("models"), list):
            model_catalog.remember(cfg, initialized["models"])
        result = client.control({"subtype": "get_usage", "skip_behaviors": True})
        if not isinstance(result, dict):
            raise ValueError("Invalid usage response")
        return result


def models(cfg):
    if cfg.backend == "cli":
        with _claude_client(cfg) as client:
            result = client.control({"subtype": "initialize", "hooks": {}})
        rows = result.get("models") if isinstance(result, dict) else None
        if not isinstance(rows, list):
            raise ValueError("Claude CLI did not provide a model list")
        model_catalog.remember(cfg, rows)
        return list(dict.fromkeys(
            row["value"] for row in rows
            if isinstance(row, dict) and isinstance(row.get("value"), str)
            and row["value"].strip() and row["value"] != "default"
        ))
    if cfg.backend == "gemini":
        return [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-3-pro-preview",
            "gemini-3-flash-preview",
        ]
    if cfg.backend != "codex":
        return []
    result = codex_request(cfg, "model/list", {"includeHidden": False, "limit": 100})
    return [
        row["model"]
        for row in result.get("data", [])
        if isinstance(row, dict) and isinstance(row.get("model"), str) and not row.get("hidden")
    ]


def codex_request(cfg, method, params):
    """Let the official CLI own credentials; only consume its public protocol."""
    from paper_daily.cli_rpc import Client

    argv = command("codex")
    if cfg.account_id:
        argv += ["-c", 'cli_auth_credentials_store="file"']
    with Client([*argv, "app-server"], env=environment(cfg), cwd=cfg.cli_home) as client:
        client.request("initialize", {"clientInfo": {"name": "paperfact", "version": "0.1.0"}})
        client.send({"method": "initialized", "params": {}})
        result = client.request(method, params)
        if not isinstance(result, dict):
            raise ValueError("Official CLI returned an invalid response")
        return result


def codex_identity(cfg):
    raw = codex_request(cfg, "account/read", {"refreshToken": False}).get("account")
    if not isinstance(raw, dict):
        return None
    return {key: raw[key] for key in ("type", "email", "planType") if isinstance(raw.get(key), str)}


def codex_status(cfg):
    try:
        account = codex_identity(cfg)
        if not account:
            return None, "尚未登入 Codex"
        if account.get("type") == "apiKey":
            return "Codex 使用 API 金鑰（非訂閱帳號）", "ok"
        label = "已登入：" + (account.get("email") or "Codex（官方未提供信箱）")
        if account.get("planType"):
            label += " · " + account["planType"]
        return label, "ok"
    except (OSError, ValueError, TimeoutError):
        return None, "無法讀取 Codex 帳號；請確認官方 CLI 版本或稍後重試"


def command(backend: str) -> list[str]:
    name = CLI_NAMES.get(backend)
    if not name:
        raise ValueError("此連線使用 API 金鑰，不需要 CLI 登入")
    exe = shutil.which(name)
    if not exe:
        raise ValueError(f"尚未安裝 {name} CLI；請先安裝官方 CLI 後重新開啟 Paperfact")
    if backend in ("codex", "gemini") and Path(exe).suffix.lower() in (".cmd", ".bat", ".ps1"):
        relative = (
            "@openai/codex/bin/codex.js"
            if backend == "codex"
            else "@google/gemini-cli/bundle/gemini.js"
        )
        script = Path(exe).parent / "node_modules" / relative
        if backend == "gemini" and not script.exists():
            script = Path(exe).parent / "node_modules/@google/gemini-cli/dist/index.js"
        node = shutil.which("node")
        if not node or not script.is_file():
            raise ValueError(f"找不到 {name} 的 Node 啟動程式，請重新安裝官方 CLI")
        return [node, str(script)]
    return [exe]


def environment(cfg: Settings) -> dict[str, str]:
    env = dict(os.environ)
    if cfg.isolated or cfg.account_id:
        # An API key in the parent process must not replace the selected login.
        for key in list(env):
            if key.startswith(("ANTHROPIC_", "CLAUDE_CODE_", "OPENAI_", "CODEX_", "GEMINI_")):
                env.pop(key)
        for key in (
            "GOOGLE_API_KEY",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "GOOGLE_GENAI_USE_VERTEXAI",
            "GOOGLE_GENAI_USE_GCA",
            "GOOGLE_CLOUD_ACCESS_TOKEN",
        ):
            env.pop(key, None)
        env.pop("CLAUDE_CONFIG_DIR", None)
        env.pop("CLAUDECODE", None)
    if cfg.account_id:
        if not cfg.cli_home:
            raise ValueError("帳號儲存位置尚未設定")
        Path(cfg.cli_home).mkdir(parents=True, exist_ok=True)
        env[
            {"cli": "CLAUDE_CONFIG_DIR", "codex": "CODEX_HOME", "gemini": "GEMINI_CLI_HOME"}[
                cfg.backend
            ]
        ] = str(Path(cfg.cli_home).resolve())
        if cfg.backend == "gemini":
            env["GEMINI_FORCE_FILE_STORAGE"] = "true"
    env["PYTHONIOENCODING"] = "utf-8"
    if cfg.backend == "gemini":
        # Keep the stdio protocol on the process we own, including timeout cleanup.
        env["GEMINI_CLI_NO_RELAUNCH"] = "true"
    return env


def auth(cfg: Settings, action: str) -> tuple[str | None, str]:
    if action not in ("login", "logout", "status"):
        raise ValueError("Unknown authentication action")
    if action != "status" and not cfg.account_id:
        return None, "請選擇獨立帳號後登入；沿用本機登入時，請在官方 CLI 管理帳號"
    if cfg.backend == "codex" and action == "status":
        return codex_status(cfg)
    if cfg.backend == "gemini":
        from paper_daily.gemini_cli import authenticate

        return authenticate(cfg, action)
    try:
        argv = command(cfg.backend)
        if cfg.backend == "cli":
            argv += ["auth", action]
            if action == "login":
                argv += ["--claudeai"]
        else:
            if cfg.account_id:
                argv += ["-c", 'cli_auth_credentials_store="file"']
            argv += ["login", "status"] if action == "status" else [action]
        proc = subprocess.run(
            argv,
            env=environment(cfg),
            cwd=cfg.cli_home or None,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240 if action == "login" else 30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return None, "登入等候逾時；請重新按登入，並在瀏覽器完成授權"
    except (OSError, ValueError) as exc:
        return None, str(exc) if isinstance(exc, ValueError) else "無法啟動官方 CLI"
    if proc.returncode:
        return None, "尚未登入或官方 CLI 未完成操作；請確認 CLI 版本與帳號權限"
    if action == "status" and cfg.backend == "cli":
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            return None, "無法確認登入狀態，請更新 Claude CLI"
        if not isinstance(data, dict):
            return None, "無法確認登入狀態，請更新 Claude CLI"
        if not data.get("loggedIn"):
            return None, "尚未登入"
        email = data.get("email")
        return "已登入" + (f"：{email}" if isinstance(email, str) else ""), "ok"
    return {
        "login": "登入完成，可按檢查登入確認帳號",
        "logout": "已登出此帳號",
        "status": "已登入 Codex",
    }[action], "ok"
