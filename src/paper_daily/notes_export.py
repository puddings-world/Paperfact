"""A paper's notes and highlights as a plain Markdown file someone can keep anywhere.

Exported files end up in Obsidian, Logseq or a git repo, and people write in them.
So the generated part sits between two marker comments and a re-export replaces only
that block; anything written above or below it survives. A file whose markers are
gone is never overwritten: the new export goes next to it as `<name>.new.md`.
Only what the person wrote, marked or kept is exported; no account or provider
details are written.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

BEGIN = "<!-- paperfact:begin (regenerated on every export; write outside this block) -->"
END = "<!-- paperfact:end -->"
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def _page(anchor: str) -> int | None:
    try:
        return int(json.loads(anchor)["p0"]) + 1
    except (ValueError, KeyError, TypeError):
        return None


def _quote(text: str) -> str:
    return "> " + " ".join(text.split())


def paper_block(conn, paper_id: str) -> tuple[str, str]:
    """(title, generated Markdown block) for one paper."""
    paper = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
    if paper is None:
        raise ValueError(f"no paper {paper_id}")
    title = " ".join(paper["title"].split())
    authors = ", ".join(json.loads(paper["authors_json"] or "[]"))
    source = " ".join(str(v) for v in (paper["venue"], paper["year"]) if v)
    link = (
        f"https://doi.org/{paper['doi']}"
        if paper["doi"]
        else f"https://arxiv.org/abs/{paper['arxiv_id']}"
        if paper["arxiv_id"]
        else paper["page_url"] or ""
    )
    out = [BEGIN, f"# {title}", ""]
    out += [line for line in (authors, " · ".join(v for v in (source, link) if v)) if line]
    out.append("")

    mine = sorted(
        conn.execute(
            "SELECT quote, anchor FROM pdf_highlights WHERE paper_id=?", (paper_id,)
        ).fetchall(),
        key=lambda row: (_page(row["anchor"]) or 0, row["anchor"]),
    )
    if mine:
        out += ["## 我的螢光筆", ""]
        for row in mine:
            page = _page(row["anchor"])
            out += [_quote(row["quote"]), *([f"— 第 {page} 頁"] if page else []), ""]

    ai = conn.execute(
        "SELECT quote, anchor, reason FROM pdf_ai_highlights WHERE paper_id=? AND hidden=0",
        (paper_id,),
    ).fetchall()
    if ai:
        # Labelled as AI so nobody later mistakes a model's pick for their own reading.
        out += ["## AI 重點", ""]
        for row in sorted(ai, key=lambda row: (_page(row["anchor"]) or 0, row["anchor"])):
            page = _page(row["anchor"])
            where = f"第 {page} 頁 · " if page else ""
            out += [_quote(row["quote"]), f"— {where}AI：{row['reason']}", ""]

    notes = conn.execute(
        "SELECT body, kind, page, created_at FROM notes WHERE paper_id=? ORDER BY created_at, id",
        (paper_id,),
    ).fetchall()
    if notes:
        out += ["## 筆記", ""]
        for row in notes:
            label = {"ask": "問 AI", "key": "關鍵筆記"}.get(row["kind"], "手寫")
            where = f" · 第 {row['page']} 頁" if row["page"] else ""
            out += [
                f"### {label}{where} · {(row['created_at'] or '')[:10]}",
                "",
                row["body"].strip(),
                "",
            ]
    if not (mine or ai or notes):
        out += ["（這篇還沒有筆記或標記。）", ""]
    out.append(END)
    return title, "\n".join(out)


def merge(existing: str | None, block: str) -> str | None:
    """The file's new text, or None when it can't be updated without losing writing."""
    if existing is None:
        return block + "\n"
    if existing.count(BEGIN) != 1 or existing.count(END) != 1:
        return None
    start, end = existing.index(BEGIN), existing.index(END) + len(END)
    if end < start:
        return None
    return existing[:start] + block + existing[end:]


def file_name(title: str, paper_id: str) -> str:
    name = " ".join(_UNSAFE.sub(" ", title).split()).strip(". ")[:90]
    return f"{name or paper_id}.md"


def export(conn, paper_ids: list[str], out_dir: Path) -> list[dict]:
    """Write one file per paper; each result says what happened to that file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    results, used = [], set()
    for pid in paper_ids:
        title, block = paper_block(conn, pid)
        name = file_name(title, pid)
        if name.casefold() in used:
            name = file_name(f"{title} {pid}", pid)
        used.add(name.casefold())
        path = out_dir / name
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        text = merge(existing, block)
        if text is None:
            path = path.with_suffix(".new.md")
            text, status = block + "\n", "kept"
        elif existing is None:
            status = "written"
        elif text == existing:
            status = "unchanged"
        else:
            status = "updated"
        if status != "unchanged":
            path.write_text(text, encoding="utf-8", newline="\n")
        results.append({"paper_id": pid, "path": path, "status": status})
    return results
