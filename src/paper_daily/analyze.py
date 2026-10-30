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

from paper_daily import paper_highlights, work_progress
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


def status(conn, paper_id: str, *, verify_sources: bool = False) -> dict[str, bool]:
    """Which parts have completion evidence, rather than merely some stored rows."""
    from paper_daily import cites, followups

    one = lambda sql: conn.execute(sql, (paper_id,)).fetchone() is not None  # noqa: E731
    return {
        "pdf": has_pdf(paper_id),
        # Both halves: the dive alone explains the argument but not the sections.
        "dive": one(
            "SELECT 1 FROM dives d JOIN close_readings c ON c.paper_id = d.paper_id "
            "WHERE d.paper_id=?"
        ),
        "highlights": paper_highlights.is_prepared(conn, paper_id),
        "cites": cites.complete(conn, paper_id, verify_source=verify_sources),
        "later": followups.done(conn, paper_id),
    }


def failed(conn, paper_id: str, step: str) -> str | None:
    """Why the last attempt at `step` made nothing, if it did."""
    return get_kv(conn, f"analyze.failed.{step}.{paper_id}")


def _record(paper_id: str, step: str, reason: str | None) -> None:
    with connect() as conn:
        set_kv(conn, f"analyze.failed.{step}.{paper_id}", reason)


def analyse(
    paper_id: str, log: Log = print, retry: bool = False, *, database=None, connections=None
) -> dict[str, bool]:
    from paper_daily import llm, research_job_lock, store

    database = (database or store.DB_PATH).resolve()
    connections = connections or llm.capture_connections()
    with (
        research_job_lock.claim(database, "analysis", paper_id) as acquired,
        llm.connection_scope(connections),
    ):
        if not acquired:
            log("Paper analysis is already in progress")
            return {step: False for step in STEPS}
        return _analyse(paper_id, log, retry, database, connections)


def _analyse(paper_id, log, retry, database, connections) -> dict[str, bool]:
    """Make whatever this paper is missing. Returns the status afterwards.

    A step that failed before is skipped unless `retry`: a PDF that no source has,
    or a reference list in a format the parser cannot read, fails the same way
    every time until someone supplies the file.
    """
    import sqlite3
    from contextlib import closing, contextmanager

    from paper_daily import cites, closeread, dive, fetch, followups, llm, resources, store, venues
    from paper_daily import research_generation as generation
    from paper_daily.research_lifecycle import ensure_lifecycle, parent_lifecycle

    @contextmanager
    def scoped_connection():
        with closing(generation._connect(database)) as connection, connection:
            yield connection

    with scoped_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
        identity, binding = generation._identity(database), generation._binding(conn)
        lifecycle = parent_lifecycle(conn, "paper", paper_id)

    def belongs():
        try:
            with scoped_connection() as conn:
                return (
                    generation._identity(database) == identity
                    and generation._binding(conn) == binding
                    and parent_lifecycle(conn, "paper", paper_id) == lifecycle
                )
        except (OSError, ValueError, sqlite3.DatabaseError):
            return False

    def current():
        return store.DB_PATH.resolve() == database and belongs()

    def record(step, reason):
        with scoped_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if (
                generation._identity(database) == identity
                and generation._binding(conn) == binding
                and parent_lifecycle(conn, "paper", paper_id) == lifecycle
            ):
                set_kv(conn, f"analyze.failed.{step}.{paper_id}", reason)

    def invoke(producer, *args, **kwargs):
        # Existing integrations may replace a producer with its older, narrower
        # callable interface. Pass the explicit scope whenever it is supported;
        # never catch a TypeError raised inside the producer and rerun it.
        import inspect

        parameters = inspect.signature(producer).parameters
        variadic = any(p.kind == p.VAR_KEYWORD for p in parameters.values())
        if "overview_too" not in parameters and not variadic:
            kwargs.pop("overview_too", None)
        for name, value in (("database", database), ("connections", connections)):
            if name in parameters or variadic:
                kwargs[name] = value
        return producer(*args, **kwargs)

    def todo(step: str) -> bool:
        if not current():
            return False
        with scoped_connection() as conn:
            have = status(conn, paper_id, verify_sources=True)[step]
            gave_up = failed(conn, paper_id, step)
        return not have and (retry or not gave_up)

    with scoped_connection() as conn:
        row = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
    if row is None:
        log(f"  no paper {paper_id}")
        return {}
    name = row["title"][:60]

    work_progress.report("取得原文與擷取文字", paper_id=paper_id)
    if todo("pdf"):
        path, _text = fetch.prepare(row)
        record("pdf", None if path else "no source had the PDF")
        log(f"  {'PDF  ' if path else 'no PDF'}  {name}")

    # Pin the original source before any remote explanation/citation work. A
    # later PDF replacement must not silently become this operation's authority.
    from paper_daily.document_reader import from_workspace
    from paper_daily.manual_highlight_ops import capture_owner

    source_root = PDF_DIR
    source_document = from_workspace(database, legacy_root=source_root).resolve(paper_id)
    annotation_owner = capture_owner(database, paper_id) if current() else None

    # Cheap, and they read the text the PDF step just extracted.
    if current():
        with scoped_connection() as conn:
            venues.refresh(conn, [paper_id], log=lambda _m: None)
    if current():
        with scoped_connection() as conn:
            if resources.needs_check(conn, paper_id):
                resources.find(conn, paper_id)

    def explain() -> None:
        if not current() or not has_pdf(paper_id):
            return
        work_progress.report("撰寫深度講解與逐節精讀", paper_id=paper_id)
        if todo("dive"):
            with scoped_connection() as conn:
                have = conn.execute("SELECT 1 FROM dives WHERE paper_id=?", (paper_id,))
                wrote = have.fetchone() is not None
            if not wrote:
                wrote = dive.dive_ahead(paper_id=paper_id, log=log) > 0
            reason = None if wrote else "the model did not return a dive"
            if not current():
                return
            if wrote:
                with scoped_connection() as conn:
                    missing = closeread.get(conn, paper_id) is None
                if missing:
                    body, why = invoke(closeread.write, paper_id)
                    log(f"  {'逐節精讀 ' + format(len(body), ',') if body else why}  {name}")
                    reason = None if body else f"close reading: {why}"
            record("dive", reason)
        work_progress.report("分析原文重點並連結素材", paper_id=paper_id)
        if todo("highlights"):
            try:
                from paper_daily import reading_annotation_jobs

                if not source_document.available or annotation_owner is None:
                    raise ValueError("The original PDF was unavailable before analysis started")
                prepared, why = reading_annotation_jobs.prepare(
                    database, paper_id, legacy_root=source_root, connections=connections,
                    owner=annotation_owner, expected_document_hash=source_document.sha256,
                )
                marks = prepared.get("marks") if prepared else None
                ok = bool(marks and marks["mapped"])
                if prepared and prepared.get("explanation_pending"):
                    ok, why = False, prepared["explanation_reason"]
                if marks and not marks["mapped"]:
                    why = "重點已保留在素材中，但無法在 PDF 精確定位；請核對原文。"
                record("highlights", None if ok else why)
                log(
                    f"  原文重點 {marks['mapped']}/{marks['total']} 已同步素材  {name}"
                    if marks
                    else f"  原文重點未完成：{why}  {name}"
                )
            except (ValueError, OSError, RuntimeError) as exc:
                record("highlights", str(exc))
                log(f"  原文重點未完成：{exc}  {name}")
        work_progress.report("整理候選研究問題", paper_id=paper_id)
        from paper_daily import research_question_jobs

        if not current():
            return
        try:
            _questions, why = research_question_jobs.ensure(
                database, paper_id, connections=connections
            )
            log(f"  候選問題：{why}  {name}")
        except (ValueError, OSError, RuntimeError) as exc:
            log(f"  候選問題未完成：{type(exc).__name__}  {name}")

    def place() -> None:
        # The 研究脈絡 is written from the references' verdicts, so 承先 comes first.
        work_progress.report("核對參考文獻與引用關係", paper_id=paper_id)
        if has_pdf(paper_id) and todo("cites"):
            n = invoke(cites.analyse, paper_id, log=log)
            with scoped_connection() as conn:
                coverage = cites.coverage(conn, paper_id, verify_source=True)
            record("cites", None if coverage["state"] == "complete" else (
                coverage["reason"] if n else "no references could be read"
            ))
        work_progress.report("查找後續研究與發展脈絡", paper_id=paper_id)
        if todo("later"):
            from paper_daily.http import FetchError

            try:
                invoke(followups.analyse, paper_id, log=log, overview_too=False)
            except FetchError:
                record("later", "The later-work service is unavailable; retry later")
                log("Later-work retrieval failed; original research was preserved")

    # The explanation and the citations read the same text but not each other, and
    # each spends minutes waiting on a model: side by side, the paper is ready in
    # the time of the longer one instead of the sum.
    def chain(worker):
        with llm.connection_scope(connections):
            worker()

    with ThreadPoolExecutor(max_workers=2) as pool:
        chains = [pool.submit(chain, explain), pool.submit(chain, place)]
    for chain in chains:
        chain.result()

    # The story consumes both chains' accepted outputs, never their in-flight drafts.
    if current():
        with scoped_connection() as conn:
            story_pending = (
                get_kv(conn, f"followups.checked.{paper_id}") is not None
                and not followups.done(conn, paper_id)
            )
        if story_pending:
            import hashlib

            from paper_daily.document_reader import document_current
            from paper_daily.sync_documents import MAX_PDF_BYTES

            unchanged = True
            if source_document.available:
                try:
                    unchanged = document_current(source_document)
                    unchanged = unchanged and source_document.path.stat().st_size <= MAX_PDF_BYTES
                    if unchanged:
                        with source_document.path.open("rb") as stream:
                            unchanged = (
                                hashlib.file_digest(stream, "sha256").hexdigest()
                                == source_document.sha256
                            )
                except OSError:
                    unchanged = False
            if not unchanged:
                record("later", "The original PDF changed; the overview was not regenerated")
            else:
                wrote, why = invoke(followups.overview, paper_id, log=log)
                record("later", None if wrote or why == "edited by hand" else why)

    if not belongs():
        log("Analysis stopped: original research workspace changed")
        return {step: False for step in STEPS}
    if not current():
        log("Workspace changed; remaining analysis stages were not started")
    with scoped_connection() as conn:
        state = status(conn, paper_id, verify_sources=True)
        work_progress.report(
            "本篇分析結束",
            sum(state.values()),
            len(state),
            paper_id=paper_id,
            outcome=None if all(state.values()) else "partial",
        )
        return state


def left(
    conn, paper_id: str, retry: bool = False, *, verify_sources: bool = True
) -> list[str]:
    """The steps still worth attempting for one paper.

    A step that failed is left out unless `retry`, and so are the steps that read
    the text when the PDF itself could not be found: otherwise a paper no source
    has would come first every night and nothing would ever be made for it.
    """
    have = status(conn, paper_id, verify_sources=verify_sources)
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
        # The desktop also asks for candidates on its UI thread. Actual worker
        # admission rechecks pending() with exact-source verification before AI.
        if left(conn, r[0], verify_sources=False):
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
    work_progress.report("開始處理論文", 0, len(todo))
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {pool.submit(analyse, pid, log, retry): pid for pid in todo}
        for done, future in enumerate(as_completed(futures), 1):
            pid = futures[future]
            try:
                state = future.result()
            except Exception as e:  # one paper's failure must not stop the rest
                work_progress.report("此篇未完成，繼續其他論文", done, len(todo),
                                     outcome="partial")
                log(f"[{done}/{len(todo)}] failed {pid}: {e}")
                continue
            work_progress.report("已處理論文（含未完成項目）", done, len(todo),
                                 outcome=None if all(state.values()) else "partial")
            complete += all(state.values())
            with connect() as conn:
                title = conn.execute("SELECT title FROM papers WHERE id=?", (pid,)).fetchone()[0]
            log(f"[{done}/{len(todo)}] {summary(state)}  {title[:60]}")
    return complete
