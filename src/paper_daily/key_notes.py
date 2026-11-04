"""Key notes: one Q&A exchange condensed into a card worth keeping.

A kept answer is the whole answer; what a reader wants to find again, cite in a
slide or build on is one claim, its support and their own understanding. The
condensing is one explicit AI call through the 論文問答 profile, made only when the
reader asks for it, and the card opens in the editor before anything is saved.
"""

from __future__ import annotations

import re

from paper_daily import llm

KIND = "key"
MAX_ANSWER = 12000

PROMPT = """你要把一段論文問答濃縮成一張「關鍵筆記」卡片，給讀者日後複習與做投影片用。
規則：
- 只能使用下面「回答」裡的內容，不可加入回答沒有的事實、數字或頁碼。
- 用繁體中文，技術名詞保留英文；數學用 LaTeX（$...$）。
- 嚴格照這個格式輸出，不要任何前言或結語：

## 一句話主張（25 字以內，寫成可以被驗證的陳述）
- 要點一（保留回答裡的出處，例如 p.3、Fig.2）
- 要點二（最多三點）

**我的理解：**

論文：{title}
問題：{question}
回答：
{answer}
"""


def prompt(title: str, question: str, answer: str) -> str:
    return PROMPT.format(title=title.strip(), question=" ".join(question.split()),
                         answer=answer.strip()[:MAX_ANSWER])


def card(text: str) -> str | None:
    """The card from the model's reply, from its claim line on; None if it has none."""
    lines = (text or "").strip().splitlines()
    start = next((i for i, line in enumerate(lines) if line.lstrip().startswith("## ")), None)
    if start is None:
        return None
    body = "\n".join(lines[start:]).strip()
    if "**我的理解：**" not in body:
        body += "\n\n**我的理解：**"
    return body + "\n"


def note_body(question: str, card_text: str) -> str:
    """The question stays as the quote line, so the note leads back to where it was asked."""
    quote = " ".join((question or "").split())[:400]
    return f"> {quote}\n\n{card_text}" if quote else card_text


# A concise answer to a many-part question ends by listing the other parts under
# this label (see ask.CONCISE_RULES). They are suggestions for the conversation,
# not part of the answer, and a note that keeps them no longer reads as one card.
FOLLOW_UPS = re.compile(r"^[\s>*_#-]*也可以問[\s*_]*[:：]", re.MULTILINE)


def answer_for_note(answer: str) -> str:
    """The answer without its trailing 也可以問 suggestions."""
    found = list(FOLLOW_UPS.finditer(answer))
    return answer[: found[-1].start()].rstrip() if found else answer


def condense(title: str, question: str, answer: str, *, connections=None, cfg=None):
    """(card, reason): the drafted card, or None and why not.

    `connections` and `cfg` are captured when the reader asks, so switching account
    while it runs cannot move the work to another one."""
    with llm.connection_scope(connections):
        result, reason = llm.complete(prompt(title, question, answer_for_note(answer)),
                                      cfg=cfg, timeout=300,
                                      task="ask")
    if not result:
        return None, reason or "AI 沒有回覆"
    drafted = card(result)
    if drafted is None:
        return None, "AI 的回覆不是筆記卡片的格式；可以再試一次，或用「＋ 存成筆記」保留全文。"
    return drafted, "ok"
