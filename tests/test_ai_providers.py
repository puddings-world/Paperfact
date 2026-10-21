"""Offline provider contracts, reported usage, privacy, and retry behavior."""

import json
from types import SimpleNamespace

import httpx
import pytest

from paper_daily import ai_providers, llm
from paper_daily.ai_types import Completion, Settings


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    return tmp_path


def test_openai_usage_and_provider_receipt_are_preserved(isolated, monkeypatch):
    seen = {}

    def fake_post(url, headers, payload, timeout):
        seen.update(url=url, headers=headers, payload=payload)
        return {
            "id": "reply-1",
            "model": "actual-model",
            "choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 12,
                "prompt_tokens_details": {"cached_tokens": 20},
            },
        }, "ok"

    monkeypatch.setattr(llm, "_post", fake_post)
    cfg = Settings("openai", model="requested", api_key="secret", max_tokens=500)
    reply = llm.complete_result("private-paper", system="private-rules", cfg=cfg, task="ask")
    assert reply.text == "answer" and reply.model == "actual-model"
    assert reply.usage.input_tokens == 50 and reply.usage.output_tokens == 12
    assert reply.usage.cached_input_tokens == 20 and reply.provider_request_id == "reply-1"
    assert seen["payload"]["max_completion_tokens"] == 500
    log = (isolated / "ai-usage.jsonl").read_text(encoding="utf-8")
    assert all(
        private not in log for private in ("private-paper", "private-rules", "secret", '"answer"')
    )
    assert json.loads(log)["task"] == "ask"


def test_anthropic_input_usage_includes_both_cache_categories(isolated, monkeypatch):
    monkeypatch.setattr(
        llm,
        "_post",
        lambda *args: (
            {
                "content": [{"type": "text", "text": "answer"}],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 8,
                    "cache_read_input_tokens": 20,
                    "cache_creation_input_tokens": 30,
                },
            },
            "ok",
        ),
    )
    result = llm.complete_result("paper", cfg=Settings("anthropic", api_key="secret"))
    assert result.usage.input_tokens == 60
    assert result.usage.output_tokens == 8 and result.usage.cached_input_tokens == 20
    assert result.usage.cache_creation_tokens == 30


def test_local_endpoint_can_omit_authorization_and_use_legacy_token_parameter(
    isolated, monkeypatch
):
    seen = {}

    def fake_post(url, headers, payload, timeout):
        seen.update(headers=headers, payload=payload)
        return {"choices": [{"message": {"content": "answer"}}]}, "ok"

    monkeypatch.setattr(llm, "_post", fake_post)
    cfg = Settings(
        "openai",
        model="local",
        base_url="http://localhost:11434/v1/",
        requires_key=False,
        token_parameter="max_tokens",
    )
    result = llm.complete_result("paper", cfg=cfg)
    assert "Authorization" not in seen["headers"] and "max_tokens" in seen["payload"]
    assert result.usage.input_tokens is None and result.usage.output_tokens is None


def test_gateway_retries_rate_limits_with_one_idempotency_key(isolated, monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429)
        return httpx.Response(
            200,
            json={
                "id": "receipt-1",
                "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    original = httpx.Client
    monkeypatch.setattr(
        llm.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    monkeypatch.setattr(llm.time, "sleep", lambda _secs: None)
    cfg = Settings(
        "gateway", model="research", base_url="https://service.example/v1", api_key="account-token"
    )
    result = llm.complete_result("paper", cfg=cfg, task="dive")
    assert result.text == "answer" and len(requests) == 2
    assert (
        requests[0].headers["Idempotency-Key"]
        == requests[1].headers["Idempotency-Key"]
        == result.request_id
    )
    assert requests[0].headers["X-Paperfact-Task"] == "dive"
    assert requests[0].headers["Authorization"] == "Bearer account-token"
    second = llm.complete_result("paper", cfg=cfg, task="dive")
    assert second.request_id != result.request_id


def test_a_lost_response_is_not_resubmitted_or_switched_to_another_provider(isolated, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("private response details", request=request)

    original = httpx.Client
    monkeypatch.setattr(
        llm.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    cfg = Settings("openai", api_key="secret")
    result = llm.complete_result("private prompt", cfg=cfg)
    assert result.text is None and len(calls) == 1
    assert "no automatic retry" in result.reason
    assert "private" not in result.reason and "secret" not in result.reason


def test_error_bodies_are_not_exposed(isolated, monkeypatch):
    original = httpx.Client
    monkeypatch.setattr(
        llm.httpx,
        "Client",
        lambda **kw: original(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(402, json={"error": "private prompt and secret"})
            ),
            **kw,
        ),
    )
    result = llm.complete_result("paper", cfg=Settings("openai", api_key="secret"))
    assert result.reason == "HTTP 402: quota or credits exhausted"
    assert "private" not in (isolated / "ai-usage.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "cfg",
    [
        Settings("gateway", model="research", api_key="token"),
        Settings("gateway", base_url="https://service.example/v1", api_key="token"),
        Settings(
            "gateway", model="research", base_url="https://service.example/v1", requires_key=False
        ),
        Settings("openai", api_key="token", base_url="https://user:secret@example.com/v1"),
    ],
)
def test_invalid_connections_do_not_reach_the_network(isolated, monkeypatch, cfg):
    monkeypatch.setattr(llm, "_post", lambda *args: pytest.fail("must not send this request"))
    assert llm.complete_result("paper", cfg=cfg).text is None


def test_truncated_replies_are_reported_and_still_record_usage(isolated, monkeypatch):
    monkeypatch.setattr(
        llm,
        "_post",
        lambda *args: (
            {
                "choices": [{"message": {"content": "unfinished"}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
            "ok",
        ),
    )
    result = llm.complete_result("paper", cfg=Settings("openai", api_key="secret"))
    assert result.text is None and "truncated" in result.reason
    assert result.usage.output_tokens == 5
    assert json.loads((isolated / "ai-usage.jsonl").read_text())["success"] is False


def test_successful_answer_survives_a_read_only_usage_log(isolated, monkeypatch):
    monkeypatch.setattr(
        llm, "_post", lambda *args: ({"choices": [{"message": {"content": "answer"}}]}, "ok")
    )
    monkeypatch.setattr(llm.os, "open", lambda *args: (_ for _ in ()).throw(OSError("read only")))
    assert llm.complete("paper", cfg=Settings("openai", api_key="secret")) == ("answer", "ok")


def test_cli_honors_model_and_rejects_partial_output_from_a_failed_process(isolated, monkeypatch):
    monkeypatch.setattr(ai_providers.shutil, "which", lambda name: "claude")
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return SimpleNamespace(returncode=1, stdout="partial", stderr="private secret")

    monkeypatch.setattr(ai_providers.subprocess, "run", fake_run)
    result = llm.complete_result("private prompt", cfg=Settings("cli", model="chosen"))
    assert seen["argv"] == ["claude", "-p", "--model", "chosen"]
    assert result.text is None and "private" not in result.reason
    assert result.usage.input_tokens is None


def test_an_adapter_can_be_added_without_changing_feature_code(isolated, monkeypatch):
    monkeypatch.setattr(llm, "_PROVIDERS", dict(llm._PROVIDERS))

    class Custom:
        def complete(self, request, cfg, post):
            assert request.task == "ask"
            return Completion("custom reply")

    llm.register_provider("custom", Custom())
    assert llm.complete("paper", cfg=Settings("custom"), task="ask") == ("custom reply", "ok")
    with pytest.raises(ValueError, match="already registered"):
        llm.register_provider("custom", Custom())
