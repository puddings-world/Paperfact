"""逐節精讀: the body of a paper walked section by section, with its own figures.

A deep dive is a reading of the whole paper at the level of its argument, and its
前導導讀 takes the introduction and related work slowly. The method and the
experiments got a paragraph each, which is a summary: enough to know what was done,
not enough to follow how, or to judge whether a table shows what the text says it
shows. This is the second half of that reading -- every section after the front
matter, in the paper's order, at the depth 前導導讀 gives the introduction.

It is its own model call rather than more sections in the dive: the dive is already
long, and a reply twice that long is where a model starts to compress the end. The
reader shows the two as one document under 深度講解, and a paper counts as explained
(講解) only when both exist.

Where the text discusses a figure or table it writes a marker line, `[[Figure 3]]`,
and the reader puts the paper's own rendering of that exhibit there (figures.py),
so the explanation and the graphic it is about sit together.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from paper_daily import brief, llm
from paper_daily.store import connect, init_db, now

Log = Callable[[str], None]

CLOSE_SPEC = "2026-10-sections"

# A marker on a line of its own: [[Figure 3]], [[Table 2]], [[Fig. 1]].
MARKER = re.compile(r"^\s*\[\[\s*((?:Figure|Fig\.|Table)\s+\d+[a-z]?)\s*\]\]\s*$", re.I)

CLOSE_INSTRUCTIONS = """\
你是一位嚴謹的研究導讀者。下面是一篇論文的 briefing pack。這篇已經有一份深度講解,
其中的「前導導讀」逐段講過 Introduction、Background 與 Related Work。你要寫的是
後半部:從方法開始的每一個章節,用同樣的細緻程度逐節講解,讓讀者不必回頭讀原文
也能說清楚每一節做了什麼、為什麼這樣做、證據是否成立。

結構:
- 依論文自己的章節順序,每個章節一個 `## ` 標題,沿用原文的編號與名稱
  (例如「## 3 Method」「## 4.2 Ablation Study」);子節用 `### `。
  前導章節(Introduction、Related Work、Background)不要再寫。
  附錄只挑對理解主文必要的部分,放在最後的「## 附錄重點」。
- 方法類章節:照原文段落順序講每一個設計。寫出它解決什麼、怎麼運作、為什麼
  這樣設計而不是另一種做法、和前作差在哪。關鍵式子用 LaTeX 寫出來,並逐項解釋
  每個符號。符號或超參數很多時,整理成 Markdown 表格(符號、意義、數值)。
- 資料與實驗設定:用 Markdown 表格列出資料集(規模、切分、標註)、評估指標
  (定義與方向)、baseline、實作細節(backbone、訓練設定)。
- 每一個實驗或表格:先說它要回答什麼問題;再用 Markdown 表格重現關鍵的幾列與
  幾欄(數字必須照原文抄,不要四捨五入,不要補沒出現的數字);接著解讀:
  差距多大、是否在變異範圍內、比較是否公平、它證明了什麼、沒有證明什麼。
- 討論、限制與結論章節:作者自己承認了什麼、哪些主張超出了實驗支撐的範圍。

圖表:
- pack 的 Figures and tables 段落列出這篇自己的圖表。講到某張圖或表時,在相關
  段落之後單獨放一行標記,格式恰好是 `[[Figure 3]]` 或 `[[Table 2]]`
  (編號照 pack 列出的寫),讀者的 app 會在那裡顯示原圖。每張圖表最多放一次,
  放在第一次詳細討論它的地方;pack 沒列出的編號不要放。
- 放了圖的段落要告訴讀者這張圖要看什麼、看出來能確認哪個論點。注意:你看不到
  圖本身,只讀得到圖說與內文。說明只能根據圖說和內文對這張圖的描述,不要猜測
  圖的形式(長條圖、圓餅圖、折線)、顏色、位置或圖上沒寫出的數字。表格則可以照
  內文抽出的數字重現。
- 需要畫圖時用 ```mermaid 區塊(多用 flowchart TD,由上往下讀),6 到 10 個節點,
  每個節點文字不超過 15 字,細節寫在圖下的說明而不是塞進節點;節點文字含括號、冒號或
  運算符時用雙引號包起來,例如 A["Y_t = c_xx + f_xᵀ Y_(t+1) f_x"]。圖裡的數學用
  Unicode,mermaid 不排 LaTeX。不要用框線字元畫圖,也不要 TikZ 或圖片語法。
- 演算法或逐步流程用 ```pseudocode Algorithm 1 · 名稱 區塊:一行一步,關鍵字用英文
  (for、while、if、return、end),縮排表示區塊,註解用 //。
- 程式碼用標了語言的區塊,例如 ```python。

輸出規則:
- 用繁體中文,技術名詞、論文標題、作者名保留英文。
- 數學用 LaTeX:行內寫 $...$(錢字號內側不留空白),獨立的式子寫成 $$ 單獨一行、
  式子、$$ 單獨一行。讀者的 app 與帶出門頁面用 KaTeX 排版。錢字號只用來包數學,
  金額寫成「USD 5」。
- 只根據 pack 裡的全文寫,數字只能引用實際讀到的。pack 說全文無法取得時,只寫一段
  說明無法逐節講解,不要編造。
- 直接輸出講解,不要前言,不要重述這些指示。
"""


def write(paper_id: str, timeout: int = 1800) -> tuple[str | None, str]:
    """Write one paper's close reading. Returns (body, reason)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT p.*, q.role, q.reason FROM papers p "
            "LEFT JOIN queue q ON q.paper_id = p.id WHERE p.id = ?",
            (paper_id,),
        ).fetchone()
        if row is None:
            return None, f"no paper {paper_id}"
        pack, pdf = brief.pack_text(conn, row)
    if pdf is None:
        return None, "no PDF: a close reading needs the full text"
    body, reason = llm.complete(pack, system=CLOSE_INSTRUCTIONS, timeout=timeout, task="dive")
    if not body:
        return None, reason
    # A refusal or an "I cannot read the text" is short; a section-by-section
    # reading of even a four-page paper is not.
    if len(body) < 3000:
        return None, f"reply too short to be a close reading: {body.splitlines()[0][:120]}"
    with connect() as conn:
        conn.execute(
            "INSERT INTO close_readings(paper_id, body, spec, written_at) VALUES (?,?,?,?) "
            "ON CONFLICT(paper_id) DO UPDATE SET body=excluded.body, spec=excluded.spec, "
            "written_at=excluded.written_at",
            (paper_id, body, CLOSE_SPEC, now()),
        )
        conn.commit()
    return body, "ok"


def get(conn, paper_id: str) -> str | None:
    row = conn.execute("SELECT body FROM close_readings WHERE paper_id=?", (paper_id,)).fetchone()
    return row["body"] if row else None


def select(conn, paper_ids: list[str], rewrite: bool = False) -> list[str]:
    """The papers among these that need one: none yet, or an older spec."""
    out = []
    for pid in paper_ids:
        row = conn.execute("SELECT spec FROM close_readings WHERE paper_id=?", (pid,)).fetchone()
        if row is None or (rewrite and row["spec"] != CLOSE_SPEC):
            out.append(pid)
    return out


def write_many(paper_ids: list[str], jobs: int = 3, log: Log = print) -> int:
    """Write several at once; each is a long wait on a model. Returns how many."""
    init_db()
    with connect() as conn:
        titles = (
            {
                r["id"]: r["title"][:56]
                for r in conn.execute(
                    f"SELECT id, title FROM papers WHERE id IN ({','.join('?' * len(paper_ids))})",
                    paper_ids,
                )
            }
            if paper_ids
            else {}
        )
    written = 0
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {pool.submit(write, pid): pid for pid in paper_ids}
        for future in as_completed(futures):
            pid = futures[future]
            body, reason = future.result()
            if body:
                written += 1
                log(f"  逐節精讀 {len(body):,} chars  {titles.get(pid, pid)}")
            else:
                log(f"  failed [{titles.get(pid, pid)}]: {reason}")
    return written
