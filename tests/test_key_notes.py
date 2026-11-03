"""A Q&A exchange condensed into a key note card, only when asked, never saved unseen."""

from paper_daily import key_notes, llm

CARD = "## SAM2 的提示傳播取代了標註\n- 幾何先驗生成點提示（p.3）\n- 逐幀傳播遮罩（p.4）\n"


def test_the_prompt_carries_the_exchange_and_forbids_new_facts():
    text = key_notes.prompt("HoughSAM", "How\n does it  work?", "It propagates (p.3).")
    assert "問題：How does it work?" in text and "It propagates (p.3)." in text
    assert "不可加入回答沒有的事實" in text


def test_a_card_starts_at_its_claim_and_always_leaves_room_for_the_readers_line():
    assert key_notes.card("好的，以下是卡片：\n\n" + CARD).startswith("## SAM2")
    assert "**我的理解：**" in key_notes.card(CARD)
    assert key_notes.card("沒有標題的回覆") is None


def test_the_question_stays_as_the_quote_line():
    body = key_notes.note_body("How does\nit work?", "## Claim\n")
    assert body == "> How does it work?\n\n## Claim\n"
    assert key_notes.note_body("", "## Claim\n") == "## Claim\n"


def test_condensing_goes_through_the_model_service_and_says_why_it_failed(monkeypatch):
    calls = []

    def complete(prompt, *args, cfg=None, task="default", **kwargs):
        calls.append((task, cfg))
        return replies.pop(0)

    monkeypatch.setattr(llm, "complete", complete)
    replies = [(CARD, "ok"), ("not a card", "ok"), (None, "rate limited")]
    drafted, _ = key_notes.condense("T", "Q", "A", connections={}, cfg="fixture")
    assert drafted.startswith("## SAM2") and calls == [("ask", "fixture")]
    assert key_notes.condense("T", "Q", "A", connections={})[0] is None
    assert key_notes.condense("T", "Q", "A", connections={}) == (None, "rate limited")
