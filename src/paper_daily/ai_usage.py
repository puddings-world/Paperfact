"""Subscription snapshots and app-local receipts are deliberately distinct."""

from __future__ import annotations

import json
import math
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from paper_daily import ai_accounts, llm

USAGE_LINKS = {
    "cli": "https://claude.ai/settings/usage",
    "codex": "https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt",
}


def quota_windows(payload):
    buckets = payload.get("rateLimitsByLimitId")
    if not isinstance(buckets, dict) or not buckets:
        buckets = {"codex": payload.get("rateLimits")}
    windows = []
    for key, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        for slot in ("primary", "secondary"):
            raw = bucket.get(slot)
            if not isinstance(raw, dict):
                continue
            used = raw.get("usedPercent")
            if type(used) not in (float, int) or not math.isfinite(used) or not 0 <= used <= 100:
                continue
            minutes, resets = raw.get("windowDurationMins"), raw.get("resetsAt")
            label = bucket.get("limitName") or key
            windows.append(
                {
                    "label": str(label),
                    "used": used,
                    "minutes": minutes if type(minutes) is int and minutes > 0 else None,
                    "reset": resets if type(resets) is int and resets > 0 else None,
                }
            )
    return windows


def subscription(cfg):
    if cfg.backend == "cli":
        try:
            raw = ai_accounts.claude_usage(cfg)
            windows = claude_windows(raw.get("rate_limits"))
            return {
                "windows": windows, "plan": raw.get("subscription_type"),
                "message": "Claude 官方方案用量（包含其他 Claude 介面的使用）。"
                if windows else "官方未提供此帳號的方案額度，剩餘量未知。",
                "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
        except (OSError, ValueError, TimeoutError):
            return {"windows": [], "message": "無法讀取 Claude 官方用量；請確認登入與 CLI 版本，"
                    "或按「官方用量查詢」（Claude Code 的 /usage）。"}
    if cfg.backend != "codex":
        return {"windows": [], "message": "此連線未提供方案額度查詢。"}
    try:
        account = ai_accounts.codex_identity(cfg)
        if not account:
            return {"windows": [], "message": "尚未登入 Codex，無法取得方案額度。"}
        if account.get("type") not in ("chatgpt", "chatgptAuthTokens"):
            return {"windows": [], "message": "此登入方式未提供 ChatGPT 訂閱額度。"}
        payload = ai_accounts.codex_request(cfg, "account/rateLimits/read", {})
        windows = quota_windows(payload)
        return {
            "windows": windows,
            "plan": account.get("planType"),
            "message": "官方方案用量，包含此帳號在其他 Codex 介面的使用。"
            if windows
            else "官方未回傳可顯示的額度資料，剩餘量未知。",
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
    except (ValueError, OSError, TimeoutError):
        return {"windows": [], "message": "暫時無法取得官方額度，剩餘量未知；可稍後重新整理。"}


def claude_windows(raw):
    if not isinstance(raw, dict):
        return []
    windows = []
    for key, label, minutes in (
        ("five_hour", "Claude", 300), ("seven_day", "Claude", 10080),
        ("seven_day_opus", "Opus", 10080), ("seven_day_sonnet", "Sonnet", 10080),
        ("seven_day_oauth_apps", "OAuth apps", 10080),
    ):
        bucket = raw.get(key)
        if not isinstance(bucket, dict):
            continue
        used = bucket.get("utilization")
        if type(used) not in (float, int) or not math.isfinite(used) or not 0 <= used <= 100:
            continue
        reset = None
        with suppress(ValueError, TypeError, OverflowError):
            stamp = datetime.fromisoformat(bucket.get("resets_at"))
            if stamp.tzinfo is not None:
                reset = int(stamp.timestamp())
        windows.append({"label": label, "used": used, "minutes": minutes, "reset": reset})
    return windows


def local_summary(cfg, *, now=None):
    """Only receipts tagged with this connection count; old untagged rows stay unknown."""
    now = now or datetime.now(UTC)
    since = now - timedelta(days=7)
    result = {"calls": 0, "failed": 0, "input": 0, "output": 0, "unknown": 0}
    path = llm.SETTINGS_PATH.parent / "ai-usage.jsonl"
    if not path.exists():
        return result
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
                if not isinstance(row, dict) or "account_id" not in row:
                    continue
                if row.get("backend") != cfg.backend or row["account_id"] != cfg.account_id:
                    continue
                if not since <= datetime.fromisoformat(row["timestamp"]) <= now:
                    continue
            except (ValueError, TypeError, KeyError):
                continue
            result["calls"] += 1
            result["failed"] += row.get("success") is False
            usage = row.get("usage")
            usage = usage if isinstance(usage, dict) else {}
            missing = False
            for key in ("input", "output"):
                value = usage.get(key + "_tokens")
                if type(value) is int and value >= 0:
                    result[key] += value
                else:
                    missing = True
            result["unknown"] += missing
    return result


def describe_window(window):
    minutes = window["minutes"]
    duration = (
        f"{minutes / 1440:g} 天"
        if minutes and minutes % 1440 == 0
        else f"{minutes / 60:g} 小時"
        if minutes and minutes % 60 == 0
        else f"{minutes} 分鐘"
        if minutes
        else "官方時段"
    )
    reset = "重設時間未知"
    if window["reset"]:
        with suppress(ValueError, OSError, OverflowError):
            reset = "重設：" + datetime.fromtimestamp(window["reset"]).astimezone().strftime(
                "%m/%d %H:%M %Z"
            )
    return f"{window['label']} · {duration}：已用 {window['used']:g}% · {reset}"
