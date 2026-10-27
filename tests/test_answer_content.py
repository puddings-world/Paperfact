"""Only final answers belong in research content; legacy repairs are read-only."""

import json
import re
from types import SimpleNamespace

import pytest
from test_dive import conn as _conn

from paper_daily import dive, llm, reading_links
from paper_daily.ai_types import Completion, Settings, TokenUsage
from paper_daily.desktop import reading
from paper_daily.desktop.main import palette

conn = _conn


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(llm, "ACCESS_CHECK", None)
    calls = []

    def install(text):
        def complete(*args):
            calls.append(1)
            return Completion(text, model="fixture", usage=TokenUsage(output_tokens=42))

        monkeypatch.setitem(llm._PROVIDERS, "cli", SimpleNamespace(complete=complete))
        return Settings("cli", model="fixture")

    return install, calls, tmp_path


@pytest.mark.parametrize("tag", ["thinking_mode", "think", "thinking", "analysis"])
def test_only_final_answer_reaches_features_and_usage(provider, tag):
    install, calls, path = provider
    cfg = install(f"<{tag}>INTERNAL_FIXTURE</{tag}>\n## Result\nFinal explanation")
    result = llm.complete_result("fixture", cfg=cfg, task="dive")
    assert result.text == "## Result\nFinal explanation"
    assert result.usage.output_tokens == 42 and result.model == "fixture"
    assert calls == [1]
    log = (path / "ai-usage.jsonl").read_text(encoding="utf-8")
    assert "INTERNAL_FIXTURE" not in log
    assert json.loads(log)["success"] is True


@pytest.mark.parametrize(
    "body",
    [
        "<thinking_mode>" + "INTERNAL_FIXTURE " * 100,
        "<think>INTERNAL_FIXTURE</think>",
        "<think><analysis>INTERNAL_FIXTURE</think>",
    ],
)
def test_no_final_answer_is_a_retryable_failure_not_a_completed_dive(provider, body):
    install, calls, path = provider
    cfg = install(body)
    result = llm.complete_result("fixture", cfg=cfg, task="dive")
    assert result.text is None
    assert "INTERNAL_FIXTURE" not in result.reason
    assert calls == [1]  # Never silently spend tokens on a retry.
    assert json.loads((path / "ai-usage.jsonl").read_text())["success"] is False


@pytest.mark.parametrize(
    "body",
    [
        "A paper about thinking and analysis.",
        "```xml\n<think>literal example</think>\n```",
        "The literal tag `<thinking_mode>` is an example.",
        '{"analysis":"keep the structured answer"}',
    ],
)
def test_legitimate_text_and_code_examples_are_preserved(provider, body):
    install, _, _ = provider
    assert llm.complete_result("fixture", cfg=install(body)).text == body


def test_nested_and_repeated_envelopes_do_not_leak(provider):
    install, _, _ = provider
    body = "<think><analysis>INTERNAL_FIXTURE</analysis></think>\n<thinking>x</thinking>\nFinal"
    assert llm.complete_result("fixture", cfg=install(body)).text == "Final"


def legacy_dive():
    headings = re.findall(r"(?m)^## (.+)$", dive.DIVE_INSTRUCTIONS)
    return "\n\n".join(
        f"# {heading}\nFinal explanation " + "evidence " * 20 for heading in headings
    )


@pytest.mark.parametrize("rich", [False, True])
@pytest.mark.parametrize("evidence", [False, True])
@pytest.mark.parametrize("summary_heading", [False, True])
def test_existing_malformed_dive_displays_final_sections_without_mutating_content(
    rich, evidence, summary_heading,
):
    final = legacy_dive()
    if not summary_heading:
        final = final.split("\n\n", 1)[1]
    raw = "<thinking_mode>INTERNAL_FIXTURE\n\n" + final
    old = raw
    highlights = (
        dict(items=[dict(text="Verified quote", page=1, reason="Evidence")]) if evidence else None
    )
    parts = reading_links.sections(raw, None)
    assert parts and all("INTERNAL_FIXTURE" not in part["text"] for part in parts)
    assert parts[0]["id"] == "dive:0"
    html = reading.render(
        raw, "## Method\nClose reading", [], palette(), highlights=highlights, rich=rich
    )
    assert "INTERNAL_FIXTURE" not in html and "thinking_mode" not in html
    assert "Final explanation" in html and "Close reading" in html
    assert raw == old


@pytest.mark.parametrize("rich", [False, True])
def test_incomplete_legacy_result_shows_explanation_and_keeps_valid_close_reading(rich):
    html = reading.render(
        "<think>INTERNAL_FIXTURE", "## Method\nValid close reading", [], palette(), rich=rich
    )
    assert "INTERNAL_FIXTURE" not in html
    assert "未包含完整正文" in html
    assert "Valid close reading" in html
    assert reading_links.sections("<think>INTERNAL_FIXTURE", None) == []


@pytest.mark.parametrize("existing", [False, True])
def test_bad_reply_preserves_saved_dive_then_explicit_retry_stores_only_final(
    conn, provider, monkeypatch, existing
):
    from paper_daily import brief

    install, calls, _ = provider
    monkeypatch.setattr(brief, "pack_text", lambda *_: ("fixture pack", None))
    if existing:
        conn.execute("INSERT INTO dives VALUES ('p1', 'previous final answer', 'before', NULL)")
        conn.commit()
    cfg = install("<thinking_mode>" + "INTERNAL_FIXTURE " * 100)
    monkeypatch.setattr(llm, "settings", lambda **_: cfg)
    assert dive.dive_ahead(paper_id="p1") == 0
    saved = conn.execute("SELECT body FROM dives WHERE paper_id='p1'").fetchone()
    assert (saved[0] if saved else None) == ("previous final answer" if existing else None)
    final = legacy_dive()
    install("<think>INTERNAL_FIXTURE</think>\n" + final)
    assert dive.dive_ahead(paper_id="p1") == 1
    assert conn.execute("SELECT body FROM dives WHERE paper_id='p1'").fetchone()[0] == final
    assert calls == [1, 1]
