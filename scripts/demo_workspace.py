"""A small workspace to photograph: one list, a paper with its PDF and a deep dive.

The build machines have no papers.db, and the screenshots taken there are how a
layout is checked on Windows, macOS and Linux side by side. Everything here is
written for the purpose; nothing is copied from a real paper.
"""

from __future__ import annotations

from datetime import datetime

LIST_ID = "demo"
PAPER_ID = "demo:paperfact"

DIVE = r"""## 一句話結論

這篇示範論文提出一個讀論文的工作流程：先讀講解，再對照原文，最後把筆記整理成簡報。

## 核心方法

閱讀進度以 $p_t = \frac{r_t}{n}$ 表示，其中 $r_t$ 是第 $t$ 天讀完的段落數。

```pseudocode
for each paper in list:
    read the deep dive
    check claims against the PDF
```

## 審稿人會問

- 這個流程和一般的筆記軟體差在哪？
- 自動標註的重點準確嗎？
"""

PDF_TEXT = (
    "Paperfact: A Reading Workflow for Research Papers",
    "Demo Author",
    "Abstract. This document exists so that screenshots taken on every platform show "
    "the same page. It describes no real result.",
    "1 Introduction",
    "Reading a paper well means moving between an explanation and the original text. "
    "This page stands in for the original text.",
)


def seed() -> None:
    """Fill an empty data directory; config must already point at it."""
    import fitz

    from paper_daily import store
    from paper_daily.config import PDF_DIR, ensure_dirs

    ensure_dirs()
    store.init_db()
    now = datetime.now().isoformat(timespec="seconds")
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                dict(
                    id=PAPER_ID,
                    title=PDF_TEXT[0],
                    venue="Demo",
                    year=2026,
                    source="demo",
                    abstract=PDF_TEXT[2],
                )
            ],
        )
        conn.execute(
            "INSERT OR REPLACE INTO lists (id, name, note, created_at) VALUES (?, ?, ?, ?)",
            (LIST_ID, "示範清單", None, now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO list_papers (list_id, paper_id, position, state, added_at)"
            " VALUES (?, ?, 0, 'pending', ?)",
            (LIST_ID, PAPER_ID, now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO dives (paper_id, body, written_at) VALUES (?, ?, ?)",
            (PAPER_ID, DIVE, now),
        )
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for i, line in enumerate(PDF_TEXT):
        size = 16 if i == 0 else 11
        page.insert_textbox(fitz.Rect(72, y, 540, y + 80), line, fontsize=size)
        y += 40 if i < 2 else 70
    doc.save(str(PDF_DIR / "demo_paperfact.pdf"))
