"""How often the 深入分析 runs on its own, how much it does, and whether to say so.

Task Scheduler still fires every night; the settings decide whether tonight is a
night to analyse. Re-registering the task for every change would need an elevated
prompt the app cannot answer, and a skipped night costs nothing.

What a run finished is kept as a batch, so the reader can say "these are ready"
the next time it is looked at, once, and only if asked to.
"""

from __future__ import annotations

from datetime import date, datetime

from paper_daily.store import connect, get_kv, now, set_kv

KEY = "analysis.schedule"
LAST_RUN = "analysis.schedule.last_run"
BATCH = "analysis.batch"
SEEN = "analysis.batch.seen"

# Days between runs; 0 is "only when I press 深入分析".
EVERY = {1: "每晚", 2: "每兩天", 7: "每週", 0: "只在我按的時候"}
DEFAULTS = {"every": 1, "queue": 4, "lists": 3, "notify": True}
MAX_PAPERS = 20


def load(conn) -> dict:
    stored = get_kv(conn, KEY, {}) or {}
    settings = dict(DEFAULTS)
    if stored.get("every") in EVERY:
        settings["every"] = stored["every"]
    for key in ("queue", "lists"):
        if isinstance(stored.get(key), int):
            settings[key] = max(0, min(MAX_PAPERS, stored[key]))
    if isinstance(stored.get("notify"), bool):
        settings["notify"] = stored["notify"]
    return settings


def save(conn, settings: dict) -> dict:
    set_kv(conn, KEY, {key: settings[key] for key in DEFAULTS})
    return load(conn)


def due(settings: dict, last_run: str | None, today: date) -> bool:
    if not settings["every"] or not (settings["queue"] or settings["lists"]):
        return False
    if not last_run:
        return True
    return (today - date.fromisoformat(last_run[:10])).days >= settings["every"]


def describe(settings: dict, last_run: str | None, today: date) -> str:
    """One line for the settings dialog: what will happen and when."""
    if not settings["every"]:
        return "不會自動分析；只有按「深入分析」的論文才會分析。"
    if not (settings["queue"] or settings["lists"]):
        return "每次分析設為 0 篇，所以不會自動分析。"
    parts = []
    if settings["queue"]:
        parts.append(f"主佇列接下來 {settings['queue']} 篇")
    if settings["lists"]:
        parts.append(f"清單裡 {settings['lists']} 篇")
    what = "、".join(parts)
    if not last_run:
        return f"今晚 00:00 會分析{what}。"
    days = (today - date.fromisoformat(last_run[:10])).days
    wait = settings["every"] - days
    when = "今晚" if wait <= 1 else f"{wait} 天後"
    return f"上次在 {last_run[:10]} 自動分析；{when} 00:00 會分析{what}。"


def run(jobs: int = 2, log=print, today: date | None = None) -> list[str] | None:
    """The scheduled 深入分析. Returns the papers it completed, or None when tonight
    is not a night to run."""
    from paper_daily import analyze

    today = today or datetime.now().date()
    with connect() as conn:
        settings = load(conn)
        if not due(settings, get_kv(conn, LAST_RUN), today):
            log(f"not due: {EVERY[settings['every']]}, {settings['queue']} + "
                f"{settings['lists']} paper(s)")
            return None
        ids = analyze.upcoming(conn, settings["queue"]) if settings["queue"] else []
        if settings["lists"]:
            ids += [
                pid for pid in analyze.upcoming(conn, settings["lists"], "all")
                if pid not in ids
            ]
    if ids:
        analyze.analyse_many(ids, jobs=jobs, log=log)
    with connect() as conn:
        complete = [pid for pid in ids if all(analyze.status(conn, pid).values())]
        set_kv(conn, LAST_RUN, today.isoformat())
        if complete:
            set_kv(conn, BATCH, {"at": now(), "ids": complete})
    log(f"scheduled analysis: {len(complete)} of {len(ids)} paper(s) complete")
    return complete


def unseen(conn) -> list[str]:
    """The last batch's papers, if the reader has not announced them yet and is
    meant to."""
    batch = get_kv(conn, BATCH)
    if not batch or not load(conn)["notify"] or get_kv(conn, SEEN) == batch["at"]:
        return []
    return batch["ids"]


def mark_seen(conn) -> None:
    batch = get_kv(conn, BATCH)
    if batch:
        set_kv(conn, SEEN, batch["at"])
