"""A reading list read as one field: where it came from, where it stands, what is open.

Each paper's deep dive already places that paper -- its 前導導讀 says what the field
looked like when it was written and what gap it claimed. A researcher picking a topic
needs the same thing one level up: the lines of work running through the whole list,
the datasets they share, how far each line has got, and which problems every paper
still names as unsolved. That is a reading across papers, so it is written from the
papers' own analyses rather than their abstracts: one model call over a condensed
digest of every paper (its conclusion, its account of the field and its gap, its
core idea, its evidence and limits, and what later work did with it).

The survey is stored per list and can be edited by hand; a hand-edited survey is
not overwritten unless asked.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from paper_daily import llm
from paper_daily.store import connect, init_db, now

Log = Callable[[str], None]

SURVEY_SPEC = "2026-10-survey"

# The whole digest goes into one call. A list of 40 papers at this budget is about
# 4k characters each, enough for the parts of a dive that carry the field.
BUDGET = 170_000
PER_PAPER_MAX = 6_000

SURVEY_SYSTEM = """你在幫一位研究者掌握一整個研究領域:他的閱讀清單裡的論文,合起來代表這個
領域。你會拿到清單裡每一篇論文的摘要卡:基本資料、一句話結論、它對當時研究狀態與缺口的
描述(前導導讀)、核心洞見、證據、限制,以及後續研究拿它做了什麼。

請寫一份領域綜覽。這是給研究者決定接下來讀什麼、做什麼的,不是逐篇摘要:要跨論文歸納、
比較、指出趨勢與矛盾。用 Markdown,必須使用下面的段落,順序固定:

## 這個領域在解決什麼
三到五句:研究對象、臨床或應用上的需求、為什麼難。

## 研究脈絡
依時間把領域分成幾個階段。每個階段寫:時間範圍、當時的主流做法與限制、
是哪幾篇論文帶來轉折(點名並說明轉折在哪)。最後一段說明現在處在哪個階段。

## 研究路線與代表作
把清單裡的論文分成幾條路線(依任務或方法,例如資料集、phase recognition、
segmentation、技能評估、多模態大模型等,以清單實際內容為準)。每條路線寫:
目標、代表作與它們各自的貢獻、路線內部的演進(誰改進了誰)、目前最好的做法與
數字(只引用卡片裡出現的數字),以及這條路線和其他路線的關係。

## 資料集與評測
一張 Markdown 表格:資料集、年份、規模、標註的任務、哪些論文使用它。表格之後
寫兩三句:評測慣例有哪些不一致、哪些 benchmark 已經飽和或不可比。

## 目前的進展
最近一兩年(以清單裡最新的論文為準)做到了什麼、方法正在往哪裡移動、
哪些過去的問題已經被解決或被證明比想像的容易。

## 面對的挑戰
分成資料、方法、評測、臨床落地四類。每項挑戰要具體:說明它是什麼、哪幾篇論文
提到或受它限制、目前有哪些嘗試以及為什麼還不夠。

## 尚未解決的問題與可做的題目
五到八個具體的研究題目。每個寫:要解決的問題、為什麼現在做得起來(可用的資料、
程式碼或前作)、預期的貢獻、主要風險。題目要能直接寫成一篇論文的 introduction,
不要寫成「可以再研究 X」這種空話。

## 建議閱讀順序
從清單裡挑十篇以內,依建議順序排,每篇一句話理由,幫一個剛進這個領域的人
最快建立全貌。

規則:
- 提到論文時用卡片上的簡稱加年份,例如「Cataract-1K (2024)」。
- 只根據卡片內容寫,不要補充卡片裡沒有的論文、數字或結論;卡片之間矛盾時要指出。
- 用繁體中文,技術名詞與論文標題保留英文,數學用 Unicode 純文字,絕不使用 LaTeX。
- 直接輸出綜覽,不要前言,不要重述這些指示。
"""


def _sections(body: str) -> dict[str, str]:
    """A dive's `## ` sections by heading."""
    out: dict[str, str] = {}
    for part in re.split(r"(?m)^## ", body or ""):
        head, _, text = part.partition("\n")
        if text.strip():
            out[head.strip()] = text.strip()
    return out


def _clip(text: str | None, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def digest(row, dive: str | None, context: str | None, followups: int, limit: int) -> str:
    """One paper's card for the survey, at most `limit` characters."""
    from paper_daily.followups import short_name

    head = (
        f"### {short_name(row['title'])} ({row['year'] or '?'})\n"
        f"{row['title']} · {row['venue'] or '?'} · "
        f"{row['citation_count'] or 0} cites · 後續研究 {followups} 篇"
    )
    if not dive:
        return _clip(f"{head}\n摘要:{row['abstract'] or '(無)'}", limit)
    parts = _sections(dive)
    # The account of the field and of the gap is what a survey is made of, so it gets
    # the largest share; the rest is there to place the paper on its line of work.
    shares = (
        ("一句話結論", 0.06),
        ("前導導讀", 0.42),
        ("問題", 0.12),
        ("核心洞見", 0.08),
        ("證據", 0.16),
        ("限制與反駁", 0.12),
    )
    lines = [head]
    for name, share in shares:
        if parts.get(name):
            lines.append(f"【{name}】{_clip(parts[name], int(limit * share))}")
    if context:
        lines.append(f"【後續研究拿它做了什麼】{_clip(context, int(limit * 0.12))}")
    return _clip("\n".join(lines), limit)


def build_input(conn, list_id: str) -> tuple[str, int]:
    """Every paper's card, in list order, and how many papers there are."""
    rows = conn.execute(
        "SELECT p.*, d.body AS dive, pc.summary AS context, "
        "  (SELECT COUNT(*) FROM followups f WHERE f.paper_id = p.id) AS later "
        "FROM list_papers lp JOIN papers p ON p.id = lp.paper_id "
        "LEFT JOIN dives d ON d.paper_id = p.id "
        "LEFT JOIN paper_context pc ON pc.paper_id = p.id "
        "WHERE lp.list_id = ? ORDER BY p.year, lp.position",
        (list_id,),
    ).fetchall()
    if not rows:
        return "", 0
    limit = min(PER_PAPER_MAX, BUDGET // len(rows))
    cards = [digest(r, r["dive"], r["context"], r["later"], limit) for r in rows]
    name = conn.execute("SELECT name FROM lists WHERE id=?", (list_id,)).fetchone()
    title = name["name"] if name else list_id
    text = f"# 閱讀清單:{title}({len(rows)} 篇,依年份排列)\n\n" + "\n\n".join(cards)
    return text, len(rows)


def write(list_id: str, force: bool = False, log: Log = lambda _m: None) -> tuple[bool, str]:
    """Write the list's survey. Returns (written, reason)."""
    init_db()
    with connect() as conn:
        old = conn.execute("SELECT edited FROM list_surveys WHERE list_id=?", (list_id,)).fetchone()
        if old and old["edited"] and not force:
            return False, "edited by hand (pass --force to replace it)"
        text, count = build_input(conn, list_id)
    if not count:
        return False, f"no papers in list {list_id}"
    log(f"  {count} papers, {len(text):,} characters of digest")
    body, reason = llm.complete(text, system=SURVEY_SYSTEM, timeout=1800, task="survey")
    if not body:
        return False, reason
    if len(body) < 2000:
        return False, f"reply too short to be a survey: {body.splitlines()[0][:120]}"
    with connect() as conn:
        conn.execute(
            "INSERT INTO list_surveys(list_id, body, papers, spec, written_at, edited) "
            "VALUES (?,?,?,?,?,0) ON CONFLICT(list_id) DO UPDATE SET body=excluded.body, "
            "papers=excluded.papers, spec=excluded.spec, written_at=excluded.written_at, "
            "edited=0",
            (list_id, body, count, SURVEY_SPEC, now()),
        )
        conn.commit()
    log(f"  survey written: {len(body):,} characters")
    return True, "ok"


def get(conn, list_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM list_surveys WHERE list_id=?", (list_id,)).fetchone()
    return dict(row) if row else None


def edit(list_id: str, body: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE list_surveys SET body=?, edited=1 WHERE list_id=?", (body, list_id))
        conn.commit()
