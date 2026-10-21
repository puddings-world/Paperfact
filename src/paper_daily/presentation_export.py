"""Offline slide exports; no model calls or desktop credentials."""

from __future__ import annotations

import base64
import html
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from paper_daily.presentations import MODES, Deck, deck_from_dict, figure_bytes
from paper_daily.slide_layout import elements_for, table_markdown, used_figures

TEMPLATE = Path(__file__).with_name("presentation.html")


def suggested_filename(title: str, suffix: str = ".pdf") -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", title)
    name = " ".join(name.split())[:150].strip(" .") or "Paper"
    return f"Slides of - {name}{suffix}"


def safe_url(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username:
            return value
    except ValueError:
        pass
    return None


def speaker_notes_text(deck: Deck, slide) -> str:
    sources = {s["id"]: s for s in deck.sources}
    lines = ["講稿", slide.speaker_notes or "（尚未撰寫講稿）", "", "引用來源"]
    for number, sid in enumerate(slide.sources, 1):
        source = sources[sid]
        label = str(source.get("label") or sid)
        page = source.get("page")
        location = f" · 原文 p.{page}" if page else ""
        lines.append(f"[{number}] {label}{location} [{sid}]")
        url = safe_url(source.get("url"))
        if url:
            lines.append(url)
    return "\n".join(lines)


def source_labels(deck: Deck, refs: list[str], *, links: bool = True) -> str:
    by_id = {s["id"]: s for s in deck.sources}
    out = []
    for sid in refs:
        source = by_id[sid]
        label = html.escape(str(source.get("label", sid)))
        page = source.get("page")
        if page and source.get("kind") != "original":
            label += f"（p.{html.escape(str(page))}）"
        url = safe_url(source.get("url"))
        if links and url:
            label = (
                f'<a href="{html.escape(url, quote=True)}" target="_blank" '
                f'rel="noopener">{label}</a>'
            )
        out.append(label)
    return " · ".join(out)


def slide_html(deck: Deck, index: int, *, notes: bool = True) -> str:
    slide = deck.slides[index]
    e = html.escape
    if slide.elements is not None:
        return canvas_html(deck, index, notes=notes)
    bullets = "".join(f"<li>{e(b)}</li>" for b in slide.bullets)
    figure = ""
    if slide.figure:
        item = next(f for f in deck.figures if f["id"] == slide.figure)
        data = base64.b64encode(figure_bytes(deck, slide.figure)).decode("ascii")
        figure = (
            '<figure><img src="data:image/png;base64,'
            + data
            + '" alt="'
            + e(str(item.get("label", "")), quote=True)
            + '"><figcaption>'
            + e(str(item.get("caption", item.get("label", ""))))
            + "</figcaption></figure>"
        )
    layout = "with-figure" if figure else ""
    notes_html = ""
    if notes:
        notes_html = (
            '<div class="speaker-notes"><h3>講者備註</h3><p>'
            + e(slide.speaker_notes).replace("\n", "<br>")
            + "</p><h3>本頁來源</h3><p>"
            + source_labels(deck, slide.sources)
            + "</p></div>"
        )
    return (
        f'<section class="slide" data-index="{index}" aria-label="第 {index + 1} 頁">'
        '<div class="canvas"><header><div class="section">'
        + e(slide.section)
        + "</div><h1>"
        + e(slide.title)
        + "</h1></header>"
        + '<div class="takeaway">'
        + e(slide.takeaway)
        + "</div>"
        + f'<main class="{layout}"><ul>{bullets}</ul>{figure}</main>'
        + '<footer><div class="evidence">'
        + source_labels(deck, slide.sources)
        + '</div><span class="number">'
        + str(index + 1)
        + " / "
        + str(len(deck.slides))
        + "</span></footer></div>"
        + notes_html
        + "</section>"
    )


def render_html(deck: Deck, *, include_notes: bool = True) -> str:
    deck_from_dict(deck.to_dict())
    template = TEMPLATE.read_text(encoding="utf-8")
    slides = "\n".join(slide_html(deck, i, notes=include_notes) for i in range(len(deck.slides)))
    coverage = (
        (
            '<div class="coverage"><strong>來源覆蓋範圍</strong><ul>'
            + "".join("<li>" + html.escape(item) + "</li>" for item in deck.coverage)
            + "</ul></div>"
        )
        if deck.coverage
        else ""
    )
    replacements = {
        "__DECK_TITLE__": html.escape(deck.title),
        "__PAPER_TITLE__": html.escape(deck.paper_title),
        "__MODE__": html.escape(MODES[deck.mode]),
        "__MINUTES__": str(deck.minutes),
        "__SLIDES__": slides,
        "__COVERAGE__": coverage,
    }
    return re.sub(
        r"__(?:DECK_TITLE|PAPER_TITLE|MODE|MINUTES|SLIDES|COVERAGE)__",
        lambda match: replacements[match.group()],
        template,
    )


def export_html(deck: Deck, dest: Path, *, include_notes: bool = True) -> Path:
    dest.write_text(render_html(deck, include_notes=include_notes), encoding="utf-8")
    return dest


def export_markdown(deck: Deck, dest: Path, *, include_notes: bool = True) -> Path:
    deck_from_dict(deck.to_dict())
    lines = [
        "# " + deck.title,
        "",
        deck.paper_title,
        "",
        f"{MODES[deck.mode]} · 約 {deck.minutes} 分鐘",
        "",
    ]
    for i, slide in enumerate(deck.slides):
        lines += [f"## {i + 1}. {slide.title}", ""]
        if slide.elements is not None:
            for obj in slide.elements:
                if obj["kind"] == "text":
                    lines.append(obj["text"])
                elif obj["kind"] == "table":
                    lines += ["", table_markdown(obj["rows"]), ""]
        else:
            lines += [slide.section, "", slide.takeaway, ""]
            lines.extend("- " + b for b in slide.bullets)
        if slide.figure:
            item = next(f for f in deck.figures if f["id"] == slide.figure)
            lines += ["", "**原圖：** " + item.get("label", slide.figure), item.get("caption", "")]
        if include_notes and slide.speaker_notes:
            lines += ["", "### 講者備註", "", slide.speaker_notes]
        labels = {s["id"]: s.get("label", s["id"]) for s in deck.sources}
        lines += ["", "**來源：** " + "；".join(labels[s] for s in slide.sources), "", "---", ""]
    if deck.coverage:
        lines += ["## 來源覆蓋範圍", "", *("- " + s for s in deck.coverage)]
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def export_json(deck: Deck, dest: Path, *, include_notes: bool = True) -> Path:
    deck_from_dict(deck.to_dict())
    data = deck.to_dict()
    if not include_notes:
        for slide in data["slides"]:
            slide["speaker_notes"] = ""
    # A shared project must not depend on the author's filesystem.
    for item in data["figures"]:
        if item["id"] in used_figures(deck):
            item["image_png_base64"] = base64.b64encode(figure_bytes(deck, item["id"])).decode()
        item.pop("asset", None)
        item.pop("file", None)
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def canvas_html(deck: Deck, index: int, *, notes: bool = True) -> str:
    slide = deck.slides[index]
    pieces = []
    for obj in elements_for(slide):
        style = (
            f"left:{obj['x'] / 12}%;top:{obj['y'] / 6.75}%;"
            f"width:{obj['w'] / 12}%;height:{obj['h'] / 6.75}%;"
        )
        if obj["kind"] == "text":
            style += (
                f"font-size:{obj['size'] / 12}cqw;color:{obj['color']};"
                f"font-weight:{700 if obj['bold'] else 400};text-align:{obj['align']};"
            )
            pieces.append(
                f'<div class="canvas-object" style="{style}">' + html.escape(obj["text"]) + "</div>"
            )
        elif obj["kind"] == "table":
            style += f"font-size:{obj['size'] / 12}cqw;"
            rows = obj["rows"]
            head = "".join(f"<th>{html.escape(c)}</th>" for c in rows[0]) if obj["header"] else ""
            body_rows = rows[1:] if obj["header"] else rows
            cells = "".join(
                "<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>"
                for row in body_rows
            )
            pieces.append(
                f'<table class="canvas-object canvas-table" style="{style}">'
                + (f"<thead><tr>{head}</tr></thead>" if head else "")
                + f"<tbody>{cells}</tbody></table>"
            )
        else:
            data = base64.b64encode(figure_bytes(deck, obj["figure"])).decode("ascii")
            pieces.append(
                f'<img class="canvas-object" style="{style}" '
                f'src="data:image/png;base64,{data}" alt="論文原圖">'
            )
    body = (
        f'<section class="slide" data-index="{index}" aria-label="第 {index + 1} 頁">'
        '<div class="canvas free-canvas"><main>' + "".join(pieces) + "</main>"
        f'<div class="canvas-footer">Paperfact　 {index + 1} / {len(deck.slides)}　'
        + html.escape(" · ".join(slide.sources))
        + "</div></div>"
    )
    if notes:
        body += (
            '<div class="speaker-notes"><h3>講者備註</h3><p>'
            + html.escape(slide.speaker_notes).replace("\n", "<br>")
            + "</p><h3>本頁來源</h3><p>"
            + source_labels(deck, slide.sources)
            + "</p></div>"
        )
    return body + "</section>"
