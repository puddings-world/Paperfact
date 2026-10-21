"""What each reference is actually doing in the paper you are reading.

The lineage block already answers "what does this build on", from the citation graph.
It cannot answer the question that decides whether a reference is worth your evening:
*why is it cited here* -- as the baseline being beaten, as the source of the dataset,
as the claim this paper overturns, or as a polite nod in the introduction. That
answer is in the sentence around the citation, nowhere else.

So: pull the citing sentences out of the text deterministically, pair them with the
reference list, and have the model say, per reference, what the citation is for and
whether it is worth reading next.

Citation styles seen in this corpus, all handled:
  Nature superscripts glued to the word   "surgical planning1-3, automate skill4-8"
  bracketed numerals                      "[12]", "[12, 13]", "[12-15]"
  author-year                             "(Ghamsarian et al., 2023)"
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from paper_daily.store import connect, now

Log = Callable[[str], None]

# A superscript reference glued to the end of a word: "planning1-3", "context12".
# The word part is required, otherwise every number in a table matches.
#
# The trailing lookahead keeps out decimals and percentages, and it has to do that
# without keeping out a full stop: the end of a sentence is where a citation most
# often sits. `(?!\.\d)` rejects "3.5" while admitting "domain shifts32." -- the
# earlier `(?![\d.%])` rejected both, which silently lost every sentence-final
# reference and truncated "assessment4-8." to "4".
SUPER_RE = re.compile(
    r"(?<=[a-zA-Z)])(\d{1,3}(?:[-–—]\d{1,3})?(?:,\s?\d{1,3}(?:[-–—]\d{1,3})?)*)"
    r"(?!\d)(?!\.\d)(?!%)"
)
BRACKET_RE = re.compile(r"\[(\d{1,3}(?:\s*[,–—-]\s*\d{1,3})*)\]")
# One author-year citation. A name broken across a line arrives as "Gham- sarian".
_ONE_AY = (
    r"[A-Z][A-Za-z\-']+(?:-\s[a-z]+)?(?:\s+(?:et al\.?|and|&)\s*[A-Za-z\-']*)?,?\s*"
    r"(?:19|20)\d{2}[a-z]?"
)
# In parentheses or square brackets, several to a group separated by semicolons:
# "[Ravi et al., 2024; Kirillov et al., 2023]" is CataractSAM-2's style, and with only
# the parenthesised single form recognised it yielded no citations at all.
AUTHOR_YEAR_RE = re.compile(rf"[(\[]({_ONE_AY}(?:\s*;\s*{_ONE_AY})*)[)\]]")

# Sentences end at a full stop that is not part of an abbreviation or a number.
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


def _expand(spec: str) -> list[str]:
    """"1-3" -> ["1","2","3"]; "4,5" -> ["4","5"].

    Numbers are normalised, because a page that prints "001" and one that prints "1"
    mean the same reference and must not become two entries.
    """
    out: list[str] = []
    for part in re.split(r",\s*", spec):
        rng = re.match(r"^(\d{1,3})[-–—](\d{1,3})$", part.strip())
        if rng:
            lo, hi = int(rng.group(1)), int(rng.group(2))
            if 0 < lo <= hi <= lo + 40:
                out.extend(str(n) for n in range(lo, hi + 1))
            continue
        if part.strip().isdigit() and int(part) > 0:
            out.append(str(int(part)))
    return out


# "ResNet50" and "VGG16" are model names, not superscript citations, and they sit at
# the end of a word exactly like one.
ARCHITECTURE_RE = re.compile(
    r"(ResNet|VGG|EfficientNet|DenseNet|MobileNet|Inception|ConvNeXt|BERT|GPT|YOLO"
    r"|U-?Net|ViT|SAM|LLaMA|Qwen|CLIP)$"
    # A lone capital carrying the depth -- "Slow R50", "ResNeXt X101". A real
    # superscript attaches to a word, not to a single letter.
    r"|\s[A-Z]$",
)


def contexts(text: str, max_per_key: int = 3, highest: int | None = None) -> dict[str, list[str]]:
    """Citation key -> the sentences that cite it.

    Keys are what the paper prints: "12" for a numbered style, "Ghamsarian et al.,
    2023" for author-year. The sentence is kept whole, because the purpose of a
    citation lives in the clause around it and nowhere smaller.
    """
    found: dict[str, list[str]] = {}
    # The running header carries the volume and the DOI on every page, and its digits
    # look exactly like superscript references: without this, "Scientific Data |
    # (2024) 11:373" is filed as the citing sentence for references 1 to 3.
    # A line that closes an author-year citation is short and full of digits too --
    # "sarian et al., 2021]." -- and dropping it loses the citation it finishes.
    keep = [
        ln for ln in text.splitlines()
        if "http" not in ln
        and "www." not in ln
        and (
            sum(c.isalpha() for c in ln) > len(ln) * 0.55
            or re.search(r"(?:et al\.?|[A-Za-z]),?\s*(?:19|20)\d{2}[a-z]?[)\]]", ln)
        )
    ]
    body = re.sub(r"\s+", " ", " ".join(keep))
    # Author affiliations are superscript digits on names -- "Negin Ghamsarian1, Yosuf
    # El-Shabrawi2" -- and are indistinguishable from references. Start at the first
    # real section instead.
    for opener in ("Background & Summary", "Background and Summary", "Introduction", "Abstract"):
        at = body.find(opener)
        if at > 0:
            body = body[at:]
            break
    for sentence in SENTENCE_RE.split(body):
        sentence = sentence.strip()
        if len(sentence) < 40 or len(sentence) > 900:
            continue
        keys: list[str] = []
        for m in BRACKET_RE.finditer(sentence):
            keys.extend(_expand(m.group(1)))
        for m in AUTHOR_YEAR_RE.finditer(sentence):
            keys.extend(
                re.sub(r"-\s(?=[a-z])", "", one).strip() for one in m.group(1).split(";")
            )
        if not keys:
            # Superscripts only when nothing else matched: a bracketed paper also
            # contains years and figure numbers glued to words.
            for m in SUPER_RE.finditer(sentence):
                if ARCHITECTURE_RE.search(sentence[max(0, m.start() - 14):m.start()]):
                    continue
                keys.extend(_expand(m.group(1)))
        if highest:
            # A paper with 40 references has no reference 50: a number that high is
            # something else the extraction glued to a word.
            keys = [k for k in keys if not k.isdigit() or int(k) <= highest]
        for key in dict.fromkeys(keys):
            seen = found.setdefault(key, [])
            if len(seen) < max_per_key and sentence not in seen:
                seen.append(sentence)
    return found


# The analysis specification this module writes. Bumped when the prompt or the
# coverage rules change, so `cites --rewrite` can walk an existing shelf forward the
# way dives.spec does rather than leaving a mix of old and new answers.
CITE_SPEC = "2026-10-full"

INSTRUCTIONS = """\
你拿到一篇論文的基本資料,以及它的參考文獻,分成兩區:

  A 區  有抓到引用句的參考文獻。你看得到論文在哪些句子裡引用它。
  B 區  在參考文獻清單裡,但文字中沒抓到引用句的。你只有標題和年份。

兩區的每一筆都要輸出,一筆都不能省略。輸出 JSON 陣列,每個物件恰好這些鍵:

  "key"      引用編號或作者年份,就是輸入裡給你的那個
  "title"    參考文獻標題;無法判斷就用引用句裡看得出的描述
  "purpose"  這篇論文引用它的目的,一句話。要具體:是拿來當 baseline、
             當資料來源、當被推翻的說法、當方法的出處、還是只是背景鋪陳
  "gist"     那一篇本身在做什麼,一句話。不知道就寫「從引用句看不出來」
  "verdict"  只能是 "必讀"、"值得"、"參考"、"略過" 其中之一
  "why"      給出 verdict 的理由,一句話,從讀者的角度:讀了它會多懂什麼

規則:
- 用繁體中文,技術名詞、論文標題、作者名保留英文。
- 數學用 Unicode 純文字,絕不使用 LaTeX。
- 只根據提供的引用句與標題判斷。看不出來就說看不出來,不要編造那篇論文的內容。
- "必讀" 留給這篇論文的方法或資料直接建立在其上的;只在背景段落被順帶提到的是 "略過"。
- B 區的判斷依據只有標題,所以 "purpose" 要以「文中未抓到引用句,從標題看…」開頭,
  而且除非標題明顯就是方法或資料的出處,verdict 給 "參考" 或 "略過"。
- 直接輸出 JSON 陣列,不要前言,不要程式碼圍欄。
"""


def _pack(
    row,
    refs: list[dict],
    ctx: dict[str, list[str]],
    numbered: dict[str, dict] | None = None,
    limit: int = 120,
) -> str:
    numbered = numbered or {}
    lines = [
        f"論文:{row['title']}({row['venue']} {row['year']})",
        "",
        "摘要:",
        (row["abstract"] or "（沒有摘要）")[:1500],
    ]

    if not numbered:
        # No publisher reference list: the model has to guess which title goes with
        # which number, so give it the candidates. With Crossref numbering this block
        # is dead weight and the numbers are already right.
        lines += ["", "參考文獻清單(來自 Semantic Scholar,順序不一定等於論文的編號):"]
        for r in refs[:120]:
            mark = " [influential]" if r.get("isInfluential") else ""
            lines.append(f"- {r.get('title')}({r.get('year')}, {r.get('venue') or 'n/a'}){mark}")

    lines += ["", "A 區 — 有引用句的參考文獻:"]
    for key, sentences in list(ctx.items())[:limit]:
        known = numbered.get(key)
        lines.append("")
        lines.append(f"[{key}] {known['title']}" if known else f"[{key}] (編號對應不明)")
        for sentence in sentences:
            lines.append(f"  - {sentence}")

    rest = [(k, v) for k, v in numbered.items() if k not in ctx]
    if rest:
        lines += ["", "B 區 — 在參考文獻清單裡,文中沒抓到引用句的:"]
        for key, known in rest[:120]:
            year = f" ({known['year']})" if known.get("year") else ""
            lines.append(f"[{key}] {known['title']}{year}")
    return "\n".join(lines)


def analyse(paper_id: str, limit: int = 120, log: Log = lambda _m: None) -> int:
    """Work out what each cited paper is doing here, and store it.

    Every reference the publisher lists gets a row, not only the ones whose citing
    sentence the text extraction found: a reference with no answer at all is the one
    case where you cannot tell whether it is worth your evening.
    """
    from paper_daily import llm
    from paper_daily.config import TEXT_DIR
    from paper_daily.enrich import s2
    from paper_daily.figures import _safe
    from paper_daily.sources import crossref
    from paper_daily.sources.openalex import same_paper

    with connect() as conn:
        row = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
        if row is None:
            log(f"  no paper {paper_id}")
            return 0

    path = TEXT_DIR / (_safe(paper_id) + ".txt")
    if not path.exists():
        log("  no extracted text; run prefetch or open the paper once")
        return 0

    # The publisher's own numbering, when there is a DOI to ask about. Without it a
    # superscript "17" is just a number and the model has to guess the title.
    numbered = crossref.reference_list(row["doi"] or "")
    highest = max((int(k) for k in numbered if k.isdigit()), default=None)

    ctx = contexts(path.read_text(encoding="utf-8"), highest=highest)
    if not ctx and not numbered:
        log("  no citation markers found in the text")
        return 0
    refs = s2.references(row["s2_id"]) if row["s2_id"] else []
    # A DOI resolves a reference exactly; a citation string from the publisher's list
    # is a poor search query, because the author block outweighs the title in it.
    by_doi = s2.papers_by_doi([v["doi"] for v in numbered.values() if v.get("doi")])
    log(
        f"  {len(numbered)} references listed, {len(ctx)} with a citing sentence, "
        f"{len(by_doi)} resolved by DOI, {len(refs)} on record at S2"
    )

    body, reason = llm.complete(
        _pack(row, refs, ctx, numbered, limit), system=INSTRUCTIONS, timeout=900, task="citations"
    )
    if not body:
        log(f"  failed: {reason}")
        return 0

    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", body.strip())
    start, end = body.find("["), body.rfind("]")
    if start == -1 or end == -1:
        log(f"  no JSON array in the reply: {body[:120]}")
        return 0
    try:
        entries = json.loads(body[start : end + 1])
    except json.JSONDecodeError as e:
        log(f"  invalid JSON ({e})")
        return 0

    stored: list[str] = []
    with connect() as conn:
        for e in entries:
            if not isinstance(e, dict) or not e.get("key"):
                continue
            # The model is asked for the key it was given and sometimes hands back
            # the bracket it saw in the prompt. "[1]" and "1" are the same reference,
            # and left alone they become two cards for it.
            key = str(e["key"]).strip().strip("[]").strip()
            if key.isdigit():
                key = str(int(key))
            known = numbered.get(key) or {}
            # The publisher's title beats the model's, which is at best a guess from
            # the citing sentence.
            title = known.get("title") or e.get("title")
            match = by_doi.get(known.get("doi") or "") or {}
            if not match and title:
                match = _s2_match(refs, title, same_paper)
            # The S2 record for a DOI carries the real title; the reference list entry
            # is often a whole citation string with the author block still on it.
            title = match.get("title") or title
            conn.execute(
                "INSERT INTO cites(paper_id, ref_key, title, s2_id, year, venue, "
                "citations, influential, purpose, gist, verdict, why, contexts_json, "
                "doi, basis, spec, written_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(paper_id, ref_key) DO UPDATE SET title=excluded.title, "
                "s2_id=excluded.s2_id, year=excluded.year, venue=excluded.venue, "
                "citations=excluded.citations, influential=excluded.influential, "
                "purpose=excluded.purpose, gist=excluded.gist, verdict=excluded.verdict, "
                "why=excluded.why, contexts_json=excluded.contexts_json, doi=excluded.doi, "
                "basis=excluded.basis, spec=excluded.spec, written_at=excluded.written_at "
                # A reference corrected by hand keeps the correction through a rerun.
                "WHERE cites.edited = 0",
                (
                    paper_id, key, title, match.get("paperId"),
                    match.get("year") or known.get("year"), match.get("venue"),
                    match.get("citationCount"), 1 if match.get("isInfluential") else 0,
                    e.get("purpose"), e.get("gist"), e.get("verdict"), e.get("why"),
                    json.dumps(ctx.get(key, []), ensure_ascii=False),
                    known.get("doi"), "context" if ctx.get(key) else "title",
                    CITE_SPEC, now(),
                ),
            )
            stored.append(key)
        # A re-analysis replaces the answer, so a marker the extraction no longer
        # produces has to go with it. Upserting alone left the previous run's noise
        # ("0", a "50" read off ResNet50) sitting in the tab for good.
        if stored:
            marks = ",".join("?" * len(stored))
            conn.execute(
                f"DELETE FROM cites WHERE paper_id=? AND ref_key NOT IN ({marks})",
                (paper_id, *stored),
            )
        conn.commit()
    return len(stored)


def _s2_match(refs: list[dict], title: str, same: Callable[[str, str], bool]) -> dict:
    """The Semantic Scholar record for a title from the publisher's reference list.

    Exact first, then the relaxed comparison that already decides whether two titles
    name the same paper elsewhere in the pipeline. The match is what makes 加入清單
    able to pull the paper in by id instead of searching for it by name.
    """
    wanted = title.strip().lower()
    for r in refs:
        if (r.get("title") or "").strip().lower() == wanted:
            return r
    for r in refs:
        if r.get("title") and same(title, r["title"]):
            return r
    return {}


BY_VERDICT = (
    "CASE verdict WHEN '必讀' THEN 0 WHEN '值得' THEN 1 WHEN '參考' THEN 2 ELSE 3 END, "
    "basis = 'title', influential DESC, COALESCE(citations, 0) DESC"
)
# The paper's own numbering, for reading alongside the text: you see "27" on the page
# and want that card, not the one the verdict happened to rank first.
BY_NUMBER = (
    "CASE WHEN ref_key GLOB '[0-9]*' THEN CAST(ref_key AS INTEGER) ELSE 1000000 END, ref_key"
)


def for_paper(conn, paper_id: str, order: str = "verdict") -> list[dict]:
    """Stored citation analysis, most worth reading first, or in reference order."""
    rows = conn.execute(
        f"SELECT * FROM cites WHERE paper_id=? ORDER BY "
        f"{BY_NUMBER if order == 'number' else BY_VERDICT}",
        (paper_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["contexts"] = json.loads(d.pop("contexts_json") or "[]")
        except json.JSONDecodeError:
            d["contexts"] = []
        out.append(d)
    return out


def analyse_ahead(count: int = 2, rewrite: bool = False, log: Log = lambda _m: None) -> int:
    """Analyse the citations of the next few papers that have none.

    Same reasoning as writing dives ahead: the tab is worth having filled in before
    you reach the paper, not after. Lists come first -- those are the papers someone
    chose deliberately, so their references are the ones most likely to be followed.

    With `rewrite`, it takes papers already analysed under an older specification
    instead, in the same order, so a prompt change reaches the papers about to be
    read without a marathon.
    """
    if rewrite:
        where = (
            "EXISTS (SELECT 1 FROM cites c WHERE c.paper_id = p.id "
            "        AND (c.spec IS NULL OR c.spec <> ?))"
        )
        params: tuple = (CITE_SPEC, count)
    else:
        where = "NOT EXISTS (SELECT 1 FROM cites c WHERE c.paper_id = p.id)"
        params = (count,)

    with connect() as conn:
        rows = conn.execute(
            f"SELECT p.id, p.title FROM papers p WHERE {where} "
            "  AND EXISTS (SELECT 1 FROM dives d WHERE d.paper_id = p.id) "
            "ORDER BY EXISTS(SELECT 1 FROM list_papers lp WHERE lp.paper_id = p.id) DESC, "
            "  COALESCE((SELECT q.rank FROM queue q WHERE q.paper_id = p.id), 1e9) "
            "LIMIT ?",
            params,
        ).fetchall()

    done = 0
    for r in rows:
        log(f"  citations: {r['title'][:58]}")
        if analyse(r["id"], log=log):
            done += 1
    if not rows:
        log(
            "  every analysed paper is already on the current specification"
            if rewrite
            else "  every explained paper already has its citations analysed"
        )
    return done
