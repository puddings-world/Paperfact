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
from paper_daily.store import connect, get_kv, now, title_key

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


def fetch(paper_id: str, log: Log = lambda _m: None, *, database=None, connections=None) -> int:
    from contextlib import closing

    from paper_daily import research_compound as compound
    from paper_daily import research_generation as generation
    from paper_daily import research_job_lock, store

    database = (database or store.DB_PATH).resolve()
    with (
        research_job_lock.claim(database, "followups", paper_id) as acquired,
        llm.connection_scope(connections),
    ):
        if not acquired:
            log("Followup research is already in progress")
            return 0
        with closing(generation._connect(database)) as conn:
            context = compound.begin(conn, phase="fetch", owner_id=paper_id)
        return _fetch(context, log)


def _fetch(context, log):
    from paper_daily import research_compound as compound

    row = context.paper
    wid = work_id(row)
    openalex = _citing_openalex(wid) if wid else []
    s2 = _citing_s2(row)
    if wid is None and s2 is None:
        log(f"  neither OpenAlex nor Semantic Scholar knows {row['title'][:60]}")
        return 0
    works = merge(openalex, s2 or [])

    originals = {r["work_id"]: r for r in context.rows}
    puts = {}
    for work in works:
        key = work["id"]
        old = originals.get(key)
        if old and old.get("edited"):
            continue
        values = {"citations": work.get("citations"), "fetched_at": context.started_at}
        if old is None:
            values.update(
                title=work.get("title") or "(untitled)",
                year=work.get("year"),
                venue=work.get("venue"),
            )
        for name in ("abstract", "doi", "arxiv_id"):
            values[name] = (old or {}).get(name) or work.get(name)
        values["contexts_json"] = (
            json.dumps(work["contexts"], ensure_ascii=False)
            if work.get("contexts")
            else (old or {}).get("contexts_json")
        )
        puts[key] = compound.row(context, key, **values)
    result = compound.publish(context, puts=list(puts.values()), completion=context.started_at)
    if result.status != "accepted":
        log(f"{result.reason}; lookup result retained: {result.candidate_id}")
        return 0
    log(f"  {len(works)} citing work(s): {len(openalex)} from OpenAlex, {len(s2 or [])} from S2")
    return len(works)


# ---- judging --------------------------------------------------------------------
def _json(text: str, opener: str, closer: str):
    start, end = text.find(opener), text.rfind(closer)
    if start < 0 or end < start:
        raise ValueError("no JSON in the answer")
    return json.loads(text[start : end + 1])


def judge(
    paper_id: str, log: Log = lambda _m: None, *, database=None, connections=None
) -> tuple[int, str]:
    from contextlib import closing

    from paper_daily import research_compound as compound
    from paper_daily import research_generation as generation
    from paper_daily import research_job_lock, store

    database = (database or store.DB_PATH).resolve()
    with (
        research_job_lock.claim(database, "followups", paper_id) as acquired,
        llm.connection_scope(connections),
    ):
        if not acquired:
            return 0, "Followup research is already in progress"
        with closing(generation._connect(database)) as conn:
            context = compound.begin(conn, phase="judge", owner_id=paper_id)
        return _judge(context, log)


def _judge(context, log):
    from paper_daily import research_compound as compound

    paper = context.paper
    rows = sorted(
        (r for r in context.rows if r["relation"] is None and not r["edited"]),
        key=lambda r: -(r["citations"] or 0),
    )
    if not rows:
        return 0, "nothing to judge"
    puts, reason = {}, ""
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
        prompt = "\n".join(lines)
        context = compound.with_prompt(context, prompt)
        text, reason = llm.complete(prompt, system=JUDGE_SYSTEM, timeout=900, task="followups")
        if not text:
            break
        try:
            verdicts = _json(text, "[", "]")
        except ValueError:
            reason = "the model's answer was not a JSON array"
            continue

        if not isinstance(verdicts, list):
            reason = "the model's answer was not a JSON array"
            continue
        for v in verdicts:
            try:
                index = int(v["id"])
                if index < 0:
                    continue
                r = batch[index]
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            if v.get("verdict") not in VERDICTS:
                continue
            puts[r["work_id"]] = compound.row(
                context,
                r["work_id"],
                verdict=v["verdict"],
                why=v.get("why"),
                relation=v.get("relation"),
            )
    if not puts:
        return 0, reason
    result = compound.publish(context, puts=list(puts.values()))
    if result.status != "accepted":
        return 0, f"{result.reason}; generated result retained: {result.candidate_id}"
    log(f"  {len(puts)} followup(s) judged")
    return len(puts), ""


def overview_inputs(conn, paper_id, *, limit=2000):
    """The bounded metadata actually consumed by the overview prompt."""
    for table in ("cites", "followups"):
        count = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE paper_id=?", (paper_id,)
        ).fetchone()[0]
        if count > limit:
            raise ValueError("Overview input exceeds its record limit")
    paper = conn.execute(
        "SELECT title,venue,year,abstract FROM papers WHERE id=?", (paper_id,)
    ).fetchone()
    dive = conn.execute("SELECT body FROM dives WHERE paper_id=?", (paper_id,)).fetchone()
    verdicts = ("必讀", "值得")
    refs = [r for r in references(conn, paper_id) if r.get("verdict") in verdicts][:30]
    later = [r for r in for_paper(conn, paper_id) if r.get("verdict") in verdicts][:30]
    return {
        "paper": dict(paper) if paper else None,
        "dive": (dive["body"] or "")[:3500] if dive else "",
        "refs": [
            {key: r.get(key) for key in ("title", "year", "verdict", "purpose")} for r in refs
        ],
        "later": [
            {key: r.get(key) for key in ("title", "year", "verdict", "relation", "why")}
            for r in later
        ],
    }


def overview(
    paper_id: str, log: Log = lambda _m: None, *, database=None, connections=None
) -> tuple[bool, str]:
    from contextlib import closing

    from paper_daily import research_generation as generation
    from paper_daily import research_job_lock, store

    database = (database or store.DB_PATH).resolve()
    with research_job_lock.claim(database, "context", paper_id) as acquired:
        if not acquired:
            return False, "overview is already in progress"
        with llm.connection_scope(connections):
            cfg = llm.settings(task="overview")
            with closing(generation._connect(database)) as conn:
                if conn.execute("SELECT 1 FROM papers WHERE id=?", (paper_id,)).fetchone() is None:
                    return False, "paper no longer exists"
                context = generation.begin_generation(
                    conn, table="paper_context", owner_id=paper_id
                )
            if context.target and context.target["edited"]:
                return False, "edited by hand"
            return _write_overview(context, cfg, log)


def _write_overview(context, cfg, log):
    from paper_daily.research_generation import publish_generated

    inputs = context.inputs
    paper, dive = inputs["paper"], {"body": inputs["dive"]}
    keep_refs, keep_later = inputs["refs"], inputs["later"]
    if not keep_refs and not keep_later:
        return False, "nothing judged yet to build an overview from"
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
        "\n".join(lines), system=OVERVIEW_SYSTEM, timeout=600, task="overview", cfg=cfg
    )
    if not text:
        return False, reason
    try:
        data = _json(text, "{", "}")
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("summary"), str)
            or not data["summary"].strip()
            or not isinstance(data.get("reading"), list)
            or any(not isinstance(item, dict) for item in data["reading"])
        ):
            raise ValueError("Invalid overview fields")
        reading = [
            {"title": str(x.get("title") or ""), "direction": str(x.get("direction") or ""),
             "why": str(x.get("why") or "")}
            for x in (data.get("reading") or []) if isinstance(x, dict) and x.get("title")
        ][:6]
        result = publish_generated(context, row={
            "paper_id": context.owner_id, "summary": str(data.get("summary") or ""),
            "reading_json": json.dumps(reading, ensure_ascii=False),
            "written_at": now(), "edited": 0,
        })
    except (ValueError, TypeError, AttributeError):
        return False, "the model's answer was not a valid overview"
    if result.status != "accepted":
        return False, f"{result.reason}; generated result retained: {result.candidate_id}"
    log("  overview written")
    return True, ""


def done(conn, paper_id: str) -> bool:
    """Retrieval alone is not a completed later-work explanation."""
    if get_kv(conn, f"followups.checked.{paper_id}") is None:
        return False
    row = conn.execute("SELECT summary FROM paper_context WHERE paper_id=?", (paper_id,)).fetchone()
    return bool(row and isinstance(row[0], str) and row[0].strip())


def analyse(
    paper_id: str, log: Log = lambda _m: None, *, database=None, connections=None,
    overview_too: bool = True,
) -> int:
    from contextlib import closing

    from paper_daily import citegraph, research_job_lock, store
    from paper_daily import research_compound as compound
    from paper_daily import research_generation as generation

    database = (database or store.DB_PATH).resolve()
    connections = connections or llm.capture_connections()
    with (
        research_job_lock.claim(database, "followups", paper_id) as acquired,
        llm.connection_scope(connections),
    ):
        if not acquired:
            log("Followup research is already in progress")
            return 0
        with closing(generation._connect(database)) as conn:
            observed = compound.begin(conn, phase="fetch", owner_id=paper_id)
        original_scope = observed
        _fetch(observed, log)
        if not compound.scope_current(original_scope):
            log("Original research owner changed; remaining phases skipped")
            return 0
        with closing(generation._connect(database)) as conn:
            observed = compound.begin(conn, phase="judge", owner_id=paper_id)
        done, reason = _judge(observed, log)
        if reason and reason != "nothing to judge":
            log(f"  judging skipped: {reason}")
        if not compound.scope_current(original_scope):
            log("Original research owner changed; remaining phases skipped")
            return done
        if overview_too:
            wrote, why = overview(paper_id, log, database=database, connections=connections)
            if not wrote and why != "edited by hand":
                log(f"  overview skipped: {why}")
        # The older graph enrichment writer has no explicit workspace contract.
        if store.DB_PATH.resolve() == database and compound.scope_current(original_scope):
            citegraph.links(paper_id, log)
        return done


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
def item_edit_snapshot(conn, paper_id, kind, key):
    from paper_daily.research_compound import begin

    if kind not in ("ref", "followup", "later"):
        raise ValueError("Unknown research item kind")
    return begin(
        conn,
        phase="edit_reference" if kind == "ref" else "edit_followup",
        owner_id=paper_id,
        key=key,
    )


def _edit_item(paper_id, key, kind, expected, fields):
    from paper_daily import research_compound as compound
    from paper_daily.sync_capture import StaleCaptureError

    names = (
        ("verdict", "purpose", "gist", "why") if kind == "ref" else ("verdict", "relation", "why")
    )
    allowed = {k: v for k, v in fields.items() if k in names}
    if not allowed:
        return
    if expected is None:
        with connect() as conn:
            expected = item_edit_snapshot(conn, paper_id, kind, key)
    phase = "edit_reference" if kind == "ref" else "edit_followup"
    if (
        expected.owner_id != paper_id
        or expected.data["phase"] != phase
        or expected.data["key"] != key
    ):
        raise ValueError("Research edit belongs to another row")
    if expected.target is None:
        raise ValueError("Research item no longer exists")
    result = compound.publish(
        expected, puts=[compound.row(expected, key, edited=1, **allowed)], manual=True
    )
    if result.status != "accepted":
        raise StaleCaptureError(result.candidate_id)


def edit_followup(paper_id: str, work_id: str, *, expected=None, **fields) -> None:
    _edit_item(paper_id, work_id, "followup", expected, fields)


def edit_reference(paper_id: str, ref_key: str, *, expected=None, **fields) -> None:
    _edit_item(paper_id, ref_key, "ref", expected, fields)


def overview_edit_snapshot(conn, paper_id):
    from paper_daily.research_generation import begin_generation

    return begin_generation(conn, table="paper_context", owner_id=paper_id, input_reader="target")


def edit_overview(paper_id: str, summary: str, reading: list[dict], *, expected=None) -> None:
    from paper_daily.research_generation import publish_edit
    from paper_daily.sync_capture import StaleCaptureError

    if expected is None:
        with connect() as conn:
            expected = overview_edit_snapshot(conn, paper_id)
    if expected.table != "paper_context" or expected.owner_id != paper_id:
        raise ValueError("The overview edit belongs to another paper")
    result = publish_edit(expected, row={
        "paper_id": paper_id, "summary": summary,
        "reading_json": json.dumps(reading, ensure_ascii=False),
        "written_at": expected.started_at, "edited": 1,
    })
    if result.status != "accepted":
        raise StaleCaptureError(result.candidate_id)
