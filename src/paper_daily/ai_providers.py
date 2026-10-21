"""Provider adapters. Features only depend on the shared request/reply contract."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from paper_daily import ai_accounts
from paper_daily.ai_types import OPENAI_DEFAULT_BASE, Completion, Request, Settings, TokenUsage

Transport = Callable[[str, dict, dict, int], tuple[dict | None, str]]


def list_models(cfg: Settings) -> tuple[list[str], str]:
    if cfg.backend in ai_accounts.CLI_NAMES:
        try:
            models = ai_accounts.models(cfg)
            return models, "ok" if models else "CLI 未回傳可選模型；可直接輸入完整模型 ID"
        except (ValueError, OSError, TimeoutError):
            return [], "無法取得 CLI 模型清單；可重試或直接輸入完整模型 ID"
    if cfg.backend not in ("anthropic", "openai", "gateway"):
        return [], "CLI 可使用預設模型，或直接輸入官方 CLI 支援的模型名稱"
    if cfg.requires_key and not cfg.api_key:
        return [], "請先提供此連線的 API 金鑰"
    try:
        if cfg.backend == "anthropic":
            url = _base_url(cfg.base_url or "https://api.anthropic.com") + "/v1/models"
            headers = {"x-api-key": cfg.api_key or "", "anthropic-version": "2023-06-01"}
        else:
            base = cfg.base_url or (OPENAI_DEFAULT_BASE if cfg.backend == "openai" else "")
            url = _base_url(base) + "/models"
            headers = {"Authorization": "Bearer " + cfg.api_key} if cfg.api_key else {}
        response = httpx.get(url, headers=headers, timeout=20)
        if response.status_code != 200:
            return [], f"無法取得模型清單（HTTP {response.status_code}）；可直接輸入模型 ID"
        payload = response.json()
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return [], "服務未提供相容模型清單；請直接輸入模型 ID"
        models = sorted(
            {
                row["id"]
                for row in rows[:1000]
                if isinstance(row, dict)
                and isinstance(row.get("id"), str)
                and 0 < len(row["id"]) <= 200
            }
        )
        return models, "ok" if models else "服務未回傳模型；請直接輸入模型 ID"
    except (httpx.HTTPError, ValueError):
        return [], "模型清單連線失敗；請檢查網址，或直接輸入模型 ID"


class Provider(Protocol):
    def complete(self, request: Request, cfg: Settings, post: Transport) -> Completion: ...


def _count(value) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Base URL must be an HTTP(S) URL without credentials, query or fragment")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Remote AI endpoints must use HTTPS")
    return value.rstrip("/")


class ClaudeCLI:
    def complete(self, request: Request, cfg: Settings, post: Transport) -> Completion:
        exe = shutil.which("claude")
        if not exe:
            return Completion(None, "claude CLI not on PATH")
        body = f"{request.system}\n\n---\n\n{request.prompt}" if request.system else request.prompt
        argv = [exe, "-p"]
        if cfg.model:
            argv += ["--model", cfg.model]
        if cfg.isolated or cfg.account_id:
            argv += [
                "--setting-sources",
                "",
                "--tools",
                "",
                "--strict-mcp-config",
                "--no-session-persistence",
            ]
        try:
            proc = subprocess.run(
                argv,
                input=body,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=request.timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                env=ai_accounts.environment(cfg),
                cwd=cfg.cli_home or None,
            )
        except subprocess.TimeoutExpired:
            return Completion(None, f"timed out after {request.timeout}s")
        except OSError as exc:
            return Completion(None, f"could not run claude: {type(exc).__name__}")
        answer = (proc.stdout or "").strip()
        if proc.returncode == 0 and answer:
            return Completion(answer, model=cfg.model)
        # CLI stderr can contain prompts or credentials; keep failures categorical.
        err = (proc.stderr or "").lower()
        if "authenticate" in err or "oauth" in err or "login" in err:
            return Completion(None, "claude authentication failed -- run 'claude' to sign in again")
        return Completion(
            None, f"claude CLI failed (exit {proc.returncode})" if proc.returncode else "no output"
        )


class CodexCLI:
    def complete(self, request: Request, cfg: Settings, post: Transport) -> Completion:
        body = f"{request.system}\n\n---\n\n{request.prompt}" if request.system else request.prompt
        try:
            argv = ai_accounts.command("codex")
            env = ai_accounts.environment(cfg)
            with tempfile.TemporaryDirectory(prefix="paperfact-codex-") as folder:
                output = Path(folder) / "answer.txt"
                argv += [
                    "exec",
                    "--sandbox",
                    "read-only",
                    "--skip-git-repo-check",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--color",
                    "never",
                    "--output-last-message",
                    str(output),
                ]
                if cfg.account_id:
                    argv += ["-c", 'cli_auth_credentials_store="file"']
                if cfg.model:
                    argv += ["--model", cfg.model]
                proc = subprocess.run(
                    [*argv, "-"],
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
                    return Completion(
                        None, f"Codex CLI failed (exit {proc.returncode}); check login"
                    )
                answer = output.read_text(encoding="utf-8").strip() if output.exists() else ""
                return Completion(answer or None, "ok" if answer else "Codex returned no answer")
        except subprocess.TimeoutExpired:
            return Completion(None, f"timed out after {request.timeout}s")
        except (OSError, ValueError) as exc:
            return Completion(
                None, str(exc) if isinstance(exc, ValueError) else "Could not run Codex CLI"
            )


class Anthropic:
    def complete(self, request: Request, cfg: Settings, post: Transport) -> Completion:
        if not cfg.api_key:
            return Completion(None, "no ANTHROPIC_API_KEY (see 'paperfact llm --help')")
        payload = {
            "model": cfg.effective_model,
            "max_tokens": request.max_tokens,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system:
            payload["system"] = request.system
        data, reason = post(
            f"{_base_url(cfg.base_url or 'https://api.anthropic.com')}/v1/messages",
            {
                "x-api-key": cfg.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            payload,
            request.timeout,
        )
        if data is None:
            return Completion(None, reason)
        content = data.get("content")
        text = (
            "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ).strip()
            if isinstance(content, list)
            else ""
        )
        raw = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        uncached = _count(raw.get("input_tokens"))
        cached = _count(raw.get("cache_read_input_tokens"))
        created = _count(raw.get("cache_creation_input_tokens"))
        usage = TokenUsage(
            input_tokens=uncached + (cached or 0) + (created or 0)
            if uncached is not None
            else None,
            output_tokens=_count(raw.get("output_tokens")),
            cached_input_tokens=cached,
            cache_creation_tokens=created,
        )
        return Completion(
            text or None,
            "ok" if text else "empty reply",
            usage=usage,
            model=data.get("model") or cfg.effective_model,
            provider_request_id=data.get("id"),
            finish_reason=data.get("stop_reason"),
        )


class OpenAICompatible:
    def complete(self, request: Request, cfg: Settings, post: Transport) -> Completion:
        if (cfg.requires_key or cfg.backend == "gateway") and not cfg.api_key:
            key_name = cfg.api_key_env or "OPENAI_API_KEY"
            return Completion(None, f"no {key_name} (see 'paperfact llm --help')")
        if cfg.backend == "gateway" and (not cfg.base_url or not cfg.model):
            return Completion(None, "gateway requires an explicit base URL and model")
        messages = ([{"role": "system", "content": request.system}] if request.system else []) + [
            {"role": "user", "content": request.prompt},
        ]
        headers = {"content-type": "application/json"}
        if cfg.api_key:
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        if cfg.backend == "gateway":
            # The service must deduplicate this key before charging an account.
            headers["Idempotency-Key"] = request.request_id
            headers["X-Paperfact-Task"] = request.task
        data, reason = post(
            f"{_base_url(cfg.base_url or OPENAI_DEFAULT_BASE)}/chat/completions",
            headers,
            {
                "model": cfg.effective_model,
                cfg.token_parameter: request.max_tokens,
                "messages": messages,
            },
            request.timeout,
        )
        if data is None:
            return Completion(None, reason)
        choices = data.get("choices")
        first = (
            choices[0]
            if isinstance(choices, list) and choices and isinstance(choices[0], dict)
            else {}
        )
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and isinstance(block.get("text"), str)
            )
        text = content.strip() if isinstance(content, str) else ""
        raw = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        details = raw.get("prompt_tokens_details")
        details = details if isinstance(details, dict) else {}
        return Completion(
            text or None,
            "ok" if text else "empty reply",
            usage=TokenUsage(
                _count(raw.get("prompt_tokens")),
                _count(raw.get("completion_tokens")),
                _count(details.get("cached_tokens")),
            ),
            model=data.get("model") or cfg.effective_model,
            provider_request_id=data.get("id"),
            finish_reason=first.get("finish_reason"),
        )
