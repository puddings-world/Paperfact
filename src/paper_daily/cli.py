"""Command line interface.

Typical first run:

    paperfact bootstrap --years 2016-2026

then, every night:

    paperfact today
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from paper_daily import __version__, brief, pipeline
from paper_daily import queue as qmod
from paper_daily.config import (
    BRIEF_DIR,
    DATA_DIR,
    DB_PATH,
    PDF_DIR,
    S2_API_KEY,
    SETTINGS,
    TEXT_DIR,
    VENUES,
)
from paper_daily.store import connect, init_db


def _log(msg: str) -> None:
    print(msg, flush=True)


def parse_years(spec: str) -> list[int]:
    """ "2016-2026" or "2020,2024" or "2024"."""
    years: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            years.extend(range(int(lo), int(hi) + 1))
        elif part:
            years.append(int(part))
    return sorted(set(years))


def parse_venues(spec: str | None) -> list[str]:
    if not spec:
        return list(VENUES)
    wanted = {v.strip().lower() for v in spec.split(",") if v.strip()}
    return [v for v in VENUES if v.lower() in wanted] or list(VENUES)


def cmd_init(args) -> int:
    init_db()
    print(f"database ready at {DB_PATH}")
    return 0


def cmd_crawl(args) -> int:
    init_db()
    pipeline.crawl(parse_years(args.years), parse_venues(args.venues), log=_log)
    return 0


def cmd_enrich(args) -> int:
    pipeline.enrich(parse_years(args.years), parse_venues(args.venues), log=_log)
    return 0


def cmd_rank(args) -> int:
    pipeline.rank_and_queue(per_year=args.per_year, log=_log)
    return 0


def cmd_bootstrap(args) -> int:
    years = parse_years(args.years)
    venues = parse_venues(args.venues)
    init_db()
    print("== crawl ==")
    pipeline.crawl(years, venues, log=_log)
    print("== enrich ==")
    pipeline.enrich(years, venues, log=_log)
    print("== rank ==")
    pipeline.rank_and_queue(per_year=args.per_year, log=_log)
    return cmd_status(args)


def cmd_refresh(args) -> int:
    """Pick up newly published papers and re-rank.

    New conference years appear at the front of the queue automatically: ranking is
    year-block descending, so a 2027 paper outranks everything from 2026. Papers
    already delivered or read keep their state, so nothing is served twice.
    """
    this_year = datetime.now(UTC).year
    years = list(range(this_year - args.back, this_year + 2))
    venues = parse_venues(args.venues)
    print(f"== refresh {years[0]}-{years[-1]} ==")
    pipeline.crawl(years, venues, log=_log)
    pipeline.enrich(years, venues, log=_log)
    pipeline.rank_and_queue(per_year=args.per_year, log=_log)
    return 0


def cmd_today(args) -> int:
    with connect() as conn:
        result = brief.deliver_next(conn)
        if not result:
            print("queue is empty -- run: paperfact rank")
            return 1
        row, path = result
        conn.commit()

    companions = pipeline.expand_lineage(row["id"], log=_log)
    print()
    print(f"{row['title']}")
    print(
        f"  {row['venue']} {row['year']}"
        + (f" ({row['award']})" if row["award"] else "")
        + f" | {row['paper_type']}"
    )
    print(f"  pack: {path}")
    if companions:
        print(f"  queued {len(companions)} companion paper(s) from its references")
    return 0


def cmd_peek(args) -> int:
    with connect() as conn:
        rows = qmod.next_papers(conn, args.n)
    if not rows:
        print("queue is empty")
        return 1
    for i, r in enumerate(rows, 1):
        award = f" [{r['award']}]" if r["award"] else ""
        print(f"{i:3d}. {r['venue']} {r['year']}{award} ({r['paper_type']})  {r['title']}")
        if r["reason"]:
            print(f"      {r['reason']}")
    return 0


def cmd_mark(args) -> int:
    with connect() as conn:
        qmod.mark(conn, args.paper_id, args.state)
    print(f"{args.paper_id} -> {args.state}")
    return 0


def cmd_status(args) -> int:
    st = pipeline.status()
    print()
    print(f"corpus: {st['total']} papers   queue: {st['queue'] or 'empty'}")

    with connect() as conn:
        cov = conn.execute(
            "SELECT COUNT(*) n,"
            " SUM(p.authors_json NOT IN ('','[]')) authors,"
            " SUM(p.abstract IS NOT NULL) abstracts,"
            " SUM(p.pdf_url IS NOT NULL OR p.arxiv_id IS NOT NULL) fetchable"
            " FROM queue q JOIN papers p ON p.id = q.paper_id WHERE q.state != 'skipped'"
        ).fetchone()
        dives = conn.execute("SELECT COUNT(*) FROM dives").fetchone()[0]
        notes = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]

    pdfs = len(list(PDF_DIR.glob("*.pdf"))) if PDF_DIR.exists() else 0
    n = cov["n"] or 1
    print("\nqueue readiness")
    for label, value in (
        ("authors", cov["authors"] or 0),
        ("abstracts", cov["abstracts"] or 0),
        ("a PDF to fetch", cov["fetchable"] or 0),
    ):
        print(f"  {label:16s} {value:5d} / {cov['n']}  ({value / n:.0%})")
    print(f"  {'PDFs downloaded':16s} {pdfs:5d}")
    print(f"  {'deep dives':16s} {dives:5d}")
    print(f"  {'notes':16s} {notes:5d}")

    print()
    print(f"{'venue':9s} {'year':5s} {'papers':>7s} {'enriched':>9s} {'scored':>7s}")
    for r in st["by_venue_year"]:
        print(
            f"{r['venue']:9s} {r['year']:<5d} {r['n']:>7d} "
            f"{r['enriched'] or 0:>9d} {r['scored'] or 0:>7d}"
        )
    return 0


def cmd_doctor(args) -> int:
    """Check that everything the pipeline and the reader need is actually there."""
    ok = True

    def line(name: str, value: str, good: bool = True) -> None:
        nonlocal ok
        ok = ok and good
        print(f"{name:22s}: {value}")

    print("-- data --")
    line("data dir", str(DATA_DIR))
    line("database", "present" if DB_PATH.exists() else "created on first launch")
    line("S2 API key", "set" if S2_API_KEY else "not set (slower, rate-limited)")

    print("\n-- reader --")
    try:
        import PySide6  # noqa: F401

        line("PySide6", "installed")
    except ImportError:
        line("PySide6", "MISSING -- run scripts/setup.ps1", False)
    try:
        from PySide6.QtPdfWidgets import QPdfView  # noqa: F401

        line("Qt PDF view", "installed (selectable text)")
    except ImportError:
        line("Qt PDF view", "absent -- falling back to PyMuPDF page images")
    try:
        import pymupdf  # noqa: F401

        line("pymupdf", "installed")
    except ImportError:
        line("pymupdf", "MISSING -- no PDF text extraction", False)
    from paper_daily import fonts

    absent = [f["family"] for f in fonts.missing()]
    line(
        "fonts",
        f"missing {', '.join(absent)} -- run 'fonts'" if absent else "installed",
        not absent,
    )
    from paper_daily import web_assets

    absent = [a["name"] for a in web_assets.missing()]
    line(
        "formula/diagram kit",
        f"missing {', '.join(absent)} -- run 'web-assets'" if absent else "installed",
        not absent,
    )

    from paper_daily import llm

    try:
        cfg = llm.settings()
    except (ValueError, OSError) as exc:
        line("LLM backend", f"invalid AI settings: {exc}", False)
    else:
        if cfg.backend == "none":
            line("LLM backend", "optional -- choose AI settings when you want AI assistance",
                 not getattr(args, "ai", False))
        elif getattr(args, "ai", False):
            # Being configured is not the same as being able to answer: a whole night of
            # dives failed on an expired OAuth session while this check said "installed".
            answered, detail = llm.probe(cfg)
            line(
                "LLM backend",
                detail if answered else f"{llm.describe(cfg)} -- NOT working: {detail}",
                answered,
            )
        else:
            line("LLM backend", f"{llm.describe(cfg)} (not contacted; --ai tests a model call)")

    if sys.platform == "darwin":
        app = Path(os.path.expanduser("~/Applications/Paperfact.app"))
        line(
            "app launcher",
            "present" if app.exists() else "missing -- run scripts/make-app-mac.sh",
        )
    if sys.platform == "win32":
        shortcut = Path(os.path.expanduser("~/Desktop/Paperfact.lnk"))
        line(
            "desktop shortcut",
            "present" if shortcut.exists() else "missing -- run scripts/make-shortcut.ps1",
        )
        task = subprocess.run(
            ["schtasks", "/query", "/tn", "paper-daily nightly"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        line(
            "nightly task",
            "registered" if task.returncode == 0
            else "not registered -- run scripts/register-nightly.ps1",
        )

    if not getattr(args, "sources", False):
        print("\nSource checks skipped; --sources contacts the optional scholarly services.")
        return 0 if ok else 1
    print("\n-- optional scholarly sources --")
    from paper_daily.http import fetch

    checks = [
        ("proceedings.mlr.press", "https://proceedings.mlr.press/"),
        ("papers.nips.cc", "https://papers.nips.cc/"),
        ("iclr.cc virtual", "https://iclr.cc/virtual/2024/papers.html?filter=titles"),
        (
            "semanticscholar",
            "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
            "?venue=ICLR&year=2024&fields=paperId&limit=1",
        ),
        ("arxiv", "http://export.arxiv.org/api/query?search_query=all:electron&max_results=1"),
    ]
    for name, url in checks:
        try:
            fetch(url, max_age=3600)
            line(name, "reachable")
        except Exception as e:
            line(name, f"FAILED ({type(e).__name__})", False)

    return 0 if ok else 1


def cmd_export(args) -> int:
    """Dump the upcoming queue as JSON, for the reader artifact."""
    with connect() as conn:
        rows = qmod.next_papers(conn, args.n)
        out = [
            {
                "id": r["id"],
                "title": r["title"],
                "venue": r["venue"],
                "year": r["year"],
                "award": r["award"],
                "type": r["paper_type"],
                "authors": json.loads(r["authors_json"] or "[]"),
                "abstract": r["abstract"],
                "pdf_url": r["pdf_url"],
                "page_url": r["page_url"],
                "citations": r["citation_count"],
                "role": r["role"],
                "reason": r["reason"],
            }
            for r in rows
        ]
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_reader_doc(args) -> int:
    """Write the JSON document the reader artifact renders for one day.

    Kept as a file rather than printed so the nightly job can hand it straight to
    `Artifact write_db --file_path` without a large payload passing through the
    conversation.
    """
    day = args.date or datetime.now(UTC).strftime("%Y-%m-%d")
    outdir = BRIEF_DIR / day
    if not outdir.exists():
        print(f"no brief directory for {day}")
        return 1

    with connect() as conn:
        row = conn.execute(
            "SELECT p.*, q.role, q.reason FROM reading_log rl "
            "JOIN papers p ON p.id = rl.paper_id "
            "LEFT JOIN queue q ON q.paper_id = p.id "
            "WHERE rl.brief_path LIKE ? ORDER BY rl.id DESC LIMIT 1",
            (f"%{day}%",),
        ).fetchone()
    if not row:
        print(f"nothing was delivered on {day}")
        return 1

    text_path = TEXT_DIR / re.sub(r"[^A-Za-z0-9._-]", "_", row["id"])
    full_text = None
    if text_path.with_suffix(".txt").exists():
        full_text = text_path.with_suffix(".txt").read_text(encoding="utf-8")

    dive_files = sorted(outdir.glob("deep-dive*.md"))
    deep_dive = dive_files[0].read_text(encoding="utf-8") if dive_files else None

    doc = {
        "day": day,
        "id": row["id"],
        "title": row["title"],
        "venue": row["venue"],
        "year": row["year"],
        "award": row["award"],
        "authors": json.loads(row["authors_json"] or "[]"),
        "abstract": row["abstract"],
        "paperType": row["paper_type"],
        "topic": row["topic"],
        "citations": row["citation_count"],
        "isCanon": bool(row["is_canon"]),
        "pageUrl": row["page_url"],
        "pdfUrl": row["pdf_url"],
        "fullText": full_text,
        "deepDive": deep_dive,
    }
    dest = outdir / "reader-doc.json"
    dest.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(dest)
    return 0


def cmd_sync_queue(args) -> int:
    """Write the upcoming queue as one document for the reader artifact's store.

    The nightly job runs in the cloud and cannot reach this machine's 100+ MB corpus,
    so it works from this slice instead: enough queued papers to cover months of
    reading, each with a public PDF link it can fetch on its own. One document rather
    than one per paper, because the store bills a write per document.
    """
    with connect() as conn:
        rows = qmod.next_papers(conn, args.limit)

    prefetched = DATA_DIR / "sync" / "papers"
    papers = [
        {
            "id": r["id"],
            "title": r["title"],
            "venue": r["venue"],
            "year": r["year"],
            "award": r["award"],
            "paperType": r["paper_type"],
            "topic": r["topic"],
            "authors": json.loads(r["authors_json"] or "[]"),
            "abstract": r["abstract"],
            "citations": r["citation_count"],
            "isCanon": bool(r["is_canon"]),
            "pdfUrl": r["pdf_url"],
            "pageUrl": r["page_url"],
            "arxivId": r["arxiv_id"],
            "role": r["role"],
            "reason": r["reason"],
            # Lets the reader show which rows it can actually open with text, and
            # filter down to them, without a per-row lookup against the store.
            "hasText": (
                prefetched / (re.sub(r"[^A-Za-z0-9._-]", "_", r["id"]) + ".json")
            ).exists(),
        }
        for r in rows
    ]
    doc = {"generatedAt": datetime.now(UTC).isoformat(timespec="seconds"), "papers": papers}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dest = DATA_DIR / "queue-sync.json"
    dest.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{dest}  ({len(papers)} papers)")
    return 0


def cmd_prefetch(args) -> int:
    """Download and extract the next N queued papers so the reader can open any of
    them, not just the one delivered tonight.

    Jumping around the queue is only useful if the text is already there: the reader
    page cannot fetch a PDF itself (the artifact CSP blocks every external host), so
    whatever it can show has to be pushed in ahead of time.
    """
    from paper_daily.fetch import prepare

    # The newest year is not in Semantic Scholar's venue index, so its papers carry no
    # arXiv id and therefore no reachable PDF. Resolve those first or every fetch here
    # fails with nothing to try.
    if args.list:
        scope = "" if args.list == "all" else "WHERE lp.list_id = ? "
        scope_args = () if args.list == "all" else (args.list,)
        with connect() as conn:
            rows = conn.execute(
                "SELECT p.* FROM list_papers lp JOIN papers p ON p.id = lp.paper_id "
                f"{scope}GROUP BY p.id ORDER BY lp.list_id, lp.position LIMIT ?",
                (*scope_args, args.n),
            ).fetchall()
    else:
        pipeline.resolve_queued(limit=args.n, log=_log)
        with connect() as conn:
            rows = qmod.next_papers(conn, args.n)

    outdir = DATA_DIR / "sync" / "papers"
    outdir.mkdir(parents=True, exist_ok=True)
    done = skipped = 0
    for r in rows:
        dest = outdir / (re.sub(r"[^A-Za-z0-9._-]", "_", r["id"]) + ".json")
        if dest.exists() and not args.force:
            skipped += 1
            continue
        _, text = prepare(r)
        if not text:
            print(f"  no text: {r['title'][:60]}")
            continue
        dest.write_text(
            json.dumps(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "venue": r["venue"],
                    "year": r["year"],
                    "fullText": text[:100_000],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        done += 1
        print(f"  {done:3d}. {r['venue']} {r['year']}  {r['title'][:58]}")
    print(f"prefetched {done}, already had {skipped} -> {outdir}")
    return 0


def cmd_sync_read(args) -> int:
    """Mark the first N pending papers as read, to catch the local queue up with the
    nightly job's cursor after it has delivered them in the cloud."""
    with connect() as conn:
        rows = qmod.next_papers(conn, args.n)
        for r in rows:
            qmod.mark(conn, r["id"], "read")
    for r in rows:
        print(f"read: {r['venue']} {r['year']}  {r['title'][:70]}")
    return 0


def cmd_app(args) -> int:
    """Open the desktop reader."""
    try:
        from paper_daily.desktop.main import run
    except ImportError as e:
        print(f"the desktop reader needs PySide6: run scripts/setup.ps1  ({e})")
        return 1
    return run(open_next=args.next, restart=args.restart, paper=args.paper)


def cmd_backfill(args) -> int:
    """Fill in metadata the bulk crawl left empty, cheapest source first."""
    n = pipeline.backfill_conference_details(limit=args.limit, log=_log)
    print(f"conference pages filled {n}")
    m = pipeline.resolve_queued(limit=args.limit, log=_log)
    print(f"semantic scholar resolved {m}")
    return 0


def cmd_dive_ahead(args) -> int:
    """Write deep dives for the next few papers, so there is always one ready."""
    from paper_daily import dive

    n = dive.dive_ahead(
        count=args.n, log=_log, paper_id=args.paper, list_id=args.list,
        rewrite=args.rewrite, jobs=args.jobs,
    )
    print(f"{n} deep dive(s) written")
    return 0


def cmd_import_list(args) -> int:
    """Turn a bibliography into a reading list the app can switch to."""
    from paper_daily import lists

    raw = Path(args.file).read_text(encoding="utf-8")
    result = lists.import_list(args.name, raw, list_id=args.slug, log=_log)
    print()
    print(
        f"list '{result.get('id')}': {result['added']} papers "
        f"({result['resolved']}/{result['parsed']} matched in Semantic Scholar)"
    )
    return 0


def cmd_list_add(args) -> int:
    """Add one paper to an existing reading list."""
    from paper_daily import lists

    citation = Path(args.file).read_text(encoding="utf-8") if args.file else args.citation
    if not citation:
        print("give a citation, a title, or --file")
        return 1
    result = lists.add_paper(
        args.list_id, citation, log=_log, create_name=args.create, doi=args.doi
    )
    print(f"{result['added']} added to '{args.list_id}' ({result['reason']})")
    if result["added"]:
        from paper_daily import resources

        # Asked now rather than at night: whether a paper has code is part of
        # deciding whether it belongs on the list.
        with connect() as conn:
            resources.refresh(conn, result["paper_ids"], log=_log)
    return 0 if result["added"] else 1


def cmd_list_remove(args) -> int:
    """Drop a paper from a reading list. The paper itself stays in the corpus."""
    from paper_daily import lists

    if lists.remove_paper(args.list_id, args.paper_id):
        print(f"removed {args.paper_id} from '{args.list_id}'")
        return 0
    print(f"'{args.list_id}' has no paper {args.paper_id}")
    return 1


def cmd_find(args) -> int:
    """Search the whole corpus, not just the queue."""
    from paper_daily.store import search_papers

    with connect() as conn:
        rows = search_papers(conn, args.text, args.n)
    if not rows:
        print("nothing matched")
        return 1
    for r in rows:
        state = r["state"] or "-"
        award = f" [{r['award']}]" if r["award"] else ""
        print(f"{r['id']:28s} {r['venue']:8s} {r['year']}  {state:9s}{award}  {r['title'][:70]}")
    return 0


def cmd_queue_add(args) -> int:
    """Put a paper into the reading queue by hand, at the front."""
    from paper_daily.store import search_papers

    with connect() as conn:
        paper_id = args.paper
        if not conn.execute("SELECT 1 FROM papers WHERE id=?", (paper_id,)).fetchone():
            rows = search_papers(conn, paper_id, 5)
            if not rows:
                print(f"no paper matching {paper_id!r} -- try: paperfact find <words>")
                return 1
            if len(rows) > 1 and not args.first:
                print("more than one match; pass the id, or --first to take the top one:")
                for r in rows:
                    print(f"  {r['id']:28s} {r['venue']} {r['year']}  {r['title'][:66]}")
                return 1
            paper_id = rows[0]["id"]
        if not qmod.add(conn, paper_id, reason=args.reason, front=not args.back):
            print(f"no paper with id {paper_id}")
            return 1
        row = conn.execute("SELECT title FROM papers WHERE id=?", (paper_id,)).fetchone()
    print(f"queued {paper_id}: {row['title'][:70]}")
    return 0


def cmd_queue_remove(args) -> int:
    """Take a paper out of the reading queue."""
    with connect() as conn:
        if not qmod.remove(conn, args.paper_id):
            print(f"{args.paper_id} is not in the queue")
            return 1
    print(f"removed {args.paper_id} from the queue")
    return 0


def cmd_resolve_missing(args) -> int:
    """Try again for papers with no route to their original."""
    n = pipeline.resolve_missing(limit=args.n, log=_log)
    print(f"{n} paper(s) now have a PDF to fetch")
    return 0


def _list_ids(list_id: str) -> list[str]:
    """Paper ids in a reading list, or in every list for 'all'."""
    with connect() as conn:
        if list_id == "all":
            rows = conn.execute(
                "SELECT DISTINCT paper_id FROM list_papers ORDER BY list_id, position"
            )
        else:
            rows = conn.execute(
                "SELECT paper_id FROM list_papers WHERE list_id=? ORDER BY position", (list_id,)
            )
        return [r[0] for r in rows]


def cmd_venues(args) -> int:
    from paper_daily import venues

    ids = _list_ids(args.list) if args.list else args.paper_ids
    if not ids:
        print("venues needs paper ids or --list", file=sys.stderr)
        return 2
    with connect() as conn:
        n = venues.refresh(conn, ids, log=_log)
    print(f"{n} venue(s) updated")
    return 0


def cmd_analyze(args) -> int:
    from paper_daily import analyze

    if args.scheduled:
        from paper_daily import analysis_schedule

        analysis_schedule.run(jobs=args.jobs, log=_log)
        return 0
    if args.ahead:
        n = analyze.ahead(args.ahead, list_id=args.list, jobs=args.jobs, log=_log)
        print(f"{n} paper(s) fully analysed")
        return 0
    ids = _list_ids(args.list) if args.list else args.paper_ids
    if not ids:
        print("analyze needs paper ids, --list or --ahead", file=sys.stderr)
        return 2
    n = analyze.analyse_many(ids, jobs=args.jobs, log=_log, retry=args.retry)
    print(f"{n} paper(s) fully analysed")
    return 0


def cmd_resources(args) -> int:
    from paper_daily import resources

    ids = _list_ids(args.list) if args.list else args.paper_ids
    if not ids:
        print("resources needs paper ids or --list", file=sys.stderr)
        return 2
    with connect() as conn:
        n = resources.refresh(conn, ids, log=_log, force=args.force or bool(args.paper_ids))
    print(f"{n} link(s) found")
    return 0


def cmd_repdf(args) -> int:
    from paper_daily import repdf

    return 0 if repdf.replace(args.paper_id, args.url, file=args.file) else 1


def cmd_cites(args) -> int:
    """Work out what each reference is doing in a paper, so the useful ones stand out."""
    from paper_daily import cites

    if args.list:
        # A whole list in one go, skipping what is already analysed: each paper is a
        # model call of a minute or two, and a rerun should only pay for the gaps.
        done = 0
        for pid in _list_ids(args.list):
            with connect() as conn:
                if conn.execute("SELECT 1 FROM cites WHERE paper_id=? LIMIT 1", (pid,)).fetchone():
                    continue
            _log(pid)
            done += bool(cites.analyse(pid, limit=args.limit, log=_log))
        print(f"{done} paper(s) analysed")
        return 0
    if not args.paper_id:
        print("cites needs a paper id or --list", file=sys.stderr)
        return 2
    n = cites.analyse(args.paper_id, limit=args.limit, log=_log)
    if not n:
        return 1
    with connect() as conn:
        rows = cites.for_paper(conn, args.paper_id)
    print()
    for r in rows:
        print(f"  [{r['verdict'] or '?'}] {(r['title'] or '(unidentified)')[:62]}")
        print(f"      用途:{r['purpose']}")
    print()
    print(f"{n} reference(s) analysed")
    return 0


def cmd_share(args) -> int:
    """Lay out papers as an editable draft, or turn an edited draft into the page."""
    from paper_daily import share

    if args.action == "draft":
        if not args.ids:
            print("share draft needs at least one paper id", file=sys.stderr)
            return 2
        made = share.draft(args.ids, slug=args.slug, with_compare=args.compare)
        print(f"draft: {made['path']}")
        if made["path"].name == "draft.new.md":
            print("  draft.md already exists and was left alone; merge what you want from this one")
        if made["compare_failed"]:
            print(f"  comparison skipped: {made['compare_failed']}")
        print(f"edit it, then: paperfact share build {made['slug']}")
        return 0

    slug = args.slug or (args.ids[0] if args.ids else None)
    if not slug:
        print("share build needs the draft's slug", file=sys.stderr)
        return 2
    built = share.build(slug)
    print(f"page: {built['page']}")
    print(f"  {len(built['files'])} figure file(s), {built['bytes'] / 1e6:.1f} MB in all")
    for ref in built["missing"]:
        print(f"  missing: {ref}")
    return 0


def cmd_followups(args) -> int:
    """Find what cites a paper across the whole field, and judge what to read next."""
    from paper_daily import followups

    if args.ahead:
        n = followups.ahead(args.ahead, log=_log)
        print(f"{n} paper(s) asked about")
        return 0
    ids = _list_ids(args.list) if args.list else args.paper_ids
    if not ids:
        print("followups needs paper ids or --list", file=sys.stderr)
        return 2
    for pid in ids:
        _log(pid)
        if args.with_cites:
            from paper_daily import cites

            with connect() as conn:
                has = conn.execute("SELECT 1 FROM cites WHERE paper_id=? LIMIT 1", (pid,))
                has = has.fetchone()
            if not has:
                cites.analyse(pid, log=_log)
        followups.analyse(pid, log=_log)
    return 0


def cmd_close_read(args) -> int:
    """Walk each paper's sections after the front matter, with its figures."""
    from paper_daily import closeread

    init_db()
    ids = _list_ids(args.list) if args.list else args.paper_ids
    if not ids:
        print("close-read needs paper ids or --list", file=sys.stderr)
        return 2
    with connect() as conn:
        todo = closeread.select(conn, ids, rewrite=args.rewrite) if not args.force else ids
    print(f"{len(todo)} of {len(ids)} paper(s) to write")
    written = closeread.write_many(todo, jobs=args.jobs, log=_log)
    print(f"{written} written")
    return 0 if written == len(todo) else 1


def cmd_fonts(args) -> int:
    """Download the typefaces the reader ships with (idempotent)."""
    from paper_daily import fonts

    done = fonts.install(log=_log)
    print(f"fonts: {', '.join(done) if done else 'already installed'} in {fonts.FONT_DIR}")
    return 0


def cmd_storage(args) -> int:
    """Where the data folder's space goes, by folder and by list."""
    from paper_daily import storage

    with connect() as conn:
        print("-- data folder --")
        for name, size, count in storage.folders():
            print(f"{name:22s} {storage.human(size):>10s}  {count:>7,} files")
        print("\n-- by list (PDF, figures, text, decks) --")
        for name, papers, size in storage.by_list(conn):
            print(f"{name[:22]:22s} {storage.human(size):>10s}  {papers:>7,} papers")
        chosen = storage.plan(conn, args.cache_days)
    print(
        f"\nprunable: {storage.human(chosen.cache_bytes)} of HTTP cache older than "
        f"{args.cache_days} days, {storage.human(chosen.paper_bytes)} of files of "
        f"{len(chosen.papers)} unclaimed papers. Run `prune` to see them."
    )
    return 0


def cmd_prune(args) -> int:
    """Delete what can be fetched or rebuilt again; a dry run unless --yes."""
    from paper_daily import storage

    with connect() as conn:
        chosen = storage.plan(conn, args.cache_days)
        print(
            f"HTTP cache older than {args.cache_days} days: {len(chosen.cache):,} files, "
            f"{storage.human(chosen.cache_bytes)}"
        )
        print(
            f"unclaimed papers (in no list or queue, no notes or analysis): "
            f"{len(chosen.papers)}, {storage.human(chosen.paper_bytes)}"
        )
        for name, paths in chosen.papers.items():
            kinds = ", ".join(sorted({p.parent.name for p in paths}))
            print(f"  {name}  ({kinds})")
        if not args.yes:
            print("\ndry run: nothing deleted. Add --yes to delete these.")
            return 0
        freed = storage.prune(conn, chosen, vacuum=args.vacuum)
    compacted = " and compacted the database" if args.vacuum else ""
    print(f"\nfreed {storage.human(freed)}{compacted}")
    return 0


def cmd_web_assets(args) -> int:
    """Download KaTeX, highlight.js and Mermaid for the reading views (idempotent)."""
    from paper_daily import web_assets

    done = web_assets.install(log=_log)
    print(
        f"web assets: {', '.join(done) if done else 'already installed'} "
        f"in {web_assets.WEB_DIR}"
    )
    return 0


def cmd_list_export(args) -> int:
    """Pack a reading list and all its analyses into one file to hand on."""
    from paper_daily import research_service
    from paper_daily.config import DATA_DIR

    stamp = datetime.now().strftime("%Y%m%d")
    out = Path(args.out) if args.out else DATA_DIR / "exports" / f"{args.list_id}-{stamp}.zip"
    made = research_service.export_bundle(
        args.list_id, out, notes=not args.no_notes, with_pdfs=args.with_pdfs, log=_log
    )
    print(f"wrote {made['out']} ({made['bytes'] / 1e6:.1f} MB)")
    print(
        f"  {made['papers']} papers, {made['dives']} deep dives, "
        f"{made['close_readings']} close readings, {made['cites']} reference analyses, "
        f"{made['followups']} later works, {made['list_surveys']} survey, "
        f"{made['files']} files"
        + (
            ""
            if args.no_notes
            else f", {made.get('notes', 0)} notes, {made.get('chat', 0)} Q&A turns"
        )
    )
    print(
        f"  PDFs: {made['pdf_packed']} included in the bundle"
        + ("" if args.with_pdfs else f"; {made['pdf_verified']} available by verified URL")
        + f"; {len(made['pdf_missing'])} with no PDF here"
    )
    return 0


def cmd_list_import(args) -> int:
    """Bring in a list exported with list-export, keeping what is already here."""
    from paper_daily import research_service

    got = research_service.import_bundle(
        Path(args.path), replace=args.replace, pdfs=not args.no_pdfs, log=_log
    )
    print(f"imported list {got['list']} ({got['name']})")
    skip = ("list", "name", "pdf_ok", "pdf_needed")
    print("  added: " + ", ".join(f"{k} {v}" for k, v in got.items() if k not in skip))
    if "pdf_ok" in got:
        print(f"  PDFs: {len(got['pdf_ok'])} in place and identical to the sharer's")
        if got["pdf_needed"]:
            print(
                f"  {len(got['pdf_needed'])} PDF(s) must come from the sharer, then "
                "`repdf <id> --file <path>`: " + ", ".join(got["pdf_needed"])
            )
    return 0


def cmd_survey(args) -> int:
    """Read a whole reading list as one field: history, lines of work, open problems."""
    from paper_daily import survey

    written, reason = survey.write(args.list_id, force=args.force, log=_log)
    print("survey written" if written else f"not written: {reason}")
    return 0 if written else 1


def cmd_cite_links(args) -> int:
    """Look up the citations among a paper's neighbours, for the 引用圖 map."""
    from paper_daily import citegraph

    ids = _list_ids(args.list) if args.list else args.paper_ids
    if not ids:
        print("cite-links needs paper ids or --list", file=sys.stderr)
        return 2
    failed = 0
    for pid in ids:
        _log(pid)
        failed += citegraph.links(pid, log=_log) < 0
    return 1 if failed else 0


def cmd_cites_ahead(args) -> int:
    """Analyse citations for the next few papers that have none."""
    from paper_daily import cites

    n = cites.analyse_ahead(count=args.n, rewrite=args.rewrite, log=_log)
    print(f"{n} paper(s) analysed")
    return 0


def cmd_lists(args) -> int:
    """Show the reading lists and how far through each one is."""
    from paper_daily import lists

    rows = lists.all_lists()
    if not rows:
        print("no reading lists yet -- see: paperfact import-list --help")
        return 0
    for r in rows:
        print(f"  {r['id']:24s} {r['read']:4d}/{r['count']:<4d} read   {r['name']}")
    return 0


def cmd_llm(args) -> int:
    """Manage AI profiles, route research tasks, or test the selected connection."""
    from paper_daily import llm

    fields = {
        "backend": args.backend, "model": args.model, "api_key": args.key,
        "base_url": args.base_url, "api_key_env": args.key_env,
        "max_tokens": args.max_tokens, "token_parameter": args.token_parameter,
        "requires_key": args.requires_key,
    }
    try:
        if any(value is not None for value in fields.values()):
            dest = llm.save_settings(profile=args.profile, **fields)
            print(f"saved to {dest}")
            if args.key:
                print(
                    "  note: the key is stored locally in plain text; "
                    "--key-env keeps it in the environment"
                )
        if args.follow_default:
            if not args.for_task:
                raise ValueError("--follow-default requires --for-task")
            llm.clear_route(args.for_task)
        if args.use:
            llm.use_profile(args.use, task=args.for_task)
        if args.list_profiles:
            for name in llm.profile_names():
                marker = " *" if name == llm.active_profile() else ""
                print(f"{name}{marker}: {llm.describe(llm.settings(profile=name))}")
            for task, profile in sorted(llm.task_routes().items()):
                print(f"  {task} -> {profile}")
        cfg = llm.settings(task=args.for_task or "default", profile=args.profile)
        print(f"backend: {llm.describe(cfg)}")
    except (ValueError, OSError) as exc:
        print(f"AI configuration error: {exc}", file=sys.stderr)
        return 2
    if args.test:
        ok, detail = llm.probe(cfg)
        print(f"probe:   {'ok -- ' if ok else 'FAILED -- '}{detail}")
        return 0 if ok else 1
    return 0


def cmd_lineage(args) -> int:
    """Record in-corpus references for the papers coming up, so the reader can show
    where each idea came from before you get there."""
    n = pipeline.build_lineage(limit=args.n, log=_log)
    print(f"{n} lineage edges recorded")
    return 0


def cmd_set_dive(args) -> int:
    """Attach a deep dive to a paper, by id.

    Replaces an earlier scheme that matched dive files to papers by the date folder
    they sat in. That collided the moment two papers were delivered on one day: the
    nightly run fires at 00:00 local, which is still the previous UTC day, and the
    wrong paper ended up showing another paper's explanation.
    """
    body = Path(args.file).read_text(encoding="utf-8").strip() if args.file else sys.stdin.read()
    if not body:
        print("nothing to store")
        return 1

    from paper_daily.desktop.main import Data

    with connect() as conn:
        row = conn.execute("SELECT title FROM papers WHERE id=?", (args.paper_id,)).fetchone()
    if not row:
        print(f"no paper with id {args.paper_id}")
        return 1

    Data().save_dive(args.paper_id, body)
    print(f"deep dive stored ({len(body)} chars) for {row['title'][:70]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="paperfact",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"paperfact {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def add_scope(sp, default_years="2016-2026"):
        sp.add_argument(
            "--years",
            default=default_years,
            help='year range or list, e.g. "2016-2026" or "2023,2024"',
        )
        sp.add_argument(
            "--venues", default=None, help="comma-separated subset of ICLR,ICML,NeurIPS"
        )

    sp = sub.add_parser("init", help="create the database")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("crawl", help="fetch paper rosters")
    add_scope(sp)
    sp.set_defaults(func=cmd_crawl)

    sp = sub.add_parser("enrich", help="add citations, authors, abstracts, awards")
    add_scope(sp)
    sp.set_defaults(func=cmd_enrich)

    sp = sub.add_parser("rank", help="score papers and rebuild the queue")
    sp.add_argument(
        "--per-year",
        type=int,
        default=None,
        help=f"papers per conference year (default: {SETTINGS.queue_target} total)",
    )
    sp.set_defaults(func=cmd_rank)

    sp = sub.add_parser("bootstrap", help="init + crawl + enrich + rank")
    add_scope(sp)
    sp.add_argument("--per-year", type=int, default=None)
    sp.set_defaults(func=cmd_bootstrap)

    sp = sub.add_parser("refresh", help="pick up newly published papers and re-rank")
    sp.add_argument("--back", type=int, default=1, help="how many years back to re-check")
    sp.add_argument("--venues", default=None)
    sp.add_argument("--per-year", type=int, default=None)
    sp.set_defaults(func=cmd_refresh)

    sp = sub.add_parser("today", help="deliver the next paper and build its briefing pack")
    sp.set_defaults(func=cmd_today)

    sp = sub.add_parser("peek", help="show what is coming without consuming it")
    sp.add_argument("n", nargs="?", type=int, default=10)
    sp.set_defaults(func=cmd_peek)

    sp = sub.add_parser("mark", help="set a paper's state")
    sp.add_argument("paper_id")
    sp.add_argument("state", choices=["pending", "read", "skipped", "deferred"])
    sp.set_defaults(func=cmd_mark)

    sp = sub.add_parser("status", help="corpus and queue summary")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("doctor", help="check local prerequisites without model or network calls")
    sp.add_argument("--ai", action="store_true",
                    help="explicitly test the selected AI with a model call (may use quota)")
    sp.add_argument("--sources", action="store_true",
                    help="also contact the optional scholarly source services")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("reader-doc", help="write the reader artifact's JSON for a day")
    sp.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    sp.set_defaults(func=cmd_reader_doc)

    sp = sub.add_parser("sync-queue", help="write the upcoming queue for the cloud job")
    sp.add_argument("--limit", type=int, default=120, help="how many papers to sync")
    sp.set_defaults(func=cmd_sync_queue)

    sp = sub.add_parser("app", help="open the desktop reader")
    sp.add_argument("--next", action="store_true",
                    help="open straight onto the next unread paper")
    sp.add_argument("--restart", action="store_true",
                    help="save drafts and safely restart the running reader")
    sp.add_argument("--paper", metavar="ID",
                    help="open this paper, in the running reader if there is one")
    sp.set_defaults(func=cmd_app)

    sp = sub.add_parser("followups", help="what cites a paper across the field, judged")
    sp.add_argument("paper_ids", nargs="*")
    sp.add_argument("--list", default=None, help="every paper in a reading list")
    sp.add_argument("--ahead", type=int, default=0,
                    help="the next N listed or queued papers never asked about")
    sp.add_argument("--with-cites", action="store_true",
                    help="analyse the references first when a paper has none")
    sp.set_defaults(func=cmd_followups)

    sp = sub.add_parser("close-read",
                        help="walk a paper's method and experiments section by section")
    sp.add_argument("paper_ids", nargs="*")
    sp.add_argument("--list", default=None, help="every paper in a reading list ('all' for all)")
    sp.add_argument("--jobs", type=int, default=3, help="how many to write at once")
    sp.add_argument("--rewrite", action="store_true",
                    help="also redo ones written under an older specification")
    sp.add_argument("--force", action="store_true", help="redo every paper given")
    sp.set_defaults(func=cmd_close_read)

    sp = sub.add_parser("fonts", help="download the typefaces the reader ships with")
    sp.set_defaults(func=cmd_fonts)

    sp = sub.add_parser(
        "web-assets", help="download the formula, code and diagram renderers"
    )
    sp.set_defaults(func=cmd_web_assets)

    sp = sub.add_parser("storage", help="disk use by folder and by list, and what is prunable")
    sp.add_argument("--cache-days", type=int, default=30,
                    help="HTTP cache entries older than this count as prunable (default 30)")
    sp.set_defaults(func=cmd_storage)

    sp = sub.add_parser(
        "prune", help="delete old HTTP cache and unclaimed papers' files (dry run by default)"
    )
    sp.add_argument("--cache-days", type=int, default=30,
                    help="delete HTTP cache entries older than this many days (default 30)")
    sp.add_argument("--yes", action="store_true", help="actually delete; without it, only list")
    sp.add_argument("--vacuum", action="store_true", help="also compact papers.db afterwards")
    sp.set_defaults(func=cmd_prune)

    sp = sub.add_parser("list-export",
                        help="pack a reading list and its analyses into one file to share")
    sp.add_argument("list_id")
    sp.add_argument("-o", "--out", default=None, help="the .zip to write")
    sp.add_argument("--no-notes", action="store_true", help="leave out notes and Q&A")
    sp.add_argument("--with-pdfs", action="store_true", default=True,
                    help="include all local PDFs (default)")
    sp.add_argument("--without-pdfs", action="store_false", dest="with_pdfs",
                    help="export a smaller package using verified download URLs instead")
    sp.set_defaults(func=cmd_list_export)

    sp = sub.add_parser("list-import", help="bring in a list exported with list-export")
    sp.add_argument("path")
    sp.add_argument("--replace", action="store_true",
                    help="overwrite analyses and files that already exist here")
    sp.add_argument("--no-pdfs", action="store_true",
                    help="do not download the PDFs from their verified URLs")
    sp.set_defaults(func=cmd_list_import)

    sp = sub.add_parser("survey", help="a survey of the field a reading list covers")
    sp.add_argument("list_id")
    sp.add_argument("--force", action="store_true",
                    help="replace a survey that was edited by hand")
    sp.set_defaults(func=cmd_survey)

    sp = sub.add_parser("cite-links",
                        help="which of a paper's references and citing works cite each other")
    sp.add_argument("paper_ids", nargs="*")
    sp.add_argument("--list", default=None, help="every paper in a reading list")
    sp.set_defaults(func=cmd_cite_links)

    sp = sub.add_parser("share", help="a page about one or more papers, to share")
    sp.add_argument("action", choices=("draft", "build"))
    sp.add_argument("ids", nargs="*",
                    help="draft: paper ids, in reading order; build: the draft's slug")
    sp.add_argument("--slug", default=None, help="folder name under data/share/")
    sp.add_argument("--compare", action="store_true",
                    help="draft: have the model write the side-by-side from the dives")
    sp.set_defaults(func=cmd_share)

    sp = sub.add_parser("backfill", help="fill in missing authors, abstracts and ids")
    sp.add_argument("--limit", type=int, default=2000)
    sp.set_defaults(func=cmd_backfill)

    sp = sub.add_parser("dive-ahead", help="pre-write deep dives for the next N papers")
    sp.add_argument("n", nargs="?", type=int, default=3)
    sp.add_argument("--paper", default=None,
                    help="write one specific paper instead, read or not")
    sp.add_argument("--list", default=None,
                help="take the next N from a reading list, or 'all' for every list")
    sp.add_argument("--rewrite", action="store_true",
                    help="rewrite dives written before the current spec, in queue order")
    sp.add_argument("--jobs", type=int, default=1,
                    help="how many dives to write at once (each one waits on the model)")
    sp.set_defaults(func=cmd_dive_ahead)

    sp = sub.add_parser("import-list", help="import a bibliography as a reading list")
    sp.add_argument("name", help='display name, e.g. "Quantisation refs"')
    sp.add_argument("--file", required=True, help="text file holding the references")
    sp.add_argument("--slug", default=None, help="list id (default: from the name)")
    sp.set_defaults(func=cmd_import_list)

    from paper_daily import llm

    sp = sub.add_parser("llm", help="configure AI profiles, task routes or test a connection")
    sp.add_argument("--backend", choices=["none", "auto", *llm.backend_names()])
    sp.add_argument("--profile", help="create, edit or test a named AI profile")
    sp.add_argument(
        "--use", metavar="PROFILE", help="select a profile as the default or for --for-task"
    )
    sp.add_argument("--for-task", choices=llm.TASKS, help="research feature to route or test")
    sp.add_argument("--follow-default", action="store_true", help="remove the route for --for-task")
    sp.add_argument(
        "--list", dest="list_profiles", action="store_true", help="list profiles and task routes"
    )
    sp.add_argument("--model", help="model ID provided by the selected service")
    sp.add_argument("--key", help="API key, stored locally in data/llm.json")
    sp.add_argument("--key-env", help="environment variable holding this profile's API key")
    sp.add_argument("--base-url", dest="base_url", help="API base URL, including /v1 when required")
    sp.add_argument("--max-tokens", type=int, help="maximum output tokens per request")
    sp.add_argument("--token-parameter", choices=["max_completion_tokens", "max_tokens"])
    sp.add_argument("--requires-key", action=argparse.BooleanOptionalAction, default=None,
                    help="use --no-requires-key for a local service without authentication")
    sp.add_argument("--test", action="store_true", help="send one small request and report")
    sp.set_defaults(func=cmd_llm)

    sp = sub.add_parser("list-add", help="add one paper to an existing reading list")
    sp.add_argument("list_id")
    sp.add_argument("citation", nargs="?", help="a citation, a title, or an arXiv id")
    sp.add_argument("--file", help="read the reference(s) from a file instead")
    sp.add_argument("--doi", help="resolve by DOI instead of searching for the title")
    sp.add_argument("--create", metavar="NAME",
                    help="create the list under this display name if it does not exist")
    sp.set_defaults(func=cmd_list_add)

    sp = sub.add_parser("list-remove", help="drop a paper from a reading list")
    sp.add_argument("list_id")
    sp.add_argument("paper_id")
    sp.set_defaults(func=cmd_list_remove)

    sp = sub.add_parser("find", help="search the whole corpus, not just the queue")
    sp.add_argument("text")
    sp.add_argument("-n", type=int, default=15)
    sp.set_defaults(func=cmd_find)

    sp = sub.add_parser("queue-add", help="put a paper into the reading queue by hand")
    sp.add_argument("paper", help="paper id, or words from the title")
    sp.add_argument("--reason", default="你自己加進來的")
    sp.add_argument("--back", action="store_true", help="add after the queue, not before it")
    sp.add_argument("--first", action="store_true", help="take the best title match")
    sp.set_defaults(func=cmd_queue_add)

    sp = sub.add_parser("queue-remove", help="take a paper out of the reading queue")
    sp.add_argument("paper_id")
    sp.set_defaults(func=cmd_queue_remove)

    sp = sub.add_parser("resolve-missing",
                        help="retry the PDF hunt for papers that have no route to one")
    sp.add_argument("n", nargs="?", type=int, default=20)
    sp.set_defaults(func=cmd_resolve_missing)

    sp = sub.add_parser("venues", help="find where preprint-only papers were published")
    sp.add_argument("paper_ids", nargs="*")
    sp.add_argument("--list", default=None,
                    help="every paper in a reading list, or 'all' for every list")
    sp.set_defaults(func=cmd_venues)

    sp = sub.add_parser(
        "analyze", help="make everything a paper is missing: PDF, dive, 承先, 啟後"
    )
    sp.add_argument("paper_ids", nargs="*")
    sp.add_argument("--list", default=None,
                    help="every paper in a reading list, or 'all' for every list")
    sp.add_argument("--jobs", type=int, default=3, help="papers analysed at once")
    sp.add_argument("--retry", action="store_true",
                    help="try again the steps that failed before (e.g. a missing PDF)")
    sp.add_argument("--ahead", type=int, metavar="N", default=0,
                    help="the next N unread papers still missing something, in reading "
                    "order: the main queue, or --list ID / --list all")
    sp.add_argument("--scheduled", action="store_true",
                    help="the nightly run: as often and as many as the reader's 分析排程 "
                    "settings say, recording what it finished so the reader can announce it")
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser("resources", help="find a paper's code, data and models")
    sp.add_argument("paper_ids", nargs="*")
    sp.add_argument("--list", default=None,
                    help="every paper in a reading list, or 'all' for every list")
    sp.add_argument("--force", action="store_true",
                    help="look again at papers already checked")
    sp.set_defaults(func=cmd_resources)

    sp = sub.add_parser("repdf", help="read a paper from another PDF, notes re-anchored")
    sp.add_argument("paper_id")
    sp.add_argument("--url", default=None, help="the PDF to use (default: its arXiv copy)")
    sp.add_argument("--file", default=None, help="a PDF on this machine to use instead")
    sp.set_defaults(func=cmd_repdf)

    sp = sub.add_parser("cites", help="what each reference is doing in a paper")
    sp.add_argument("paper_id", nargs="?")
    sp.add_argument("--list", default=None,
                    help="every paper in a reading list that has no analysis yet")
    sp.add_argument("--limit", type=int, default=120,
                    help="how many cited works with a citing sentence to analyse")
    sp.set_defaults(func=cmd_cites)

    sp = sub.add_parser("cites-ahead", help="analyse citations for the next N papers")
    sp.add_argument("n", nargs="?", type=int, default=2)
    sp.add_argument("--rewrite", action="store_true",
                    help="redo papers analysed under an older specification")
    sp.set_defaults(func=cmd_cites_ahead)

    sp = sub.add_parser("lists", help="show the reading lists")
    sp.set_defaults(func=cmd_lists)

    sp = sub.add_parser("lineage", help="record in-corpus references for queued papers")
    sp.add_argument("n", nargs="?", type=int, default=200)
    sp.set_defaults(func=cmd_lineage)

    sp = sub.add_parser("set-dive", help="attach a deep dive to a paper by id")
    sp.add_argument("paper_id")
    sp.add_argument("--file", default=None, help="markdown file (default: read stdin)")
    sp.set_defaults(func=cmd_set_dive)

    sp = sub.add_parser("prefetch", help="download + extract the next N queued papers")
    sp.add_argument("n", nargs="?", type=int, default=20)
    sp.add_argument("--force", action="store_true", help="re-extract papers already done")
    sp.add_argument("--list", default=None,
                help="fetch a reading list instead of the queue, or 'all' for every list")
    sp.set_defaults(func=cmd_prefetch)

    sp = sub.add_parser("sync-read", help="mark the first N pending papers read")
    sp.add_argument("n", type=int)
    sp.set_defaults(func=cmd_sync_read)

    sp = sub.add_parser("export", help="dump the upcoming queue as JSON")
    sp.add_argument("n", nargs="?", type=int, default=50)
    sp.set_defaults(func=cmd_export)

    return p


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to a legacy codepage; paper titles are full of
    # characters it cannot encode, and a print() crash would kill a scheduled run.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    if args.func not in (cmd_app, cmd_llm):
        from paper_daily import llm

        with llm.connection_scope():
            return args.func(args)
    return args.func(args)
