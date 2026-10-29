"""AI service facade: profile selection, provider dispatch, and local usage receipts.

All paper features call complete(). Providers never access papers.db. complete_result()
adds reported token usage without changing the existing (text, reason) interface.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from paper_daily import ai_profiles
from paper_daily.ai_providers import Anthropic, ClaudeCLI, CodexCLI, OpenAICompatible, Provider
from paper_daily.ai_types import (
    DEFAULT_MAX_TOKENS as DEFAULT_MAX_TOKENS,
)
from paper_daily.ai_types import (
    DEFAULT_MODELS as DEFAULT_MODELS,
)
from paper_daily.ai_types import (
    OPENAI_DEFAULT_BASE,
    Completion,
    Request,
    Settings,
)
from paper_daily.config import DATA_DIR
from paper_daily.gemini_cli import GeminiCLI

SETTINGS_PATH = DATA_DIR / "llm.json"
TASKS = ai_profiles.TASKS
_PROVIDERS: dict[str, Provider] = {
    "cli": ClaudeCLI(),
    "codex": CodexCLI(),
    "gemini": GeminiCLI(),
    "anthropic": Anthropic(),
    "openai": OpenAICompatible(),
    "gateway": OpenAICompatible(),
}
BACKENDS = tuple(_PROVIDERS)
_CONNECTIONS: ContextVar[tuple | None] = ContextVar("paperfact_ai_connections", default=None)
# Optional host preflight. Desktop installs a thread-safe login notifier; CLI and
# library consumers remain independent of Qt.
ACCESS_CHECK = None


def register_provider(name: str, provider: Provider) -> None:
    """Register an adapter at application startup; built-ins cannot be replaced."""
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) or name in ("auto", "none"):
        raise ValueError("Invalid provider name")
    if name in _PROVIDERS:
        raise ValueError(f"Provider already registered: {name}")
    if not callable(getattr(provider, "complete", None)):
        raise TypeError("Provider must implement complete()")
    _PROVIDERS[name] = provider


def backend_names() -> tuple[str, ...]:
    return tuple(_PROVIDERS)


def _stored() -> dict:
    return ai_profiles.load(SETTINGS_PATH)


def save_settings(*, profile: str | None = None, **fields) -> Path:
    return ai_profiles.save(SETTINGS_PATH, profile, (*backend_names(), "none"), **fields)


def profile_names() -> list[str]:
    return sorted(_stored().get("profiles", {}))


def active_profile() -> str | None:
    return _stored().get("active_profile")


def profile_fields(profile: str | None = None) -> dict:
    """Editable fields without exposing a stored key to UI or CLI output."""
    raw = ai_profiles.fields(_stored(), profile)
    return {
        **{key: value for key, value in raw.items() if key != "api_key"},
        "has_api_key": bool(raw.get("api_key")),
    }


def use_profile(profile: str, task: str | None = None, *, desktop=False) -> Path:
    return ai_profiles.use(SETTINGS_PATH, profile, task, desktop=desktop)


def task_routes() -> dict[str, str]:
    return dict(_stored().get("routes", {}))


def clear_route(task: str) -> Path:
    return ai_profiles.unroute(SETTINGS_PATH, task)


def save_routes(routes: dict[str, str]) -> Path:
    data = _stored()
    for task, profile in routes.items():
        if task not in TASKS:
            raise ValueError(f"Unknown AI task: {task}")
        ai_profiles.fields(data, profile)
    data["route_models"] = {
        task: model
        for task, model in data.get("route_models", {}).items()
        if task in routes and routes[task] == data.get("routes", {}).get(task)
    }
    data["routes"] = dict(routes)
    data["prefer_saved_profiles"] = True
    return ai_profiles.write(SETTINGS_PATH, data)


def save_task_choices(selections: dict) -> Path:
    return ai_profiles.assign(SETTINGS_PATH, selections, (*backend_names(), "none"))


def settings(task: str = "default", profile: str | None = None) -> Settings:
    data, environ, directory = _CONNECTIONS.get() or capture_connections()
    if isinstance(data, Exception):
        raise ValueError(str(data)) from data
    return ai_profiles.resolve(
        data,
        task,
        profile,
        backends=(*backend_names(), "none"),
        environ=environ,
        accounts_dir=directory / "ai-accounts",
    )


def capture_connections():
    try:
        data = _stored()
    except (ValueError, OSError) as exc:
        # A non-AI operation may share the worker without needing valid AI settings.
        data = exc
    return data, dict(os.environ), SETTINGS_PATH.parent


@contextmanager
def connection_scope(snapshot=None):
    token = _CONNECTIONS.set(snapshot or _CONNECTIONS.get() or capture_connections())
    try:
        yield
    finally:
        _CONNECTIONS.reset(token)


def describe(cfg: Settings | None = None) -> str:
    cfg = cfg or settings()
    label = f"[{cfg.profile}] " if cfg.profile else ""
    if cfg.backend in ("cli", "codex", "gemini"):
        name = "claude" if cfg.backend == "cli" else cfg.backend
        account = "獨立帳號" if cfg.account_id else "本機 CLI 帳號"
        model = cfg.model or "CLI 預設模型"
        return f"{label}{name} · {account} · {model}" + (
            " (not on PATH)" if not shutil.which(name) else ""
        )
    if cfg.backend == "none":
        return "nothing configured"
    state = "key present" if cfg.api_key else ("NO key" if cfg.requires_key else "no key required")
    base = cfg.base_url or (OPENAI_DEFAULT_BASE if cfg.backend == "openai" else "")
    parsed = urlsplit(base)
    port = f":{parsed.port}" if parsed.port else ""
    safe_base = f"{parsed.scheme}://{parsed.hostname}{port}{parsed.path}" if base else ""
    return f"{label}{cfg.backend}, model {cfg.effective_model}, {state}" + (
        f" at {safe_base}" if safe_base else ""
    )


def _post(url: str, headers: dict, payload: dict, timeout: int) -> tuple[dict | None, str]:
    for attempt in range(3):
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, read=timeout)) as client:
                resp = client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            # A lost response may already have consumed credits; don't resubmit blindly.
            return None, f"{type(exc).__name__}: request failed; no automatic retry"
        if 200 <= resp.status_code < 300:
            try:
                data = resp.json()
            except ValueError:
                return None, "AI endpoint returned invalid JSON"
            return (
                (data, "ok")
                if isinstance(data, dict)
                else (None, "AI endpoint returned a non-object reply")
            )
        if resp.status_code in (429, 503, 529) and attempt < 2:
            time.sleep(4 * (attempt + 1))
            continue
        meanings = {
            401: "credential rejected",
            403: "access denied",
            402: "quota or credits exhausted",
            429: "rate limit exceeded",
        }
        return (
            None,
            f"HTTP {resp.status_code}: {meanings.get(resp.status_code, 'AI request rejected')}",
        )
    return None, "AI endpoint unavailable"


_FAILURE_KINDS = (
    ("policy", ("使用政策", "policy")),
    ("limit", ("usage limit", "rate limit", "quota", "credits", "用量", "http 429", "http 402")),
    ("auth", ("sign in", "authenticat", "credential rejected", "登入", "api_key", "http 401")),
    ("timeout", ("timed out", "逾時")),
)


def failure_kind(reason: str) -> str:
    """A coarse, content-free class of a failed call for the usage log."""
    low = (reason or "").lower()
    for kind, needles in _FAILURE_KINDS:
        if any(needle in low for needle in needles):
            return kind
    return "error"


def _record(result: Completion, task: str, elapsed_ms: int, cfg: Settings) -> None:
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "request_id": result.request_id,
        "provider_request_id": result.provider_request_id,
        "backend": result.backend,
        "profile": result.profile,
        "account_id": cfg.account_id,
        "model": result.model,
        "task": task,
        "usage": asdict(result.usage),
        "finish_reason": result.finish_reason,
        "success": result.text is not None,
        "failure": None if result.text is not None else failure_kind(result.reason),
        "elapsed_ms": elapsed_ms,
    }
    # Prompts, answers, endpoint URLs, API keys, and error bodies never enter this log.
    dest = SETTINGS_PATH.parent / "ai-usage.jsonl"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        row = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        fd = os.open(dest, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            if os.write(fd, row) != len(row):
                raise OSError("incomplete usage record")
        finally:
            os.close(fd)
    except OSError:
        # An already-generated answer must survive a full disk or a read-only log.
        logging.getLogger(__name__).warning("Could not save local AI usage receipt")


def _request_label(cfg: Settings) -> str:
    """Name the captured request without reading accounts or guessing reply versions."""
    brand = {
        "cli": "Claude",
        "codex": "Codex",
        "gemini": "Gemini",
        "anthropic": "Anthropic",
        "openai": "OpenAI 相容服務",
        "gateway": "AI 閘道",
    }.get(cfg.backend, cfg.backend)
    if cfg.model:
        model = f"指定模型：{cfg.model}"
    elif cfg.effective_model:
        model = f"預設模型：{cfg.effective_model}"
    else:
        model = "服務預設模型（未指定）"
    return f"{brand} / {model}"


def complete_result(
    prompt: str,
    system: str | None = None,
    timeout: int = 900,
    cfg: Settings | None = None,
    *,
    task: str = "default",
    profile: str | None = None,
    max_tokens: int | None = None,
) -> Completion:
    request_id = str(uuid4())
    try:
        cfg = cfg or settings(task=task, profile=profile)
        ai_profiles.validate(
            {
                "backend": cfg.backend,
                "max_tokens": cfg.max_tokens,
                "token_parameter": cfg.token_parameter,
                "requires_key": cfg.requires_key,
            },
            (*backend_names(), "none"),
        )
        limit = cfg.max_tokens if max_tokens is None else max_tokens
        if type(limit) is not int or limit < 1 or timeout <= 0:
            raise ValueError("Token limit and timeout must be positive")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", task):
            raise ValueError("Invalid AI task name")
    except (ValueError, OSError) as exc:
        return Completion(None, f"Invalid AI configuration: {exc}", request_id=request_id)
    if ACCESS_CHECK is not None:
        reason = ACCESS_CHECK(cfg, task)
        if reason:
            return Completion(None, reason, request_id=request_id, backend=cfg.backend)
    provider = _PROVIDERS.get(cfg.backend)
    if provider is None:
        return Completion(
            None,
            "no LLM backend configured -- open AI settings or run 'paperfact llm --help'",
            request_id=request_id,
            backend=cfg.backend,
            profile=cfg.profile,
        )
    request = Request(prompt, system, timeout, limit, task, request_id)
    from paper_daily import feedback

    feedback.safe_record("ai.started", task, backend=cfg.backend, model=cfg.model,
                         input_chars=len(prompt), node_id=request_id)
    from paper_daily.work_progress import report

    report(f"等待 {_request_label(cfg)} 回覆")
    start = time.monotonic()
    try:
        result = provider.complete(request, cfg, _post)
    except ValueError as exc:
        feedback.safe_record("ai.completed", task, backend=cfg.backend, model=cfg.model,
                             success=False, node_id=request_id)
        return Completion(None, f"Invalid AI endpoint: {exc}", request_id=request_id)
    report("已收到模型回覆，正在核對與整理內容")
    result = replace(
        result,
        request_id=request_id,
        backend=cfg.backend,
        profile=cfg.profile,
        model=result.model or cfg.effective_model,
    )
    if result.finish_reason in ("length", "max_tokens", "model_context_window_exceeded"):
        result = replace(
            result,
            text=None,
            reason="AI reply was truncated; increase the token limit or reduce context",
        )
    if result.text is not None:
        from paper_daily.answer_content import final_text

        cleaned = final_text(result.text)
        result = replace(
            result, text=cleaned,
            reason=result.reason if cleaned is not None else (
                "AI 回覆未包含完整正文，請重試；尚未儲存為分析結果。"
            ),
        )
    _record(result, task, int((time.monotonic() - start) * 1000), cfg)
    from paper_daily import usage_cache

    feedback.safe_record("ai.completed", task, backend=cfg.backend, model=result.model,
                         success=result.text is not None,
                         elapsed_ms=int((time.monotonic() - start) * 1000), input_chars=len(prompt),
                         node_id=request_id)

    try:
        usage_cache.invalidate(cfg)
    except OSError:
        logging.getLogger(__name__).warning("Could not mark account usage for refresh")
    return result


def complete(
    prompt: str,
    system: str | None = None,
    timeout: int = 900,
    cfg: Settings | None = None,
    *,
    task: str = "default",
    profile: str | None = None,
    max_tokens: int | None = None,
) -> tuple[str | None, str]:
    result = complete_result(
        prompt, system, timeout, cfg, task=task, profile=profile, max_tokens=max_tokens
    )
    return result.text, result.reason


def probe(cfg: Settings | None = None) -> tuple[bool, str]:
    text, reason = complete(
        "Reply with exactly the word OK.", timeout=120, cfg=cfg, task="probe", max_tokens=128
    )
    return bool(text), reason


def available(task: str = "default") -> bool:
    try:
        cfg = settings(task=task)
    except (ValueError, OSError):
        return False
    return cfg.backend in _PROVIDERS


_FENCE = re.compile(r"^\s*```[\w-]*\s*|\s*```\s*$")


def reply_json(text: str, expect: type = dict, items: type | None = None):
    """The first JSON value of type `expect` in a model's reply.

    Models wrap JSON in fences or put a sentence before it, and that sentence often
    holds brackets of its own ("A 區 [12]"): taking the first "[" to the last "]"
    turned those replies into parse errors. Every candidate opening is tried in turn;
    with `items`, a list only counts when its entries have that type, so "[12]"
    is not mistaken for the answer.
    """
    text = _FENCE.sub("", text or "")
    opener = "[" if expect is list else "{"
    decoder = json.JSONDecoder()
    start = text.find(opener)
    while start >= 0:
        try:
            value, _end = decoder.raw_decode(text, start)
        except ValueError:
            value = None
        if isinstance(value, expect) and (
            items is None or all(isinstance(v, items) for v in value)
        ):
            return value
        start = text.find(opener, start + 1)
    raise ValueError("AI 回覆中沒有可讀的 JSON")
