"""Original-only selection, quote grounding, coverage and cache lifecycle."""

import json
from types import SimpleNamespace

import pytest

from paper_daily import paper_highlights as highlights

PAGES = [
    {
        "page": 1,
        "text": "The experiment isolates the effect of the intervention from baseline variation.",
    },
    {"page": 2, "text": "This result does not establish causality outside the sampled population."},
]


def selected(index=0):
    return dict(
        text=PAGES[index]["text"],
        page=PAGES[index]["page"],
        kind="evidence" if index == 0 else "limitation",
        reason="交代研究結論的證據或適用邊界。",
    )


def choice(index=0):
    return dict(
        ids=[index],
        kind="evidence" if index == 0 else "limitation",
        reason="交代研究結論的證據或適用邊界。",
    )


@pytest.fixture
def original(tmp_path, monkeypatch):
    monkeypatch.setattr(highlights, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(highlights, "read_original", lambda _id: PAGES)
    monkeypatch.setattr(highlights.llm, "settings", lambda **kwargs: "configured-provider")
    return tmp_path


def fake_reply(data):
    return SimpleNamespace(
        text=json.dumps(data, ensure_ascii=False),
        reason="ok",
        backend="gateway",
        profile="research",
        model="test",
        request_id="id",
    )


def test_original_only_verified_quotes_and_cache_avoid_another_call(original, monkeypatch):
    calls = []

    def complete(prompt, **kwargs):
        calls.append((prompt, kwargs))
        assert all(p["text"] in prompt for p in PAGES)
        assert kwargs["task"] == "paper_highlights" and kwargs["cfg"] == "configured-provider"
        return fake_reply({"items": [choice(1), choice(0)]})

    monkeypatch.setattr(highlights.llm, "complete_result", complete)
    result, reason = highlights.generate("paper")
    assert reason == "ok" and result["items"][0]["source"] == "page:2"
    assert result["items"][0]["text"] == PAGES[1]["text"]
    assert result["generation"][0]["profile"] == "research"
    assert highlights.generate("paper")[1] == "cached" and len(calls) == 1
    assert highlights.generate("paper", force=True)[1] == "ok" and len(calls) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"ids": [99]},
        {"ids": [True]},
        {"ids": [1, 0]},
        {"reason": ""},
        {"kind": "claim"},
    ],
)
def test_invalid_ai_quotes_never_replace_old_cache(original, monkeypatch, change):
    monkeypatch.setattr(
        highlights.llm, "complete_result", lambda *a, **k: fake_reply({"items": [choice()]})
    )
    assert highlights.generate("paper")[0]
    old = highlights._path("paper").read_bytes()
    monkeypatch.setattr(
        highlights.llm,
        "complete_result",
        lambda *a, **k: fake_reply({"items": [dict(choice(), **change)]}),
    )
    result, reason = highlights.generate("paper", force=True)
    assert result is None and reason != "ok"
    assert highlights._path("paper").read_bytes() == old


def test_changed_original_invalidates_cache_and_inflight_result(original, monkeypatch):
    monkeypatch.setattr(
        highlights.llm, "complete_result", lambda *a, **k: fake_reply({"items": [choice()]})
    )
    highlights.generate("paper")
    altered = [dict(PAGES[0], text=PAGES[0]["text"] + " New evidence.")]
    assert highlights.cached("paper", altered) is None
    reads = iter([PAGES, altered])
    monkeypatch.setattr(highlights, "read_original", lambda _id: next(reads))
    result, reason = highlights.generate("paper", force=True)
    assert result is None and "原文已變更" in reason
    assert highlights.cached("paper", PAGES) is not None


def test_all_chunks_are_read_then_globally_ranked(original, monkeypatch):
    monkeypatch.setattr(highlights, "CHUNK_CHARS", 1100)
    pages = [dict(p, text=("Context " * 75) + p["text"]) for p in PAGES]
    monkeypatch.setattr(highlights, "read_original", lambda _id: pages)
    calls = []

    def complete(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) <= 2:
            return fake_reply({"items": [choice()]})
        return fake_reply({"ids": [1, 0]})

    monkeypatch.setattr(highlights.llm, "complete_result", complete)
    result, reason = highlights.generate("paper")
    assert reason == "ok" and len(calls) == 3
    assert result["coverage"]["chunks"] == 2
    assert [i["page"] for i in result["items"]] == [2, 1]


def test_failed_chunk_does_not_save_partial_analysis(original, monkeypatch):
    monkeypatch.setattr(highlights, "CHUNK_CHARS", 1100)
    monkeypatch.setattr(
        highlights,
        "read_original",
        lambda _id: [dict(p, text=("Context " * 75) + p["text"]) for p in PAGES],
    )
    replies = iter(
        [fake_reply({"items": [choice()]}), SimpleNamespace(text=None, reason="quota exhausted")]
    )
    monkeypatch.setattr(highlights.llm, "complete_result", lambda *a, **k: next(replies))
    result, reason = highlights.generate("paper")
    assert result is None and reason == "quota exhausted"
    assert not highlights._path("paper").exists()


def test_reply_with_prose_before_the_json_is_read(original, monkeypatch):
    reply = fake_reply({"items": [choice(1)]})
    reply.text = "以下是我挑選的重點（共 [1] 項）：\n```json\n" + reply.text + "\n```"
    monkeypatch.setattr(highlights.llm, "complete_result", lambda *a, **k: reply)
    result, reason = highlights.generate("paper")
    assert reason == "ok" and result["items"][0]["text"] == PAGES[1]["text"]


def test_unreadable_reply_gives_a_short_retryable_reason_and_keeps_old_result(
    original, monkeypatch
):
    monkeypatch.setattr(
        highlights.llm, "complete_result", lambda *a, **k: fake_reply({"items": [choice()]})
    )
    highlights.generate("paper")
    old = highlights._path("paper").read_bytes()
    reply = fake_reply({})
    reply.text = "I could not find anything worth highlighting."
    monkeypatch.setattr(highlights.llm, "complete_result", lambda *a, **k: reply)
    result, reason = highlights.generate("paper", force=True)
    assert result is None and "Expecting value" not in reason
    assert "格式無法解析" in reason and highlights.transient(reason)
    assert highlights._path("paper").read_bytes() == old


def test_one_invalid_item_is_dropped_without_losing_the_valid_ones(original, monkeypatch):
    items = [choice(0), dict(choice(1), ids=[99]), dict(choice(1), kind="claim")]
    monkeypatch.setattr(
        highlights.llm, "complete_result", lambda *a, **k: fake_reply({"items": items})
    )
    result, reason = highlights.generate("paper")
    assert reason == "ok" and [i["text"] for i in result["items"]] == [PAGES[0]["text"]]


def test_a_chunk_with_only_invalid_items_does_not_sink_a_long_paper(original, monkeypatch):
    monkeypatch.setattr(highlights, "CHUNK_CHARS", 1100)
    pages = [dict(p, text=("Context " * 75) + p["text"]) for p in PAGES]
    monkeypatch.setattr(highlights, "read_original", lambda _id: pages)
    replies = iter(
        [
            fake_reply({"items": [choice()]}),
            fake_reply({"items": [dict(choice(), ids=[99])]}),
            fake_reply({"ids": [0, 7]}),
        ]
    )
    monkeypatch.setattr(highlights.llm, "complete_result", lambda *a, **k: next(replies))
    result, reason = highlights.generate("paper")
    assert reason == "ok" and [i["page"] for i in result["items"]] == [1]


def test_retry_after_a_failed_chunk_does_not_pay_for_finished_chunks(original, monkeypatch):
    monkeypatch.setattr(highlights, "CHUNK_CHARS", 1100)
    pages = [dict(p, text=("Context " * 75) + p["text"]) for p in PAGES]
    monkeypatch.setattr(highlights, "read_original", lambda _id: pages)
    prompts = []

    def failing(prompt, **kwargs):
        prompts.append(prompt)
        if len(prompts) == 1:
            return fake_reply({"items": [choice()]})
        return SimpleNamespace(text=None, reason="timed out after 900s")

    monkeypatch.setattr(highlights.llm, "complete_result", failing)
    result, reason = highlights.generate("paper")
    assert result is None and highlights.transient(reason) and "timed out" in reason
    assert not highlights._path("paper").exists()
    prompts.clear()

    def answering(prompt, **kwargs):
        prompts.append(prompt)
        return fake_reply({"items": [choice()]} if len(prompts) == 1 else {"ids": [1, 0]})

    monkeypatch.setattr(highlights.llm, "complete_result", answering)
    result, reason = highlights.generate("paper")
    assert reason == "ok" and len(prompts) == 2
    assert "2/2" in prompts[0] and "1/2" not in prompts[0]
    assert {i["page"] for i in result["items"]} == {1, 2}


def test_permanent_failures_are_not_marked_transient(original, monkeypatch):
    monkeypatch.setattr(
        highlights.llm,
        "complete_result",
        lambda *a, **k: SimpleNamespace(text=None, reason="HTTP 401: credential rejected"),
    )
    reason = highlights.generate("paper")[1]
    assert reason == "HTTP 401: credential rejected" and not highlights.transient(reason)
    monkeypatch.setattr(
        highlights.llm,
        "complete_result",
        lambda *a, **k: SimpleNamespace(text=None, reason="HTTP 429: rate limit exceeded"),
    )
    assert highlights.transient(highlights.generate("paper")[1])


def test_no_original_means_no_model_call(original, monkeypatch):
    monkeypatch.setattr(highlights, "read_original", lambda _id: [])
    monkeypatch.setattr(
        highlights.llm, "complete_result", lambda *a, **k: pytest.fail("No original")
    )
    assert highlights.generate("paper")[0] is None


def test_pdf_reader_includes_pages_beyond_120_and_reports_empty_pages(tmp_path, monkeypatch):
    import pymupdf

    monkeypatch.setattr(highlights, "PDF_DIR", tmp_path)
    monkeypatch.setattr(highlights, "TEXT_DIR", tmp_path)
    doc = pymupdf.open()
    for _ in range(121):
        doc.new_page()
    doc[120].insert_text((30, 60), PAGES[1]["text"])
    doc.save(tmp_path / "paper.pdf")
    pages = highlights.read_original("paper")
    assert len(pages) == 121 and pages[-1]["page"] == 121
    assert PAGES[1]["text"] in pages[-1]["text"]


def test_text_fallback_has_no_invented_page_and_normalizes_pdf_whitespace(tmp_path, monkeypatch):
    monkeypatch.setattr(highlights, "PDF_DIR", tmp_path)
    monkeypatch.setattr(highlights, "TEXT_DIR", tmp_path)
    (tmp_path / "paper.txt").write_text(
        "The inter-\nvention is limited to this population.", encoding="utf-8"
    )
    pages = highlights.read_original("paper")
    assert pages == [{"page": None, "text": "The intervention is limited to this population."}]
    result = highlights._validate(
        [dict(text=pages[0]["text"], page=None, kind="limitation", reason="保留適用條件")], pages
    )
    assert result[0]["source"] == "original"


def test_source_spans_keep_all_text_and_only_allow_adjacent_same_page_quotes():
    chunk = [
        dict(page=1, text="這個研究問題決定了後續方法的設計。方法的適用範圍需要明確限定。"),
        dict(page=2, text="The validation population differs from the target population."),
    ]
    passages = highlights._passages(chunk)
    assert [p["page"] for p in passages] == [1, 1, 2]
    assert passages[0]["text"] + passages[1]["text"] == chunk[0]["text"]
    with pytest.raises(ValueError, match="跨頁"):
        highlights._resolve([dict(choice(), ids=[1, 2])], passages, chunk)
    with pytest.raises(ValueError, match="核對"):
        highlights._validate([dict(selected(), page=2)], PAGES)
    with pytest.raises(ValueError, match="核對"):
        highlights._validate(
            [dict(selected(), text="A fabricated finding that is absent from the original paper.")],
            PAGES,
        )


def test_single_source_id_cannot_replace_original_text_or_page():
    passages = highlights._passages(PAGES)
    result = highlights._resolve(
        [dict(id=1, text="invented", page=999, kind="limitation", reason="適用範圍")],
        passages,
        PAGES,
    )
    assert result[0]["text"] == PAGES[1]["text"] and result[0]["page"] == 2
