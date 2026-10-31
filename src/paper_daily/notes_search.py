"""Find what you wrote or marked in any paper, and which notes point at a paper.

Every word typed must appear (LIKE rather than full-text search: Chinese has no
spaces for a tokenizer to split on, and a workspace holds thousands of notes, not
millions). A hit carries its anchor so opening it lands on the passage itself, not
only on its page.

`[[Paper title]]` in a note links to that paper, matched on the whole title with case
and spacing ignored; each paper can list the notes elsewhere that link to it.
"""

from __future__ import annotations

import json
import re

LINK = re.compile(r"\[\[([^\[\]\n]{1,300})\]\]")


def _like(term: str) -> str:
    return "%" + re.sub(r"([\\%_])", r"\\\1", term) + "%"


def _snippet(text: str, term: str, width: int = 120) -> str:
    flat = " ".join(text.split())
    at = flat.casefold().find(term.casefold())
    start = max(0, at - width // 3) if at >= 0 else 0
    cut = flat[start : start + width]
    return ("…" if start else "") + cut + ("…" if start + width < len(flat) else "")


def _page(anchor: str | None) -> int | None:
    try:
        return int(json.loads(anchor)["p0"]) + 1
    except (TypeError, ValueError, KeyError):
        return None


def search(conn, query: str, limit: int = 60) -> list[dict]:
    terms = query.split()
    if not terms:
        return []
    hits = []
    for kind, sql, text_col in (
        (
            "note",
            "SELECT n.id, n.paper_id, n.body AS text, n.page, n.anchor, n.kind AS sub, "
            "n.created_at AS at, p.title FROM notes n JOIN papers p ON p.id = n.paper_id",
            "n.body",
        ),
        (
            "highlight",
            "SELECT h.id, h.paper_id, h.quote AS text, NULL AS page, h.anchor, "
            "'mine' AS sub, h.created_at AS at, p.title FROM pdf_highlights h "
            "JOIN papers p ON p.id = h.paper_id",
            "h.quote",
        ),
    ):
        where = " AND ".join(f"{text_col} LIKE ? ESCAPE '\\'" for _ in terms)
        rows = conn.execute(
            f"{sql} WHERE {where} ORDER BY at DESC LIMIT ?", (*map(_like, terms), limit)
        ).fetchall()
        for row in rows:
            hits.append(
                {
                    "kind": kind,
                    "id": row["id"],
                    "paper_id": row["paper_id"],
                    "title": row["title"],
                    "snippet": _snippet(row["text"], terms[0]),
                    "page": row["page"] or _page(row["anchor"]),
                    "anchor": row["anchor"],
                    "ask": row["sub"] == "ask",
                    "at": row["at"] or "",
                }
            )
    hits.sort(key=lambda hit: hit["at"], reverse=True)
    return hits[:limit]


def _key(title: str) -> str:
    return " ".join(title.casefold().split())


def resolve(conn, titles: list[str]) -> dict[str, str]:
    """{title as written: paper id} for the titles that name exactly one paper."""
    wanted = {_key(t): t for t in titles}
    if not wanted:
        return {}
    found: dict[str, list[str]] = {}
    for row in conn.execute("SELECT id, title FROM papers"):
        key = _key(row["title"])
        if key in wanted:
            found.setdefault(key, []).append(row["id"])
    return {wanted[k]: ids[0] for k, ids in found.items() if len(ids) == 1}


def linked(conn, body: str) -> str:
    """The note with each resolvable `[[title]]` as a Markdown link to that paper."""
    targets = resolve(conn, [m.group(1) for m in LINK.finditer(body)])
    return LINK.sub(
        lambda m: (
            f"[{m.group(1)}](paper:{targets[m.group(1)]})" if m.group(1) in targets else m.group(0)
        ),
        body,
    )


def backlinks(conn, paper_id: str) -> list[dict]:
    """Notes in other papers that link here with `[[this paper's title]]`."""
    row = conn.execute("SELECT title FROM papers WHERE id=?", (paper_id,)).fetchone()
    if row is None:
        return []
    key = _key(row["title"])
    out = []
    for note in conn.execute(
        "SELECT n.id, n.paper_id, n.body, p.title FROM notes n JOIN papers p "
        "ON p.id = n.paper_id WHERE n.paper_id != ? AND n.body LIKE '%[[%' "
        "ORDER BY n.created_at DESC",
        (paper_id,),
    ):
        match = next((m for m in LINK.finditer(note["body"]) if _key(m.group(1)) == key), None)
        if match and resolve(conn, [match.group(1)]):
            out.append(
                {
                    "note_id": note["id"],
                    "paper_id": note["paper_id"],
                    "title": note["title"],
                    "snippet": _snippet(note["body"], match.group(0)),
                }
            )
    return out
