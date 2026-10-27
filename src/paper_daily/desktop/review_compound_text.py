"""Readable, non-executing grouped research previews; never edits their typed payload."""

import json

FIELDS = {
    "ref_key": ("Reference", "引用識別"),
    "work_id": ("Work", "文獻識別"),
    "url": ("URL", "網址"),
    "year": ("Year", "年份"),
    "venue": ("Venue", "會議／期刊"),
    "doi": ("DOI", "DOI"),
    "purpose": ("Purpose", "用途"),
    "gist": ("Key point", "重點"),
    "verdict": ("Assessment", "評估"),
    "why": ("Why it matters", "重要性"),
    "relation": ("Relation", "關係"),
    "abstract": ("Abstract", "摘要"),
    "context": ("Context", "脈絡"),
    "contexts_json": ("Evidence", "依據"),
    "citations": ("Citations", "引用數"),
    "kind": ("Resource type", "資源種類"),
    "note": ("Note", "筆記"),
    "license": ("License", "授權"),
    "stars": ("Stars", "星號數"),
    "source": ("Discovery source", "發現來源"),
    "basis": ("Basis", "依據種類"),
    "written_at": ("Written", "撰寫時間"),
    "fetched_at": ("Fetched", "蒐集時間"),
    "checked_at": ("Checked", "檢查時間"),
    "pushed_at": ("Updated", "更新時間"),
    "arxiv_id": ("arXiv", "arXiv"),
    "s2_id": ("Semantic Scholar", "Semantic Scholar"),
    "edited": ("Manually edited", "曾手動編輯"),
    "own": ("Authors' resource", "作者資源"),
    "alive": ("Available", "可取得"),
    "influential": ("Influential", "具影響力"),
}


def group_text(value, *, chinese=False):
    if value is None:
        return "無資料或無法取得" if chinese else "Absent or unavailable"
    language = int(chinese)
    lines = []
    paper = value.get("paper")
    if paper:
        lines.append(("論文：" if chinese else "Paper: ") + paper.get("title", paper["id"]))
        lines.append(paper["id"])
        for name in ("year", "venue", "abstract", "doi", "arxiv_id"):
            if paper.get(name) not in (None, ""):
                lines.append(FIELDS[name][language] + ": " + str(paper[name]))
        lines.append("")
    rows = value.get("puts", value.get("rows", []))
    heading = (
        ("新增／取代" if chinese else "Add or replace")
        if "puts" in value
        else ("資料" if chinese else "Records")
    )
    lines.append(f"{heading} ({len(rows)})")
    for index, row in enumerate(rows, 1):
        title = row.get("title") or row.get("url") or row.get("ref_key") or row.get("work_id", "")
        lines.extend(["", f"{index}. {json.dumps(title, ensure_ascii=False)}"])
        for name, labels in FIELDS.items():
            item = row.get(name)
            if item is None or item == "":
                continue
            lines.append(labels[language] + ": " + str(item))
    if "deletes" in value:
        removed = value["deletes"]
        lines.extend(["", ("刪除" if chinese else "Remove") + f" ({len(removed)})"])
        lines.extend("- " + key for key in removed)
    if value.get("completion") is not None:
        lines.extend(
            ["", "包含此階段完成狀態更新" if chinese else "Includes this phase's completion update"]
        )
    return "\n".join(lines)
