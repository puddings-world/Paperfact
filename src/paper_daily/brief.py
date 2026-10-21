"""Assemble the briefing pack that the nightly session turns into a deep dive.

Division of labour: Python decides *which* paper and gathers everything needed to
discuss it -- metadata, ranking rationale, lineage, what has already been read, and
the full extracted text. The explanation itself is written by the scheduled Claude
session reading this pack, because that is the part that needs judgement.

Keeping the selection deterministic and in the database means the reading order
survives across sessions, machines, and any given night's run failing.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from paper_daily import queue as qmod
from paper_daily.config import BRIEF_DIR, ensure_dirs
from paper_daily.fetch import prepare
from paper_daily.sources import virtual_site
from paper_daily.store import now


def _safe(paper_id: str) -> str:
    """Paper id as a filename, so a pack and its deep dive can be paired by name."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", paper_id)


def _fmt_authors(authors_json: str | None, limit: int = 8) -> str:
    try:
        names = json.loads(authors_json or "[]")
    except json.JSONDecodeError:
        return "unknown"
    if not names:
        return "unknown"
    if len(names) > limit:
        return ", ".join(names[:limit]) + f", and {len(names) - limit} more"
    return ", ".join(names)


def _why_ranked(row: sqlite3.Row) -> str:
    """Explain the paper's position in plain terms, from the stored score parts."""
    try:
        parts = json.loads(row["score_parts_json"] or "{}")
    except json.JSONDecodeError:
        parts = {}
    bits = []
    if row["award"]:
        bits.append(f"{row['award']} at {row['venue']} {row['year']}")
    if row["citation_count"] is not None:
        age = max(datetime.now(UTC).year - row["year"], 1)
        bits.append(f"{row['citation_count']} citations (~{row['citation_count'] / age:.0f}/yr)")
    if row["author_strength"]:
        bits.append(f"strongest author h-index {int(row['author_strength'])}")
    if row["paper_type"]:
        bits.append(f"classified {row['paper_type']}")
    if row["is_canon"]:
        bits.append("on the canon list (guaranteed reading)")
    if parts:
        top = max(parts, key=lambda k: parts[k])
        bits.append(f"strongest signal: {top}")
    return "; ".join(bits) or "no ranking signals available"


def _dive_gist(conn: sqlite3.Connection, paper_id: str) -> str | None:
    """The one-line conclusion from a paper's stored deep dive.

    Lets tonight's explanation pick up where an earlier one left off instead of
    treating every paper as if it were the first thing ever read.
    """
    row = conn.execute("SELECT body FROM dives WHERE paper_id=?", (paper_id,)).fetchone()
    if not row:
        return None
    lines = (row["body"] or "").splitlines()
    for i, line in enumerate(lines):
        if line.strip().lstrip("#").strip() == "一句話結論":
            for follow in lines[i + 1 :]:
                if follow.strip() and not follow.startswith("#"):
                    return follow.strip()
            break
    body = [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]
    return body[0] if body else None


def _lineage_context(conn: sqlite3.Connection, paper_id: str) -> str:
    ancestors = conn.execute(
        "SELECT p.id, p.title, p.venue, p.year, q.state FROM refs r "
        "JOIN papers p ON p.id = r.ref_paper_id "
        "LEFT JOIN queue q ON q.paper_id = p.id "
        "WHERE r.paper_id = ? ORDER BY r.influential DESC, p.score DESC LIMIT 8",
        (paper_id,),
    ).fetchall()
    descendants = conn.execute(
        "SELECT p.title, p.venue, p.year FROM refs r "
        "JOIN papers p ON p.id = r.paper_id "
        "WHERE r.ref_paper_id = ? ORDER BY p.score DESC LIMIT 5",
        (paper_id,),
    ).fetchall()

    lines = []
    if ancestors:
        lines.append("**Builds on (already in the corpus):**")
        for a in ancestors:
            mark = " [read]" if a["state"] == "read" else ""
            lines.append(f"- {a['title']} ({a['venue']} {a['year']}){mark}")
            gist = _dive_gist(conn, a["id"]) if a["state"] == "read" else None
            if gist:
                # What the reader was told about that paper, so tonight's dive can
                # connect to it by name rather than re-deriving the background.
                lines.append(f"  - 當時的結論:{gist}")
    if descendants:
        lines.append("")
        lines.append("**Later work in the corpus that cites it:**")
        for d in descendants:
            lines.append(f"- {d['title']} ({d['venue']} {d['year']})")
    return "\n".join(lines) or "_No in-corpus lineage recorded yet._"


def _recent_reading(conn: sqlite3.Connection, limit: int = 8) -> str:
    """What has been read lately, each with what it was said to establish.

    Carrying the conclusions, not just the titles, is what lets tonight's
    explanation build on the last one instead of restarting from nothing.
    """
    rows = conn.execute(
        "SELECT p.id, p.title, p.venue, p.year, q.read_at, q.delivered_at FROM queue q "
        "JOIN papers p ON p.id = q.paper_id WHERE q.state IN ('read','delivered') "
        "ORDER BY COALESCE(q.read_at, q.delivered_at) DESC LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        return "_Nothing read yet -- this is the first paper._"
    out = []
    for r in rows:
        out.append(f"- {r['title']} ({r['venue']} {r['year']})")
        gist = _dive_gist(conn, r["id"])
        if gist:
            out.append(f"  - {gist}")
    return "\n".join(out)


_CAPTION_PREFIX = re.compile(r"^(Figure|Fig\.|Table)\s+\d+[a-z]?\s*[:.]\s*", re.I)


def _exhibits(paper_id: str, pdf_path: Path | None) -> str:
    """The paper's figure and table captions, numbered as the paper numbers them.

    The full text carries captions inline, buried in tens of thousands of words, and
    an explanation that says "the ablation shows" without naming the exhibit cannot be
    checked against the 圖表 tab. Listed separately, the dive can point at Figure 5 and
    the reader can look at Figure 5.
    """
    if not pdf_path:
        return "_No local PDF, so no figures could be extracted._"
    try:
        from paper_daily.figures import extract

        found = extract(paper_id, pdf_path)
    except Exception:
        return "_Figure extraction failed._"
    if not found:
        return "_No captioned figures or tables found in this PDF._"

    lines = []
    for fig in found[:40]:
        # The caption still carries its own "Figure 1:" prefix, which would read twice.
        caption = _CAPTION_PREFIX.sub("", fig.caption)
        if len(caption) > 240:
            caption = caption[:237] + "..."
        lines.append(f"- **{fig.label}** (p{fig.page}) {caption}")
    if len(found) > 40:
        lines.append(f"- _...and {len(found) - 40} more._")
    return "\n".join(lines)


PACK_TEMPLATE = """# Briefing pack: {title}

- **Paper id:** `{paper_id}`
- **Venue:** {venue} {year}{award}
- **Authors:** {authors}
- **Paper page:** {page_url}
- **PDF:** {pdf_url}
- **Local PDF:** {local_pdf}
- **Queue role:** {role}{reason}
- **Why this paper is here:** {why}

## Abstract

{abstract}

## Figures and tables

{exhibits}

## Lineage

{lineage}

## Recently read

{recent}

---

## Full text

{body}
"""


def _backfill_from_conference_page(conn: sqlite3.Connection, row: sqlite3.Row) -> sqlite3.Row:
    """Fill missing authors/abstract from the conference's own paper page.

    The newest conference year is not in Semantic Scholar yet -- ICLR 2026 matched
    18 of 5468 papers -- so without this the first papers the reader ever sees would
    arrive with no authors and no abstract. One request, and only for a paper that
    is actually being delivered.
    """
    needs_authors = row["authors_json"] in (None, "", "[]")
    if not needs_authors and row["abstract"]:
        return row
    page = row["page_url"] or ""
    if "/virtual/" not in page:
        return row

    detail = virtual_site.fetch_paper_detail(page)
    if not detail:
        return row

    conn.execute(
        "UPDATE papers SET "
        "authors_json = CASE WHEN authors_json IN ('','[]') OR authors_json IS NULL "
        "               THEN COALESCE(?, authors_json) ELSE authors_json END, "
        "abstract = COALESCE(abstract, ?), topic = COALESCE(topic, ?) WHERE id = ?",
        (
            json.dumps(detail["authors"], ensure_ascii=False) if detail.get("authors") else None,
            detail.get("abstract"),
            detail.get("keywords"),
            row["id"],
        ),
    )
    refreshed = conn.execute(
        "SELECT p.*, q.role, q.reason FROM papers p JOIN queue q ON q.paper_id = p.id "
        "WHERE p.id = ?",
        (row["id"],),
    ).fetchone()
    return refreshed or row


def pack_text(conn: sqlite3.Connection, row: sqlite3.Row) -> tuple[str, Path | None]:
    """The briefing pack as text, plus the local PDF if one was fetched.

    Split out from build_pack so a dive can be generated for a paper without
    delivering it: writing the file and logging the delivery are what consume the
    queue, and reading ahead must not.
    """
    row = _backfill_from_conference_page(conn, row)
    pdf_path, body = prepare(row)
    if not body:
        body = (
            "_Full text unavailable -- the PDF could not be fetched or parsed. "
            "Work from the abstract and the linked paper page._"
        )
    columns = set(row.keys())
    text = PACK_TEMPLATE.format(
        paper_id=row["id"],
        title=row["title"],
        venue=row["venue"],
        year=row["year"],
        award=f" ({row['award']})" if row["award"] else "",
        authors=_fmt_authors(row["authors_json"]),
        page_url=row["page_url"] or "n/a",
        pdf_url=row["pdf_url"] or "n/a",
        local_pdf=str(pdf_path) if pdf_path else "not downloaded",
        # A sqlite3.Row is not a mapping, so membership has to go through keys().
        # Reading ahead passes a row with no queue columns joined on.
        role=row["role"] if "role" in columns else "main",
        reason=f" -- {row['reason']}" if "reason" in columns and row["reason"] else "",
        why=_why_ranked(row),
        abstract=row["abstract"] or "_No abstract on record._",
        exhibits=_exhibits(row["id"], pdf_path),
        lineage=_lineage_context(conn, row["id"]),
        recent=_recent_reading(conn),
        body=body,
    )
    return text, pdf_path


def build_pack(conn: sqlite3.Connection, row: sqlite3.Row) -> Path:
    """Write the pack for one paper and return its path."""
    ensure_dirs()
    # Local date, not UTC: the nightly job fires at 00:00 local, which in UTC+8 is
    # still the previous UTC day, so a UTC folder name put tonight's paper in
    # yesterday's directory alongside a paper already delivered there.
    day = datetime.now().astimezone().strftime("%Y-%m-%d")
    outdir = BRIEF_DIR / day
    outdir.mkdir(parents=True, exist_ok=True)

    text, _ = pack_text(conn, row)
    path = outdir / f"{_safe(row['id'])}-pack.md"
    path.write_text(text, encoding="utf-8")

    conn.execute(
        "INSERT INTO reading_log(paper_id, delivered_at, brief_path, role) VALUES (?,?,?,?)",
        (row["id"], now(), str(path), row["role"]),
    )
    return path


def deliver_next(conn: sqlite3.Connection) -> tuple[sqlite3.Row, Path] | None:
    """Pop the next paper, build its pack, and mark it delivered."""
    rows = qmod.next_papers(conn, 1)
    if not rows:
        return None
    row = rows[0]
    path = build_pack(conn, row)
    qmod.mark(conn, row["id"], "delivered")
    return row, path
