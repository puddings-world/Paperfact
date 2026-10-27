"""The 深度講解 tab's document: the dive, then the close reading, with the paper's own
figures set where the text discusses them.

The close reading marks those places with a line of its own, `[[Figure 3]]`, naming
an exhibit from the pack's list; the figure itself is the rendering figures.py
already made for the 圖表 tab. A marker naming an exhibit that was not extracted is
dropped rather than shown as a broken image.

`rich` renders for the web view (typeset formulas, figures and evidence as
styled blocks); without it, for Qt's own rich text.
"""

from __future__ import annotations

import html

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImageReader

from paper_daily import reading_links
from paper_daily.answer_content import final_text, reading_text
from paper_daily.closeread import MARKER
from paper_daily.desktop import md, rich_html
from paper_daily.materials import exhibit_key

# Wide enough to read a results table, narrow enough to sit in the side pane.
MAX_WIDTH = 640


def _md(text: str, palette: dict[str, str], rich: bool) -> str:
    return rich_html.markdown(text) if rich else md.to_html(text, palette)


def _figure_html(fig, palette: dict[str, str], rich: bool = False) -> str:
    caption = fig.caption if len(fig.caption) <= 260 else fig.caption[:259] + "…"
    if rich:
        return (
            f'<figure class="paper"><img src="{QUrl.fromLocalFile(str(fig.path)).toString()}">'
            f"<figcaption>{html.escape(caption)} (p{fig.page})</figcaption></figure>"
        )
    size = QImageReader(str(fig.path)).size()
    # Rendered at 2x for zooming; shown at its printed size, capped to the pane.
    width = min(MAX_WIDTH, max(1, size.width() // 2)) if size.isValid() else MAX_WIDTH
    return (
        f'<p align="center" style="margin:6px 0 2px 0;">'
        f'<img src="{QUrl.fromLocalFile(str(fig.path)).toString()}" width="{width}"></p>'
        f'<p align="center" style="margin:0 0 14px 0;color:{palette["muted"]};'
        f'font-size:12px;">{html.escape(caption)} (p{fig.page})</p>'
    )


def render(
    dive: str,
    close: str | None,
    figures: list,
    palette: dict[str, str],
    *,
    highlights=None,
    links=None,
    rich: bool = False,
) -> str:
    """HTML for the whole explanation, including read-only legacy cleanup."""
    old_dive, old_close = dive, close
    dive = reading_text(dive, legacy_dive=True) or ""
    close = reading_text(close)
    notice = ""
    if (old_dive and not dive) or (old_close and not close):
        notice = _md(
            "**先前的 AI 回覆未包含完整正文，已隱藏格式異常的內容。** "
            "請重新分析；原始儲存資料未被覆寫。", palette, rich,
        )
    elif old_dive and final_text(old_dive) is None:
        notice = _md(
            "_先前回覆格式異常，以下保留可辨識的正式章節；原始資料未改動。_",
            palette, rich,
        )
    if highlights:
        return notice + _with_evidence(dive, close, figures, palette, highlights, links, rich)
    text = dive
    if close:
        text += "\n\n---\n\n# 逐節精讀\n\n" + close
    else:
        text += (
            "\n\n---\n\n_逐節精讀(方法與實驗逐節講解,附原文圖表)還沒寫。"
            "清單上的「分析未完成的」會補上,或執行 `close-read <論文 id>`。_"
        )
    by_label = {exhibit_key(f.label): f for f in figures}
    shown: set[str] = set()
    out: list[str] = []
    chunk: list[str] = []
    for line in text.replace("\r", "").split("\n"):
        hit = MARKER.match(line)
        if not hit:
            chunk.append(line)
            continue
        key = exhibit_key(hit.group(1))
        fig = by_label.get(key)
        if fig is None or key in shown:
            continue
        out.append(_md("\n".join(chunk), palette, rich))
        out.append(_figure_html(fig, palette, rich))
        shown.add(key)
        chunk = []
    out.append(_md("\n".join(chunk), palette, rich))
    return notice + "".join(out)


def _evidence_card(index, item, explanation, pal, rich=False):
    e = html.escape
    page = f"第 {item['page']} 頁" if item.get("page") else "原文"
    if rich:
        return (
            f'<aside class="evidence"><div class="head">原文依據 · {e(page)}'
            f'<a href="paperfact-highlight:{index}">查看原文標記</a></div>'
            f"<p>{e(item['text'])}</p>"
            f'<div class="label">為何畫重點</div><p>{e(item.get("reason", ""))}</p>'
            + (
                f'<div class="label">與這段講解的關係</div><p>{e(explanation)}</p>'
                if explanation
                else ""
            )
            + "</aside>"
        )
    return (
        f'<table width="100%" cellpadding="10" style="margin:8px 0;font-size:14px;" '
        f'bgcolor="{pal["surface"]}"><tr><td>'
        f"<b>原文依據 · {e(page)}</b>　"
        f'<a href="paperfact-highlight:{index}">查看原文標記</a>'
        f"<p>{e(item['text'])}</p><b>為何畫重點</b>"
        f"<p>{e(item.get('reason', ''))}</p>"
        + (f"<b>與這段講解的關係</b><p>{e(explanation)}</p>" if explanation else "")
        + "</td></tr></table>"
    )


def _with_evidence(dive, close, figures, pal, analysis, links, rich=False):
    parts = reading_links.sections(dive, close)
    by_section, used = {}, set()
    for link in (links or {}).get("links", []):
        by_section.setdefault(link["section"], []).append(link)
    out, close_started = [], False
    for part in parts:
        if part["kind"] == "close" and not close_started:
            out.append(_md("# 逐節精讀", pal, rich))
            close_started = True
        out.append(_section_html(part["text"], figures, pal, rich))
        for link in by_section.get(part["id"], []):
            index = link["quote"]
            if 0 <= index < len(analysis["items"]):
                used.add(index)
                out.append(
                    _evidence_card(
                        index, analysis["items"][index], link["explanation"], pal, rich
                    )
                )
    remaining = [i for i in range(len(analysis["items"])) if i not in used]
    if remaining:
        out.append(_md("## 原文重點（尚未對應到講解段落）", pal, rich))
        for index in remaining:
            out.append(_evidence_card(index, analysis["items"][index], "", pal, rich))
    return "".join(out)


def _section_html(text, figures, pal, rich=False):
    by_label = {exhibit_key(f.label): f for f in figures}
    out, chunk = [], []
    for line in text.splitlines():
        hit = MARKER.match(line)
        if hit:
            fig = by_label.get(exhibit_key(hit.group(1)))
            if fig:
                out.append(_md("\n".join(chunk), pal, rich))
                out.append(_figure_html(fig, pal, rich))
                chunk = []
        else:
            chunk.append(line)
    out.append(_md("\n".join(chunk), pal, rich))
    return "".join(out)
