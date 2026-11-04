"""Read-only access to everything a workspace holds about its papers and lists.

External agents connected through MCP (or the JSON CLI) read the same research the
desktop shows: deep dives, close readings, notes, Q&A, highlights, research
questions, context, citations, later work, code links and the extracted text.
Nothing here writes, calls AI, downloads or opens a path a caller names; the
caller passes identifiers only.

Long texts come back clipped to a character budget with their full length, so an
agent can page through one section with `offset` instead of receiving a dive and
a 200 000-character paper in one reply.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from paper_daily import store

SECTIONS = (
    "paper",
    "dive",
    "close_reading",
    "notes",
    "chat",
    "highlights",
    "questions",
    "context",
    "citations",
    "later_work",
    "resources",
    "full_text",
)
# The extracted paper is the one section most readers do not need and the largest
# by far; it is read only when asked for by name.
DEFAULT_SECTIONS = tuple(s for s in SECTIONS if s != "full_text")
DEFAULT_CHARS = 20_000
MAX_CHARS = 100_000
MAX_ITEMS = 300
SEARCH_LIMIT = 50


class ReadError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _clip(text: str | None, offset: int, budget: int) -> dict | None:
    if text is None:
        return None
    part = text[offset: offset + budget]
    end = offset + len(part)
    return {
        "text": part,
        "length": len(text),
        "offset": offset,
        "next_offset": end if end < len(text) else None,
    }


def _page(anchor) -> int | None:
    try:
        return int(json.loads(anchor)["p0"]) + 1
    except (ValueError, KeyError, TypeError):
        return None


def _json(text, default):
    try:
        return json.loads(text) if text else default
    except ValueError:
        return default


def _items(conn, sql, args, fn=dict):
    rows = conn.execute(sql + " LIMIT ?", (*args, MAX_ITEMS + 1)).fetchall()
    return {"items": [fn(r) for r in rows[:MAX_ITEMS]], "more": len(rows) > MAX_ITEMS}


def _paper(conn, paper_id):
    row = conn.execute(
        "SELECT id,title,venue,year,abstract,doi,arxiv_id,page_url,pdf_url,award,"
        "citation_count,reference_count,paper_type,topic,authors_json FROM papers WHERE id=?",
        (paper_id,),
    ).fetchone()
    info = dict(row)
    info["authors"] = _json(info.pop("authors_json"), [])
    info["lists"] = [
        dict(r)
        for r in conn.execute(
            "SELECT l.id AS list_id,l.name,lp.state,lp.position,lp.citation,lp.read_at "
            "FROM list_papers lp JOIN lists l ON l.id=lp.list_id WHERE lp.paper_id=? "
            "ORDER BY l.created_at,l.id",
            (paper_id,),
        )
    ]
    return info


def _body(conn, table, paper_id):
    row = conn.execute(
        f"SELECT body,written_at FROM {table} WHERE paper_id=?", (paper_id,)
    ).fetchone()
    return (row["body"], row["written_at"]) if row else (None, None)


def _annotation(conn, feature, paper_id):
    from paper_daily import annotation_content

    row = conn.execute(
        f"SELECT body_json,document_hash,written_at FROM {annotation_content.FEATURES[feature]} "
        "WHERE paper_id=?",
        (paper_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        body = annotation_content.decode(feature, row["body_json"])
    except ValueError:
        return {"unreadable": True, "written_at": row["written_at"]}
    return {**body, "document_hash": row["document_hash"], "written_at": row["written_at"]}


def _highlights(conn, paper_id):
    def mark(row):
        item = dict(row)
        item["page"] = _page(item.pop("anchor"))
        return item

    return {
        "ai_marks": _items(
            conn,
            "SELECT quote,reason,anchor FROM pdf_ai_highlights "
            "WHERE paper_id=? AND COALESCE(hidden,0)=0 ORDER BY id",
            (paper_id,),
            mark,
        ),
        "my_marks": _items(
            conn,
            "SELECT quote,anchor FROM pdf_highlights WHERE paper_id=? ORDER BY created_at,id",
            (paper_id,),
            mark,
        ),
        "analysis": _annotation(conn, "highlight_analysis", paper_id),
    }


def _context(conn, paper_id):
    row = conn.execute(
        "SELECT summary,reading_json,written_at,edited FROM paper_context WHERE paper_id=?",
        (paper_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "summary": row["summary"],
        "reading": _json(row["reading_json"], []),
        "written_at": row["written_at"],
        "edited_by_reader": bool(row["edited"]),
    }


def _citations(conn, paper_id):
    def cite(row):
        item = dict(row)
        item["contexts"] = _json(item.pop("contexts_json"), [])
        item["edited_by_reader"] = bool(item.pop("edited"))
        return item

    return _items(
        conn,
        "SELECT ref_key,title,year,venue,doi,citations,influential,purpose,gist,verdict,why,"
        "contexts_json,edited FROM cites WHERE paper_id=? ORDER BY ref_key",
        (paper_id,),
        cite,
    )


def _later_work(conn, paper_id):
    def later(row):
        item = dict(row)
        item["contexts"] = _json(item.pop("contexts_json"), [])
        item["edited_by_reader"] = bool(item.pop("edited"))
        return item

    return _items(
        conn,
        "SELECT work_id,title,year,venue,doi,arxiv_id,citations,relation,verdict,why,"
        "contexts_json,edited FROM followups WHERE paper_id=? ORDER BY citations DESC,work_id",
        (paper_id,),
        later,
    )


def _full_text(paper_id):
    name = re.sub(r"[^A-Za-z0-9._-]", "_", paper_id) + ".txt"
    path = Path(store.DB_PATH).parent / "text" / name
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _bounds(max_chars, offset):
    if type(max_chars) is not int or not 1 <= max_chars <= MAX_CHARS:
        raise ReadError("invalid_input", f"max_chars must be 1–{MAX_CHARS}")
    if type(offset) is not int or offset < 0:
        raise ReadError("invalid_input", "offset must be nonnegative")


def read_paper(paper_id, sections=None, max_chars=DEFAULT_CHARS, offset=0):
    """The chosen sections of one paper; long texts clipped to `max_chars` each."""
    if not isinstance(paper_id, str) or not paper_id.strip() or len(paper_id) > 512:
        raise ReadError("invalid_input", "paper_id must identify a saved paper")
    _bounds(max_chars, offset)
    if sections is None:
        sections = list(DEFAULT_SECTIONS)
    if (not isinstance(sections, list) or not sections
            or any(s not in SECTIONS for s in sections)):
        raise ReadError("invalid_input", "sections: choose from " + ", ".join(SECTIONS))
    if offset and len(sections) != 1:
        raise ReadError("invalid_input", "offset pages one section; name exactly one")
    out = {"paper_id": paper_id, "sections": {}}
    with store.connect(timeout=0.2) as conn:
        if conn.execute("SELECT 1 FROM papers WHERE id=?", (paper_id,)).fetchone() is None:
            raise ReadError("not_found", "Paper does not exist in this workspace")
        for section in dict.fromkeys(sections):
            if section == "paper":
                value = _paper(conn, paper_id)
            elif section in ("dive", "close_reading"):
                body, written = _body(
                    conn, "dives" if section == "dive" else "close_readings", paper_id
                )
                value = (
                    None if body is None
                    else {**_clip(body, offset, max_chars), "written_at": written}
                )
            elif section == "notes":
                value = _items(
                    conn,
                    "SELECT id,kind,body,page,created_at FROM notes WHERE paper_id=? "
                    "ORDER BY created_at,id",
                    (paper_id,),
                )
            elif section == "chat":
                value = _items(
                    conn,
                    "SELECT id,role,body,page,created_at FROM chat WHERE paper_id=? ORDER BY id",
                    (paper_id,),
                )
            elif section == "highlights":
                value = _highlights(conn, paper_id)
            elif section == "questions":
                value = _annotation(conn, "research_questions", paper_id)
            elif section == "context":
                value = _context(conn, paper_id)
            elif section == "citations":
                value = _citations(conn, paper_id)
            elif section == "later_work":
                value = _later_work(conn, paper_id)
            elif section == "resources":
                value = _items(
                    conn,
                    "SELECT url,kind,own,note,stars,license,alive FROM resources "
                    "WHERE paper_id=? ORDER BY own DESC,stars DESC,url",
                    (paper_id,),
                )
            else:
                value = _clip(_full_text(paper_id), offset, max_chars)
            out["sections"][section] = value
    return out


def list_context(list_id):
    """What a list is for and what has been written about it as a whole."""
    with store.connect(timeout=0.2) as conn:
        row = conn.execute(
            "SELECT id,name,note,created_at FROM lists WHERE id=?", (list_id,)
        ).fetchone()
        if row is None:
            raise ReadError("not_found", "List does not exist in this workspace")
        goal = conn.execute(
            "SELECT body,written_at FROM list_reading_goals WHERE list_id=?", (list_id,)
        ).fetchone()
        survey = conn.execute(
            "SELECT body,written_at,edited FROM list_surveys WHERE list_id=?", (list_id,)
        ).fetchone()
        states = dict(
            conn.execute(
                "SELECT COALESCE(state,'pending'),COUNT(*) FROM list_papers WHERE list_id=? "
                "GROUP BY 1",
                (list_id,),
            ).fetchall()
        )
    return {
        **dict(row),
        "reading_goal": dict(goal) if goal else None,
        "survey": (
            {"body": survey["body"], "written_at": survey["written_at"],
             "edited_by_reader": bool(survey["edited"])}
            if survey else None
        ),
        "states": states,
    }


def search_papers(query, list_id=None, limit=20):
    """Papers whose title, notes or Q&A mention every word of `query`."""
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        raise ReadError("invalid_input", "query must be 1–200 characters")
    if type(limit) is not int or not 1 <= limit <= SEARCH_LIMIT:
        raise ReadError("invalid_input", f"limit must be 1–{SEARCH_LIMIT}")
    words = query.split()[:8]
    like = [f"%{w.replace('%', '').replace('_', '')}%" for w in words]
    scope, args = "", []
    if list_id is not None:
        scope = " AND p.id IN (SELECT paper_id FROM list_papers WHERE list_id=?)"
        args = [list_id]
    found = {}
    with store.connect(timeout=0.2) as conn:
        title = " AND ".join("p.title LIKE ?" for _ in like)
        for r in conn.execute(
            f"SELECT p.id,p.title,p.year,p.venue FROM papers p WHERE {title}{scope} "
            "ORDER BY p.year DESC,p.id LIMIT ?",
            (*like, *args, limit),
        ):
            found[r["id"]] = {**dict(r), "matched": ["title"]}
        for table, label in (("notes", "notes"), ("chat", "chat")):
            body = " AND ".join("t.body LIKE ?" for _ in like)
            for r in conn.execute(
                f"SELECT DISTINCT p.id,p.title,p.year,p.venue FROM {table} t "
                f"JOIN papers p ON p.id=t.paper_id WHERE {body}{scope} LIMIT ?",
                (*like, *args, limit),
            ):
                found.setdefault(r["id"], {**dict(r), "matched": []})["matched"].append(label)
    return {"papers": list(found.values())[:limit]}
