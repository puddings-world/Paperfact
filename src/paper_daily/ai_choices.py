"""Account/model choices for the simple picker; advanced routes stay independent."""

from dataclasses import replace
from uuid import uuid4

from paper_daily import ai_profiles, llm, model_catalog
from paper_daily.ai_types import Settings

LABELS = {"cli": "Claude", "codex": "Codex", "gemini": "Gemini"}
# Google ended Gemini CLI for personal accounts on 2026-06-18 and does not permit
# third-party tools to drive Antigravity with a subscription login, so a personal
# Gemini account reaches Paperfact through an AI Studio key on this endpoint.
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_API_PROFILE = "gemini-api"
_account_labels = {}


def is_gemini_api(cfg):
    return cfg.backend == "openai" and (cfg.base_url or "").rstrip("/") == GEMINI_API_URL


def uses_key(cfg):
    return cfg.backend in ("anthropic", "openai", "gateway")


def brand(cfg):
    return "Gemini" if is_gemini_api(cfg) else LABELS.get(cfg.backend, cfg.backend)


def remember_identity(cfg, text):
    _account_labels[account_key(cfg)] = text


def account_label(cfg):
    if is_gemini_api(cfg):
        return "API 金鑰 · 按用量計費" if cfg.api_key else "尚未輸入 API 金鑰"
    if cfg.backend not in LABELS:
        return cfg.profile or "API 連線"
    return _account_labels.get(account_key(cfg)) or (
        f"{cfg.profile or '獨立帳號'}（待確認）" if cfg.account_id else "本機帳號（待確認）"
    )


def account_title(cfg):
    """Readable identity for pickers; aliases never replace the account identity."""
    label = account_label(cfg).removeprefix("已登入：")
    names = ai_profiles.load(llm.SETTINGS_PATH).get("account_names", {})
    nickname = names.get(f"{cfg.backend}:{cfg.account_id or 'local'}", "")
    return f"{nickname} · {label}" if nickname else label


def rename_account(cfg, nickname):
    nickname = nickname.strip()
    if len(nickname) > 40 or any(ord(char) < 32 for char in nickname):
        raise ValueError("帳號暱稱限 40 字，不能包含換行。")
    data = ai_profiles.load(llm.SETTINGS_PATH)
    identity = f"{cfg.backend}:{cfg.account_id or 'local'}"
    names = data.setdefault("account_names", {})
    if nickname:
        names[identity] = nickname
    else:
        names.pop(identity, None)
    ai_profiles.write(llm.SETTINGS_PATH, data)


def dependents(cfg):
    identity = account_key(cfg)
    result = ["default"] if account_key(llm.settings()) == identity else []
    return result + [task for task in llm.task_routes()
                     if account_key(llm.settings(task=task)) == identity]


def forget_account(cfg):
    """Remove unused app connections only; vendor-owned credentials are untouched."""
    if dependents(cfg):
        raise ValueError("此帳號仍被使用，請先變更全域預設與個別功能的分配。")
    data = ai_profiles.load(llm.SETTINGS_PATH)
    profiles = data.get("profiles", {})
    names = [name for name in profiles
             if account_key(llm.settings(profile=name)) == account_key(cfg)]
    if not names:
        raise ValueError("這是本機共用登入，沒有可移除的 Paperfact 連線。")
    for name in names:
        del profiles[name]
    data.get("account_names", {}).pop(f"{cfg.backend}:{cfg.account_id or 'local'}", None)
    ai_profiles.write(llm.SETTINGS_PATH, data)
    _account_labels.pop(account_key(cfg), None)


def account_options(backend, preferred=None):
    """One row per login, retaining a requested profile's configuration."""
    options = {}
    for cfg in choices(backend):
        identity = account_key(cfg)
        if identity not in options or cfg.profile == preferred:
            options[identity] = cfg
    return list(options.values())


def model_label(cfg):
    return model_option_label(cfg.backend, cfg.model, cfg=cfg)


def model_option_label(backend, model, *, cfg=None):
    """Keep routing IDs separate from human-readable alias/default descriptions."""
    if not model:
        name = brand(cfg) if cfg else LABELS.get(backend, "服務")
        known = model_catalog.name(cfg, "") if cfg else None
        return f"{name} 預設：{known}" if known else f"使用 {name} 預設模型"
    known = model_catalog.name(cfg, model) if cfg else None
    if known:
        return known
    if backend == "cli" and model in {"sonnet", "opus", "haiku", "opusplan", "fable"}:
        return model.capitalize()
    return model


def model_hint(backend, model, *, cfg=None):
    if cfg and is_gemini_api(cfg):
        return (
            "以 Google AI Studio 的 API 金鑰呼叫，按用量計費；Google AI Pro / Ultra 訂閱額度"
            "不適用。Gemini 4 Argon 需要付費層級。"
        )
    if backend == "gemini":
        return (
            "個人 Google 帳號已無法使用 Gemini CLI，請改用「Gemini」的 API 金鑰；"
            "此項僅供企業版 Google 帳號。模型選單為常用 ID，不代表帳號已獲授權。"
        )
    if not model:
        return "使用此帳號目前的預設模型；也可以在上方直接選擇其他模型。"
    if cfg and model_catalog.name(cfg, model):
        return "模型名稱由官方服務提供；用量與使用權限依你的方案計算。"
    return "使用你指定的模型；用量與使用權限依你的方案計算。"


def connection_label(cfg):
    if cfg.backend == "none":
        return "AI 未啟用"
    return f"{brand(cfg)} · {account_title(cfg)} · {model_label(cfg)}"


HELP = {
    "cli": "https://code.claude.com/docs/en/setup",
    "codex": "https://developers.openai.com/codex/cli/",
    "gemini": "https://geminicli.com/docs/get-started/installation/",
}


def _under(cfg, backend):
    """Whether a connection is listed under that provider's button."""
    return cfg.backend == backend or (backend == "gemini" and is_gemini_api(cfg))


def choices(backend):
    result = []
    for name in llm.profile_names():
        cfg = llm.settings(profile=name)
        if _under(cfg, backend):
            result.append(cfg)
    current = llm.settings()
    if _under(current, backend) and not any(cfg.profile == current.profile for cfg in result):
        result.insert(0, current)
    if backend == "gemini":
        # A personal account can only use a key, so that is what Gemini offers first;
        # an existing Workspace CLI login stays listed after it.
        result.sort(key=lambda cfg: not is_gemini_api(cfg))
        if not any(is_gemini_api(cfg) for cfg in result):
            result.insert(0, Settings("openai", base_url=GEMINI_API_URL))
    if not result:
        result.append(Settings(backend, isolated=True))
    return result


def account_key(cfg):
    if cfg.backend in LABELS:
        return cfg.backend, cfg.account_id or "local"
    return cfg.backend, cfg.profile


def accounts():
    """Reusable accounts, independent of models or task assignments."""
    current = llm.settings()
    candidates = [current, *(llm.settings(profile=name) for name in llm.profile_names())]
    result = {}
    used = set(llm.task_routes().values())
    for cfg in candidates:
        if cfg.backend in LABELS or cfg.profile in used or is_gemini_api(cfg):
            result.setdefault(account_key(cfg), cfg)
    return list(result.values())


def new_account(backend, model=None):
    account = uuid4().hex
    return Settings(
        backend,
        model=model,
        isolated=True,
        account_id=account,
        cli_home=str((llm.SETTINGS_PATH.parent / "ai-accounts" / backend / account).resolve()),
    )


def save_gemini_key(key, model, *, profile=None):
    """Store an AI Studio key as its own connection; replacing a key keeps its name."""
    key = key.strip()
    if not key or any(char.isspace() for char in key):
        raise ValueError("請貼上 Google AI Studio 的 API 金鑰。")
    name = profile
    if not name:
        name, number = GEMINI_API_PROFILE, 2
        while name in llm.profile_names():
            name = f"{GEMINI_API_PROFILE}-{number}"
            number += 1
    llm.save_settings(
        profile=name,
        backend="openai",
        base_url=GEMINI_API_URL,
        api_key=key,
        requires_key=True,
        model=model or "",
    )
    return llm.settings(profile=name)


def save(cfg, model, *, activate=True):
    """Save one choice without silently discarding task overrides or legacy defaults."""
    if uses_key(cfg):
        if not cfg.profile:
            raise ValueError("請先輸入 API 金鑰。")
        llm.save_settings(profile=cfg.profile, model=model or "")
        if activate:
            llm.use_profile(cfg.profile, desktop=True)
        return replace(llm.settings(profile=cfg.profile), model=model or None)
    data = ai_profiles.load(llm.SETTINGS_PATH)
    names = llm.profile_names()
    if not activate and not names and not any(field in data for field in ai_profiles.FIELDS):
        # Login may finish before the user chooses to use the account.
        llm.save_settings(profile="default", backend="auto")
    name = cfg.profile
    if not name:
        stem = "account-" + ("claude" if cfg.backend == "cli" else cfg.backend)
        name = stem
        number = 2
        while name in llm.profile_names():
            name = f"{stem}-{number}"
            number += 1
    llm.save_settings(
        profile=name,
        backend=cfg.backend,
        model=model or "",
        isolated=True,
        account_id=cfg.account_id or "",
    )
    if activate:
        llm.use_profile(name, desktop=True)
    return replace(llm.settings(profile=name), model=model or None)
