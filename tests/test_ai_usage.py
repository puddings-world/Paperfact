"""Official quota is never inferred from partial app-local usage receipts."""

import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication, QProgressBar

from paper_daily import ai_accounts, ai_usage, gemini_cli, llm
from paper_daily.ai_types import Settings
from paper_daily.desktop.ai_usage import AIUsageDialog, UsageSummary
from paper_daily.desktop.ask import AskRunner

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_codex_identity_uses_public_account_response_only(monkeypatch):
    calls = []

    def request(cfg, method, params):
        calls.append((method, params))
        return {
            "account": {
                "type": "chatgpt",
                "email": "me@example.org",
                "planType": "plus",
                "token": "secret",
            }
        }

    monkeypatch.setattr(ai_accounts, "codex_request", request)
    cfg = Settings("codex")
    assert ai_accounts.codex_identity(cfg) == {
        "type": "chatgpt",
        "email": "me@example.org",
        "planType": "plus",
    }
    status, reason = ai_accounts.auth(cfg, "status")
    assert "me@example.org" in status and "plus" in status and "secret" not in status
    assert reason == "ok"
    assert all(call == ("account/read", {"refreshToken": False}) for call in calls)


@pytest.mark.parametrize(
    "account,expected",
    [(None, "尚未登入"), ({"type": "apiKey"}, "API 金鑰"), ({"type": "chatgpt"}, "官方未提供信箱")],
)
def test_codex_status_distinguishes_missing_identity_and_api_login(monkeypatch, account, expected):
    monkeypatch.setattr(ai_accounts, "codex_identity", lambda cfg: account)
    label, reason = ai_accounts.auth(Settings("codex"), "status")
    assert expected in (label or reason)


def test_quota_preserves_each_official_bucket_and_window():
    result = ai_usage.quota_windows(
        {
            "rateLimitsByLimitId": {
                "codex": {
                    "limitName": "Codex",
                    "primary": {
                        "usedPercent": 12.5,
                        "windowDurationMins": 300,
                        "resetsAt": 1800000000,
                    },
                    "secondary": {"usedPercent": 0, "windowDurationMins": 10080},
                },
                "spark": {"primary": {"usedPercent": 100}},
            }
        }
    )
    assert [row["used"] for row in result] == [12.5, 0, 100]
    assert result[0]["minutes"] == 300 and result[1]["reset"] is None
    assert "5 小時" in ai_usage.describe_window(result[0])
    assert "7 天" in ai_usage.describe_window(result[1])
    assert "重設時間未知" in ai_usage.describe_window(result[1])


@pytest.mark.parametrize("value", [None, True, -1, 101, float("nan"), "20"])
def test_unknown_or_invalid_quota_never_looks_unused(value):
    assert ai_usage.quota_windows({"rateLimits": {"primary": {"usedPercent": value}}}) == []


def test_codex_subscription_uses_official_snapshot(monkeypatch):
    cfg = Settings("codex", account_id="a" * 32)
    monkeypatch.setattr(
        ai_accounts, "codex_identity", lambda chosen: {"type": "chatgpt", "planType": "pro"}
    )

    def request(chosen, method, params):
        assert chosen is cfg and method == "account/rateLimits/read" and params == {}
        return {"rateLimits": {"primary": {"usedPercent": 35}}}

    monkeypatch.setattr(ai_accounts, "codex_request", request)
    snapshot = ai_usage.subscription(cfg)
    assert snapshot["plan"] == "pro" and snapshot["windows"][0]["used"] == 35
    assert snapshot["checked_at"]


def test_quota_failure_is_unknown_and_error_body_not_displayed(monkeypatch):
    def fail(cfg):
        raise ValueError("sensitive response")

    monkeypatch.setattr(ai_accounts, "codex_identity", fail)
    snapshot = ai_usage.subscription(Settings("codex"))
    assert snapshot["windows"] == [] and "未知" in snapshot["message"]
    assert "sensitive" not in snapshot["message"]


def test_gemini_subscription_renders_official_model_percentages(monkeypatch):
    monkeypatch.setattr(gemini_cli, "usage", lambda cfg: {
        "plan": "Google AI Pro",
        "buckets": [
            {"modelId": "gemini-pro", "remainingFraction": .73,
             "resetTime": "2026-10-22T12:00:00Z"},
            {"modelId": "gemini-flash", "remainingFraction": 1},
            {"modelId": "gemini-other", "remainingFraction": 0},
        ],
    })
    snapshot = ai_usage.subscription(Settings("gemini"))
    assert snapshot["plan"] == "Google AI Pro" and snapshot["checked_at"]
    assert [w["used"] for w in snapshot["windows"]] == [27, 0, 100]
    assert snapshot["windows"][0]["reset"]
    assert snapshot["windows"][1]["reset"] is None
    assert "不可相加" in snapshot["message"]


@pytest.mark.parametrize("fraction", [None, True, -1, 1.01, float("nan"), "0.7"])
def test_gemini_unknown_quota_is_not_fabricated(fraction):
    assert ai_usage.gemini_windows([{"modelId": "gemini-pro", "remainingFraction": fraction}]) == []


def test_gemini_upstream_rejection_is_distinct_from_missing_quota(monkeypatch):
    monkeypatch.setattr(gemini_cli, "usage", lambda cfg: {
        "buckets": [], "needs_setup": True, "unsupported_client": True,
    })
    result = ai_usage.subscription(Settings("gemini"))
    assert not result["windows"] and "UNSUPPORTED_CLIENT" in result["message"]
    assert "完成帳號設定" not in result["message"]
    assert "服務已停止" in result["message"]
    assert "Paperfact 尚未串接" in result["message"]
    assert "Claude 或 Codex" in result["message"]
    assert "code-assist-individuals" in ai_usage.USAGE_LINKS["gemini"]
    monkeypatch.setattr(gemini_cli, "usage", lambda cfg: {"buckets": [], "needs_setup": True})
    assert "完成帳號設定" in ai_usage.subscription(Settings("gemini"))["message"]


def test_gemini_network_failure_does_not_leak_account_or_http_headers(monkeypatch):
    def fail(cfg):
        raise ValueError("secret access token")
    monkeypatch.setattr(gemini_cli, "usage", fail)
    snapshot = ai_usage.subscription(Settings("gemini"))
    assert not snapshot["windows"] and "/stats model" in snapshot["message"]
    assert "secret" not in snapshot["message"]


def test_model_quota_bars_match_labels_and_plan_and_reset_on_switch():
    app = QApplication.instance() or QApplication([])
    widget = UsageSummary()
    widget.reset(Settings("gemini"))
    widget.show_result({
        "plan": "Google AI Pro", "message": "official",
        "windows": ai_usage.gemini_windows([
            {"modelId": "gemini-pro", "remainingFraction": .73},
            {"modelId": "gemini-flash", "remainingFraction": 1},
        ]),
    }, None)
    assert "Google AI Pro" in widget.quota_status.text()
    assert widget.windows.itemAt(0).widget().text().startswith("gemini-pro")
    assert widget.windows.itemAt(1).widget().value() == 270
    assert not widget.windows.itemAt(1).widget().isTextVisible()
    assert widget.windows.itemAt(3).widget().value() == 0
    widget.reset(Settings("codex"))
    widget.show_result({"windows": [], "message": "unknown"}, None)
    assert not widget.windows.count() and widget.scroll.isHidden()
    assert "Google AI Pro" not in widget.quota_status.text()
    widget.deleteLater()
    app.processEvents()


def test_claude_official_snapshot_has_real_windows_without_a_model_call(monkeypatch):
    monkeypatch.setattr(ai_accounts, "claude_usage", lambda cfg: {
        "subscription_type": "max", "rate_limits_available": True,
        "rate_limits": {"five_hour": {"utilization": 5, "resets_at": "2026-10-20T17:00:00Z"},
                        "seven_day": {"utilization": 68, "resets_at": None}},
    })
    result = ai_usage.subscription(Settings("cli"))
    assert result["plan"] == "max" and result["checked_at"]
    assert [w["used"] for w in result["windows"]] == [5, 68]
    assert [w["minutes"] for w in result["windows"]] == [300, 10080]
    assert result["windows"][0]["reset"] and result["windows"][1]["reset"] is None


def test_claude_unsupported_version_is_explicit_and_private_error_hidden(monkeypatch):
    def unsupported(cfg):
        raise ValueError("private cli output")

    monkeypatch.setattr(ai_accounts, "claude_usage", unsupported)
    result = ai_usage.subscription(Settings("cli"))
    assert result["windows"] == [] and "CLI 版本" in result["message"]
    assert "private" not in result["message"] and "/usage" in result["message"]


@pytest.mark.parametrize("used", [None, True, -1, 101, float("nan"), "20"])
def test_claude_invalid_percentage_is_never_shown_as_zero(used):
    assert ai_usage.claude_windows({"five_hour": {"utilization": used}}) == []


def test_local_summary_filters_connection_time_and_incomplete_receipts(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    now = datetime(2026, 10, 19, tzinfo=UTC)
    base = {
        "timestamp": now.isoformat(),
        "backend": "codex",
        "account_id": "selected",
        "success": True,
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }
    rows = [
        base,
        {**base, "usage": {}, "success": False},
        {**base, "account_id": "other"},
        {**base, "backend": "cli"},
        {**base, "timestamp": (now - timedelta(days=8)).isoformat()},
        {**base, "timestamp": (now + timedelta(days=1)).isoformat()},
        {**base, "timestamp": "invalid"},
        {key: value for key, value in base.items() if key != "account_id"},
    ]
    (tmp_path / "ai-usage.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n{broken\n[]", encoding="utf-8"
    )
    assert ai_usage.local_summary(Settings("codex", account_id="selected"), now=now) == {
        "calls": 2,
        "failed": 1,
        "input": 100,
        "output": 20,
        "unknown": 1,
    }


def test_usage_dialog_refresh_clears_previous_quota_on_failure(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(ai_accounts, "auth", lambda cfg, action: ("me@example.org", "ok"))
    monkeypatch.setattr(
        ai_usage,
        "subscription",
        lambda cfg: {
            "windows": [{"label": "Codex", "used": 42, "minutes": 300, "reset": None}],
            "message": "official",
            "plan": "plus",
        },
    )

    def start(self, prompt, done, failed, call):
        value, reason = call(prompt)
        done(value)

    monkeypatch.setattr(AskRunner, "start", start)
    widget = AIUsageDialog(Settings("codex"))
    widget.show()
    app.processEvents()
    assert "me@example.org" in widget.account.text()
    assert widget.findChild(QProgressBar).value() == 420
    assert "0 次呼叫" in widget.local.text()
    monkeypatch.setattr(
        AskRunner, "start", lambda self, prompt, done, failed, call: failed("error")
    )
    widget.refresh()
    assert widget.windows.count() == 0
    assert "未知" in widget.quota_status.text() and widget.refresh_button.isEnabled()
    widget.reject()
    widget.deleteLater()
    app.processEvents()


@pytest.mark.parametrize(
    "local,expected",
    [
        (None, "暫時無法讀取"),
        ({"calls": 0, "failed": 0, "input": 0, "output": 0, "unknown": 0}, "尚無"),
        ({"calls": 2, "failed": 0, "input": 100, "output": 20, "unknown": 1}, "總量未知"),
        ({"calls": 2, "failed": 0, "input": 100, "output": 20, "unknown": 0}, "輸入 100／輸出 20"),
        ({"calls": 1, "failed": 0, "input": 0, "output": 0, "unknown": 0}, "輸入 0／輸出 0"),
    ],
)
def test_inline_receipts_distinguish_missing_partial_and_reported_zero(local, expected):
    app = QApplication.instance() or QApplication([])
    widget = UsageSummary()
    widget.reset(Settings("cli"))
    widget.show_result({"windows": [], "message": "unknown quota"}, local)
    assert expected in widget.local.text()
    assert widget.refresh_button.isEnabled()
    widget.deleteLater()
    app.processEvents()
