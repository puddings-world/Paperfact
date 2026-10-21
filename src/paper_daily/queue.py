"""Build and serve the reading queue.

Order is year-block descending, importance descending inside each block: you finish
the papers that mattered from 2026 before starting 2025. Each year gets the same
quota so a year's block takes a predictable number of days regardless of how many
papers that conference happened to accept.

Two things break the pure ordering on purpose:
  * canon papers are injected on a fixed cadence, so foundational work arrives early
    instead of waiting years for its year-block;
  * after a paper is delivered, its references that are already in the corpus get
    pulled forward as companions, so reading follows the lineage of an idea rather
    than a flat list.
"""

from __future__ import annotations

import sqlite3

from paper_daily.config import SETTINGS
from paper_daily.rank.canon import canon_index
from paper_daily.store import now

# Rank is sortable ascending. Year block dominates; score orders within the block.
YEAR_BLOCK = 1_000_000

# Roles the ranking did not put there and must not take away: a reference pulled
# forward from the lineage block, and a paper added by hand.
PINNED_ROLES = ("companion", "manual")
PINNED_SQL = "('" + "','".join(PINNED_ROLES) + "')"


def _rank(year: int, max_year: int, score: float) -> float:
    return (max_year - year) * YEAR_BLOCK + (1.0 - min(max(score, 0.0), 1.0)) * 1000


def build(conn: sqlite3.Connection, per_year: int | None = None) -> dict[str, int]:
    """(Re)build the pending part of the queue. Papers already read or delivered keep
    their state -- rebuilding after a re-crawl must never re-serve old papers."""
    # The main queue is the three conferences and nothing else. Imported reading
    # lists put their papers in the same table -- NAACL, CVPR, arXiv-only and so on --
    # and without this they would be ranked into the nightly queue on the next rebuild.
    row = conn.execute(
        "SELECT MAX(year) AS y FROM papers WHERE score IS NOT NULL AND venue IN "
        "('ICLR','ICML','NeurIPS')"
    ).fetchone()
    if not row or row["y"] is None:
        return {"queued": 0, "canon": 0}
    max_year = row["y"]

    years = [
        r["year"]
        for r in conn.execute(
            "SELECT DISTINCT year FROM papers WHERE score IS NOT NULL "
            "AND venue IN ('ICLR','ICML','NeurIPS') ORDER BY year DESC"
        )
    ]
    quota = per_year or max(1, SETTINGS.queue_target // max(len(years), 1))

    # Everything the ranking produced is rebuilt from scratch, but rows someone put
    # there deliberately are not the ranking's to delete. A companion pulled forward
    # from the lineage block, or a paper added by hand, used to vanish at the next
    # rebuild -- or worse, survive at a rank the rebuild then overwrote, which made
    # "move to the front of the queue" look like it had done nothing.
    conn.execute("DELETE FROM queue WHERE state='pending' AND role NOT IN " + PINNED_SQL)
    pinned = {
        r["paper_id"]
        for r in conn.execute("SELECT paper_id FROM queue WHERE role IN " + PINNED_SQL)
    }
    kept = {r["paper_id"] for r in conn.execute("SELECT paper_id FROM queue")}

    queued = 0
    for year in years:
        rows = conn.execute(
            "SELECT id, year, score FROM papers WHERE year=? AND score IS NOT NULL "
            "AND venue IN ('ICLR','ICML','NeurIPS') "
            "ORDER BY score DESC, citation_count DESC, id LIMIT ?",
            (year, quota),
        ).fetchall()

        # A paper that has been read or delivered must be ranked alongside the rest,
        # even if fresh scores pushed it out of this year's quota. Leaving it at its
        # old rank was a real bug: enrichment shifts every percentile, so the newly
        # ranked papers moved to ~244 while an already-read paper sat at 400 and sank
        # from the top of the list to the middle of nowhere.
        ranked_ids = {r["id"] for r in rows}
        stragglers = conn.execute(
            "SELECT p.id, p.year, p.score FROM queue q JOIN papers p ON p.id = q.paper_id "
            "WHERE p.year = ? AND p.score IS NOT NULL AND q.state != 'pending'",
            (year,),
        ).fetchall()
        rows = list(rows) + [r for r in stragglers if r["id"] not in ranked_ids]
        rows.sort(key=lambda r: -r["score"])

        # The newest year has no citations and no author h-index yet, so every oral
        # principle paper scores identically. Without a tiebreak those ties resolve
        # in whatever order SQLite feels like, and the reading order for the year the
        # reader starts on would shuffle on every rebuild. The fetch position is
        # already score-then-citations ordered, so fold it in as a stable minor key.
        inserts, reranks = [], []
        for idx, r in enumerate(rows):
            if r["id"] in pinned:
                continue
            rank = _rank(r["year"], max_year, r["score"]) + idx * 1e-4
            if r["id"] in kept:
                reranks.append((rank, r["id"]))
            else:
                inserts.append((r["id"], rank, "pending", "main", now()))

        conn.executemany(
            "INSERT OR IGNORE INTO queue(paper_id, rank, state, role, queued_at) "
            "VALUES (?,?,?,?,?)",
            inserts,
        )
        conn.executemany("UPDATE queue SET rank=? WHERE paper_id=?", reranks)
        queued += len(inserts)

    n_canon = _inject_canon(conn, kept)
    return {"queued": queued, "canon": n_canon}


def _inject_canon(conn: sqlite3.Connection, kept: set[str]) -> int:
    """Interleave canon papers into the queue, one every `canon_every_n` positions.

    Ranks are chosen against the queue that actually exists rather than computed from
    the score scale. An earlier version placed the i-th canon paper at rank i*1000,
    which looked like a cadence but sat past the entire newest-year block (whose ranks
    run 0..1000) -- so all forty canon papers queued up behind a year's worth of
    reading instead of arriving every couple of weeks.
    """
    index = canon_index()
    if not index:
        return 0
    keys = list(index)
    placeholders = ",".join("?" for _ in keys)
    rows = conn.execute(
        f"SELECT id, title_key FROM papers WHERE title_key IN ({placeholders})",
        keys,
    ).fetchall()

    # Preserve the curated order of CANON rather than corpus order.
    order = {k: i for i, k in enumerate(keys)}
    rows = sorted(rows, key=lambda r: order.get(r["title_key"], 1e9))
    rows = [r for r in rows if r["id"] not in kept]
    if not rows:
        return 0

    # A canon paper that also earned its way in on score is moved, not duplicated.
    canon_ids = [r["id"] for r in rows]
    conn.execute(
        f"DELETE FROM queue WHERE state='pending' AND paper_id IN "
        f"({','.join('?' for _ in canon_ids)})",
        canon_ids,
    )

    every = max(1, SETTINGS.weights.canon_every_n)
    n = 0
    for i, r in enumerate(rows):
        position = (i + 1) * every
        window = conn.execute(
            "SELECT rank FROM queue WHERE state='pending' ORDER BY rank LIMIT 2 OFFSET ?",
            (position - 1,),
        ).fetchall()
        if not window:
            break  # queue shorter than the cadence needs; the rest wait for a rebuild
        lo = window[0]["rank"]
        hi = window[1]["rank"] if len(window) > 1 else lo + 1.0
        rank = lo + (hi - lo) / 2 if hi > lo else lo + 1e-5

        _, _, _, why = index[r["title_key"]]
        conn.execute(
            "INSERT OR IGNORE INTO queue(paper_id, rank, state, role, reason, queued_at) "
            "VALUES (?,?,?,?,?,?)",
            (r["id"], float(rank), "pending", "canon", why, now()),
        )
        n += 1
    return n


def next_papers(conn: sqlite3.Connection, n: int = 1) -> list[sqlite3.Row]:
    """The next n unread papers, without changing any state."""
    return conn.execute(
        "SELECT p.*, q.rank, q.role, q.reason FROM queue q JOIN papers p ON p.id=q.paper_id "
        "WHERE q.state='pending' ORDER BY q.rank LIMIT ?",
        (n,),
    ).fetchall()


def mark(conn: sqlite3.Connection, paper_id: str, state: str) -> None:
    col = {"delivered": "delivered_at", "read": "read_at"}.get(state)
    sql = f"UPDATE queue SET state=?{', ' + col + '=?' if col else ''} WHERE paper_id=?"
    args = (state, now(), paper_id) if col else (state, paper_id)
    conn.execute(sql, args)


def add(
    conn: sqlite3.Connection,
    paper_id: str,
    reason: str = "你自己加進來的",
    front: bool = True,
) -> bool:
    """Put a corpus paper into the reading queue by hand.

    The ranking decides what is worth reading in general; it cannot know that you
    need this one next week. Role 'manual' is what keeps the row through the nightly
    rebuild, and what stops the rebuild from overwriting the rank chosen here.

    A paper already in the queue is moved, not duplicated, and one that was skipped
    comes back -- "add it again" is the obvious way to undo a removal.
    """
    if not conn.execute("SELECT 1 FROM papers WHERE id=?", (paper_id,)).fetchone():
        return False
    edge = conn.execute("SELECT MIN(rank) FROM queue WHERE state != 'skipped'").fetchone()[0]
    rank = (edge or 0.0) - 1.0 if front else (edge or 0.0) + 1.0
    conn.execute(
        "INSERT INTO queue(paper_id, rank, state, role, reason, queued_at) "
        "VALUES (?,?,'pending','manual',?,?) "
        "ON CONFLICT(paper_id) DO UPDATE SET rank=excluded.rank, role='manual', "
        "reason=excluded.reason, "
        # A read paper stays read: re-adding it is about where it sits, not about
        # pretending it was never read.
        "state=CASE WHEN queue.state='skipped' THEN 'pending' ELSE queue.state END",
        (paper_id, rank, reason, now()),
    )
    return True


def remove(conn: sqlite3.Connection, paper_id: str) -> bool:
    """Take a paper out of the reading queue.

    Skipped rather than deleted: the row carries whether it was read and when, and a
    delete would also invite the next rebuild to queue it again as if it were new.
    """
    cur = conn.execute(
        "UPDATE queue SET state='skipped' WHERE paper_id=? AND state != 'skipped'",
        (paper_id,),
    )
    return bool(cur.rowcount)


def add_companions(conn: sqlite3.Connection, paper_id: str, limit: int = 2) -> list[str]:
    """Pull this paper's in-corpus references forward as companion reading."""
    rows = conn.execute(
        "SELECT r.ref_paper_id AS rid, p.title, p.score, r.influential "
        "FROM refs r JOIN papers p ON p.id=r.ref_paper_id "
        "WHERE r.paper_id=? AND r.ref_paper_id NOT IN "
        "  (SELECT paper_id FROM queue WHERE state IN ('read','delivered')) "
        "ORDER BY r.influential DESC, p.score DESC LIMIT ?",
        (paper_id, limit),
    ).fetchall()
    parent_rank = conn.execute("SELECT rank FROM queue WHERE paper_id=?", (paper_id,)).fetchone()
    base = parent_rank["rank"] if parent_rank else 0.0

    out = []
    for i, r in enumerate(rows):
        conn.execute(
            "INSERT INTO queue(paper_id, rank, state, role, parent_id, reason, queued_at) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(paper_id) DO UPDATE SET rank=excluded.rank, role='companion', "
            "parent_id=excluded.parent_id, reason=excluded.reason "
            "WHERE queue.state='pending'",
            (
                r["rid"],
                base + 0.1 * (i + 1),
                "pending",
                "companion",
                paper_id,
                "referenced by the paper you just read",
                now(),
            ),
        )
        out.append(r["rid"])
    return out


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT state, COUNT(*) AS n FROM queue GROUP BY state").fetchall()
    return {r["state"]: r["n"] for r in rows}
