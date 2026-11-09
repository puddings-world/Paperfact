"""What the reader says while a paper has no PDF, and the link that looks for one.

Opening a paper never starts the lookup on its own: it asks Semantic Scholar,
OpenAlex and arXiv and may read the publisher's page, which is network work the
reader asks for with one click.
"""

from __future__ import annotations

import html

FIND_PDF = "pdf:find"


def _link(text: str, accent: str) -> str:
    return f'<a href="{FIND_PDF}" style="color:{accent};">{text}</a>'


def no_pdf_message(accent: str) -> str:
    return (
        "這篇還沒有原文 PDF 的連結。<br><br>"
        + _link("查找原文", accent)
        + "：會讀會議論文頁（目前支援 MICCAI），再用標題查 Semantic Scholar、"
        "OpenAlex 與 arXiv，找到開放 PDF 就直接下載。"
    )


def hunt_message(state, accent: str) -> str:
    """One line per download state; a failed lookup offers to look again."""
    text = html.escape(state.label)
    if state.phase in ("error", "cancelled"):
        return (
            text
            + "<br><br>"
            + _link("再查一次", accent)
            + "，或用上方的 Google Scholar 搜尋自行找原文後，右鍵補入。"
        )
    return text
