"""Gemini's official Google login (ACP) and headless research answers."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from paper_daily import ai_accounts
from paper_daily.ai_types import Completion
from paper_daily.cli_rpc import Client


def prepare_workspace(folder):
    settings = Path(folder) / ".gemini" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"tools": {"core": [], "useRipgrep": False}}), encoding="utf-8")
    return str(folder)


def auth_dir(cfg):
    home = cfg.cli_home or (None if cfg.isolated else os.environ.get("GEMINI_CLI_HOME"))
    return (Path(home) if home else Path.home()) / ".gemini"


def status(cfg):
    folder = auth_dir(cfg)
    # Current official CLI stores encrypted credentials; older releases use JSON.
    # Only inspect presence: the CLI owns decryption, refresh and validation.
    if not any(
        (folder / name).is_file() for name in ("oauth_creds.json", "gemini-credentials.json")
    ):
        return None, "尚未登入 Google"
    email = None
    try:
        data = json.loads((folder / "google_accounts.json").read_text(encoding="utf-8"))
        email = data.get("active") if isinstance(data, dict) else None
    except (ValueError, OSError):
        pass
    return "已儲存 Google 登入" + (f"：{email}" if isinstance(email, str) else ""), "ok"


def quota_module(entry):
    """Resolve the active installed bundle, never a stale chunk left by an upgrade."""
    entry = Path(entry).resolve()
    source = entry.read_text(encoding="utf-8")
    for names, relative in re.findall(r'import\s*\{([^}]+)\}\s*from\s*["\']([^"\']+)', source):
        if "getOauthClient" not in names.split(",") and not re.search(r"\bgetOauthClient\b", names):
            continue
        candidate = (entry.parent / relative).resolve()
        if candidate.is_relative_to(entry.parent) and candidate.is_file():
            return candidate
    # Older unbundled npm releases expose the official core package.
    for parent in entry.parents:
        candidate = parent / "node_modules/@google/gemini-cli-core/dist/src/index.js"
        if candidate.is_file():
            return candidate
    raise ValueError("此 Gemini CLI 版本未提供可用的配額介面")


def usage(cfg):
    if not status(cfg)[0]:
        raise ValueError("尚未登入 Gemini")
    argv = ai_accounts.command("gemini")
    entry = Path(argv[-1]).resolve()
    node = argv[0] if len(argv) > 1 else shutil.which("node")
    if not node or not entry.is_file():
        raise ValueError("找不到 Gemini CLI")
    module = quota_module(entry)
    env = ai_accounts.environment(cfg)
    # Quota must use the selected cached Google login, never an ambient access token.
    env.pop("GOOGLE_CLOUD_ACCESS_TOKEN", None)
    env["NO_BROWSER"] = "true"
    with tempfile.TemporaryDirectory(prefix="paperfact-gemini-quota-") as folder:
        proc = subprocess.run(
            [node, str(Path(__file__).with_name("gemini_usage.mjs")), str(module)],
            env=env, cwd=folder, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=45,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    if not proc.returncode:
        for line in proc.stdout.splitlines():
            if line.startswith("PAPERFACT_QUOTA="):
                result = json.loads(line.removeprefix("PAPERFACT_QUOTA="))
                if isinstance(result, dict):
                    return result
    raise ValueError("無法讀取 Gemini 配額；請確認登入與 CLI 版本")


def authenticate(cfg, action):
    try:
        argv = ai_accounts.command("gemini")
        if action == "status":
            return status(cfg)
        if not cfg.account_id or not cfg.cli_home:
            return None, "請新增獨立帳號"
        if action == "logout":
            for name in ("oauth_creds.json", "gemini-credentials.json", "google_accounts.json"):
                (auth_dir(cfg) / name).unlink(missing_ok=True)
            return "已移除此帳號的本機 Google 登入", "ok"
        env = ai_accounts.environment(cfg)
        with (
            tempfile.TemporaryDirectory(prefix="paperfact-gemini-auth-") as folder,
            Client(
                [*argv, "--acp", "--extensions", "none"], env=env, cwd=prepare_workspace(folder)
            ) as client,
        ):
            hello = client.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
            methods = hello.get("authMethods", [])
            if not any(m.get("id") == "oauth-personal" for m in methods if isinstance(m, dict)):
                return None, "此 Gemini CLI 未提供 Google 登入；請更新官方 CLI"
            client.request("authenticate", {"methodId": "oauth-personal"}, timeout=240)
        return "Google 登入完成", "ok"
    except TimeoutError:
        return None, "登入等候逾時；請重新登入並在瀏覽器完成授權"
    except (OSError, ValueError):
        return None, "Gemini 登入未完成；請確認官方 CLI 版本與 Google 帳號資格"


class GeminiCLI:
    def complete(self, request, cfg, post):
        if not status(cfg)[0]:
            return Completion(None, "請先在 AI 設定登入 Gemini")
        body = f"{request.system}\n\n---\n\n{request.prompt}" if request.system else request.prompt
        try:
            env = ai_accounts.environment(cfg)
            env["GOOGLE_GENAI_USE_GCA"] = "true"
            with tempfile.TemporaryDirectory(prefix="paperfact-gemini-") as folder:
                prepare_workspace(folder)
                policy = Path(folder) / "no-tools.toml"
                policy.write_text('[[rule]]\ntoolName = "*"\ndecision = "deny"\npriority = 999\n')
                argv = [
                    *ai_accounts.command("gemini"),
                    "-p",
                    "Answer using the supplied text.",
                    "--output-format",
                    "json",
                    "--extensions",
                    "none",
                    "--policy",
                    str(policy),
                ]
                if cfg.model:
                    argv += ["--model", cfg.model]
                proc = subprocess.run(
                    argv,
                    input=body,
                    env=env,
                    cwd=folder,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=request.timeout,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if proc.returncode:
                    return Completion(None, "Gemini 未完成回覆；請檢查登入、模型或額度")
                data = json.loads(proc.stdout)
                answer = data.get("response") if isinstance(data, dict) else None
                if (
                    not isinstance(data, dict)
                    or data.get("error")
                    or not isinstance(answer, str)
                    or not answer.strip()
                ):
                    return Completion(None, "Gemini 未回傳完整回答")
                return Completion(answer.strip(), model=cfg.model)
        except subprocess.TimeoutExpired:
            return Completion(None, f"timed out after {request.timeout}s")
        except (ValueError, OSError):
            return Completion(None, "無法取得 Gemini 回覆；請確認官方 CLI 已安裝並登入")
