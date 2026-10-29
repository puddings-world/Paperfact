"""A paper's place in its field: what came after it, and what to read next.

The lineage used to be drawn from the citation graph inside the corpus. The corpus is
three ML conferences plus the lists imported by hand, so for a surgical-video dataset
it showed five descendants out of forty-seven and one ancestor out of forty
references: an accurate picture of the corpus and a wrong one of the field.

Each direction now comes from where it is actually known:

* What a paper builds on is in its own text, and cites.py already reads it: every
  reference with the sentence that cites it and what it is there for.
* What builds on it is in the later papers' text. OpenAlex and Semantic Scholar both
  answer "who cites this" with no key and no crawling, and neither is complete: on
  Cataract-1K OpenAlex found 27 citing works and S2 47, and only S2 carries the
  sentence in the later paper that cites this one. Both are asked and merged, and
  each citing work is judged from that sentence and its abstract -- what it does with
  this paper, and whether that is worth reading.
* What to read next, and the story connecting the two, is one more model call over
  both, kept as a short overview: a few sentences of before-and-after and an ordered
  list of the handful of papers that matter most.

All of it is stored, because it costs a model call per paper, and all of it can be
corrected by hand; a corrected row is never overwritten by a later run.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Callable

from paper_daily import llm
from paper_daily.http import FetchError, fetch_text
from paper_daily.sources.openalex import API, MAILTO, _abstract, _venue, same_paper
from paper_daily.store import connect, get_kv, now, set_kv, title_key

Log = Callable[[str], None]

# A dataset paper two years old has a few dozen citing works; a famous one has
# thousands. The most-cited 150 and the newest 50 cover what a reader acts on.
MOST_CITED = 150
NEWEST = 50
JUDGE_BATCH = 60

SELECT = (
    "id,doi,display_name,publication_year,cited_by_count,primary_location,"
    "abstract_inverted_index"
)

VERDICTS = ("必讀", "值得", "參考", "略過")
VERDICT_RANK = {v: i for i, v in enumerate(VERDICTS)}

JUDGE_SYSTEM = """你在幫一位研究生決定,一篇論文發表之後的哪些後續研究值得讀。

你會拿到原論文的標題與摘要,以及一串引用它的後續論文。每一篇附上:標題、年份、出處、
被引用數、摘要,以及(如果有)那篇後續論文裡引用原論文的句子。

輸出 JSON 陣列,每個物件恰好這些鍵:
  "id"        輸入給你的編號
  "relation"  一句話:這篇後續論文拿原論文做了什麼。優先根據引用句判斷,例如「用原論文的
              phase 標註當主要實驗資料集」「沿用它的 13 類 phase 定義」「指出它跨中心的
              domain shift 並提出解法」「只在 related work 列為既有資料集」
  "verdict"   只能是 "必讀"、"值得"、"參考"、"略過" 其中之一
  "why"       一句話,從讀者的角度:讀了它能對原論文多懂什麼,或能學到什麼

規則:
- "必讀" 留給直接延伸、改進、或挑戰原論文的;只在 survey 或 related work 順帶引用的是 "略過"。
- 用原論文的資料或 benchmark 做新任務的,通常是 "值得"。
- 有引用句就以引用句為準;沒有引用句也沒有摘要時,relation 以「只能從標題看,」開頭。
- 用繁體中文,技術名詞與論文標題保留英文,數學用 Unicode 純文字,絕不使用 LaTeX。
- 不要編造內容。直接輸出 JSON 陣列,不要前言,不要程式碼圍欄。
"""

OVERVIEW_SYSTEM = """你在幫一位研究生快速掌握一篇論文在研究脈絡裡的位置。

你會拿到這篇論文的基本資料與深度講解的開頭、它建立在其上的參考文獻(附引用目的),
以及引用它的後續研究(附它們拿這篇做了什麼)。

輸出一個 JSON 物件,恰好這些鍵:
  "summary"  四到六句話的承先啟後敘述:它出現之前這個問題卡在哪、它建立在哪幾篇之上、
             它補上了什麼、之後的研究拿它做了什麼、目前還留著什麼缺口。要具體點名論文。
  "reading"  陣列,最多六項,依建議閱讀順序排列,是往前與往後最關鍵的幾篇:
             {"title": 從輸入原樣複製的標題, "direction": "承先" 或 "啟後", "why": 一句話理由}

規則:
- 只根據提供的內容,不要補充輸入裡沒有的論文或數字。
- 用繁體中文,技術名詞與論文標題保留英文,數學用 Unicode 純文字,絕不使用 LaTeX。
- 直接輸出 JSON 物件,不要前言,不要程式碼圍欄。
"""


# ---- asking the field -------------------------------------------------------------
def _get(params: dict) -> dict:
    query = urllib.parse.urlencode({**params, "mailto": MAILTO})
    return json.loads(fetch_text(f"{API}?{query}", max_age=7 * 86400, retries=4))


def work_id(row) -> str | None:
    """OpenAlex's id for a paper: by DOI when there is one, else by exact title."""
    if row["doi"]:
        try:
            work = json.loads(
                fetch_text(
                    f"{API}/doi:{urllib.parse.quote(row['doi'])}?select=id&mailto={MAILTO}",
                    max_age=30 * 86400,
                    retries=4,
                )
            )
            return work["id"].rsplit("/", 1)[-1]
        except FetchError:
            pass
    # A colon or comma inside a filter value is read as filter syntax, and half of
    # these titles are "Name: what it does".
    plain = re.sub(r"[:,|]", " ", row["title"])
    for params in ({"filter": f"title.search:{plain}"}, {"search": plain}):
        hits = _get({**params, "per-page": 5, "select": "id,display_name"})
        for work in hits.get("results") or []:
            if same_paper(row["title"], work.get("display_name") or ""):
                return work["id"].rsplit("/", 1)[-1]
    return None


def _citing_openalex(wid: str) -> list[dict]:
    seen: dict[str, dict] = {}
    for sort, limit in (("cited_by_count:desc", MOST_CITED), ("publication_date:desc", NEWEST)):
        cursor = "*"
        taken = 0
        while cursor and taken < limit:
            page = _get(
                {"filter": f"cites:{wid}", "sort": sort, "per-page": 50,
                 "cursor": cursor, "select": SELECT}
            )
            results = page.get("results") or []
            for w in results:
                wid2 = w["id"].rsplit("/", 1)[-1]
                # OpenAlex occasionally lists a work among its own citers.
                if wid2 != wid and wid2 not in seen:
                    seen[wid2] = {
                        "id": wid2,
                        "title": w.get("display_name") or "",
                        "year": w.get("publication_year"),
                        "venue": _venue(w),
                        "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
                        "citations": w.get("cited_by_count"),
                        "abstract": _abstract(w),
                    }
            taken += len(results)
            cursor = (page.get("meta") or {}).get("next_cursor")
            if not results:
                break
    return list(seen.values())


S2_API = "https://api.semanticscholar.org/graph/v1/paper"
S2_FIELDS = "title,year,venue,externalIds,citationCount,abstract,contexts"


def _citing_s2(row) -> list[dict] | None:
    """Semantic Scholar's citing works, with the sentences that cite this paper.

    Returns None when S2 does not know the paper at all.
    """
    ref = (
        row["s2_id"]
        or (f"arXiv:{row['arxiv_id']}" if row["arxiv_id"] else None)
        or (f"DOI:{row['doi']}" if row["doi"] else None)
    )
    if not ref:
        return None
    out: list[dict] = []
    offset = 0
    while offset < MOST_CITED + NEWEST:
        url = (
            f"{S2_API}/{urllib.parse.quote(ref)}/citations"
            f"?fields={S2_FIELDS}&limit=100&offset={offset}"
        )
        try:
            page = json.loads(fetch_text(url, max_age=7 * 86400, retries=6))
        except FetchError:
            return out or None
        for item in page.get("data") or []:
            w = item.get("citingPaper") or {}
            if not w.get("paperId") or not w.get("title"):
                continue
            ext = w.get("externalIds") or {}
            out.append({
                "id": f"S2:{w['paperId']}",
                "title": w["title"],
                "year": w.get("year"),
                "venue": w.get("venue") or None,
                "doi": ext.get("DOI"),
                "arxiv_id": ext.get("ArXiv"),
                "citations": w.get("citationCount"),
                "abstract": w.get("abstract"),
                "contexts": [c for c in (item.get("contexts") or []) if c][:4],
            })
        if page.get("next") is None:
            break
        offset = page["next"]
    return out


def merge(openalex: list[dict], s2: list[dict]) -> list[dict]:
    """One list from both sources, matched by DOI or normalised title.

    OpenAlex's id is kept where it has the work, so an earlier run's rows are updated
    rather than duplicated; S2 fills in what OpenAlex lacks -- abstracts it withholds
    for some publishers, and the citing sentences it never has.
    """
    merged = [dict(w) for w in openalex]
    by_doi = {(w["doi"] or "").lower(): w for w in merged if w.get("doi")}
    by_title = {title_key(w["title"]): w for w in merged}
    for w in s2:
        hit = by_doi.get((w.get("doi") or "").lower()) or by_title.get(title_key(w["title"]))
        if hit is None:
            merged.append(dict(w))
            continue
        for key in ("abstract", "doi", "arxiv_id", "venue", "year"):
            if not hit.get(key) and w.get(key):
                hit[key] = w[key]
        hit["contexts"] = w.get("contexts") or hit.get("contexts") or []
        hit["citations"] = max(hit.get("citations") or 0, w.get("citations") or 0)
    return merged


def fetch(paper_id: str, log: Log = lambda _m: None) -> int:
    """Record every work that cites this paper. Returns how many."""
    with connect() as conn:
        row = conn.execute(
            "SELECT id, title, doi, s2_id, arxiv_id FROM papers WHERE id=?", (paper_id,)
        ).fetchone()
    if row is None:
        raise ValueError(f"no paper {paper_id}")
    wid = work_id(row)
    openalex = _citing_openalex(wid) if wid else []
    s2 = _citing_s2(row)
    if wid is None and s2 is None:
        log(f"  neither OpenAlex nor Semantic Scholar knows {row['title'][:60]}")
        return 0
    works = merge(openalex, s2 or [])

    stamp = now()
    with connect() as conn:
        # Recorded even when nothing cites it yet, so "none" reads as an answer and
        # not as "never asked".
        set_kv(conn, f"followups.checked.{paper_id}", stamp)
        for w in works:
            conn.execute(
                "INSERT INTO followups(paper_id, work_id, title, year, venue, doi, citations, "
                "abstract, arxiv_id, contexts_json, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(paper_id, work_id) DO UPDATE SET "
                "citations=excluded.citations, fetched_at=excluded.fetched_at, "
                "abstract=COALESCE(followups.abstract, excluded.abstract), "
                "doi=COALESCE(followups.doi, excluded.doi), "
                "arxiv_id=COALESCE(followups.arxiv_id, excluded.arxiv_id), "
                "contexts_json=COALESCE(excluded.contexts_json, followups.contexts_json)",
                (
                    paper_id, w["id"], w.get("title") or "(untitled)", w.get("year"),
                    w.get("venue"), w.get("doi"), w.get("citations"), w.get("abstract"),
                    w.get("arxiv_id"),
                    json.dumps(w["contexts"], ensure_ascii=False) if w.get("contexts") else None,
                    stamp,
                ),
            )
        conn.commit()
    log(f"  {len(works)} citing work(s): {len(openalex)} from OpenAlex, {len(s2 or [])} from S2")
    return len(works)


# ---- judging --------------------------------------------------------------------
def _json(text: str, opener: str, closer: str):
    return llm.reply_json(text, list if opener == "[" else dict, dict if opener == "[" else None)


def judge(paper_id: str, log: Log = lambda _m: None) -> tuple[int, str]:
    """Say what each citing work does with this paper and whether to read it.

    Only rows never judged with a relation, and never corrected by hand.
    Returns (how many, reason when none).
    """
    with connect() as conn:
        paper = conn.execute(
            "SELECT title, venue, year, abstract FROM papers WHERE id=?", (paper_id,)
        ).fetchone()
        rows = conn.execute(
            "SELECT * FROM followups WHERE paper_id=? AND relation IS NULL AND edited=0 "
            "ORDER BY citations DESC",
            (paper_id,),
        ).fetchall()
    if not rows:
        return 0, "nothing to judge"

    done, reason = 0, ""
    for start in range(0, len(rows), JUDGE_BATCH):
        batch = rows[start : start + JUDGE_BATCH]
        lines = [
            f"原論文:{paper['title']}({paper['venue']} {paper['year']})",
            f"摘要:{paper['abstract'] or '(無)'}",
            "",
            "後續論文:",
        ]
        for i, r in enumerate(batch):
            lines.append(
                f"[{i}] {r['title']} ({r['year']}, {r['venue'] or '?'}, "
                f"{r['citations'] or 0} cites)"
            )
            for c in json.loads(r["contexts_json"] or "[]")[:3]:
                lines.append(f"    引用句:{c[:400]}")
            lines.append(f"    摘要:{(r['abstract'] or '(無摘要)')[:500]}")
        text, reason = llm.complete(
            "\n".join(lines), system=JUDGE_SYSTEM, timeout=900, task="followups"
        )
        if not text:
            break
        try:
            verdicts = _json(text, "[", "]")
        except ValueError:
            reason = "AI 回覆格式無法解析"
            continue
        with connect() as conn:
            for v in verdicts:
                try:
                    r = batch[int(v["id"])]
                except (KeyError, ValueError, IndexError, TypeError):
                    continue
                if v.get("verdict") not in VERDICTS:
                    continue
                conn.execute(
                    "UPDATE followups SET verdict=?, why=?, relation=? "
                    "WHERE paper_id=? AND work_id=? AND edited=0",
                    (v["verdict"], v.get("why"), v.get("relation"), paper_id, r["work_id"]),
                )
                done += 1
            conn.commit()
    log(f"  {done} followup(s) judged")
    return done, ("" if done else reason)


def overview(paper_id: str, log: Log = lambda _m: None) -> tuple[bool, str]:
    """Write the before-and-after story and the reading order. Never over a hand edit."""
    with connect() as conn:
        mine = conn.execute(
            "SELECT edited FROM paper_context WHERE paper_id=?", (paper_id,)
        ).fetchone()
        if mine and mine["edited"]:
            return False, "edited by hand"
        paper = conn.execute(
            "SELECT title, venue, year, abstract FROM papers WHERE id=?", (paper_id,)
        ).fetchone()
        dive = conn.execute("SELECT body FROM dives WHERE paper_id=?", (paper_id,)).fetchone()
        refs = references(conn, paper_id)
        later = for_paper(conn, paper_id)
    keep_refs = [r for r in refs if r.get("verdict") in ("必讀", "值得")][:30]
    keep_later = [r for r in later if r.get("verdict") in ("必讀", "值得")][:30]
    if not keep_refs and not keep_later:
        # A paper whose references are all background still sits somewhere in its
        # field; insisting on 必讀/值得 left the story unwritten for good while the
        # tab kept offering to write it.
        keep_refs = [r for r in refs if r.get("verdict")][:30]
        keep_later = [r for r in later if r.get("verdict")][:30]
    if not keep_refs and not keep_later:
        with connect() as conn:
            set_kv(conn, f"followups.overview.none.{paper_id}", now())
        return False, NOTHING_TO_TELL

    lines = [
        f"論文:{paper['title']}({paper['venue']} {paper['year']})",
        f"摘要:{paper['abstract'] or '(無)'}",
        "",
        "深度講解開頭:",
        (dive["body"] if dive else "(無)")[:3500],
        "",
        "它建立在其上的參考文獻:",
    ]
    for r in keep_refs:
        what = r.get("purpose") or ""
        lines.append(f"- [{r['verdict']}] {r['title']} ({r.get('year') or '?'}):{what}")
    lines += ["", "引用它的後續研究:"]
    for r in keep_later:
        what = r.get("relation") or r.get("why") or ""
        lines.append(f"- [{r['verdict']}] {r['title']} ({r.get('year') or '?'}):{what}")
    text, reason = llm.complete(
        "\n".join(lines), system=OVERVIEW_SYSTEM, timeout=600, task="overview"
    )
    if not text:
        return False, reason
    try:
        data = _json(text, "{", "}")
    except ValueError:
        return False, "AI 回覆格式無法解析"
    if not str(data.get("summary") or "").strip():
        return False, "AI 沒有寫出研究脈絡"
    reading = [
        {"title": str(x.get("title") or ""), "direction": str(x.get("direction") or ""),
         "why": str(x.get("why") or "")}
        for x in (data.get("reading") or [])
        if x.get("title")
    ][:6]
    with connect() as conn:
        conn.execute(
            "INSERT INTO paper_context(paper_id, summary, reading_json, written_at, edited) "
            "VALUES (?,?,?,?,0) ON CONFLICT(paper_id) DO UPDATE SET summary=excluded.summary, "
            "reading_json=excluded.reading_json, written_at=excluded.written_at",
            (paper_id, str(data.get("summary") or ""), json.dumps(reading, ensure_ascii=False),
             now()),
        )
        conn.commit()
    log("  overview written")
    return True, ""


# Neither a judged reference nor a judged citing work: there is nothing to tell, and
# that is an answer rather than a step left to do.
NOTHING_TO_TELL = "沒有已判讀的參考文獻或後續研究可整理成脈絡"


def done(conn, paper_id: str) -> bool:
    """啟後 is done once the field was asked and the 研究脈絡 exists, or there was
    nothing to write it from. Asking alone said done while the tab still offered to
    write the story."""
    if get_kv(conn, f"followups.checked.{paper_id}") is None:
        return False
    if conn.execute("SELECT 1 FROM paper_context WHERE paper_id=?", (paper_id,)).fetchone():
        return True
    return get_kv(conn, f"followups.overview.none.{paper_id}") is not None


def nothing_to_tell(conn, paper_id: str) -> bool:
    return get_kv(conn, f"followups.overview.none.{paper_id}") is not None


def analyse(paper_id: str, log: Log = lambda _m: None, overview_too: bool = True) -> int:
    """Ask the field, judge what came back and, unless the caller writes it later
    with more in hand, the 研究脈絡. Returns how many citing works were judged."""
    return analyse_result(paper_id, log, overview_too)[0]


def analyse_result(
    paper_id: str, log: Log = lambda _m: None, overview_too: bool = True
) -> tuple[int, str]:
    """Like `analyse`, with the reason the 啟後 part is not finished ("" when it is)."""
    try:
        fetch(paper_id, log)
    except FetchError as e:
        log(f"  followups not fetched: {e}")
        return 0, "查詢後續研究的服務暫時無法連線，請稍後再試"
    judged, reason = judge(paper_id, log)
    failure = ""
    if reason and reason != "nothing to judge":
        log(f"  judging skipped: {reason}")
        failure = f"後續研究判讀未完成：{reason}"
    if overview_too:
        wrote, why = overview(paper_id, log)
        if not wrote and why not in ("edited by hand", NOTHING_TO_TELL):
            log(f"  overview skipped: {why}")
            failure = failure or f"研究脈絡未完成：{why}"
    from paper_daily import citegraph

    # No model call, a few requests: the map is ready whenever the lists are.
    try:
        citegraph.links(paper_id, log)
    except FetchError as e:
        log(f"  citation map skipped: {e}")
    return judged, failure


def ahead(count: int = 3, log: Log = lambda _m: None) -> int:
    """Ask the field about the next few papers that have never been asked about.

    Lists first, then the queue in reading order -- the same order as citations are
    analysed ahead, so the 引用 tab is filled in before the paper is reached.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT p.id, p.title FROM papers p "
            "WHERE NOT EXISTS (SELECT 1 FROM kv WHERE kv.key = 'followups.checked.' || p.id) "
            "  AND (EXISTS (SELECT 1 FROM list_papers lp WHERE lp.paper_id = p.id "
            "               AND lp.state = 'pending') "
            "       OR EXISTS (SELECT 1 FROM queue q WHERE q.paper_id = p.id "
            "                  AND q.state = 'pending')) "
            "ORDER BY EXISTS(SELECT 1 FROM list_papers lp WHERE lp.paper_id = p.id) DESC, "
            "  COALESCE((SELECT q.rank FROM queue q WHERE q.paper_id = p.id), 1e9) "
            "LIMIT ?",
            (count,),
        ).fetchall()
    for r in rows:
        log(f"  followups: {r['title'][:58]}")
        analyse(r["id"], log=log)
    return len(rows)


# ---- reading it back -------------------------------------------------------------
def for_paper(conn, paper_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM followups WHERE paper_id=?", (paper_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["contexts"] = json.loads(d.pop("contexts_json") or "[]")
        out.append(d)
    out.sort(key=lambda r: (VERDICT_RANK.get(r["verdict"] or "", 4), -(r["citations"] or 0)))
    return out


def overview_for(conn, paper_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM paper_context WHERE paper_id=?", (paper_id,)).fetchone()
    if row is None:
        return None
    return {
        "summary": row["summary"] or "",
        "reading": json.loads(row["reading_json"] or "[]"),
        "edited": bool(row["edited"]),
        "written_at": row["written_at"],
    }


def short_name(title: str) -> str:
    """What people call a paper: "StepAL", "Cataract-1K", not the full title."""
    head = title.split(":")[0].strip()
    return head if len(head.split()) <= 3 else head.split()[0]


def references(conn, paper_id: str) -> list[dict]:
    """Every reference the citation analysis judged, plus in-corpus edges it has not.

    A dataset paper also cites its own data deposit ("Cataract-1k. Synapse ..."),
    which is the paper itself rather than something it stands on, so it is left out.
    Most queue papers have no citation analysis yet, but Semantic Scholar's graph
    already links them to what they cite inside the corpus; those edges carry no
    reading of the text, so they come after and say where they came from.
    """
    from paper_daily import cites, pipeline

    paper = conn.execute("SELECT title FROM papers WHERE id=?", (paper_id,)).fetchone()
    own = short_name(paper["title"]).casefold() if paper else ""
    out = [
        r for r in cites.for_paper(conn, paper_id, "verdict")
        if not (own and own in (r["title"] or "").casefold())
    ]
    listed = {title_key(r["title"] or "") for r in out}
    for r in pipeline.lineage_of(conn, paper_id)["ancestors"]:
        if title_key(r["title"]) in listed:
            continue
        out.append({
            "ref_key": "", "title": r["title"], "year": r["year"], "venue": r["venue"],
            "doi": None, "verdict": None, "citations": None, "corpus_id": r["id"],
            "influential": r["influential"], "contexts": [], "basis": "graph",
            "purpose": "Semantic Scholar 引用圖裡的參考文獻,還沒讀內文判斷",
        })
    return out


def in_corpus(
    conn, doi: str | None, title: str | None, known: str | None = None
) -> dict | None:
    """The corpus row for a work, if it is already here, with its reading state."""
    row = {"id": known} if known else None
    if row is None and doi:
        row = conn.execute(
            "SELECT id FROM papers WHERE doi = ? COLLATE NOCASE", (doi,)
        ).fetchone()
    if row is None and title:
        row = conn.execute(
            "SELECT id FROM papers WHERE title_key=?", (title_key(title),)
        ).fetchone()
    if row is None:
        return None
    read = conn.execute(
        "SELECT 1 FROM queue WHERE paper_id=? AND state='read' "
        "UNION SELECT 1 FROM list_papers WHERE paper_id=? AND state='read'",
        (row["id"], row["id"]),
    ).fetchone()
    return {"id": row["id"], "read": read is not None}


def checked(conn, paper_id: str) -> str | None:
    """When the field was last asked about this paper, if ever."""
    return get_kv(conn, f"followups.checked.{paper_id}")


# ---- corrections by hand ----------------------------------------------------------
def edit_followup(paper_id: str, work_id: str, **fields) -> None:
    allowed = {k: v for k, v in fields.items() if k in ("verdict", "relation", "why")}
    if not allowed:
        return
    sets = ", ".join(f"{k}=?" for k in allowed)
    with connect() as conn:
        conn.execute(
            f"UPDATE followups SET {sets}, edited=1 WHERE paper_id=? AND work_id=?",
            (*allowed.values(), paper_id, work_id),
        )
        conn.commit()


def edit_reference(paper_id: str, ref_key: str, **fields) -> None:
    allowed = {k: v for k, v in fields.items() if k in ("verdict", "purpose", "gist", "why")}
    if not allowed:
        return
    sets = ", ".join(f"{k}=?" for k in allowed)
    with connect() as conn:
        conn.execute(
            f"UPDATE cites SET {sets}, edited=1 WHERE paper_id=? AND ref_key=?",
            (*allowed.values(), paper_id, ref_key),
        )
        conn.commit()


def edit_overview(paper_id: str, summary: str, reading: list[dict]) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO paper_context(paper_id, summary, reading_json, written_at, edited) "
            "VALUES (?,?,?,?,1) ON CONFLICT(paper_id) DO UPDATE SET summary=excluded.summary, "
            "reading_json=excluded.reading_json, written_at=excluded.written_at, edited=1",
            (paper_id, summary, json.dumps(reading, ensure_ascii=False), now()),
        )
        conn.commit()
