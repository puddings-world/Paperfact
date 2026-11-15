"""The paper the nightly run delivered, and the question it leaves for the reader.

The run does not spend model calls on its own unless the 分析排程 says so. What it
can do is say which paper it delivered, so the reader opens on that one whatever
list was on screen, and asks once whether to analyse it now: some nights there is
no time to read it, and that is the reader's call to make.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from paper_daily.store import get_kv, now, set_kv

KEY = "nightly.tonight"
ANSWERED = "nightly.tonight.answered"
# A delivery older than this is last night's: the next run has not happened, and
# opening or asking about it now would be a surprise rather than tonight's paper.
FRESH = timedelta(hours=24)


def record(conn, paper_id: str) -> None:
    set_kv(conn, KEY, {"at": now(), "id": paper_id})


def _latest(conn, at: datetime | None = None) -> dict | None:
    kept = get_kv(conn, KEY)
    if not isinstance(kept, dict) or not kept.get("id") or not kept.get("at"):
        return None
    try:
        delivered = datetime.fromisoformat(kept["at"])
    except (TypeError, ValueError):
        return None
    if (at or datetime.now(UTC)) - delivered > FRESH:
        return None
    return kept


def paper(conn, at: datetime | None = None) -> str | None:
    """The paper to open on, if the run delivered one within the last day."""
    kept = _latest(conn, at)
    if not kept:
        return None
    exists = conn.execute("SELECT 1 FROM papers WHERE id=?", (kept["id"],)).fetchone()
    return kept["id"] if exists else None


def offer(conn, at: datetime | None = None) -> str | None:
    """The paper to ask about: tonight's, not yet answered for, and unexplained."""
    kept = _latest(conn, at)
    if not kept or get_kv(conn, ANSWERED) == kept["at"]:
        return None
    unexplained = conn.execute(
        "SELECT 1 FROM papers p WHERE p.id=? "
        "AND NOT EXISTS (SELECT 1 FROM dives WHERE paper_id=p.id)",
        (kept["id"],),
    ).fetchone()
    return kept["id"] if unexplained else None


def answer(conn) -> None:
    """The reader said yes or no; either way tonight's question is not asked again."""
    kept = get_kv(conn, KEY)
    if isinstance(kept, dict) and kept.get("at"):
        set_kv(conn, ANSWERED, kept["at"])
