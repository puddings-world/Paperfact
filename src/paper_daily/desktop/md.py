"""Markdown -> HTML for Qt's rich text widgets.

QTextBrowser understands a subset of HTML 4 with a subset of CSS, not Markdown, and
not the CSS a browser would take. So this renders to plain tags and carries styling
inline where Qt actually honours it.

Deliberately small: it only has to handle what the deep dives emit -- headings,
paragraphs, lists, tables, fenced code, bold, italic, inline code, blockquotes.
"""

from __future__ import annotations

import html
import re

from paper_daily.desktop import fonts

# Qt picks the document's proportional font for <pre> unless the family is named
# inline, and the dives now draw box-drawing diagrams that only line up in a
# fixed-pitch face carrying those glyphs.
MONO = fonts.css(fonts.MONO)

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _inline(text: str, palette: dict[str, str]) -> str:
    out = html.escape(text)
    out = _INLINE_CODE.sub(
        rf'<code style="background:{palette["sunk"]};color:{palette["ink"]};'
        rf'font-family:{MONO};">\1</code>',
        out,
    )
    out = _BOLD.sub(r"<b>\1</b>", out)
    out = _ITALIC.sub(r"<i>\1</i>", out)
    out = _LINK.sub(rf'<a href="\2" style="color:{palette["accent"]};">\1</a>', out)
    return out


def _table(rows: list[str], palette: dict[str, str]) -> str:
    """Render a GitHub-style pipe table. The separator row is dropped."""
    cells = [
        [c.strip() for c in row.strip().strip("|").split("|")]
        for row in rows
        if not re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", row)
    ]
    if not cells:
        return ""
    head, *body = cells
    parts = [
        f'<table cellspacing="0" cellpadding="6" width="100%" '
        f'style="border:1px solid {palette["border"]};">',
        "<tr>",
    ]
    parts += [
        f'<th align="left" style="background:{palette["sunk"]};'
        f'border-bottom:1px solid {palette["border"]};">{_inline(c, palette)}</th>'
        for c in head
    ]
    parts.append("</tr>")
    for row in body:
        parts.append("<tr>")
        parts += [
            f'<td style="border-bottom:1px solid {palette["border"]};">'
            f"{_inline(c, palette)}</td>"
            for c in row
        ]
        parts.append("</tr>")
    parts.append("</table>")
    return "".join(parts)


def to_html(src: str, palette: dict[str, str]) -> str:
    """Render Markdown to the HTML subset QTextBrowser displays correctly."""
    lines = (src or "").replace("\r", "").split("\n")
    out: list[str] = []
    para: list[str] = []
    list_tag: str | None = None
    fence: list[str] | None = None
    table: list[str] | None = None

    def flush_para() -> None:
        nonlocal para
        if para:
            out.append(f'<p style="margin:0 0 11px 0;">{_inline(" ".join(para), palette)}</p>')
            para = []

    def flush_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    def flush_table() -> None:
        nonlocal table
        if table:
            out.append(_table(table, palette))
            table = None

    for raw in lines:
        if raw.startswith("```"):
            if fence is None:
                flush_para()
                flush_list()
                flush_table()
                fence = []
            else:
                body = html.escape("\n".join(fence))
                out.append(
                    f'<pre style="background:{palette["sunk"]};color:{palette["ink"]};'
                    f'padding:10px;border:1px solid {palette["border"]};'
                    f'font-family:{MONO};font-size:12px;line-height:120%;">{body}</pre>'
                )
                fence = None
            continue
        if fence is not None:
            fence.append(raw)
            continue

        line = raw.rstrip()

        if line.lstrip().startswith("|") and line.count("|") >= 2:
            flush_para()
            flush_list()
            table = table or []
            table.append(line)
            continue
        flush_table()

        if not line.strip():
            flush_para()
            flush_list()
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading:
            flush_para()
            flush_list()
            level = len(heading[1])
            size = {1: 20, 2: 17, 3: 15, 4: 14}[level]
            weight = "600" if level > 1 else "700"
            top = "4px" if not out else "20px"
            out.append(
                f'<div style="font-size:{size}px;font-weight:{weight};'
                f'color:{palette["ink"]};margin:{top} 0 8px 0;">'
                f"{_inline(heading[2], palette)}</div>"
            )
            continue

        if re.match(r"^\s*[-*+]\s+", line) or re.match(r"^\s*\d+[.)]\s+", line):
            flush_para()
            ordered = bool(re.match(r"^\s*\d+[.)]\s+", line))
            want = "ol" if ordered else "ul"
            if list_tag != want:
                flush_list()
                out.append(f'<{want} style="margin:0 0 11px 18px;">')
                list_tag = want
            item = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line)
            out.append(f'<li style="margin-bottom:5px;">{_inline(item, palette)}</li>')
            continue

        if line.startswith(">"):
            flush_para()
            flush_list()
            out.append(
                f'<p style="margin:0 0 11px 12px;color:{palette["muted"]};">'
                f'<i>{_inline(line.lstrip("> "), palette)}</i></p>'
            )
            continue

        flush_list()
        para.append(line.strip())

    flush_para()
    flush_list()
    flush_table()
    if fence is not None:
        out.append(
            f'<pre style="font-family:{MONO};font-size:12px;">'
            f"{html.escape(chr(10).join(fence))}</pre>"
        )

    return (
        f'<div style="color:{palette["ink"]};font-size:14px;line-height:150%;">'
        + "".join(out)
        + "</div>"
    )
