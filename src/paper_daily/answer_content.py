"""Separate explicit leading reasoning envelopes from user-facing content.

Only recognized envelopes at the start are transport-like; quoted tags, code
examples and ordinary uses of 'analysis' remain untouched. Malformed envelopes
are rejected instead of treating their length as a successful completion.
"""

from __future__ import annotations

import re

_OPEN = re.compile(r"\A\s*<(think|thinking|thinking_mode|analysis)\s*>", re.I)
_TAG = re.compile(r"<(\/?)(think|thinking|thinking_mode|analysis)\s*>", re.I)


def final_text(text: str | None) -> str | None:
    if not text:
        return None
    while opening := _OPEN.match(text):
        stack = [opening[1].lower()]
        for tag in _TAG.finditer(text, opening.end()):
            name = tag[2].lower()
            if not tag[1]:
                stack.append(name)
            elif not stack or stack.pop() != name:
                return None
            if not stack:
                text = text[tag.end() :].lstrip()
                break
        else:
            return None
    return text if text.strip() else None


# A legacy CLI response sometimes omitted its closing marker but did contain the
# complete requested deep-dive document. Recover only this known structure at
# read time; never guess a boundary for new responses or rewrite stored research.
_LEGACY_SECTIONS = (
    "前導導讀",
    "核心洞見",
    "方法",
    "機制圖解",
    "證據",
    "該看哪三張圖",
    "限制與反駁",
    "血緣位置",
    "三個討論問題",
)


def reading_text(text: str | None, *, legacy_dive: bool = False) -> str | None:
    cleaned = final_text(text)
    if cleaned is not None or not text or not legacy_dive:
        return cleaned
    opening = _OPEN.match(text)
    if not opening or opening[1].lower() != "thinking_mode":
        return None
    # Mismatched/nested delimiters do not provide a reliable recovery boundary.
    if _TAG.search(text, opening.end()):
        return None
    headings = list(re.finditer(r"(?m)^#{1,2}[ \t]+([^\r\n]+)", text))
    # Some legacy responses did not give the opening summary a heading. Start
    # at the first recognized chapter rather than guessing where its prose began.
    titles = tuple(h[1].strip() for h in headings)
    if titles != _LEGACY_SECTIONS and not (
        len(headings) == 10 and titles[1:] == _LEGACY_SECTIONS
    ):
        return None
    body = text[headings[0].start() :]
    return body if len(body) > 800 else None
