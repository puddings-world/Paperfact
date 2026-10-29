"""A page about one or two papers, for someone who has not read them.

The desktop reader is for reading and the pocket page is for reading away from the
desk; both carry the PDF, because they are for the person doing the reading. This is
for everyone else. It carries no PDF -- a reader of the page wants the understanding,
and a publisher's file is not ours to hand around -- only the notes, the analysis,
the figures and what the references are doing.

It is made in two steps with a person in between. `draft` lays out what the database
already holds as one Markdown file; `build` turns that file into the page. The draft
is written once and never overwritten, because the moment it is edited the database
stops being the source of truth for it. That is also why it holds plain Markdown and
nothing else: quotes and figures are written out in full when the draft is made, so
any editor can change it and nothing needs re-resolving at build time.

Places for the reader's own words are HTML comments. An unedited draft still builds
into a page that reads cleanly, instead of one full of "<< fill this in >>".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from paper_daily import llm
from paper_daily.config import DATA_DIR
from paper_daily.figures import FIG_DIR, _safe
from paper_daily.pocket import cites_for, figures_for, lineage_for
from paper_daily.store import connect

SHARE_DIR = DATA_DIR / "share"
TEMPLATE = Path(__file__).with_name("share_page.html")
TYPESET = Path(__file__).with_name("typeset.js")

WORTH = ("必讀", "值得")
VERDICT_CLASS = {"必讀": "must", "值得": "worth", "參考": "ref", "略過": "skip"}

# A figure is re-encoded only when that saves real weight; a chart compresses better
# as PNG than as JPEG and keeps its edges.
JPEG_QUALITY = 82

COMPARE_SYSTEM = (
    "你在幫一位研究生整理兩到三篇論文的對讀。只根據提供的內容回答,不要補充你自己知道"
    "但文中沒有的數字。用繁體中文,技術名詞保留英文。數學用純 Unicode 寫(例如 "
    "Dice = 2·|A∩B| / (|A|+|B|)),絕對不要用 LaTeX、$ 符號或反斜線指令。"
)


def slug_for(paper_ids: list[str]) -> str:
    return "-".join(_safe(pid).split("-")[-1][:16] for pid in paper_ids)[:60]


def _demote(markdown: str, levels: int) -> str:
    """Push every heading down, so a dive's sections sit under the paper's title."""
    return re.sub(
        r"^(#{1,6})(\s)",
        lambda m: "#" * min(6, len(m.group(1)) + levels) + m.group(2),
        markdown,
        flags=re.MULTILINE,
    )


def _authors(names: list[str]) -> str:
    if len(names) > 3:
        return f"{names[0]} et al."
    return ", ".join(names)


def _short(title: str) -> str:
    """What people call the paper: "StepAL", "Cataract-1K", not the full title."""
    head = title.split(":")[0].strip()
    return head if len(head.split()) <= 3 else head.split()[0]


def _figure_file(paper_id: str, name: str, dest_dir: Path) -> str:
    """Copy a figure next to the draft, as JPEG when that is clearly smaller."""
    import pymupdf

    src = FIG_DIR / _safe(paper_id) / name
    dest_dir.mkdir(parents=True, exist_ok=True)
    png = src.read_bytes()
    jpeg = pymupdf.Pixmap(str(src)).tobytes("jpeg", jpg_quality=JPEG_QUALITY)
    if len(jpeg) < len(png) * 0.6:
        out = dest_dir / (Path(name).stem + ".jpg")
        out.write_bytes(jpeg)
    else:
        out = dest_dir / name
        out.write_bytes(png)
    return out.name


def _notes(conn, paper_id: str) -> list[dict]:
    """The reader's notes in the order the paper is read: by page, then as written."""
    rows = conn.execute(
        "SELECT body, kind, page, created_at FROM notes WHERE paper_id=? "
        "ORDER BY page IS NULL, page, id",
        (paper_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _split_quote(body: str) -> tuple[str, str]:
    """A note's leading "> " lines are the passage, the rest is what was thought.

    The reader writes the two with a single newline between them, and Markdown would
    read the thought as a continuation of the quote.
    """
    lines = body.strip().splitlines()
    n = 0
    while n < len(lines) and lines[n].startswith(">"):
        n += 1
    return "\n".join(lines[:n]), "\n".join(lines[n:]).strip()


def _note_md(note: dict) -> str:
    quote, thought = _split_quote(note["body"])
    who = "問 AI" if note["kind"] == "ask" else "筆記"
    where = f" · 第 {note['page']} 頁" if note["page"] else ""
    return (
        f'<div class="note {note["kind"]}">\n\n'
        f'<p class="note-meta">{who}{where}</p>\n\n'
        + (f"{quote}\n\n" if quote else "")
        + f"{thought}\n\n"
        "</div>"
    )


def _cite_md(c: dict) -> str:
    meta = [str(x) for x in (c["year"], c["venue"]) if x]
    if c["citations"]:
        meta.append(f"{c['citations']:,} cites")
    title = c["title"] or "(無法辨識是哪一篇)"
    if c["doi"]:
        title = f"[{title}](https://doi.org/{c['doi']})"
    lines = [
        f'<div class="cite {VERDICT_CLASS.get(c["verdict"] or "", "ref")}">\n',
        f'<p class="cite-head"><span class="verdict">{c["verdict"] or "?"}</span> '
        f'<span class="key">[{c["key"]}]</span></p>\n',
        f"**{title}**" + (f"  \n<small>{' · '.join(meta)}</small>" if meta else ""),
        "",
    ]
    for label, value in (("用途", c["purpose"]), ("判斷", c["why"])):
        if value:
            lines.append(f"**{label}**　{value}  ")
    if c["contexts"]:
        lines += ["", f"> {c['contexts'][0]}"]
    lines += ["", "</div>"]
    return "\n".join(lines)


def _paper_md(conn, paper_id: str, out_dir: Path) -> tuple[str, dict]:
    row = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
    if row is None:
        raise ValueError(f"no paper {paper_id}")
    authors = json.loads(row["authors_json"] or "[]")
    dive = conn.execute("SELECT body FROM dives WHERE paper_id=?", (paper_id,)).fetchone()
    notes = _notes(conn, paper_id)
    cites = cites_for(conn, paper_id)
    lineage = lineage_for(conn, paper_id)
    figures = figures_for(paper_id)

    byline = [_authors(authors), f"{row['venue']} {row['year']}"]
    if row["doi"]:
        byline.append(f"[doi:{row['doi']}](https://doi.org/{row['doi']})")
    out = [f"## {row['title']}", "", '<p class="byline">' + " · ".join(byline) + "</p>", ""]
    out += ["<!-- 一句話:你讀完這篇最想讓別人知道的事。寫在這行下面。 -->", ""]

    if row["abstract"]:
        abstract = row["abstract"].strip()
        out += ["<details><summary>摘要</summary>", "", abstract, "", "</details>", ""]

    out += ["### 我的筆記", ""]
    if notes:
        out += [_note_md(n) + "\n" for n in notes]
    else:
        out += [
            "<!-- 還沒有筆記。在桌面 app 框選原文寫筆記、或把問答按「＋ 存成便條」,",
            "     再重跑 share draft(會寫成 draft.new.md,不會蓋掉這份)。 -->",
            "",
        ]

    if dive:
        body = _demote(dive["body"].strip(), 2)
        out += ["### 深度講解", "", '<div class="dive">', "", body, "", "</div>", ""]

    if figures:
        fig_dir = out_dir / "fig" / _safe(paper_id)
        out += ["### 圖表", "", '<div class="figures">', ""]
        for f in figures:
            name = _figure_file(paper_id, f["file"], fig_dir)
            out += [
                f"![{f['label']}](fig/{_safe(paper_id)}/{name})",
                f"<small>{f['caption']} · 原文第 {f['page']} 頁</small>",
                "",
            ]
        out += ["</div>", ""]

    out += ["### 引用", ""]
    if lineage["ancestors"] or lineage["descendants"]:
        out += ["#### 在文獻裡的位置", ""]
        for label, rows in (("建立在", lineage["ancestors"]), ("被引用於", lineage["descendants"])):
            for r in rows:
                star = " ★" if r["influential"] else ""
                out.append(f"- {label} **{r['title']}** · {r['venue']} {r['year']}{star}")
        out.append("")
    if cites:
        worth = [c for c in cites if c["verdict"] in WORTH]
        rest = [c for c in cites if c["verdict"] not in WORTH]
        out += [
            "#### 參考文獻在做什麼",
            "",
            f"{len(cites)} 筆參考文獻,其中 {len(worth)} 筆值得往下讀。"
            "每筆附上論文引用它的那一句,判斷可以自己核對。",
            "",
        ]
        out += [_cite_md(c) + "\n" for c in worth]
        if rest:
            out += [f"<details><summary>其餘 {len(rest)} 筆(參考 / 略過)</summary>", ""]
            out += [_cite_md(c) + "\n" for c in rest]
            out += ["</details>", ""]

    facts = {
        "title": row["title"],
        "short": _short(row["title"]),
        "venue": f"{row['venue']} {row['year']}",
        "authors": _authors(authors),
        "doi": row["doi"],
        "notes": len(notes),
        "cites": len(cites),
        "worth": sum(1 for c in cites if c["verdict"] in WORTH),
        "figures": sum(1 for f in figures if f["kind"] == "figure"),
        "tables": sum(1 for f in figures if f["kind"] == "table"),
        "dive": dive["body"] if dive else "",
        "abstract": row["abstract"] or "",
    }
    return "\n".join(out), facts


def _facts_table(facts: list[dict]) -> str:
    head = "| | " + " | ".join(f["short"] for f in facts) + " |"
    rule = "|---" * (len(facts) + 1) + "|"
    rows = [
        ("出處", [f["venue"] for f in facts]),
        ("作者", [f["authors"] for f in facts]),
        ("DOI", [f"[{f['doi']}](https://doi.org/{f['doi']})" if f["doi"] else "—" for f in facts]),
        ("圖 / 表", [f"{f['figures']} / {f['tables']}" for f in facts]),
        ("參考文獻", [f"{f['cites']} 筆 · {f['worth']} 筆值得讀" for f in facts]),
        ("我的筆記", [f"{f['notes']} 則" for f in facts]),
    ]
    body = ["| " + label + " | " + " | ".join(vals) + " |" for label, vals in rows]
    return "\n".join([head, rule, *body])


def compare(facts: list[dict]) -> tuple[str | None, str]:
    """Ask the model for the comparison, from the dives -- never from its own memory."""
    parts = []
    for f in facts:
        parts.append(
            f"### {f['title']} ({f['venue']})\n\n摘要:\n{f['abstract']}\n\n"
            f"深度講解:\n{f['dive'][:9000]}"
        )
    prompt = (
        "\n\n".join(parts)
        + "\n\n---\n\n請輸出 Markdown,只要以下兩部分,不要前言:\n"
        "1. 一張對照表,欄是各篇的簡稱,列是:研究問題、資料來源與規模、標註內容、"
        "提供的任務與 benchmark、評估指標、主要限制。每格一兩句。\n"
        "2. 一個「放在一起看」小節,三到五個條列:這幾篇的關係(延伸、互補、取代?)、"
        "彼此能補上對方哪個缺口、讀者該先讀哪篇以及為什麼。\n"
        "標題用 #### 層級。"
    )
    return llm.complete(prompt, system=COMPARE_SYSTEM, timeout=600, task="compare")


def draft(
    paper_ids: list[str],
    slug: str | None = None,
    with_compare: bool = False,
    force: bool = False,
) -> dict:
    """Lay the papers out as one Markdown file to edit. Never overwrites an edit."""
    slug = slug or slug_for(paper_ids)
    out_dir = SHARE_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    edited = (out_dir / "draft.md").exists()

    sections, facts = [], []
    with connect() as conn:
        for pid in paper_ids:
            md, f = _paper_md(conn, pid, out_dir)
            sections.append(md)
            facts.append(f)

    title = " × ".join(f["short"] for f in facts)
    doc = [f"# {title}", "", "<!-- 一句話:這幾篇放在一起說明了什麼。寫在這行下面。 -->", ""]
    failed = ""
    if len(facts) > 1:
        doc += ["## 對讀", "", _facts_table(facts), ""]
        if with_compare and edited and not force:
            # build only reads draft.md, so a comparison written to draft.new.md is
            # paid for and then never shown unless the reader merges it by hand.
            failed = (
                "draft.md 已存在，未重新付費產生 AI 對照；"
                "要重做請先移走 draft.md"
            )
        elif with_compare:
            text, reason = compare(facts)
            if not text:
                failed = reason
            else:
                doc += [
                    '<p class="provenance">以下由 AI 依各篇的深度講解整理,'
                    "未逐條對照原文。</p>",
                    "",
                    text.strip(),
                    "",
                ]
        doc += ["<!-- 對讀表可以自己加列:你在意、但上面沒有的比較點。 -->", ""]
    doc += sections

    path = out_dir / "draft.md"
    if path.exists():
        path = out_dir / "draft.new.md"
    path.write_text("\n".join(doc), encoding="utf-8")
    return {"path": path, "slug": slug, "compare_failed": failed}


def build(slug: str) -> dict:
    """Render the edited draft into the page, with its figures beside it."""
    out_dir = SHARE_DIR / slug
    source = (out_dir / "draft.md").read_text(encoding="utf-8")
    # The Markdown travels inside a <script> element; a literal "</script>" in a
    # quote would end it early.
    payload = json.dumps(source, ensure_ascii=False).replace("</", "<\\/")
    title = next((ln[2:].strip() for ln in source.splitlines() if ln.startswith("# ")), slug)
    html = (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("__TITLE__", title.replace("<", "&lt;"))
        .replace("/*__DRAFT__*/null", payload)
        .replace("/*__TYPESET__*/", TYPESET.read_text(encoding="utf-8"))
    )
    page = out_dir / "index.html"
    page.write_text(html, encoding="utf-8")

    referenced = set(re.findall(r"\]\((fig/[^)\s]+)\)", source))
    files = {ref: str(out_dir / ref) for ref in sorted(referenced) if (out_dir / ref).exists()}
    missing = sorted(referenced - files.keys())
    return {
        "page": page,
        "files": files,
        "missing": missing,
        "bytes": page.stat().st_size + sum(Path(p).stat().st_size for p in files.values()),
    }
