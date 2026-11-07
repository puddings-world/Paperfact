"""Saved-reader HTML from immutable inputs. No widgets, database or file lookup."""

from __future__ import annotations

import html
from dataclasses import dataclass

from paper_daily import reading_links
from paper_daily.desktop import md, reading, rich_html
from paper_daily.reader_saved_inputs import MAX_BYTES, SavedSnapshot, worker_only

PASSAGE_MARK = "關於這段原文:"


def pair_exchanges(rows):
    """Portable turns pair by identity; unlinked legacy turns retain their old order."""
    rows = [dict(row) for row in rows]
    users = {
        row.get("message_id"): row
        for row in rows
        if row["role"] == "user" and row.get("message_id")
    }
    answers = {}
    for row in rows:
        parent = users.get(row.get("reply_to"))
        if (
            row["role"] == "assistant"
            and parent is not None
            and parent.get("exchange_id") == row.get("exchange_id")
            and parent.get("paper_id") == row.get("paper_id")
        ):
            answers.setdefault(parent["message_id"], []).append(row)
    consumed = {row["id"] for values in answers.values() for row in values}
    out = []
    for row in rows:
        if row.get("exchange_id"):
            if row["role"] == "user":
                matched = answers.get(row.get("message_id"), [])
                out.extend((row, answer) for answer in matched) if matched else out.append(
                    (row, None)
                )
            elif row["id"] not in consumed:
                out.append((None, row))
        elif row["role"] == "user":
            out.append((row, None))
        elif (
            out
            and out[-1][1] is None
            and out[-1][0] is not None
            and not out[-1][0].get("exchange_id")
        ):
            out[-1] = (out[-1][0], row)
        else:
            out.append((None, row))
    return out


def _markdown(text, palette, rich):
    return rich_html.markdown(text) if rich else md.to_html(text, palette)


def _exchange(question, answer, pending, pal, rich, active_request=None):
    asked, _, passage = (question["body"] if question else "").partition(PASSAGE_MARK)
    where = f" · 第 {question['page']} 頁" if question and question["page"] else ""
    head = (
        f'<td bgcolor="{pal["accentSoft"]}">'
        f'<span style="color:{pal["accent"]};font-size:10px;">問{where}</span><br>'
        f'<span style="color:{pal["ink"]};font-size:13px;font-weight:600;">'
        f"{html.escape(asked.strip())}</span>"
    )
    if passage.strip():
        shown = " ".join(passage.split())
        head += (
            f'<div style="color:{pal["muted"]};font-size:11px;margin-top:4px;">'
            f"{html.escape(shown[:200] + ('…' if len(shown) > 200 else ''))}</div>"
        )
    head += "</td>"
    if answer is None:
        body = f'<span style="color:{pal["faint"]};">未完成，可重試</span>'
        links = (f'<a href="retryq:{int(question["id"])}">修改後重問</a>&nbsp; '
                 if question else "")
        item = pending.get(question.get("message_id")) if question else None
        if item:
            text = ("思考中…" if item["request_id"] == active_request
                    and item["status"] == "prepared" else
                    "未完成，可重試" if item["status"] == "prepared" else "已保留回答，待核對")
            body = f'<span style="color:{pal["faint"]};">{text}</span>'
            action = "resumeqa" if item["status"] == "prepared" else "reviewqa"
            label = "選擇目前 AI 繼續" if item["status"] == "prepared" else "檢視保留答案"
            identity = html.escape(item["request_id"], quote=True)
            links += f'<a href="{action}:{identity}">{label}</a>&nbsp; '
    else:
        body = _markdown(answer["body"], pal, rich)
        links = (
            f'<a href="keep:{int(answer["id"])}" style="color:{pal["accent"]};">'
            "＋ 存成筆記</a>&nbsp;&nbsp; "
        )
    if question is not None:
        links += (
            f'<a href="delq:{int(question["id"])}" style="color:{pal["faint"]};">刪除這組問答</a>'
        )
    return (
        '<table class="note-card" width="100%" cellpadding="10" cellspacing="0" '
        f'style="margin-bottom:12px;border:1px solid {pal["border"]};">'
        f"<tr>{head}</tr>"
        f'<tr><td bgcolor="{pal["surface"]}">'
        f'<div style="color:{pal["ink"]};font-size:13px;">{body}</div>'
        f'<div align="right" style="font-size:11px;">{links}</div></td></tr></table>'
    )


@dataclass(frozen=True)
class RenderedSaved:
    snapshot: SavedSnapshot
    chat_html: str
    dive_html: str
    coverage: tuple[str, ...]
    highlights: dict | None = None


def render(snapshot, palette, *, rich=False, dive_rich=None, figures=(), empty_dive=None,
           active_request=None):
    """Typeset captured saved content; figure previews never grant source authority."""
    worker_only()
    if not isinstance(snapshot, SavedSnapshot):
        raise ValueError("A saved-reader snapshot is required")
    data = snapshot.data
    pal = dict(palette)
    rows = [item["row"] for item in data["chat"]["rows"]]
    pending = {item["user_key"]: item for item in data["pending"]}
    chat = (
        "<h3>問答紀錄</h3>"
        + "".join(
            _exchange(q, a, pending, pal, rich, active_request) for q, a in pair_exchanges(rows)
        )
        if rows
        else f'<div style="color:{pal["faint"]};font-size:12px;">'
        "問答紀錄 · 尚無對話。可在底部自行輸入，或先選擇提問建議。</div>"
    )
    dive = data["dives"][0]["body"] if data["dives"] else ""
    close = data["close_readings"][0]["body"] if data["close_readings"] else None
    analysis, links = None, None
    digest = data["source"]["document_hash"]
    saved = data["annotations"]["highlight_analysis"]
    if digest and saved["row"] and saved["row"]["document_hash"] == digest:
        analysis = {**saved["body"], "source_hash": saved["row"]["source_hash"]}
        saved_links = data["annotations"]["reading_links"]
        if (
            saved_links["row"]
            and saved_links["row"]["document_hash"] == digest
            and saved_links["body"]["analysis_hash"] == analysis["source_hash"]
            and saved_links["row"]["source_hash"]
            == reading_links._key(reading_links.sections(dive, close), analysis)
        ):
            links = saved_links["body"]
    target_rich = rich if dive_rich is None else dive_rich
    page = (
        reading.render(
            dive, close, list(figures), pal, highlights=analysis, links=links, rich=target_rich
        )
        if dive or empty_dive is None
        else _markdown(empty_dive, pal, target_rich)
    )
    if figures and len(chat.encode()) + len(page.encode()) > MAX_BYTES * 8:
        page = reading.render(
            dive, close, [], pal, highlights=analysis, links=links, rich=target_rich
        )
        page += "<p>Cached figure previews exceed the display budget; saved text is unchanged.</p>"
    if len(chat.encode()) + len(page.encode()) > MAX_BYTES * 8:
        raise ValueError("Rendered saved content exceeds its supported budget")
    navigation = (
        {**analysis, "items": [{**item, "document_hash": digest} for item in analysis["items"]]}
        if analysis
        else None
    )
    return RenderedSaved(snapshot, chat, page, tuple(data["not_prepared"]), navigation)
