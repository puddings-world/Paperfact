"""Crawl -> enrich -> score -> queue.

Each stage is idempotent and resumable: HTTP responses are cached on disk, papers are
upserted by id, and enrichment only overwrites columns it actually has values for. A
run that dies halfway can simply be run again.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable

from paper_daily import queue as qmod
from paper_daily.config import SETTINGS, VENUES
from paper_daily.enrich import s2
from paper_daily.rank.score import score_all
from paper_daily.sources import arxiv, neurips, pmlr, virtual_site
from paper_daily.store import connect, counts_by_venue_year, now, title_key, upsert_papers

Log = Callable[[str], None]

# First year the conference "virtual" sites carry a full paper listing. Before this,
# an absent roster means the site did not exist; from this year on, it means the
# programme has not been announced yet -- two situations needing opposite handling.
VIRTUAL_SITE_ERA = 2018


def _noop(msg: str) -> None:
    pass


def crawl(years: list[int], venues: list[str] | None = None, log: Log = _noop) -> dict:
    """Build the roster from the authoritative sources, newest year first.

    The virtual site is the roster of record because it is the only source that is
    both accepted-papers-only and available for the current year. Proceedings crawls
    run on top of it to attach real PDF links, and to cover years before the virtual
    sites existed.
    """
    venues = venues or list(VENUES)
    totals: dict[str, int] = {}
    with connect() as conn:
        for year in sorted(years, reverse=True):
            for venue in venues:
                rows = virtual_site.fetch_roster(venue, year)
                src = "virtual"

                proceedings: list[dict] = []
                if venue == "ICML":
                    proceedings = pmlr.crawl_year(year)
                elif venue == "NeurIPS":
                    proceedings = neurips.crawl_year(year)

                if proceedings:
                    rows = _merge_proceedings(rows, proceedings)
                    src = "virtual+" + proceedings[0]["source"]
                elif not rows and year < VIRTUAL_SITE_ERA:
                    # Early ICLR has neither a virtual site nor an open proceedings
                    # site, so Semantic Scholar is the only roster available. It is
                    # looser -- some workshop papers slip in -- but the alternative
                    # is losing those years entirely.
                    rows = _s2_roster(venue, year)
                    src = "s2"
                    if not rows:
                        continue
                elif not rows:
                    # From VIRTUAL_SITE_ERA on, an empty roster means the programme
                    # is genuinely not announced yet. Falling back to S2 here would
                    # invent a year: a NeurIPS 2026 query returns ~90 mis-filed
                    # preprints, and they would land at the very front of a
                    # newest-first queue.
                    log("  " + venue + " " + str(year) + ": not published yet, skipped")
                    continue

                n = upsert_papers(conn, iter(rows))
                totals[venue + " " + str(year)] = n
                log("  " + venue + " " + str(year) + ": " + str(n) + " papers (" + src + ")")
        conn.commit()
    return totals


def _s2_roster(venue: str, year: int) -> list[dict]:
    """Last-resort roster built straight from Semantic Scholar.

    Restricted to the exact year (no +/- window) because without an authoritative
    roster to match against there is nothing to stop a neighbouring year's papers
    from being filed here.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for p in s2.bulk_venue_year(venue, year, window=0):
        title = (p.get("title") or "").strip()
        key = title_key(title)
        if not key or key in seen:
            continue
        seen.add(key)
        ext = p.get("externalIds") or {}
        oa = p.get("openAccessPdf") or {}
        arxiv_id = ext.get("ArXiv")
        names = [a.get("name") for a in (p.get("authors") or []) if a.get("name")]
        out.append(
            {
                "id": venue + ":" + str(year) + ":s" + str(p["paperId"])[:16],
                "venue": venue,
                "year": year,
                "title": title,
                "title_key": key,
                "authors_json": json.dumps(names, ensure_ascii=False),
                "abstract": p.get("abstract"),
                "pdf_url": oa.get("url"),
                "s2_id": p.get("paperId"),
                "arxiv_id": str(arxiv_id) if arxiv_id else None,
                "doi": ext.get("DOI"),
                "citation_count": p.get("citationCount"),
                "influential_count": p.get("influentialCitationCount"),
                "reference_count": p.get("referenceCount"),
                "source": "s2",
                "crawled_at": now(),
            }
        )
    return out


def _merge_proceedings(roster: list[dict], proceedings: list[dict]) -> list[dict]:
    """Prefer proceedings rows, which carry authors and a real PDF link, but keep any
    roster paper the proceedings lack -- the virtual site is usually months ahead."""
    by_key = {r["title_key"]: r for r in roster}
    out: list[dict] = []
    for p in proceedings:
        match = by_key.pop(p["title_key"], None)
        if match:
            p = dict(p)
            p["page_url"] = p.get("page_url") or match.get("page_url")
        out.append(p)
    out.extend(by_key.values())
    return out


def enrich(years: list[int], venues: list[str] | None = None, log: Log = _noop) -> dict:
    """Attach abstracts, citation counts, author ids and award labels."""
    venues = venues or list(VENUES)
    stats = {"matched": 0, "awarded": 0, "failed": 0}
    with connect() as conn:
        for year in sorted(years, reverse=True):
            for venue in venues:
                try:
                    got = _enrich_venue_year(conn, venue, year, log)
                except Exception as e:
                    # One venue-year failing (almost always a Semantic Scholar 429)
                    # must not abandon the run: author strength and scoring happen
                    # after this loop, so an exception here would leave the corpus
                    # with no scores and no queue at all. Re-running enrich later
                    # picks the missing year up, cheaply, from the HTTP cache.
                    log(f"  {venue} {year}: FAILED ({type(e).__name__}) -- skipped")
                    stats["failed"] += 1
                    continue
                for k in ("matched", "awarded"):
                    stats[k] += got.get(k, 0)
                conn.commit()
        _resolve_author_strength(conn, log)
        conn.commit()
    return stats


def _enrich_venue_year(conn: sqlite3.Connection, venue: str, year: int, log: Log) -> dict:
    existing = {
        r["title_key"]: r["id"]
        for r in conn.execute(
            "SELECT id, title_key FROM papers WHERE venue=? AND year=?", (venue, year)
        )
    }
    if not existing:
        return {}

    # Semantic Scholar frequently holds several records for one paper -- the arXiv
    # preprint and the proceedings version -- and both match the same roster title.
    # Applied in arrival order the last one wins, which can overwrite a published
    # record's 300 citations with a preprint's 3. Keep only the best record per title.
    best: dict[str, dict] = {}
    for p in s2.bulk_venue_year(venue, year):
        key = title_key(p.get("title") or "")
        if key not in existing:
            continue  # workshop and non-accepted noise the roster correctly excludes
        prev = best.get(key)
        if prev is None:
            best[key] = p
            continue
        # Take the higher-citation record, but fill its gaps from the other one.
        # Picking a winner outright lost data: some duplicates are citation-rich
        # stubs with no author list, which left 425 queued papers showing no authors
        # at all even though Semantic Scholar had them.
        hi, lo = (
            (p, prev)
            if (p.get("citationCount") or 0) > (prev.get("citationCount") or 0)
            else (prev, p)
        )
        for field in ("abstract", "authors", "externalIds", "openAccessPdf",
                      "referenceCount", "influentialCitationCount"):
            if not hi.get(field) and lo.get(field):
                hi[field] = lo[field]
        best[key] = hi

    matched = len(best)
    updates: list[tuple] = []
    author_links: list[tuple[str, str, int]] = []
    author_rows: dict[str, tuple] = {}

    for key, p in best.items():
        pid = existing[key]
        ext = p.get("externalIds") or {}
        oa = p.get("openAccessPdf") or {}
        arxiv_id = ext.get("ArXiv")
        names = [a.get("name") for a in (p.get("authors") or []) if a.get("name")]
        updates.append(
            (
                p.get("paperId"),
                p.get("abstract"),
                p.get("citationCount"),
                p.get("influentialCitationCount"),
                p.get("referenceCount"),
                str(arxiv_id) if arxiv_id else None,
                ext.get("DOI"),
                oa.get("url"),
                # A virtual-site roster has no author list at all, so S2 supplies it.
                json.dumps(names, ensure_ascii=False) if names else None,
                now(),
                pid,
            )
        )
        for i, a in enumerate(p.get("authors") or []):
            aid = a.get("authorId")
            if aid:
                author_links.append((pid, aid, i))
                author_rows.setdefault(aid, (aid, a.get("name")))

    conn.executemany(
        "UPDATE papers SET s2_id=?, abstract=COALESCE(abstract,?), citation_count=?, "
        "influential_count=?, reference_count=?, arxiv_id=COALESCE(arxiv_id,?), "
        "doi=COALESCE(doi,?), pdf_url=COALESCE(pdf_url,?), "
        "authors_json=CASE WHEN authors_json IN ('','[]') THEN COALESCE(?, authors_json) "
        "ELSE authors_json END, enriched_at=? WHERE id=?",
        updates,
    )
    conn.executemany(
        "INSERT OR IGNORE INTO authors(s2_author_id, name) VALUES (?,?)",
        list(author_rows.values()),
    )
    conn.executemany(
        "INSERT OR IGNORE INTO paper_authors(paper_id, s2_author_id, position) VALUES (?,?,?)",
        author_links,
    )

    awards = virtual_site.fetch_awards(venue, year)
    awarded = 0
    if awards:
        pairs = [(v, existing[k]) for k, v in awards.items() if k in existing]
        conn.executemany("UPDATE papers SET award=? WHERE id=?", pairs)
        awarded = len(pairs)

    log(
        "  "
        + venue
        + " "
        + str(year)
        + ": matched "
        + str(matched)
        + "/"
        + str(len(existing))
        + ", awards "
        + str(awarded)
    )
    return {"matched": matched, "awarded": awarded}


def _resolve_author_strength(conn: sqlite3.Connection, log: Log) -> None:
    """Fetch h-index for authors we have not looked up, then fold onto papers.

    Author strength is the MAX h-index on the paper, not the mean. A paper with one
    established author and six students is a strong-group paper, and averaging would
    erase exactly the signal we want for papers too new to have citations yet.
    """
    pending = [
        r["s2_author_id"]
        for r in conn.execute("SELECT s2_author_id FROM authors WHERE fetched_at IS NULL")
    ]
    if pending:
        log("  authors: fetching h-index for " + str(len(pending)))
        for i in range(0, len(pending), 1000):
            try:
                batch = s2.author_batch(pending[i : i + 1000])
            except Exception as e:
                # Authors whose lookup fails stay unfetched and are retried by the
                # next enrich; losing a chunk costs a little ranking signal, while
                # raising here would cost the entire scoring pass.
                log(f"  authors: chunk {i // 1000} failed ({type(e).__name__})")
                continue
            for a in batch:
                conn.execute(
                    "UPDATE authors SET name=COALESCE(?,name), citation_count=?, h_index=?, "
                    "paper_count=?, fetched_at=? WHERE s2_author_id=?",
                    (
                        a.get("name"),
                        a.get("citationCount"),
                        a.get("hIndex"),
                        a.get("paperCount"),
                        now(),
                        a.get("authorId"),
                    ),
                )
            conn.commit()

    conn.execute(
        "UPDATE papers SET author_strength = ("
        "  SELECT MAX(COALESCE(a.h_index,0)) FROM paper_authors pa "
        "  JOIN authors a ON a.s2_author_id = pa.s2_author_id WHERE pa.paper_id = papers.id"
        ") WHERE EXISTS (SELECT 1 FROM paper_authors pa WHERE pa.paper_id = papers.id)"
    )


def resolve_queued(limit: int = 50, log: Log = _noop) -> int:
    """Fill in Semantic Scholar data for queued papers the venue search missed.

    Only the queue is worth this: it costs one request per paper, and the papers that
    need it are almost all from the newest conference year, where the venue search
    matches almost nothing. Without it those papers have no arXiv id, and with no
    arXiv id there is no PDF at all -- OpenReview 403s -- so the first papers the
    reader ever opens would have no text.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT p.id, p.title FROM queue q JOIN papers p ON p.id = q.paper_id "
            # 'delivered' belongs here as much as 'pending': a paper handed over
            # before it was resolved is precisely the one being read tonight, and
            # leaving it out meant the current paper was the one without text.
            "WHERE q.state != 'skipped' AND ("
            "  p.s2_id IS NULL"
            # Missing authors earns a lookup of its own: the bulk venue search can
            # match a paper and still leave the author list empty, and a row with no
            # authors reads as broken however good its ranking is.
            "  OR p.authors_json IS NULL OR p.authors_json IN ('', '[]')"
            "  OR p.abstract IS NULL) "
            "ORDER BY CASE q.state WHEN 'delivered' THEN 0 ELSE 1 END, q.rank LIMIT ?",
            (limit,),
        ).fetchall()
        if not rows:
            return 0

        resolved = 0
        by_arxiv = 0
        for r in rows:
            m = s2.match_title(r["title"])
            if not m:
                # Not in Semantic Scholar at all. arXiv is the only remaining route
                # to a PDF, since OpenReview 403s; record just the id.
                aid = arxiv.match_title(r["title"])
                if aid:
                    conn.execute(
                        "UPDATE papers SET arxiv_id=COALESCE(arxiv_id,?), enriched_at=? "
                        "WHERE id=?",
                        (aid, now(), r["id"]),
                    )
                    by_arxiv += 1
                continue
            ext = m.get("externalIds") or {}
            oa = m.get("openAccessPdf") or {}
            arxiv_id = ext.get("ArXiv")
            names = [a.get("name") for a in (m.get("authors") or []) if a.get("name")]
            conn.execute(
                "UPDATE papers SET s2_id=?, abstract=COALESCE(abstract,?), "
                "citation_count=COALESCE(citation_count,?), "
                "influential_count=COALESCE(influential_count,?), "
                "reference_count=COALESCE(reference_count,?), "
                "arxiv_id=COALESCE(arxiv_id,?), doi=COALESCE(doi,?), "
                "pdf_url=COALESCE(pdf_url,?), "
                "authors_json=CASE WHEN authors_json IN ('','[]') OR authors_json IS NULL "
                "             THEN COALESCE(?, authors_json) ELSE authors_json END, "
                "enriched_at=? WHERE id=?",
                (
                    m.get("paperId"), m.get("abstract"), m.get("citationCount"),
                    m.get("influentialCitationCount"), m.get("referenceCount"),
                    str(arxiv_id) if arxiv_id else None, ext.get("DOI"), oa.get("url"),
                    json.dumps(names, ensure_ascii=False) if names else None,
                    now(), r["id"],
                ),
            )
            resolved += 1
            if resolved % 10 == 0:
                conn.commit()
                log(f"  resolved {resolved}/{len(rows)}")
        conn.commit()
        log(f"  resolved {resolved} of {len(rows)} unmatched queued papers"
            + (f" (+{by_arxiv} arXiv-only)" if by_arxiv else ""))
        return resolved


def backfill_conference_details(limit: int = 2000, log: Log = _noop) -> int:
    """Fill authors, abstract and the official topic from the conference paper page.

    Faster and better than Semantic Scholar for the newest year, which is where the
    gaps are: the page is not rate-limited, and it carries the programme's own topic
    keywords, which S2 does not have at all. One request per paper, so it is scoped
    to queued papers that are actually missing something.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT p.id, p.page_url, p.authors_json, p.abstract FROM queue q "
            "JOIN papers p ON p.id = q.paper_id "
            "WHERE q.state != 'skipped' AND p.page_url LIKE '%/virtual/%' AND ("
            "  p.authors_json IS NULL OR p.authors_json IN ('', '[]')"
            "  OR p.abstract IS NULL) "
            "ORDER BY q.rank LIMIT ?",
            (limit,),
        ).fetchall()
        if not rows:
            return 0

        filled = 0
        for i, r in enumerate(rows, 1):
            detail = virtual_site.fetch_paper_detail(r["page_url"])
            if not detail:
                continue
            conn.execute(
                "UPDATE papers SET "
                "authors_json = CASE WHEN authors_json IS NULL OR authors_json IN ('','[]') "
                "               THEN COALESCE(?, authors_json) ELSE authors_json END, "
                "abstract = COALESCE(abstract, ?), topic = COALESCE(topic, ?) WHERE id = ?",
                (
                    json.dumps(detail["authors"], ensure_ascii=False)
                    if detail.get("authors") else None,
                    detail.get("abstract"),
                    detail.get("keywords"),
                    r["id"],
                ),
            )
            filled += 1
            if filled % 25 == 0:
                conn.commit()
                log(f"  conference pages: {i}/{len(rows)}")
        conn.commit()
        log(f"  conference pages: filled {filled} of {len(rows)}")
        return filled


def rank_and_queue(per_year: int | None = None, log: Log = _noop) -> dict:
    with connect() as conn:
        n = score_all(conn, SETTINGS.weights)
        log("  scored " + str(n) + " papers")
        res = qmod.build(conn, per_year=per_year)
        log("  queued " + str(res["queued"]) + " (+" + str(res["canon"]) + " canon)")
        return {"scored": n, **res}


def build_lineage(limit: int = 200, log: Log = _noop) -> int:
    """Record in-corpus references for queued and listed papers that have none yet.

    Lineage is the point of the queue -- reading an idea back to where it came from
    rather than down a ranked list -- but the graph only grew one paper at a time, at
    the moment of delivery, so it was empty exactly when it was needed. This walks
    ahead of the reading instead, one request per paper, newest-first.

    Reading lists need it more than the queue does, and used to be excluded: a list
    is one topic, so its papers cite each other, and the edges between them are the
    shape of that literature. The venue fence in `queue.build` keeps list papers out
    of the nightly ranking; it is not a reason to leave them out of the graph.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT p.id, p.s2_id FROM papers p "
            "WHERE p.s2_id IS NOT NULL "
            "  AND NOT EXISTS (SELECT 1 FROM refs r WHERE r.paper_id = p.id) "
            "  AND (EXISTS (SELECT 1 FROM list_papers lp WHERE lp.paper_id = p.id) "
            "       OR EXISTS (SELECT 1 FROM queue q WHERE q.paper_id = p.id "
            "                  AND q.state != 'skipped')) "
            "ORDER BY EXISTS (SELECT 1 FROM list_papers lp WHERE lp.paper_id = p.id) DESC, "
            "  COALESCE((SELECT q.rank FROM queue q WHERE q.paper_id = p.id), 1e9) "
            "LIMIT ?",
            (limit,),
        ).fetchall()
        if not rows:
            return 0

        by_s2 = {
            r["s2_id"]: r["id"]
            for r in conn.execute("SELECT id, s2_id FROM papers WHERE s2_id IS NOT NULL")
        }

        edges_total = 0
        for i, r in enumerate(rows, 1):
            refs = s2.references(r["s2_id"])
            edges = [
                (r["id"], by_s2[ref["paperId"]], 1 if ref.get("isInfluential") else 0)
                for ref in refs
                if ref.get("paperId") in by_s2 and by_s2[ref["paperId"]] != r["id"]
            ]
            conn.executemany(
                "INSERT OR IGNORE INTO refs(paper_id, ref_paper_id, influential) "
                "VALUES (?,?,?)",
                edges,
            )
            edges_total += len(edges)
            if i % 20 == 0:
                conn.commit()
                log(f"  lineage: {i}/{len(rows)} papers, {edges_total} edges")
        conn.commit()
        log(f"  lineage: {len(rows)} papers, {edges_total} in-corpus edges")
        return edges_total


def lineage_of(conn: sqlite3.Connection, paper_id: str, limit: int = 12) -> dict:
    """What a paper builds on, and what in the corpus builds on it."""
    ancestors = conn.execute(
        "SELECT p.id, p.title, p.venue, p.year, p.award, r.influential, "
        "       COALESCE(q.state,'') state "
        "FROM refs r JOIN papers p ON p.id = r.ref_paper_id "
        "LEFT JOIN queue q ON q.paper_id = p.id "
        "WHERE r.paper_id = ? "
        "ORDER BY r.influential DESC, p.score DESC LIMIT ?",
        (paper_id, limit),
    ).fetchall()
    descendants = conn.execute(
        "SELECT p.id, p.title, p.venue, p.year, p.award, r.influential, "
        "       COALESCE(q.state,'') state "
        "FROM refs r JOIN papers p ON p.id = r.paper_id "
        "LEFT JOIN queue q ON q.paper_id = p.id "
        "WHERE r.ref_paper_id = ? ORDER BY p.score DESC LIMIT ?",
        (paper_id, limit),
    ).fetchall()
    return {"ancestors": ancestors, "descendants": descendants}


def expand_lineage(paper_id: str, log: Log = _noop) -> list[str]:
    """Record which of this paper's references are in the corpus, then queue the best
    of them as companions. Called after delivery, so the graph only grows along the
    path actually being read.
    """
    with connect() as conn:
        row = conn.execute("SELECT s2_id FROM papers WHERE id=?", (paper_id,)).fetchone()
        if not row or not row["s2_id"]:
            return []
        refs = s2.references(row["s2_id"])
        by_s2 = {
            r["s2_id"]: r["id"]
            for r in conn.execute("SELECT id, s2_id FROM papers WHERE s2_id IS NOT NULL")
        }
        edges = [
            (paper_id, by_s2[r["paperId"]], 1 if r.get("isInfluential") else 0)
            for r in refs
            if r.get("paperId") in by_s2
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO refs(paper_id, ref_paper_id, influential) VALUES (?,?,?)",
            edges,
        )
        log("  lineage: " + str(len(edges)) + " in-corpus references")
        return qmod.add_companions(conn, paper_id, limit=SETTINGS.companions_per_day)


def resolve_missing(limit: int = 20, log: Log = _noop) -> int:
    """Try again for papers with no route to their original.

    A lookup that failed is not a paper that cannot be found. Semantic Scholar refuses
    with 429 and arXiv with 406 whenever either is busy, and the import that hit one
    of those wrote a row with no PDF and no year and never looked again -- a Nature
    paper whose open-access PDF is one search away sat in a list reading "unknown 0".

    So this re-runs the whole chain over whatever is still missing, and the nightly
    job calls it. Papers that genuinely have no free original (a paywalled journal, a
    GitHub project that is not a paper) cost one lookup a night and are honestly
    marked as unavailable in their dive.
    """
    from paper_daily import resolve
    from paper_daily.enrich import s2

    with connect() as conn:
        rows = conn.execute(
            "SELECT p.* FROM papers p WHERE p.pdf_url IS NULL AND p.arxiv_id IS NULL "
            # Lists first: the queue has its own resolver, and a list paper with no
            # PDF is the one actually on screen in front of someone.
            "ORDER BY EXISTS(SELECT 1 FROM list_papers lp WHERE lp.paper_id = p.id) DESC, "
            "         EXISTS(SELECT 1 FROM queue q WHERE q.paper_id = p.id "
            "                AND q.state != 'skipped') DESC, p.id LIMIT ?",
            (limit,),
        ).fetchall()
        if not rows:
            log("  nothing missing a PDF")
            return 0

        fixed = 0
        for r in rows:
            row = dict(r)
            if not row.get("s2_id"):
                # Worth one more try before the others: an S2 match carries the arXiv
                # id, the abstract and the citation count in a single request.
                match = s2.match_title(row["title"])
                if match:
                    ext = match.get("externalIds") or {}
                    oa = match.get("openAccessPdf") or {}
                    row["s2_id"] = match.get("paperId")
                    row["arxiv_id"] = row["arxiv_id"] or (
                        str(ext["ArXiv"]) if ext.get("ArXiv") else None
                    )
                    row["pdf_url"] = row["pdf_url"] or oa.get("url")
                    row["abstract"] = row["abstract"] or match.get("abstract")
                    row["doi"] = row["doi"] or ext.get("DOI")

            row, found = resolve.fill_gaps(row)
            if not found and not row.get("s2_id"):
                log(f"  still nothing: {row['title'][:60]}")
                continue
            conn.execute(
                "UPDATE papers SET pdf_url=?, arxiv_id=?, doi=?, s2_id=?, venue=?, "
                "year=?, abstract=COALESCE(?, abstract), authors_json=?, "
                "citation_count=COALESCE(?, citation_count), title=?, title_key=? "
                "WHERE id=?",
                (
                    row.get("pdf_url"), row.get("arxiv_id"), row.get("doi"),
                    row.get("s2_id"), row.get("venue") or "unknown", row.get("year") or 0,
                    row.get("abstract"), row.get("authors_json") or "[]",
                    row.get("citation_count"), row["title"],
                    row.get("title_key") or r["title_key"], row["id"],
                ),
            )
            conn.commit()
            if row.get("pdf_url") or row.get("arxiv_id"):
                fixed += 1
                log(f"  found via {','.join(found) or 's2'}: {row['title'][:56]}")
                # A dive written before the original was found says so, at length:
                # "this pack has only a title, so I cannot tell you what it proved".
                # Clearing the spec marks it stale, and the rewrite pass that already
                # exists picks it up and writes it again from the full text.
                if conn.execute(
                    "UPDATE dives SET spec=NULL WHERE paper_id=? AND spec IS NOT NULL",
                    (row["id"],),
                ).rowcount:
                    log("    its deep dive was written without the paper; queued a rewrite")
                conn.commit()
            else:
                log(f"  metadata only ({','.join(found)}): {row['title'][:52]}")
        return fixed


def status() -> dict:
    with connect() as conn:
        return {
            "by_venue_year": [dict(r) for r in counts_by_venue_year(conn)],
            "queue": qmod.stats(conn),
            "total": conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"],
        }
