"""Everything the reader shows about a paper, made in one call.

A paper on a reading list is only useful once four things exist: the original, a
deep dive on the whole paper (its argument, then every section read closely --
dive.py and closeread.py together), what each of its references is doing there (承先),
and what later work did with it (啟後), summed up as a 研究脈絡. They were separate
commands run by hand -- dive-ahead, cites, followups -- so after adding ten papers
it took a while to see which of them still lacked what.

`analyse` makes whatever one paper is missing and skips what it has; `analyse_many`
runs several papers at once, because each step spends its time waiting on a model
or an API rather than computing. Each step records a failure in kv, so a paper
whose references cannot be parsed is not retried every night unless asked.

This is what the reader's 深入分析 button runs for the paper on screen, and what
`ahead` runs for the papers coming up, every night: the three were once scheduled
separately, with different budgets, so a paper could arrive explained but with an
引用 tab that only showed the handful of references already in the corpus.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from paper_daily import paper_highlights
from paper_daily.config import PDF_DIR
from paper_daily.fetch import _safe_name
from paper_daily.store import connect, get_kv, set_kv

Log = Callable[[str], None]

# What a fully analysed paper has, in the order they are made, and how the reader
# names each one.
STEPS = {"pdf": "原文", "dive": "講解", "highlights": "原文重點", "cites": "承先", "later": "啟後"}
# Read from the paper's own text: without the original they cannot start.
NEEDS_PDF = ("dive", "highlights", "cites")


def has_pdf(paper_id: str) -> bool:
    return (PDF_DIR / f"{_safe_name(paper_id)}.pdf").exists()


def status(conn, paper_id: str) -> dict[str, bool]:
    """Which parts exist. 啟後 counts once the field was asked, even if nobody cites
    the paper yet: a preprint from last month has no later work to find."""
    one = lambda sql: conn.execute(sql, (paper_id,)).fetchone() is not None  # noqa: E731
    return {
        "pdf": has_pdf(paper_id),
        # Both halves: the dive alone explains the argument but not the sections.
        "dive": one(
            "SELECT 1 FROM dives d JOIN close_readings c ON c.paper_id = d.paper_id "
            "WHERE d.paper_id=?"
        ),
        "highlights": paper_highlights.is_prepared(conn, paper_id),
        "cites": one("SELECT 1 FROM cites WHERE paper_id=? LIMIT 1"),
        "later": get_kv(conn, f"followups.checked.{paper_id}") is not None,
    }


def failed(conn, paper_id: str, step: str) -> str | None:
    """Why the last attempt at `step` made nothing, if it did."""
    return get_kv(conn, f"analyze.failed.{step}.{paper_id}")


def _record(paper_id: str, step: str, reason: str | None) -> None:
    with connect() as conn:
        set_kv(conn, f"analyze.failed.{step}.{paper_id}", reason)


def analyse(paper_id: str, log: Log = print, retry: bool = False) -> dict[str, bool]:
    """Make whatever this paper is missing. Returns the status afterwards.

    A step that failed before is skipped unless `retry`: a PDF that no source has,
    or a reference list in a format the parser cannot read, fails the same way
    every time until someone supplies the file.
    """
    from paper_daily import cites, closeread, dive, fetch, followups, resources, venues

    def todo(step: str) -> bool:
        with connect() as conn:
            have = status(conn, paper_id)[step]
            gave_up = failed(conn, paper_id, step)
        return not have and (retry or not gave_up)

    with connect() as conn:
        row = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
    if row is None:
        log(f"  no paper {paper_id}")
        return {}
    name = row["title"][:60]

    if todo("pdf"):
        path, _text = fetch.prepare(row)
        _record(paper_id, "pdf", None if path else "no source had the PDF")
        log(f"  {'PDF  ' if path else 'no PDF'}  {name}")

    # Cheap, and they read the text the PDF step just extracted.
    with connect() as conn:
        venues.refresh(conn, [paper_id], log=lambda _m: None)
        if resources.needs_check(conn, paper_id):
            resources.find(conn, paper_id)

    def explain() -> None:
        if not has_pdf(paper_id):
            return
        if todo("dive"):
            with connect() as conn:
                have = conn.execute("SELECT 1 FROM dives WHERE paper_id=?", (paper_id,))
                wrote = have.fetchone() is not None
            if not wrote:
                wrote = dive.dive_ahead(paper_id=paper_id, log=log) > 0
            reason = None if wrote else "the model did not return a dive"
            if wrote:
                with connect() as conn:
                    missing = closeread.get(conn, paper_id) is None
                if missing:
                    body, why = closeread.write(paper_id)
                    log(f"  {'逐節精讀 ' + format(len(body), ',') if body else why}  {name}")
                    reason = None if body else f"close reading: {why}"
            _record(paper_id, "dive", reason)
        if todo("highlights"):
            try:
                prepared, why = paper_highlights.prepare_reading(paper_id)
                marks = prepared.get("marks") if prepared else None
                ok = bool(marks and marks["mapped"])
                if prepared and prepared.get("explanation_pending"):
                    ok, why = False, prepared["explanation_reason"]
                if marks and not marks["mapped"]:
                    why = "重點已保留在素材中，但無法在 PDF 精確定位；請核對原文。"
                _record(paper_id, "highlights", None if ok else why)
                log(f"  原文重點 {marks['mapped']}/{marks['total']} 已同步素材  {name}"
                    if marks else f"  原文重點未完成：{why}  {name}")
            except (ValueError, OSError, RuntimeError) as exc:
                _record(paper_id, "highlights", str(exc))
                log(f"  原文重點未完成：{exc}  {name}")
        from paper_daily import research_questions

        try:
            _questions, why = research_questions.ensure(paper_id)
            log(f"  候選問題：{why}  {name}")
        except (ValueError, OSError, RuntimeError) as exc:
            log(f"  候選問題未完成：{type(exc).__name__}  {name}")

    def place() -> None:
        # The 研究脈絡 is written from the references' verdicts, so 承先 comes first.
        if has_pdf(paper_id) and todo("cites"):
            n = cites.analyse(paper_id, log=log)
            _record(paper_id, "cites", None if n else "no references could be read")
        if todo("later"):
            followups.analyse(paper_id, log=log)

    # The explanation and the citations read the same text but not each other, and
    # each spends minutes waiting on a model: side by side, the paper is ready in
    # the time of the longer one instead of the sum.
    with ThreadPoolExecutor(max_workers=2) as pool:
        chains = [pool.submit(explain), pool.submit(place)]
    for chain in chains:
        chain.result()

    with connect() as conn:
        return status(conn, paper_id)


def left(conn, paper_id: str, retry: bool = False) -> list[str]:
    """The steps still worth attempting for one paper.

    A step that failed is left out unless `retry`, and so are the steps that read
    the text when the PDF itself could not be found: otherwise a paper no source
    has would come first every night and nothing would ever be made for it.
    """
    have = status(conn, paper_id)
    gave_up = {s for s in STEPS if failed(conn, paper_id, s)}
    if not have["pdf"] and "pdf" in gave_up:
        gave_up.update(NEEDS_PDF)
    return [s for s, ok in have.items() if not ok and (retry or s not in gave_up)]


def pending(conn, paper_ids: list[str], retry: bool = False) -> list[str]:
    """The papers with something left to make."""
    return [pid for pid in paper_ids if left(conn, pid, retry)]


def upcoming(conn, count: int, list_id: str | None = None, scan: int = 300) -> list[str]:
    """The next `count` papers, in reading order, that still lack part of the analysis.

    Unread only: a paper already read was read without it, and the button is there
    when one is reopened. `list_id` takes a reading list, or 'all' for every list
    in turn; without it, the main queue.
    """
    if list_id:
        scope = "" if list_id == "all" else "AND lp.list_id = ? "
        rows = conn.execute(
            "SELECT lp.paper_id FROM list_papers lp "
            f"WHERE lp.state IN ('pending', 'delivered') {scope}"
            "GROUP BY lp.paper_id ORDER BY MIN(lp.list_id), MIN(lp.position) LIMIT ?",
            (*(() if list_id == "all" else (list_id,)), scan),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT paper_id FROM queue WHERE state IN ('pending', 'delivered') "
            "ORDER BY rank LIMIT ?",
            (scan,),
        ).fetchall()
    out = []
    for r in rows:
        if left(conn, r[0]):
            out.append(r[0])
            if len(out) == count:
                break
    return out


def ahead(count: int, list_id: str | None = None, jobs: int = 2, log: Log = print) -> int:
    """Analyse the next few papers before they are reached. Returns how many came
    out complete."""
    with connect() as conn:
        ids = upcoming(conn, count, list_id)
    if not ids:
        log("nothing to analyse: the papers coming up already have all they can get")
        return 0
    return analyse_many(ids, jobs=jobs, log=log)


def summary(state: dict[str, bool]) -> str:
    """"原文✓ 講解✓ 承先✗ 啟後✓", for a progress line."""
    return " ".join(f"{STEPS[s]}{'✓' if ok else '✗'}" for s, ok in state.items())


def analyse_many(paper_ids: list[str], jobs: int = 3, log: Log = print,
                 retry: bool = False) -> int:
    """Analyse several papers at once. Returns how many came out complete.

    Each worker takes a whole paper, so one paper's steps stay in order (its dive
    and reference analysis read the PDF its first step fetched).
    """
    with connect() as conn:
        todo = pending(conn, paper_ids, retry)
    if not todo:
        log("nothing to analyse: every paper has all it can get")
        return 0
    log(f"analysing {len(todo)} paper(s), {jobs} at a time")
    complete = 0
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {pool.submit(analyse, pid, log, retry): pid for pid in todo}
        for done, future in enumerate(as_completed(futures), 1):
            pid = futures[future]
            try:
                state = future.result()
            except Exception as e:  # one paper's failure must not stop the rest
                log(f"[{done}/{len(todo)}] failed {pid}: {e}")
                continue
            complete += all(state.values())
            with connect() as conn:
                title = conn.execute("SELECT title FROM papers WHERE id=?", (pid,)).fetchone()[0]
            log(f"[{done}/{len(todo)}] {summary(state)}  {title[:60]}")
    return complete
