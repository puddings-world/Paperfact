"""Local AI profiles and task routing, independent of the reader database."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from paper_daily.ai_types import DEFAULT_MAX_TOKENS, Settings

FIELDS = {
    "backend",
    "model",
    "api_key",
    "base_url",
    "api_key_env",
    "max_tokens",
    "token_parameter",
    "requires_key",
    "isolated",
    "account_id",
}
CONNECTION_FIELDS = {
    "model",
    "api_key",
    "base_url",
    "api_key_env",
    "token_parameter",
    "requires_key",
    "account_id",
}
TASKS = (
    "ask",
    "translate",
    "dive",
    "list_parse",
    "citations",
    "followups",
    "overview",
    "compare",
    "survey",
    "slides",
    "paper_highlights",
)


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("AI settings are invalid JSON; repair the file before saving") from exc
    if not isinstance(data, dict):
        raise ValueError("AI settings must be a JSON object")
    for key in ("profiles", "routes", "route_models", "account_names"):
        if key in data and not isinstance(data[key], dict):
            raise ValueError(f"AI {key} must be a JSON object")
    if any(not isinstance(value, str) for value in data.get("route_models", {}).values()):
        raise ValueError("Task models must be text")
    if any(not isinstance(value, str) for value in data.get("account_names", {}).values()):
        raise ValueError("Account names must be text")
    return data


def write(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=".llm-",
        delete=False,
    ) as handle:
        temp = Path(handle.name)
        json.dump(data, handle, indent=2)
        handle.write("\n")
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return path


def fields(data: dict, profile: str | None = None) -> dict:
    profile = profile or data.get("active_profile")
    if profile is None:
        return {key: value for key, value in data.items() if key in FIELDS}
    raw = data.get("profiles", {}).get(profile)
    if not isinstance(raw, dict):
        raise ValueError(f"Unknown AI profile: {profile}")
    return dict(raw)


def _migrate(data: dict) -> None:
    if "profiles" not in data:
        legacy = {key: data.pop(key) for key in FIELDS if key in data}
        data["profiles"] = {"default": legacy} if legacy else {}
        if legacy:
            data["active_profile"] = "default"
    data["version"] = 2


def validate(raw: dict, backends: tuple[str, ...]) -> None:
    if raw.get("backend", "auto") not in (*backends, "auto"):
        raise ValueError("Unknown AI backend")
    limit = raw.get("max_tokens", DEFAULT_MAX_TOKENS)
    if type(limit) is not int or limit < 1:
        raise ValueError("max_tokens must be a positive integer")
    if raw.get("token_parameter", "max_completion_tokens") not in (
        "max_completion_tokens",
        "max_tokens",
    ):
        raise ValueError("token_parameter must be max_completion_tokens or max_tokens")
    if type(raw.get("requires_key", True)) is not bool:
        raise ValueError("requires_key must be true or false")
    if type(raw.get("isolated", False)) is not bool:
        raise ValueError("isolated must be true or false")
    account = raw.get("account_id")
    if account is not None and (
        not isinstance(account, str) or (account and not re.fullmatch(r"[a-f0-9]{32}", account))
    ):
        raise ValueError("Invalid account ID")
    for key in ("model", "api_key", "base_url", "api_key_env"):
        if key in raw and raw[key] is not None and not isinstance(raw[key], str):
            raise ValueError(f"{key} must be text")
    if raw.get("api_key_env") and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw["api_key_env"]):
        raise ValueError("api_key_env must name an environment variable")


def save(path: Path, profile: str | None, backends: tuple[str, ...], **updates) -> Path:
    if set(updates) - FIELDS:
        raise ValueError("Unknown AI setting")
    data = load(path)
    if profile is not None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", profile):
            raise ValueError(
                "Profile names must use 1-64 letters, digits, dots, underscores or dashes"
            )
        _migrate(data)
    profile = profile or data.get("active_profile")
    raw = dict(data.get("profiles", {}).get(profile, {})) if profile else fields(data)
    updates = {key: value for key, value in updates.items() if value is not None}
    new_backend = updates.get("backend")
    if new_backend is not None and new_backend != raw.get("backend", "auto"):
        for key in CONNECTION_FIELDS:
            raw.pop(key, None)
    if "base_url" in updates and (updates["base_url"] or "") != (raw.get("base_url") or ""):
        # A key for one host must not silently follow an endpoint change.
        raw.pop("api_key", None)
        raw.pop("api_key_env", None)
    raw.update(updates)
    validate(raw, backends)
    if profile:
        data.setdefault("profiles", {})[profile] = raw
        if not data.get("active_profile"):
            data["active_profile"] = profile
    else:
        for key in FIELDS:
            data.pop(key, None)
        data.update(raw)
    return write(path, data)


def use(path: Path, profile: str, task: str | None = None, *, desktop=False) -> Path:
    data = load(path)
    fields(data, profile)
    if desktop:
        data["prefer_saved_profiles"] = True
    if task:
        if task not in TASKS:
            raise ValueError(f"Unknown AI task: {task}")
        data.setdefault("routes", {})[task] = profile
        data.get("route_models", {}).pop(task, None)
    else:
        data["active_profile"] = profile
    return write(path, data)


def unroute(path: Path, task: str) -> Path:
    if task not in TASKS:
        raise ValueError(f"Unknown AI task: {task}")
    data = load(path)
    data.get("routes", {}).pop(task, None)
    data.get("route_models", {}).pop(task, None)
    return write(path, data)


def assign(path: Path, selections: dict, backends: tuple[str, ...]) -> Path:
    """Save account/model choices atomically without changing shared accounts."""
    data = load(path)
    for task, selection in selections.items():
        if task not in TASKS:
            raise ValueError(f"Unknown AI task: {task}")
        if selection is None:
            data.get("routes", {}).pop(task, None)
            data.get("route_models", {}).pop(task, None)
            continue
        cfg, model = selection
        if model is not None and not isinstance(model, str):
            raise ValueError("Task models must be text")
        if "profiles" not in data:
            # Creating a task choice must preserve the implicit/legacy default.
            if not any(key in data for key in FIELDS):
                data["backend"] = "auto"
            _migrate(data)
        name = cfg.profile
        if name:
            fields(data, name)
        else:
            if cfg.backend not in ("cli", "codex", "gemini"):
                raise ValueError("Sign in to an AI account first")
            raw = {"backend": cfg.backend, "isolated": True, "account_id": cfg.account_id or ""}
            validate(raw, backends)
            name = next((key for key, value in data["profiles"].items() if value == raw), None)
            if name is None:
                stem = "account-" + cfg.backend
                name = stem
                number = 2
                while name in data["profiles"]:
                    name = f"{stem}-{number}"
                    number += 1
                data["profiles"][name] = raw
        data.setdefault("routes", {})[task] = name
        data.setdefault("route_models", {})[task] = (model or "").strip()
    data["prefer_saved_profiles"] = True
    return write(path, data)


def resolve(
    data: dict,
    task: str = "default",
    profile: str | None = None,
    *,
    backends: tuple[str, ...],
    environ=None,
    accounts_dir: Path | None = None,
) -> Settings:
    explicit_profile = profile
    env = (os.environ if environ is None else environ).get
    saved = data.get("routes", {}).get(task) or data.get("active_profile")
    profile = (
        profile
        or (saved if data.get("prefer_saved_profiles") else None)
        or env("PAPERFACT_PROFILE")
        or env("PAPER_DAILY_PROFILE")
        or data.get("routes", {}).get(task)
        or data.get("active_profile")
    )
    raw = fields(data, profile)
    validate(raw, backends)
    isolated = raw.get("isolated", False)
    inherited_env = env
    if isolated:

        def env(_key):
            return None

    stored_backend = raw.get("backend", "auto")
    backend = (env("PAPERFACT_LLM") or env("PAPER_DAILY_LLM") or stored_backend).lower()
    if backend != stored_backend:
        raw = {key: value for key, value in raw.items() if key not in CONNECTION_FIELDS}
    model = env("PAPERFACT_MODEL") or env("PAPER_DAILY_MODEL") or raw.get("model")
    base = env("PAPERFACT_BASE_URL") or env("PAPER_DAILY_BASE_URL") or raw.get("base_url")
    if backend == "auto":
        if shutil.which("claude"):
            backend = "cli"
        elif env("ANTHROPIC_API_KEY"):
            backend = "anthropic"
        elif env("OPENAI_API_KEY") or env("OPENAI_BASE_URL"):
            backend = "openai"
        else:
            backend = "none"
    if backend == "openai":
        base = (
            env("PAPERFACT_BASE_URL")
            or env("PAPER_DAILY_BASE_URL")
            or env("OPENAI_BASE_URL")
            or base
        )
    key_env = raw.get("api_key_env") or {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gateway": "PAPERFACT_API_KEY",
    }.get(backend)
    if isolated:
        key_env = raw.get("api_key_env") or None
        key = inherited_env(key_env) if key_env else raw.get("api_key")
    else:
        key = (env(key_env) if key_env else None) or raw.get("api_key")
    account_id = raw.get("account_id") or None
    if (
        explicit_profile is None
        and task in data.get("routes", {})
        and profile == data.get("routes", {}).get(task)
        and task in data.get("route_models", {})
    ):
        model = data["route_models"][task] or None
    cli_home = str(accounts_dir / backend / account_id) if accounts_dir and account_id else None
    return Settings(
        backend=backend,
        model=model,
        base_url=base,
        api_key=key,
        profile=profile,
        api_key_env=key_env,
        max_tokens=raw.get("max_tokens", DEFAULT_MAX_TOKENS),
        token_parameter=raw.get("token_parameter", "max_completion_tokens"),
        requires_key=raw.get("requires_key", True),
        isolated=isolated,
        account_id=account_id,
        cli_home=cli_home,
    )
