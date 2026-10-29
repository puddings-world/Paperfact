"""Write deep dives ahead of the reading.

One paper a night is the floor, not the pace: the reader jumps around the queue and
follows lineage backwards, and an explanation that only exists for tonight's paper is
missing exactly when it is wanted. This keeps a buffer of the next few papers already
explained.

Generation goes through `llm.complete`, so the same dive can be written by the local
`claude` CLI, an Anthropic key, or any OpenAI-compatible endpoint.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from paper_daily import brief, closeread, llm
from paper_daily.store import connect, get_kv, init_db, now, set_kv

Log = Callable[[str], None]

# Bumped when the specification below changes, so `dive-ahead --rewrite` can tell
# which dives are already on the current one.
DIVE_SPEC = "2026-10-front-matter"

# The canonical specification of what a deep dive is. `.claude/commands/paper-today.md`
# describes the same thing for the interactive path; keep them in step.
DIVE_INSTRUCTIONS = """\
你是一位嚴謹的 ML 研究導讀者。下面是一篇論文的 briefing pack,請據此寫一份深度講解。

輸出規則:
- 用繁體中文,技術名詞、論文標題、作者名保留英文。
- 數學用 LaTeX:行內寫 $...$(錢字號內側不留空白),獨立的式子寫成 $$ 單獨一行、
  式子、$$ 單獨一行。讀者的 app 與帶出門頁面用 KaTeX 排版。錢字號只用來包數學,
  金額寫成「USD 5」。
- 只根據 pack 裡的內容寫。pack 說全文無法取得時,明說你只能依摘要判斷,不要編造細節。
- 數字只能引用你實際讀到的。
- 直接輸出講解本文,不要任何前言、不要說「好的」、不要重述這些指示。
- 需要畫圖時用 ```mermaid 區塊(多用 flowchart TD,由上往下讀),6 到 10 個節點,
  每個節點文字不超過 15 字,細節寫在圖下的說明而不是塞進節點;節點文字含括號、冒號或
  運算符時用雙引號包起來,例如 A["Y_t = c_xx + f_xᵀ Y_(t+1) f_x"]。圖裡的數學用
  Unicode,mermaid 不排 LaTeX。不要用框線字元畫圖,也不要 TikZ 或圖片語法。
- 演算法或逐步流程用 ```pseudocode Algorithm 1 · 名稱 區塊:一行一步,關鍵字用英文
  (for、while、if、return、end),縮排表示區塊,註解用 //。
- 程式碼用標了語言的區塊,例如 ```python。
- pack 的 Figures and tables 段落列出這篇自己的圖表編號。要指涉證據時直接寫
  「Figure 5」「Table 2」,讀者在 app 的圖表分頁看得到同一張圖;pack 沒列出的編號不要提。

必須使用這十個段落,順序固定。「前導導讀」是全文最長的段落,其餘段落維持精簡:

## 一句話結論
這篇實際確立了什麼,一句話。

## 前導導讀
帶讀者讀懂 Introduction、Background、Related Work(以及 Preliminaries、Motivation
這類放在方法之前的章節)。讀者要靠這一段掌握這篇的敘事:研究當下處在什麼狀態、
作者怎麼把問題框出來、站在誰的肩膀上又和誰劃清界線。這是導讀,不是摘要:
依照論文自己的順序走,把每一步論證講清楚,寫到讀者不必回頭讀那幾頁也能說出
作者的論點。用下面五個小節(### 標題),每一節都要具體:

### 研究當下的狀態
這篇寫成時這個領域的現況:主流做法與代表作、大家用的資料集與 benchmark、
典型的數字水準、業界或臨床的實際需求,以及大家默認的假設。以論文前導章節實際
寫到的為準,點名它引用的工作(保留引用編號,例如 [12])。

### 作者的論證怎麼推進
照 Introduction 的段落順序,一段一段講:這一段主張什麼、拿什麼支撐(引用、數字、
例子、圖)、怎麼接到下一段。關鍵的一兩句可以引原文英文(每句不超過 25 字),
再用中文解釋它在論證中的作用。指出論證的轉折點:作者在哪裡從「現況」轉到「缺口」,
又從「缺口」轉到「我們的做法」。

### 相關研究的地圖
把 Related Work 和前導章節提到的前作分成幾條路線。每條路線寫:代表作(帶引用
編號)、它們做到什麼、作者認為它們缺什麼,以及這篇和它們的關係(沿用、改進、
並列,或反對)。若作者對某條路線的描述不完整或偏頗,直接指出。

### 缺口、主張與貢獻
作者宣稱要解決的確切問題或研究問題;列出論文自己條列的貢獻(照原文的順序與
措辭轉述);每項貢獻後註明後文用哪個實驗或圖表支撐(例如「見 Table 2」),
或註明「後文沒有直接驗證」。

### 讀前導章節時該帶著的問題
三到五個讀者應該帶進方法與實驗章節的疑問:哪些前提只是被宣稱、哪裡的框架
可能誇大了缺口、哪個對比的選擇值得懷疑。

pack 說全文無法取得時,這一段只依摘要寫,並在開頭明說;不要編造前導章節的內容。

## 核心洞見
這篇賴以成立的那一個想法。兩句話說不清楚就表示你還沒抓到。

## 方法
機制上怎麼運作,關鍵式子用 LaTeX 寫出來。解釋每個部件為什麼在那裡,而不只是它是什麼。

## 機制圖解
把上面的方法畫成一張 mermaid 流程圖:資料或梯度怎麼流、關鍵張量的形狀或位元寬在哪裡變、
這篇動的是哪一個方塊(在那個節點的文字前加 ★)。圖下面三到五行說明怎麼讀這張圖。
機制是純數學、沒有結構可畫時,改畫量之間的關係(例如誤差隨 bit 數的走勢),並說明為什麼。

## 證據
實驗實際證明了什麼,以及同樣重要的——沒有證明什麼。點名撐起論證的 baseline 與 ablation,
並指名 pack 裡列出的圖表編號(例如「Table 3 的 4-bit 那一列」),讓讀者可以自己去核對。

## 該看哪三張圖
從 pack 的 Figures and tables 裡挑三個最值得停下來看的,每個寫:編號與頁數、
要看的是哪一條線或哪一格、看出來會改變什麼判斷。挑不出三個就說明為什麼。

## 限制與反駁
誠實的弱點。一個嚴格的審稿人會從哪裡切入?

## 血緣位置
承接 pack 裡列出的前作,以及它後來啟用了什麼。

## 三個討論問題
依「回答之後對理解的改變程度」排序。

接續先前的閱讀:
pack 的 Lineage 與 Recently read 段落會附上讀者已讀論文當時的一句話結論。若這篇建立在
其中某篇之上,指名道姓說明改了什麼;若這篇推翻了先前的結論,明講哪個成立、為什麼。
不要重講讀者已經有的背景。
"""


def generate(conn, row, timeout: int = 900) -> tuple[str | None, str]:
    """Produce the deep dive for one paper.

    Returns (body, reason). A bare None told the nightly log nothing: a whole night's
    dives failed on an expired OAuth session and every line just said "failed",
    which looks identical to the model declining.
    """
    pack, _ = brief.pack_text(conn, row)
    return _from_pack(pack, timeout)


def _from_pack(pack: str, timeout: int = 900) -> tuple[str | None, str]:
    body, reason = llm.complete(pack, system=DIVE_INSTRUCTIONS, timeout=timeout, task="dive")
    if not body:
        return None, reason
    # A refusal or an error message is short; a real dive runs to thousands of
    # characters. Storing a stub would look like the paper had been explained.
    if len(body) > 800:
        return body, "ok"
    return None, f"reply too short to be a dive: {body.splitlines()[0][:120]}"


def _select(conn, count: int, paper_id: str | None, list_id: str | None, rewrite: bool):
    """The papers to write, in the order they should be written.

    Rewriting is ordered by queue rank, not by how old the dive is: the point of a
    spec change is that the papers about to be read are the ones that benefit, and the
    `spec` column is what keeps a repeated run walking forward instead of redoing the
    front of the queue every time.
    """
    if paper_id:
        return conn.execute(
            "SELECT p.*, q.role, q.reason FROM papers p "
            "LEFT JOIN queue q ON q.paper_id = p.id WHERE p.id = ?",
            (paper_id,),
        ).fetchall()

    have_dive = "d.paper_id IS NOT NULL AND COALESCE(d.spec,'') != ?" if rewrite else None
    # A paper the model keeps refusing was picked again every night, each time a
    # paid call ending in the same refusal.
    have_dive = (
        f"({have_dive or 'd.paper_id IS NULL'}) "
        "AND NOT EXISTS (SELECT 1 FROM kv WHERE kv.key = 'dive.gave_up.' || p.id)"
    )
    args: list = [DIVE_SPEC] if rewrite else []

    if list_id:
        # 'all' is what the nightly job passes: every list, in turn, so a list
        # imported today starts getting explained tonight without being named.
        # GROUP BY because a paper can be in two lists and must not be written twice.
        scope = "" if list_id == "all" else "lp.list_id = ? AND "
        scope_args = () if list_id == "all" else (list_id,)
        return conn.execute(
            "SELECT p.*, 'list' role, lp.citation reason FROM list_papers lp "
            "JOIN papers p ON p.id = lp.paper_id "
            "LEFT JOIN dives d ON d.paper_id = p.id "
            f"WHERE {scope}{have_dive or 'd.paper_id IS NULL'} "
            "GROUP BY p.id ORDER BY lp.list_id, lp.position LIMIT ?",
            (*scope_args, *args, count),
        ).fetchall()

    return conn.execute(
        "SELECT p.*, q.role, q.reason FROM queue q "
        "JOIN papers p ON p.id = q.paper_id "
        "LEFT JOIN dives d ON d.paper_id = p.id "
        f"""WHERE q.state IN ('pending', 'delivered'{", 'read'" if rewrite else ""}) """
        f"  AND {have_dive or 'd.paper_id IS NULL'} "
        "ORDER BY q.rank LIMIT ?",
        (*args, count),
    ).fetchall()


def _generate_for(paper_id: str) -> tuple[str | None, str]:
    """Build the pack on this thread's own connection, then let go of the database.

    A sqlite3 connection belongs to the thread that made it, and assembling a pack
    reads the corpus and can backfill it, so a worker cannot borrow the caller's.

    The connection is closed before the model call, which is the whole point of the
    split: holding it open across a call that runs for minutes kept a write
    transaction alive that long, and three workers plus the reader then collided --
    a bulk run died with "database is locked" and the script above it read the empty
    result as "nothing left to do".
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT p.*, q.role, q.reason FROM papers p "
            "LEFT JOIN queue q ON q.paper_id = p.id WHERE p.id = ?",
            (paper_id,),
        ).fetchone()
        if row is None:
            return None, "paper vanished between selection and writing"
        pack, _ = brief.pack_text(conn, row)
    return _from_pack(pack)


def _fatal(reason: str) -> bool:
    """Would every remaining paper fail the same way?

    An expired login and an exhausted quota both do. A bulk rewrite once spent a
    whole batch reporting "out of usage credits" one paper at a time.
    """
    low = reason.lower()
    return any(
        phrase in low
        for phrase in ("authenticate", "sign in", "usage credits", "usage limit", "quota")
    )


def dive_ahead(
    count: int = 3,
    log: Log = lambda _msg: None,
    paper_id: str | None = None,
    list_id: str | None = None,
    rewrite: bool = False,
    jobs: int = 1,
) -> int:
    """Make sure the next `count` unread papers each have a deep dive.

    `paper_id` overrides the selection and writes one specific paper, including an
    already-read one -- a paper you are looking at now is exactly the one you might
    want explained, and the queue-order scan skips those by design.

    `rewrite` takes papers whose dive predates the current `DIVE_SPEC`, in queue
    order, which is how a spec change is rolled through an existing shelf of dives.

    `jobs` runs that many dives at once. Each one is a subprocess or an HTTPS call
    waiting on a model, so the time is spent waiting, not computing.
    """
    init_db()
    with connect() as conn:
        rows = _select(conn, count, paper_id, list_id, rewrite)
    if not rows:
        log("  nothing to write: every paper in scope is already on the current spec")
        return 0

    written = 0
    for paper_id_, body, reason, label in _run(rows, jobs, log):
        if not body:
            log(f"    failed [{label}]: {reason}")
            if _fatal(reason):
                log("  stopping: nothing will succeed until the login is renewed")
                break
            _note_failure(paper_id_, reason, log)
            continue
        with connect() as conn:
            conn.execute(
                "INSERT INTO dives(paper_id, body, written_at, spec) VALUES (?,?,?,?) "
                "ON CONFLICT(paper_id) DO UPDATE SET body=excluded.body, "
                "written_at=excluded.written_at, spec=excluded.spec",
                (paper_id_, body, now(), DIVE_SPEC),
            )
        with connect() as conn:
            set_kv(conn, f"dive.failures.{paper_id_}", None)
            set_kv(conn, f"dive.gave_up.{paper_id_}", None)
            # 講解 is the dive and the close reading together; rolling dives forward
            # without the second half left hundreds of papers explained halfway.
            missing = closeread.get(conn, paper_id_) is None
        written += 1
        log(f"    stored {len(body)} chars [{label}]")
        if missing:
            close, why = closeread.write(paper_id_)
            log(f"    逐節精讀 {len(close):,} chars" if close else f"    逐節精讀未完成：{why}")
        _prepare_highlights(paper_id_, log)
    return written


# Retrying these cannot help: the same text meets the same policy.
REFUSALS = ("safeguard", "usage policy", "flagged", "違反使用政策", "安全機制")
GIVE_UP_AFTER = 3


def _note_failure(paper_id: str, reason: str, log: Log) -> None:
    """Count a failed dive; past a refusal or a few failures, stop picking the paper.

    The 深入分析 button still writes it on request: `paper_id` bypasses the skip.
    """
    with connect() as conn:
        seen = get_kv(conn, f"dive.failures.{paper_id}") or {}
        count = int(seen.get("count", 0)) + 1
        set_kv(conn, f"dive.failures.{paper_id}", {"count": count, "reason": reason[:300]})
        if count >= GIVE_UP_AFTER or any(r in reason.lower() for r in REFUSALS):
            set_kv(conn, f"dive.gave_up.{paper_id}", now())
            log(f"    not picking this paper again on its own ({count} failure(s))")


def _prepare_highlights(paper_id: str, log: Log):
    from paper_daily import paper_highlights
    from paper_daily.store import get_kv, set_kv

    with connect() as conn:
        # Off until the reader ticks it, as the toolbar shows on a fresh install;
        # a missing key once meant on here and spent AI quota behind an unticked box.
        if get_kv(conn, "ui.auto_highlights") != "1":
            return
    path = paper_highlights.PDF_DIR / (paper_highlights._safe_name(paper_id) + ".pdf")
    if not path.exists():
        return
    try:
        prepared, reason = paper_highlights.prepare_reading(paper_id)
    except (ValueError, OSError, RuntimeError) as exc:
        prepared, reason = None, str(exc)
    marks = prepared.get("marks") if prepared else None
    ok = bool(marks and marks["mapped"])
    if prepared and prepared.get("explanation_pending"):
        ok, reason = False, prepared["explanation_reason"]
    if marks and not marks["mapped"]:
        reason = "重點已保留在素材中，但無法在 PDF 精確定位；請核對原文。"
    with connect() as conn:
        transient = not ok and paper_highlights.transient(reason)
        set_kv(conn, f"analyze.failed.highlights.{paper_id}", None if ok or transient else reason)
    log(f"    原文重點 {marks['mapped']}/{marks['total']} 段已標記並同步素材"
        if marks else f"    原文重點未完成（講解已保存）：{reason}")


def _run(rows, jobs: int, log: Log):
    """Yield (paper_id, body, reason, label) as each dive comes back."""
    labels = {r["id"]: f"{r['venue']} {r['year']} {r['title'][:44]}" for r in rows}
    if jobs <= 1:
        for r in rows:
            log(f"  writing: {labels[r['id']]}")
            body, reason = _generate_for(r["id"])
            yield r["id"], body, reason, labels[r["id"]]
        return

    log(f"  writing {len(rows)} dives, {jobs} at a time")
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(_generate_for, r["id"]): r["id"] for r in rows}
        try:
            for future in as_completed(futures):
                pid = futures[future]
                body, reason = future.result()
                yield pid, body, reason, labels[pid]
        finally:
            # Breaking out of the loop (an expired login) must not leave the rest of
            # the batch running against a backend that cannot answer.
            for future in futures:
                future.cancel()
