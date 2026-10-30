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

from paper_daily import brief, llm
from paper_daily.store import connect, init_db, now

Log = Callable[[str], None]

# Bumped when the specification below changes, so `dive-ahead --rewrite` can tell
# which dives are already on the current one.
DIVE_SPEC = "2026-10-research-evidence"

# The canonical specification of what a deep dive is. `.claude/commands/paper-today.md`
# describes the same thing for the interactive path; keep them in step.
DIVE_INSTRUCTIONS = """\
你是一位嚴謹的跨領域學術研究導讀者。下面是一篇論文的 briefing pack,請據此寫一份深度講解。

研究判讀規則:
- 先依原文辨識研究類型與研究問題，再使用適合該研究設計的檢核。
  理論證明、定量實驗、觀察研究、質性研究與文獻綜述不可套用同一組品質分數。
- 區分作者主張、實際觀察或證明、你的推論與尚無依據的部分。引用存在不等於主張受支持。
- 原文有樣本數、效應、單位與不確定性時一併呈現；未報告不等於零，推算值必須標明。
- 不把關聯寫成因果，不把重現計畫寫成已重現。缺少全文、引句或後續論文時明列證據缺口。
- 引文與頁碼須能回到正確版本核對；不要用整體分數代替可核對的理由。

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
依照論文自己的順序走,把每一步論證講清楚,寫到讀者能掌握
作者的論點，也能回到原文核對證據。用下面五個小節(### 標題),每一節都要具體:

### 研究當下的狀態
這篇寫成時這個領域的現況:主流做法與代表作、適用的資料或研究對象、
實際需求與大家默認的假設。原文有資料集、benchmark 或量化水準時才具體列出。以論文前導章節實際
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
先說明研究設計與它能回答的問題，再拆解方法、適用假設與可重現步驟。
依研究類型核對樣本或材料、比較或控制、測量與分析、統計不確定性，
或定理條件與證明、質性取樣與編碼、綜述的檢索和納排標準。
只討論適用且原文有依據的項目；未報告之處明列為缺口。關鍵式子用 LaTeX。
解釋每個部件為什麼在那裡，而不只是它是什麼。

## 機制圖解
用適合該研究的 mermaid 圖，例如取樣、介入、資料分析、論證或篩選流程。
只有原文確實討論模型、梯度或張量時才畫那些元件；不可硬套神經網路或量化架構。
標出本文實際改動的部件，並說明圖怎麼讀。沒有適合的機制圖時明說，改列關鍵關係。

## 證據
資料、觀察、推導或實驗實際支持了什麼，以及沒有支持什麼。
有比較、敏感度分析、控制或 ablation 時具體核對；不把關聯寫成因果。
指向 pack 已列出的圖表、定理或原文段落，讓讀者可以自己核對。

## 該看哪三張圖
從 pack 的 Figures and tables 裡挑三個最值得停下來看的,每個寫:編號與頁數、
要看的是哪一條線或哪一格、看出來會改變什麼判斷。挑不出三個就說明為什麼。

## 限制與反駁
分開列出作者自述限制與讀者可提出的反駁，每項附上依據或明標為推論。
說明結論成立的範圍、未回答的問題，以及一個能檢驗關鍵主張的後續步驟。

## 血緣位置
根據 pack 已提供的前作和後續工作解釋研究缺口與改變；引用某篇不等於沿用或支持它。
關係有原文依據時指出依據，僅推測時標明推論。沒有相關全文時，不編造研究血緣。

## 三個討論問題
依「回答之後對理解的改變程度」排序。

接續先前的閱讀:
pack 的 Lineage 與 Recently read 段落會附上讀者已讀論文當時的一句話結論。若這篇建立在
其中某篇之上,指名道姓說明改了什麼;若這篇推翻了先前的結論,明講哪個成立、為什麼。
不要重講讀者已經有的背景。
"""


def generate(conn, row, timeout: int = 900) -> tuple[str | None, str]:
    """Generate and publish for the caller's explicit database, outside its transaction."""
    from pathlib import Path

    if conn.in_transaction:
        raise ValueError("Finish the caller transaction before generating a deep dive")
    database = next(r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main")
    if not database:
        raise ValueError("Generation requires an on-disk research workspace")
    return _generate_for(row["id"], database=Path(database), timeout=timeout)


def _from_pack(pack: str, timeout: int = 900, *, cfg=None) -> tuple[str | None, str]:
    body, reason = llm.complete(
        pack, system=DIVE_INSTRUCTIONS, timeout=timeout, task="dive", cfg=cfg
    )
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


class DiveResult(tuple):
    """Compatible (body, reason), with the durable publication outcome attached."""

    def __new__(cls, body, reason, publication=None, annotation=None):
        result = super().__new__(cls, (body, reason))
        result.publication = publication
        result.annotation = annotation
        return result


class DiveCompletion(tuple):
    def __new__(cls, paper_id, result, label):
        value = super().__new__(cls, (paper_id, *result, label))
        value.publication = getattr(result, "publication", None)
        value.annotation = getattr(result, "annotation", None)
        return value


def _generate_for(paper_id: str, *, database=None, timeout=900, connections=None):
    """Capture, generate and publish on the original workspace; no DB lock during AI."""
    from contextlib import closing

    from paper_daily import research_generation as generation
    from paper_daily import research_job_lock, store

    database = (database or store.DB_PATH).resolve()
    with research_job_lock.claim(database, "dive", paper_id) as acquired:
        if not acquired:
            return DiveResult(None, "deep dive is already in progress")
        with llm.connection_scope(connections):
            cfg = llm.settings(task="dive")
            with closing(generation._connect(database)) as conn, conn:
                row = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
                if row is None:
                    return DiveResult(None, "paper vanished between selection and writing")
                context = generation.begin_generation(conn, table="dives", owner_id=paper_id)
                prepared = brief.pack_text(conn, row)
                pack, _pdf = prepared
                if isinstance(prepared, brief.PreparedPack):
                    context = generation.bind_inputs(
                        context, document=prepared.document, input_snapshot=prepared.snapshot
                    )
                elif context.data["binding"] is not None:
                    return DiveResult(
                        None, "prepared input provenance is required for enrolled research"
                    )
            from paper_daily.manual_highlight_ops import capture_owner

            annotation = None
            if (isinstance(prepared, brief.PreparedPack) and prepared.document is not None
                    and prepared.document.available):
                annotation = (capture_owner(database, paper_id), prepared.document.sha256)
            body, reason = _from_pack(pack, timeout, cfg=cfg)
        if body is None:
            return DiveResult(None, reason)
        result = generation.publish_generated(context, row={
            "paper_id": paper_id, "body": body, "written_at": now(), "spec": DIVE_SPEC,
        })
        if result.status != "accepted":
            return DiveResult(
                None, f"{result.reason}; generated result retained: {result.candidate_id}", result
            )
        return DiveResult(body, "ok", result, annotation)


def edit_snapshot(conn, paper_id):
    from paper_daily.research_generation import begin_generation

    return begin_generation(conn, table="dives", owner_id=paper_id, input_reader="target")


def save(paper_id, body, *, expected=None):
    """Store an external/manual explanation against its original loaded target."""
    from paper_daily.research_generation import publish_edit
    from paper_daily.sync_capture import StaleCaptureError

    if not isinstance(body, str) or not body.strip():
        raise ValueError("A deep dive needs nonempty text")
    if expected is None:
        with connect() as conn:
            expected = edit_snapshot(conn, paper_id)
    if expected.table != "dives" or expected.owner_id != paper_id:
        raise ValueError("The deep dive edit belongs to another paper")
    result = publish_edit(expected, row={
        "paper_id": paper_id, "body": body,
        "written_at": expected.started_at, "spec": (expected.target or {}).get("spec"),
    })
    if result.status != "accepted":
        raise StaleCaptureError(result.candidate_id)
    return result


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
    from contextlib import closing

    from paper_daily import research_generation as generation
    from paper_daily import store

    init_db()
    database = store.DB_PATH.resolve()
    connections = llm.capture_connections()
    with closing(generation._connect(database)) as conn:
        rows = _select(conn, count, paper_id, list_id, rewrite)
        # Custom legacy iterators keep the four-item interface. Observe their
        # fallback targets before execution, in the same explicit workspace.
        fallback = {row["id"]: edit_snapshot(conn, row["id"]) for row in rows}
        auto_highlights = store.get_kv(conn, "ui.auto_highlights") == "1"
    # Compatibility iterators lack their own source receipt. Observe their owner
    # and available PDF before starting work; never resolve a later global target.
    from paper_daily import paper_highlights
    from paper_daily.document_reader import from_workspace
    from paper_daily.manual_highlight_ops import capture_owner

    legacy_root = paper_highlights.PDF_DIR
    fallback_annotations = {}
    for row in rows if auto_highlights else []:
        document = from_workspace(database, legacy_root=legacy_root).resolve(row["id"])
        if document.available:
            fallback_annotations[row["id"]] = (
                capture_owner(database, row["id"]), document.sha256
            )
    if not rows:
        log("  nothing to write: every paper in scope is already on the current spec")
        return 0
    written = 0
    for completion in _run(rows, jobs, log, database, connections):
        paper_id_, body, reason, label = completion
        if not body:
            log(f"    failed [{label}]: {reason}")
            if _fatal(reason):
                log("  stopping: nothing will succeed until the login is renewed")
                break
            continue
        if getattr(completion, "publication", None) is None:
            expected = fallback[paper_id_]
            if expected.data["binding"] is not None:
                log("    custom generation has no captured input provenance")
                continue
            result = generation.publish_generation(expected, row={
                "paper_id": paper_id_, "body": body, "written_at": now(), "spec": DIVE_SPEC,
            })
            if result.status != "accepted":
                log(f"    retained for review: {result.candidate_id}")
                continue
        written += 1
        log(f"    stored {len(body)} chars [{label}]")
        annotation = getattr(completion, "annotation", None)
        if annotation is None and getattr(completion, "publication", None) is None:
            annotation = fallback_annotations.get(paper_id_)
        if annotation is not None:
            _prepare_highlights(
                paper_id_, log, database=database, connections=connections,
                owner=annotation[0], expected_document_hash=annotation[1], legacy_root=legacy_root,
            )
    return written


def _prepare_highlights(paper_id: str, log: Log, *, database=None, connections=None,
                        owner=None, expected_document_hash=None, legacy_root=None):
    import sqlite3
    from contextlib import closing
    from pathlib import Path

    from paper_daily import paper_highlights, reading_annotation_jobs, store
    from paper_daily import research_generation as generation
    from paper_daily.document_reader import from_workspace
    from paper_daily.manual_highlight_ops import capture_owner
    from paper_daily.store import get_kv, set_kv

    database = Path(database or store.DB_PATH).resolve(strict=True)
    legacy_root = Path(legacy_root or paper_highlights.PDF_DIR)
    try:
        with closing(generation._connect(database)) as conn:
            if owner is not None:
                owner.check(conn)
            # Opt-in belongs to the original workspace, even after a global switch.
            if get_kv(conn, "ui.auto_highlights") != "1":
                return
    except (ValueError, OSError, sqlite3.DatabaseError) as exc:
        log(f"    Highlight preparation skipped: {exc}")
        return
    try:
        if owner is None:
            owner = capture_owner(database, paper_id)
        if expected_document_hash is None:
            document = from_workspace(database, legacy_root=legacy_root).resolve(paper_id)
            if not document.available:
                return
            expected_document_hash = document.sha256
        prepared, reason = reading_annotation_jobs.prepare(
            database, paper_id, legacy_root=legacy_root, connections=connections,
            owner=owner, expected_document_hash=expected_document_hash,
        )
    except (ValueError, OSError, RuntimeError, sqlite3.DatabaseError) as exc:
        prepared, reason = None, str(exc)
    marks = prepared.get("marks") if prepared else None
    ok = bool(marks and marks["mapped"])
    if prepared and prepared.get("explanation_pending"):
        ok, reason = False, prepared["explanation_reason"]
    if marks and not marks["mapped"]:
        reason = "重點已保留在素材中，但無法在 PDF 精確定位；請核對原文。"
    try:
        with closing(generation._connect(database)) as conn, conn:
            # A deleted/recreated paper cannot receive a late failure marker either.
            if owner is not None:
                owner.check(conn)
            set_kv(conn, f"analyze.failed.highlights.{paper_id}", None if ok else reason)
    except (ValueError, OSError, sqlite3.DatabaseError) as exc:
        log(f"    Highlight status not applied to a changed research owner: {exc}")
        return
    log(f"    原文重點 {marks['mapped']}/{marks['total']} 段已標記並同步素材"
        if marks else f"    原文重點未完成（講解已保存）：{reason}")


def _run(rows, jobs: int, log: Log, database=None, connections=None):
    """Yield (paper_id, body, reason, label) as each dive comes back."""
    from paper_daily import store

    database = (database or store.DB_PATH).resolve()
    connections = connections or llm.capture_connections()
    labels = {r["id"]: f"{r['venue']} {r['year']} {r['title'][:44]}" for r in rows}
    if jobs <= 1:
        for r in rows:
            log(f"  writing: {labels[r['id']]}")
            result = _generate_for(r["id"], database=database, connections=connections)
            yield DiveCompletion(r["id"], result, labels[r["id"]])
        return

    log(f"  writing {len(rows)} dives, {jobs} at a time")
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {
            pool.submit(_generate_for, r["id"], database=database, connections=connections): r["id"]
            for r in rows
        }
        try:
            for future in as_completed(futures):
                pid = futures[future]
                result = future.result()
                yield DiveCompletion(pid, result, labels[pid])
        finally:
            # Breaking out of the loop (an expired login) must not leave the rest of
            # the batch running against a backend that cannot answer.
            for future in futures:
                future.cancel()
