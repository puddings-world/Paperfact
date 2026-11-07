"""Localized CLI failures keep stable categories and never reflect private error bodies."""

import json
from types import SimpleNamespace

import pytest

from paper_daily import ai_providers, dive, llm
from paper_daily.ai_types import Settings


@pytest.mark.parametrize(
    "message,word,kind,fatal",
    [
        ("API Error: 400 output blocked by usage policy", "使用政策", "policy", False),
        ("Error: usage limit reached", "用量", "limit", True),
        ("Execution error: authentication failed", "重新登入", "auth", True),
        ("API Error: 500 service error", "API Error: 500", "error", False),
        ("Error: rate limit reached", "速率上限", "limit", False),
        ("API Error: 429 request throttled", "速率上限", "limit", False),
        ("Error: overloaded", "速率上限", "limit", False),
    ],
)
def test_failed_cli_retains_localized_action_category_and_private_receipt(
    tmp_path, monkeypatch, message, word, kind, fatal
):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(llm, "ACCESS_CHECK", None)
    monkeypatch.setattr(ai_providers.shutil, "which", lambda _name: "fixture-claude")
    private = "private-paper private-account@example.test sk-ant-" + "x" * 40
    monkeypatch.setattr(
        ai_providers.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0, stdout=message + " " + private, stderr=private
        ),
    )
    result = llm.complete_result("private prompt", cfg=Settings("cli"), task="ask")
    assert result.text is None and word in result.reason
    assert (
        len(result.reason) < 200 and "private" not in result.reason and "sk-" not in result.reason
    )
    assert llm.failure_kind(result.reason) == kind and dive._fatal(result.reason) is fatal
    row = json.loads((tmp_path / "ai-usage.jsonl").read_text("utf-8"))
    assert row["failure"] == kind and row["success"] is False
    assert "private" not in json.dumps(row) and "sk-" not in json.dumps(row)


@pytest.mark.parametrize(
    "text", ["API Error: 500000 private", "API Error: 500private", "prefix API Error: 500 private"]
)
def test_unknown_error_body_is_not_shortened_into_an_apparent_status(text):
    assert ai_providers._cli_failure("fixture", text, "") is None


@pytest.mark.parametrize(
    "reason", ["請重新登入", "已達用量限制", "HTTP 401", "out of usage credits"]
)
def test_bulk_stops_for_account_or_limit_categories_in_either_language(reason):
    assert dive._fatal(reason)


@pytest.mark.parametrize("reason", ["因使用政策拒絕", "API Error: 500", "timed out after 5s"])
def test_per_document_policy_and_transient_errors_do_not_stop_every_paper(reason):
    assert not dive._fatal(reason)
