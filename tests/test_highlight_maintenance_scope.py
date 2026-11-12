"""Resuming highlight chunks preserves sources and actual provider attribution."""

import json

import pytest

from paper_daily import paper_highlights as highlights


@pytest.fixture
def original(tmp_path, monkeypatch):
    from test_paper_highlights import original

    return original.__wrapped__(tmp_path, monkeypatch)


def long_paper(monkeypatch):
    from test_paper_highlights import PAGES

    monkeypatch.setattr(highlights, "CHUNK_CHARS", 1100)
    pages = [dict(p, text=("Context " * 75) + p["text"]) for p in PAGES]
    monkeypatch.setattr(highlights, "read_original", lambda _pid: pages)
    return pages


def fail_second_chunk(monkeypatch):
    from types import SimpleNamespace

    from test_paper_highlights import choice, fake_reply

    calls = []

    def complete(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            reply = fake_reply({"items": [choice()]})
            reply.request_id = "first-original-call"
            return reply
        return SimpleNamespace(text=None, reason="timed out after 900s")

    monkeypatch.setattr(highlights.llm, "complete_result", complete)
    assert highlights.generate("paper", cfg="route-A")[0] is None
    assert len(calls) == 2
    assert not highlights._path("paper").exists()
    return highlights._path("paper").with_suffix(".chunks.json")


def test_resume_keeps_original_chunk_receipt_and_removes_progress_only_after_full_save(
    original,
    monkeypatch,
):
    from test_paper_highlights import choice, fake_reply

    long_paper(monkeypatch)
    progress = fail_second_chunk(monkeypatch)
    assert progress.exists()
    calls = []

    def complete(prompt, **kwargs):
        calls.append(prompt)
        reply = fake_reply({"items": [choice()]} if len(calls) == 1 else {"ids": [1, 0]})
        reply.request_id = "second-chunk" if len(calls) == 1 else "final-rank"
        return reply

    monkeypatch.setattr(highlights.llm, "complete_result", complete)
    result, reason = highlights.generate("paper", cfg="route-A")
    assert reason == "ok" and len(calls) == 2 and "2/2" in calls[0]
    assert [r["request_id"] for r in result["generation"]] == [
        "first-original-call",
        "second-chunk",
        "final-rank",
    ]
    assert highlights.cached("paper")["items"] == result["items"]
    assert not progress.exists()


@pytest.mark.parametrize("changed", ["route", "quote", "receipt"])
def test_changed_route_or_invalid_cached_chunk_is_not_reused(original, monkeypatch, changed):
    from test_paper_highlights import choice, fake_reply

    long_paper(monkeypatch)
    progress = fail_second_chunk(monkeypatch)
    if changed != "route":
        data = json.loads(progress.read_text("utf-8"))
        if changed == "quote":
            data["chunks"]["0"]["items"][0]["text"] = "Forged quote absent from the original paper."
        else:
            data["chunks"]["0"]["receipts"] = [{"private": "not a valid receipt"}]
        progress.write_text(json.dumps(data), "utf-8")
    calls = []

    def complete(prompt, **kwargs):
        calls.append(prompt)
        return fake_reply({"items": [choice()]} if len(calls) <= 2 else {"ids": [1, 0]})

    monkeypatch.setattr(highlights.llm, "complete_result", complete)
    result, reason = highlights.generate(
        "paper", cfg="route-B" if changed == "route" else "route-A"
    )
    assert reason == "ok" and len(calls) == 3
    assert "1/2" in calls[0] and "2/2" in calls[1]
    assert {i["page"] for i in result["items"]} == {1, 2}
    assert all("Forged" not in i["text"] for i in result["items"])
    assert not progress.exists()


def test_pure_producer_does_not_read_or_save_a_global_workspace(original, monkeypatch):
    from test_paper_highlights import PAGES, choice, fake_reply

    monkeypatch.setattr(highlights, "read_original", lambda *a: pytest.fail("global original read"))
    monkeypatch.setattr(highlights, "_path", lambda *a: pytest.fail("global cache path"))
    monkeypatch.setattr(highlights, "_atomic_json", lambda *a: pytest.fail("global save"))
    monkeypatch.setattr(
        highlights.llm, "complete_result", lambda *a, **k: fake_reply({"items": [choice()]})
    )
    result, reason = highlights.produce(PAGES, cfg="captured-route")
    assert reason == "ok" and result["items"][0]["text"] == PAGES[0]["text"]
    assert list(original.iterdir()) == []
