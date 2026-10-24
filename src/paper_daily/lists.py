"""Reading lists beside the main queue.

The nightly queue answers "what should I read next from the field". A list answers
a different question -- the bibliography of a paper being written, a colleague's
shortlist, a topic to binge -- and those papers are mostly not ICLR/ICML/NeurIPS at
all. They live in the same `papers` table so the reader, the PDF fetcher, the dive
writer and the notes all work on them unchanged; `queue.build` fences the nightly
queue to the three venues so they never leak into it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from paper_daily import resolve
from paper_daily.enrich import s2
from paper_daily.sources import arxiv
from paper_daily.store import connect, get_kv, now, set_kv, title_key

Log = Callable[[str], None]

PARSE_INSTRUCTIONS = """\
Below is a bibliography copied out of a PDF. It is messy: line numbers, page
headers, words hyphenated across line breaks, and entries wrapped over several
lines.

Return a JSON array, one object per reference, with exactly these keys:
  "title"   the paper title, de-hyphenated and on one line
  "authors" array of author names as written
  "venue"   the venue as written, or "arXiv" for preprints
  "year"    integer
  "url"     the URL if one is given, else null

Rules:
- One object per reference. Do not merge or split entries.
- Repair words broken across lines ("vision-language" not "visionlanguage").
- Include software and non-paper entries too; use the project name as the title.
- Output the JSON array and nothing else. No prose, no code fence.
"""

# Page furniture from the source PDF. Stripped before parsing so the model is not
# asked to distinguish a line number from a year.
_NOISE = re.compile(r"^\s*(\d{1,4}|Under review as a conference paper.*|REFERENCES)\s*$")


def clean_bibliography(raw: str) -> str:
    return "\n".join(ln for ln in raw.splitlines() if not _NOISE.match(ln))


def _fallback_parse(text: str) -> list[dict]:
    """Split on blank-line-separated blocks. Only used when the CLI is unavailable;
    it gets the entry boundaries roughly right and leaves the title to the matcher."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    out = []
    for block in blocks:
        joined = " ".join(block.split())
        year = re.search(r"\b(19|20|21)\d{2}\b", joined)
        out.append(
            {
                "title": joined[:300],
                "authors": [],
                "venue": "",
                "year": int(year.group()) if year else 0,
                "url": None,
            }
        )
    return out


def parse_bibliography(raw: str, log: Log = lambda _m: None, *, strict=False) -> list[dict]:
    """Messy bibliography text -> structured entries."""
    from paper_daily import llm

    text = clean_bibliography(raw)
    body, reason = llm.complete(text, system=PARSE_INSTRUCTIONS, timeout=600, task="list_parse")
    if not body:
        if strict:
            raise ValueError(reason)
        log(f"  {reason}; falling back to blank-line splitting")
        return _fallback_parse(text)

    # The model is told not to fence the output, but a stray ```json is cheap to undo
    # and expensive to debug.
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", body).strip()
    start, end = body.find("["), body.rfind("]")
    if start == -1 or end == -1:
        if strict:
            raise ValueError("AI 未回傳有效參考文獻清單，請重試。")
        log(f"  parse produced no JSON array: {body[:120]}")
        return _fallback_parse(text)
    try:
        entries = json.loads(body[start : end + 1])
    except json.JSONDecodeError as e:
        if strict:
            raise ValueError("AI 回傳格式無法解析，請重試。") from e
        log(f"  parse produced invalid JSON ({e}); falling back")
        return _fallback_parse(text)
    return [e for e in entries if isinstance(e, dict) and e.get("title")]


def _paper_from_match(entry: dict, match: dict | None) -> dict:
    """Build a papers row, preferring Semantic Scholar over the citation text."""
    if match:
        ext = match.get("externalIds") or {}
        oa = match.get("openAccessPdf") or {}
        arxiv_id = ext.get("ArXiv") or entry.get("arxiv_id")
        names = [a.get("name") for a in (match.get("authors") or []) if a.get("name")]
        title = match.get("title") or entry["title"]
        return {
            "id": "ref:" + (match.get("paperId") or title_key(title))[:24],
            "title_key": title_key(title),
            "venue": (match.get("venue") or entry.get("venue") or "arXiv")[:120],
            "year": int(match.get("year") or entry.get("year") or 0),
            "title": title,
            "authors_json": json.dumps(names or entry.get("authors") or [], ensure_ascii=False),
            "abstract": match.get("abstract"),
            "pdf_url": oa.get("url"),
            "page_url": entry.get("url"),
            "s2_id": match.get("paperId"),
            "arxiv_id": str(arxiv_id) if arxiv_id else None,
            "doi": ext.get("DOI"),
            "citation_count": match.get("citationCount"),
            "influential_count": match.get("influentialCitationCount"),
            "reference_count": match.get("referenceCount"),
            "source": "import",
        }

    return {
        "id": "ref:" + title_key(entry["title"])[:24],
        "title_key": title_key(entry["title"]),
        "venue": (entry.get("venue") or "unknown")[:120],
        "year": int(entry.get("year") or 0),
        "title": entry["title"],
        "authors_json": json.dumps(entry.get("authors") or [], ensure_ascii=False),
        "abstract": entry.get("abstract"),
        "page_url": entry.get("url"),
        "arxiv_id": entry.get("arxiv_id"),
        "source": "import",
    }


def _store_entry(
    conn, entry: dict, list_id: str, position: int, keep_position: bool = False
) -> tuple[str, bool, str]:
    """Resolve one reference and put it in the list.

    Returns (paper_id, matched, flag), where flag is also how the caller learns the
    paper was already a member: re-importing a bibliography should renumber it, but
    adding one paper by hand must not drag an existing member to the end of the list.
    """
    from paper_daily.store import upsert_papers

    # A DOI from the publisher's reference list identifies the paper outright. The
    # title path stays for bibliographies pasted by hand, which carry no identifier.
    match = s2.by_doi(entry["doi"]) if entry.get("doi") else None
    if match is None:
        match = s2.match_title(entry["title"])
    row = _paper_from_match(entry, match)

    # Reuse the crawled paper when this reference is one the corpus already holds.
    # Ten of the first list's references were ICLR/ICML/NeurIPS papers already sitting
    # there with a proceedings PDF, and importing them as fresh `ref:` rows threw that
    # away and split their notes and dives across two ids for the same paper.
    existing = conn.execute(
        "SELECT id FROM papers WHERE title_key = ? AND source != 'import' LIMIT 1",
        (row["title_key"],),
    ).fetchone()
    if existing:
        # Fill the crawled row's gaps rather than upserting over it: venue, year and
        # source belong to the crawl, and an upsert would also have to supply them
        # because the INSERT half evaluates either way.
        row["id"] = existing["id"]
        conn.execute(
            "UPDATE papers SET "
            "abstract = COALESCE(abstract, ?), "
            "s2_id = COALESCE(s2_id, ?), "
            "arxiv_id = COALESCE(arxiv_id, ?), "
            "doi = COALESCE(doi, ?), "
            "citation_count = COALESCE(citation_count, ?) "
            "WHERE id = ?",
            (
                row.get("abstract"),
                row.get("s2_id"),
                row.get("arxiv_id"),
                row.get("doi"),
                row.get("citation_count"),
                row["id"],
            ),
        )

    if not existing:
        # Semantic Scholar did not give a way to the paper, or gave a match with no
        # open-access link. CVF, arXiv and OpenAlex between them cover conference
        # papers, preprints and everything published anywhere else.
        row, _found = resolve.fill_gaps(row)

    if not existing:
        upsert_papers(conn, iter([dict(row)]))

    member = conn.execute(
        "SELECT 1 FROM list_papers WHERE list_id=? AND paper_id=?", (list_id, row["id"])
    ).fetchone()
    if member and keep_position:
        return row["id"], bool(match), "dup  "
    conn.execute(
        "INSERT INTO list_papers(list_id, paper_id, position, citation, added_at) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(list_id, paper_id) DO UPDATE SET position=excluded.position",
        (list_id, row["id"], position, entry["title"], now()),
    )
    if existing:
        flag = "reuse"
    elif row.get("pdf_url") or row.get("arxiv_id"):
        flag = "ok   "
    else:
        flag = "MISS "
    return row["id"], bool(match), flag


def import_list(
    name: str, raw: str, list_id: str | None = None, log: Log = lambda _m: None,
    *, entries: list[dict] | None = None,
) -> dict:
    """Parse a bibliography, resolve each entry, and store it as a reading list."""
    entries = parse_bibliography(raw, log) if entries is None else entries
    log(f"  parsed {len(entries)} references")
    if not entries:
        return {"parsed": 0, "resolved": 0, "added": 0}

    slug = list_id or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "list"
    resolved = 0

    with connect() as conn:
        conn.execute(
            "INSERT INTO lists(id, name, created_at) VALUES (?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name",
            (slug, name, now()),
        )

        for position, entry in enumerate(entries):
            _paper_id, matched, flag = _store_entry(conn, entry, slug, position)
            resolved += int(matched)
            log(f"  {position + 1:3d}. {flag} {entry['title'][:62]}")
            if position % 10 == 9:
                conn.commit()
        conn.commit()

        added = conn.execute(
            "SELECT COUNT(*) FROM list_papers WHERE list_id=?", (slug,)
        ).fetchone()[0]

    return {"parsed": len(entries), "resolved": resolved, "added": added, "id": slug}


def add_paper(
    list_id: str,
    citation: str,
    log: Log = lambda _m: None,
    create_name: str | None = None,
    doi: str | None = None,
) -> dict:
    """Append one paper to an existing list.

    An imported bibliography is someone's first draft of what to read: entries get
    missed, and a citation that resolved to the wrong paper has to be replaced. This
    takes the same path as an import entry -- one line of citation, a title, or an
    arXiv id -- so a paper added later is indistinguishable from one imported.
    """
    text = clean_bibliography(citation).strip()
    if not text:
        return {"added": 0, "reason": "nothing to add"}

    with connect() as conn:
        if not conn.execute("SELECT 1 FROM lists WHERE id=?", (list_id,)).fetchone():
            if not create_name:
                return {"added": 0, "reason": f"no list called '{list_id}'"}
            # "Add this reference to my reading" should not fail because the list it
            # belongs in does not exist yet.
            conn.execute(
                "INSERT INTO lists(id, name, created_at) VALUES (?,?,?)",
                (list_id, create_name, now()),
            )
            conn.commit()

    bare = arxiv.BARE_ID.match(text)
    paper = arxiv.by_id(bare.group(1)) if bare else None
    if bare and paper is None:
        return {"added": 0, "reason": f"arXiv has no paper {bare.group(1)}"}

    # One line is usually a bare title; anything longer is a citation worth parsing,
    # and the parser is what repairs hyphenation and pulls the year out.
    entries = [{**paper, "venue": "arXiv", "url": None}] if paper else (
        parse_bibliography(text, log)
        if len(text.splitlines()) > 1 or len(text) > 160
        else [{"title": text, "authors": [], "venue": "", "year": 0, "url": None}]
    )
    if not entries:
        return {"added": 0, "reason": "could not read that as a reference"}
    # The caller knew which paper this is -- from a reference list, not from a search.
    if doi and len(entries) == 1:
        entries[0]["doi"] = doi

    with connect() as conn:
        start = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM list_papers WHERE list_id=?",
            (list_id,),
        ).fetchone()[0]
        added, already = [], []
        for entry in entries:
            paper_id, _matched, flag = _store_entry(
                conn, entry, list_id, start + len(added), keep_position=True
            )
            log(f"  {flag} {entry['title'][:62]}")
            (already if flag == "dup  " else added).append(paper_id)
        conn.commit()
    reason = "ok" if added else "already in this list"
    return {"added": len(added), "paper_ids": added, "already": already, "reason": reason}


def remove_paper(list_id: str, paper_id: str) -> bool:
    """Take a paper out of a list, and close the gap it leaves.

    The paper itself stays: it may be in the nightly queue or another list, and its
    notes and dive are worth keeping even if this list was wrong about wanting it.
    """
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM list_papers WHERE list_id=? AND paper_id=?", (list_id, paper_id)
        )
        if not cur.rowcount:
            return False
        # Positions are what "the order someone chose" means; leaving holes in them
        # makes the next insert land in the middle of the list.
        rows = conn.execute(
            "SELECT paper_id FROM list_papers WHERE list_id=? ORDER BY position",
            (list_id,),
        ).fetchall()
        conn.executemany(
            "UPDATE list_papers SET position=? WHERE list_id=? AND paper_id=?",
            [(i, list_id, r["paper_id"]) for i, r in enumerate(rows)],
        )
        return True


def all_lists() -> list[dict]:
    """Every reading list, with how far through it the reader is."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT l.id, l.name, l.note, COUNT(lp.paper_id) n, "
            "       SUM(lp.state = 'read') read, "
            "       SUM(EXISTS (SELECT 1 FROM dives d WHERE d.paper_id = lp.paper_id)) explained, "
            "       (SELECT COUNT(*) FROM pins p WHERE p.scope = l.id) pinned "
            "FROM lists l LEFT JOIN list_papers lp ON lp.list_id = l.id "
            "GROUP BY l.id ORDER BY l.created_at"
        ).fetchall()
        order = get_kv(conn, "lists.order", []) or []
    ranks = {key: i for i, key in enumerate(order)}
    rows = sorted(rows, key=lambda r: ranks.get(r["id"], len(ranks)))
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "note": r["note"],
            "count": r["n"],
            "read": r["read"] or 0,
            "explained": r["explained"] or 0,
            "pinned": r["pinned"],
        }
        for r in rows
    ]



def up_next(list_id: str, limit: int = 5) -> list[dict]:
    """The unread papers a reader meets first in a list: pinned ones, then the
    list's own order."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT p.id, p.title, pin.paper_id IS NOT NULL pinned "
            "FROM list_papers lp JOIN papers p ON p.id = lp.paper_id "
            "LEFT JOIN pins pin ON pin.scope = lp.list_id AND pin.paper_id = lp.paper_id "
            "WHERE lp.list_id = ? AND lp.state != 'read' "
            "ORDER BY pinned DESC, pin.pinned_at, lp.position LIMIT ?",
            (list_id, limit),
        ).fetchall()
    return [{"id": r["id"], "title": r["title"], "pinned": bool(r["pinned"])} for r in rows]

def rename(list_id: str, name: str) -> None:
    """Names are editable labels; identifiers and research data never change."""
    name = name.strip()
    if not name or len(name) > 200:
        raise ValueError("清單名稱請填寫 1–200 個字。")
    with connect() as conn:
        if not conn.execute("UPDATE lists SET name=? WHERE id=?", (name, list_id)).rowcount:
            raise ValueError("清單已不存在，請重新整理。")


def reorder(list_ids: list[str]) -> None:
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = {r[0] for r in conn.execute("SELECT id FROM lists")}
        if len(list_ids) != len(current) or set(list_ids) != current:
            raise ValueError("清單已變動，請重新整理後再排序。")
        set_kv(conn, "lists.order", list_ids)


def reorder_papers(list_id: str, paper_ids: list[str]) -> None:
    """Persist a complete permutation atomically, rejecting stale/partial views."""
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM lists WHERE id=?", (list_id,)).fetchone():
            raise ValueError("清單已不存在。")
        current = {r[0] for r in conn.execute(
            "SELECT paper_id FROM list_papers WHERE list_id=?", (list_id,)
        )}
        if len(paper_ids) != len(current) or set(paper_ids) != current:
            raise ValueError("論文已變動，請重新整理後再排序。")
        conn.executemany(
            "UPDATE list_papers SET position=? WHERE list_id=? AND paper_id=?",
            [(i, list_id, pid) for i, pid in enumerate(paper_ids)],
        )


def adopt_legacy_queue() -> str | None:
    """Once, retain the old desktop queue as an ordinary, independently editable list.

    CLI ranking tables remain intact for legacy workflows. They no longer own the
    desktop reading order or restore papers the user removed from this list.
    """
    from uuid import uuid4

    from paper_daily import analysis_schedule

    with connect() as conn:
        adopted = get_kv(conn, "lists.legacy_queue")
        if adopted:
            return adopted
        rows = conn.execute(
            "SELECT q.* FROM queue q JOIN papers p ON p.id=q.paper_id "
            "WHERE q.state != 'skipped' ORDER BY q.rank, q.paper_id"
        ).fetchall()
        if not rows:
            return None
        # Normal refresh is read-only. Acquire a write lock only for the actual
        # one-time migration, then recheck in case another process adopted it.
        conn.execute("BEGIN IMMEDIATE")
        adopted = get_kv(conn, "lists.legacy_queue")
        if adopted:
            return adopted
        rows = conn.execute(
            "SELECT q.* FROM queue q JOIN papers p ON p.id=q.paper_id "
            "WHERE q.state != 'skipped' ORDER BY q.rank, q.paper_id"
        ).fetchall()
        if not rows:
            return None
        list_id = "ml-" + uuid4().hex[:12]
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES (?,?,?)",
                     (list_id, "ML 頂會論文", now()))
        conn.executemany(
            "INSERT INTO list_papers(list_id,paper_id,position,state,added_at,"
            "delivered_at,read_at) VALUES (?,?,?,?,?,?,?)",
            [(list_id, r["paper_id"], i, r["state"], r["queued_at"] or now(),
              r["delivered_at"], r["read_at"]) for i, r in enumerate(rows)],
        )
        conn.execute(
            "INSERT INTO pins(scope,paper_id,pinned_at) "
            "SELECT ?,paper_id,pinned_at FROM pins WHERE scope='queue'", (list_id,)
        )
        set_kv(conn, "lists.legacy_queue", list_id)
        settings = analysis_schedule.load(conn)
        analysis_schedule.save(conn, {**settings, "queue": 0})
        return list_id


def delete_list(list_id: str) -> None:
    """Drop a list. The papers stay -- they may be in another list or the queue."""
    with connect() as conn:
        conn.execute("DELETE FROM list_papers WHERE list_id=?", (list_id,))
        conn.execute("DELETE FROM lists WHERE id=?", (list_id,))
