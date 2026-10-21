"""The phone reader: a handful of papers packed into one page to read away from here.

The desktop reader is the primary interface and it needs the machine. This builds a
page that does not: the paper's own PDF in a built-in viewer, the deep dive with its
section-by-section reading and the paper's figures set into it, the citation
analysis, the survey of the list the papers came from, the slide decks made for
them (to read, not to edit), and a place to write notes that come back.

What goes out is a selection, not the queue. An hour on a train is two or three
papers, and every paper in the page is a PDF to carry; `data/pocket/marked` holds
whatever was ticked on the queue screen, so rebuilding is a button rather than a
command with fifteen ids in it.

The page carried extracted text for a while instead of the PDF. Extraction is how the
pipeline reads a paper, not how a person should: a two-column surgical paper came out
with figure captions adrift, table cells as one-word paragraphs, and headings invented
from whatever line happened to be short. The PDF has none of those problems because it
is the document, and a text layer good enough to select from.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from paper_daily import cites, closeread, http, pipeline, web_assets
from paper_daily.config import DATA_DIR, PDF_DIR
from paper_daily.figures import FIG_DIR, _safe
from paper_daily.store import connect

OUT_DIR = DATA_DIR / "pocket"
POCKET_PDF_DIR = OUT_DIR / "pdf"
SLIDES_DIR = OUT_DIR / "slides"
TEMPLATE = Path(__file__).with_name("pocket_reader.html")
TYPESET = Path(__file__).with_name("typeset.js")

# Vendored rather than loaded from the CDN so the worker is same-origin: a published
# artifact serves its own files, and a cross-origin worker is the one thing its CSP
# does not clearly allow. 3.x is the last line with a UMD build and a plain global.
PDFJS_VERSION = "3.11.174"
PDFJS_FILES = ("pdf.min.js", "pdf.worker.min.js")

# A screen is not a printing press. The originals run to 27 MB because a surgical
# paper is mostly photographs at print resolution; re-encoding them at roughly retina
# density for a phone page leaves the text layer -- the part the reader selects from
# -- byte for byte the same.
PDF_DPI_THRESHOLD = 150
PDF_DPI_TARGET = 130
PDF_JPEG_QUALITY = 65


def marked_ids() -> list[str]:
    """The papers ticked on the queue screen, in the order they were ticked."""
    path = OUT_DIR / "marked.json"
    if not path.exists():
        return []
    try:
        return [str(x) for x in json.loads(path.read_text(encoding="utf-8"))]
    except (ValueError, OSError):
        return []


def set_marked(paper_ids: list[str]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "marked.json").write_text(
        json.dumps(paper_ids, ensure_ascii=False), encoding="utf-8"
    )


def has_pdf(paper_id: str) -> bool:
    """Whether the original is on disk, which decides what this paper can carry."""
    return (PDF_DIR / (_safe(paper_id) + ".pdf")).exists()


def pocket_pdf(paper_id: str) -> Path | None:
    """A copy of the paper's PDF small enough to open over mobile data."""
    src = PDF_DIR / (_safe(paper_id) + ".pdf")
    if not src.exists():
        return None

    dest = POCKET_PDF_DIR / (_safe(paper_id) + ".pdf")
    if dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime:
        return dest

    import pymupdf

    dest.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(src)
    doc.rewrite_images(
        dpi_threshold=PDF_DPI_THRESHOLD,
        dpi_target=PDF_DPI_TARGET,
        quality=PDF_JPEG_QUALITY,
        lossy=True,
    )
    doc.subset_fonts()
    doc.save(dest, garbage=4, deflate=True, deflate_images=True, clean=True)
    doc.close()
    return dest


def ensure_pdfjs() -> dict[str, str]:
    """Fetch pdf.js once into the page's own directory. Returns its files map."""
    base = f"https://cdnjs.cloudflare.com/ajax/libs/pdf.js/{PDFJS_VERSION}"
    served: dict[str, str] = {}
    for name in PDFJS_FILES:
        dest = OUT_DIR / "lib" / name
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(http.fetch(f"{base}/{name}"))
        served[f"lib/{name}"] = str(dest)
    return served


def ensure_typesetting() -> dict[str, str]:
    """KaTeX (with its fonts) and Mermaid, from the app's own copies, so the
    page typesets formulas and diagrams the way the reader does, offline."""
    web_assets.install()
    katex = web_assets.WEB_DIR / "katex"
    served = {
        "lib/katex/katex.min.js": str(katex / "katex.min.js"),
        "lib/katex/katex.min.css": str(katex / "katex.min.css"),
        "lib/mermaid.min.js": str(web_assets.WEB_DIR / "mermaid.min.js"),
    }
    # Phones all take woff2; the older formats would only double the upload.
    for font in sorted((katex / "fonts").glob("*.woff2")):
        served[f"lib/katex/fonts/{font.name}"] = str(font)
    return served


def figures_for(paper_id: str) -> list[dict]:
    index = FIG_DIR / _safe(paper_id) / "index.json"
    found = json.loads(index.read_text(encoding="utf-8")) if index.exists() else None
    if not found:
        # Only the 圖表 tab and the briefing pack extract figures, and a paper
        # added from a list may have had neither -- or an older caption rule
        # found nothing and left an empty index. The close reading's markers
        # need the renderings, so they are made here when the PDF is on disk.
        src = PDF_DIR / (_safe(paper_id) + ".pdf")
        if not src.exists():
            return []
        from paper_daily.figures import extract

        extract(paper_id, src, force=True)
        found = json.loads(index.read_text(encoding="utf-8")) if index.exists() else []
    return found


def cites_for(conn, paper_id: str) -> list[dict]:
    """The citation analysis, trimmed to what a phone screen can use.

    The stored rows carry every context sentence the extractor found; two are enough
    to show why a reference is there, and the rest is weight on a mobile connection.
    """
    out = []
    for row in cites.for_paper(conn, paper_id, "number"):
        out.append(
            {
                "key": row["ref_key"],
                "title": row["title"],
                "year": row["year"],
                "venue": row["venue"],
                "citations": row["citations"],
                "influential": row["influential"],
                "purpose": row["purpose"],
                "gist": row["gist"],
                "verdict": row["verdict"],
                "why": row["why"],
                "basis": row["basis"],
                "doi": row["doi"],
                "contexts": [c[:300] for c in row["contexts"][:2]],
            }
        )
    return out


def lineage_for(conn, paper_id: str) -> dict:
    """What this paper builds on, and what builds on it, as titles rather than ids.

    Only in-corpus papers have edges at all, so for a reading list this is the shape
    of that one literature: the dataset everything rests on, and the lines of work
    that go through it.
    """
    graph = pipeline.lineage_of(conn, paper_id)

    def pack(rows) -> list[dict]:
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "venue": r["venue"],
                "year": r["year"],
                "influential": r["influential"],
            }
            for r in rows
        ]

    return {"ancestors": pack(graph["ancestors"]), "descendants": pack(graph["descendants"])}


def context_for(conn, paper_id: str) -> dict:
    """The research overview and every later work, trimmed to what a phone uses."""
    from paper_daily import followups

    later = []
    for r in followups.for_paper(conn, paper_id):
        item = {
            k: r[k]
            for k in ("title", "year", "venue", "doi", "verdict", "why", "relation", "citations")
            if r.get(k) is not None
        }
        if r["contexts"]:
            item["context"] = r["contexts"][0][:320]
        here = followups.in_corpus(conn, r.get("doi"), r.get("title"))
        if here:
            item["id"] = here["id"]
        later.append(item)
    return {
        "overview": followups.overview_for(conn, paper_id),
        "followups": later,
        "checked": followups.checked(conn, paper_id),
    }


def surveys_for(conn, paper_ids: list[str]) -> list[dict]:
    """The field surveys of the lists these papers came from.

    A survey belongs to a list, not a paper, so it goes out once per list with the
    page's papers that are in it, and the page shows it above the papers.
    """
    if not paper_ids:
        return []
    marks = ",".join("?" * len(paper_ids))
    out = []
    for row in conn.execute(
        "SELECT l.id, l.name, s.body, s.written_at, s.papers FROM lists l "
        "JOIN list_surveys s ON s.list_id = l.id "
        f"WHERE EXISTS (SELECT 1 FROM list_papers lp WHERE lp.list_id = l.id "
        f"              AND lp.paper_id IN ({marks})) ORDER BY l.name",
        paper_ids,
    ):
        here = [
            r["paper_id"]
            for r in conn.execute(
                f"SELECT paper_id FROM list_papers WHERE list_id=? AND paper_id IN ({marks})",
                (row["id"], *paper_ids),
            )
        ]
        out.append(
            {
                "id": row["id"],
                "name": row["name"],
                "body": row["body"],
                "written_at": row["written_at"],
                "papers_total": row["papers"],
                "papers": here,
            }
        )
    return out


def decks_for(paper_id: str, files: dict[str, str]) -> list[dict]:
    """The paper's slide decks, each as an outline for the page and a full export.

    The outline (title, takeaway, bullets, notes, figure) reads on a phone without
    the canvas; the export is the same self-contained HTML the desktop makes, for
    the slides as laid out. Neither can be edited here: editing is the canvas's job,
    and a deck edited in two places is two decks.
    """
    from paper_daily import presentation_export, presentations

    out = []
    for mode, label in presentations.MODES.items():
        deck = presentations.load_deck(paper_id, mode)
        if deck is None:
            continue
        stem = f"{_safe(paper_id)}-{mode}"
        page = SLIDES_DIR / f"{stem}.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        presentation_export.export_html(deck, page, include_notes=True)
        files[f"slides/{page.name}"] = str(page)
        by_id = {f["id"]: f for f in deck.figures}
        slides = []
        for slide in deck.slides:
            figure = None
            item = by_id.get(slide.figure) if slide.figure else None
            if item:
                blob = presentations.figure_bytes(deck, slide.figure)
                name = hashlib.sha256(blob).hexdigest()[:20] + ".png"
                src = SLIDES_DIR / stem / name
                src.parent.mkdir(parents=True, exist_ok=True)
                if not src.exists():
                    src.write_bytes(blob)
                files[f"slides/{stem}/{name}"] = str(src)
                figure = {
                    "src": f"slides/{stem}/{name}",
                    "label": item.get("label", ""),
                    "caption": item.get("caption", ""),
                    "page": item.get("page"),
                }
            # A table dropped onto the canvas lives only among the slide's objects,
            # not in its outline fields, so the outline would otherwise lose it.
            tables = [
                {"rows": obj["rows"], "header": bool(obj.get("header", True))}
                for obj in slide.elements or []
                if obj.get("kind") == "table" and isinstance(obj.get("rows"), list)
            ]
            slides.append(
                {
                    "title": slide.title,
                    "section": slide.section,
                    "takeaway": slide.takeaway,
                    "bullets": slide.bullets,
                    "notes": slide.speaker_notes,
                    "figure": figure,
                    "tables": tables,
                }
            )
        out.append(
            {
                "mode": mode,
                "label": label,
                "title": deck.title,
                "audience": deck.audience,
                "minutes": deck.minutes,
                "edited": deck.edited,
                "created": deck.created_at,
                "href": f"slides/{page.name}",
                "slides": slides,
            }
        )
    return out


def collect(paper_ids: list[str]) -> tuple[list[dict], dict[str, str], list[dict]]:
    papers: list[dict] = []
    files: dict[str, str] = {**ensure_pdfjs(), **ensure_typesetting()}
    with connect() as conn:
        surveys = surveys_for(conn, paper_ids)
        for pid in paper_ids:
            row = conn.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
            if row is None:
                raise ValueError(f"no paper {pid}")
            dive = conn.execute("SELECT body FROM dives WHERE paper_id=?", (pid,)).fetchone()
            close = closeread.get(conn, pid)
            desk = conn.execute(
                "SELECT body, created_at, page FROM notes WHERE paper_id=? ORDER BY id", (pid,)
            ).fetchall()

            pdf = pocket_pdf(pid)
            served_pdf = None
            if pdf is not None:
                served_pdf = f"pdf/{pdf.name}"
                files[served_pdf] = str(pdf)

            # The dive cites figures by label, and a chip that opens the figure beats
            # hunting for it in the PDF. That is all the extracted figures are for now.
            figs = []
            for f in figures_for(pid):
                served = f"fig/{_safe(pid)}/{f['file']}"
                files[served] = str(FIG_DIR / _safe(pid) / f["file"])
                figs.append(
                    {
                        "label": f["label"],
                        "caption": f["caption"],
                        "page": f["page"],
                        "kind": f["kind"],
                        "src": served,
                    }
                )

            papers.append(
                {
                    "id": pid,
                    "title": row["title"],
                    "authors": json.loads(row["authors_json"] or "[]"),
                    "venue": row["venue"],
                    "year": row["year"],
                    "doi": row["doi"],
                    "abstract": row["abstract"] or "",
                    "pdf": served_pdf,
                    "pdf_bytes": pdf.stat().st_size if pdf else 0,
                    "figures": figs,
                    "dive": (dive["body"] if dive else ""),
                    "close": close or "",
                    "decks": decks_for(pid, files),
                    "cites": cites_for(conn, pid),
                    "context": context_for(conn, pid),
                    "desk_notes": [
                        {"body": n["body"], "created": n["created_at"], "page": n["page"]}
                        for n in desk
                    ],
                }
            )
    return papers, files, surveys


def write(paper_ids: list[str], out: Path | None = None) -> dict:
    """Build the page and put every file it references next to it.

    Returns what was built, so a caller with a progress area has something to say.
    """
    out = out or (OUT_DIR / "index.html")
    papers, files, surveys = collect(paper_ids)

    html = (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("/*__PAPERS__*/null", json.dumps(papers, ensure_ascii=False))
        .replace("/*__SURVEYS__*/null", json.dumps(surveys, ensure_ascii=False))
        .replace("/*__TYPESET__*/", TYPESET.read_text(encoding="utf-8"))
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    # Copy everything next to the page under the paths it references, so the file on
    # disk is the same page that gets published rather than one with dead links.
    for served, source in files.items():
        dest = out.parent / served
        if dest.resolve() == Path(source).resolve():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(Path(source).read_bytes())

    (out.parent / "files.json").write_text(
        json.dumps(files, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return {
        "out": out,
        "papers": papers,
        "surveys": surveys,
        "files": files,
        "page_bytes": out.stat().st_size,
        "total_bytes": sum(Path(s).stat().st_size for s in files.values()),
        "no_pdf": [d["title"] for d in papers if not d["pdf"]],
    }


# Every note filed from the shared page carries this, so a second pull can recognise
# its own work and the desktop can say where a note came from.
STAMP = "[共享]"


def _norm(text: str) -> str:
    return re.sub(r"[\s\u00ad\u2010-\u2014-]+", "", text).casefold()


def anchor_for(paper_id: str, page: int, quote: str) -> dict | None:
    """The desktop's word-order anchor for a passage known only by its words.

    A note written on the shared page remembers the quote and the page, because
    pdf.js and PyMuPDF never agree on where a run of text starts. Matching with all
    whitespace and hyphens removed finds the same words from either side.
    """
    if page < 1:
        return None
    return locate(paper_id, quote, pages=[page])


def locate(paper_id: str, quote: str, pages: list[int] | None = None) -> dict | None:
    """Where `quote` is printed, searching `pages` (one-based) or the whole paper."""
    src = PDF_DIR / (_safe(paper_id) + ".pdf")
    want = _norm(quote)
    if not src.exists() or len(want) < 4:
        return None

    import pymupdf

    with pymupdf.open(src) as doc:
        texts = {
            page: _flatten(doc[page - 1].get_text("words"))
            for page in (pages or range(1, doc.page_count + 1))
            if 1 <= page <= doc.page_count
        }
    # The whole passage anywhere beats a prefix of it on an earlier page.
    for n in (len(want), 80, 40, 20):
        if n > len(want):
            continue
        for page, (text, owner) in texts.items():
            at = text.find(want[:n])
            if at >= 0:
                end = min(at + len(want), len(text)) - 1
                return {"p0": page - 1, "o0": owner[at], "p1": page - 1, "o1": owner[end]}
    return None


def _flatten(words: list) -> tuple[str, list[int]]:
    """A page's words run together, and which word each character came from."""
    owner: list[int] = []
    flat = []
    for i, w in enumerate(words):
        t = _norm(w[4])
        flat.append(t)
        owner.extend([i] * len(t))
    return "".join(flat), owner


def _page_of(note: dict) -> int | None:
    # Older notes anchored to a paragraph number; only a page label means a page.
    match = re.match(r"第 (\d+) 頁", note.get("section") or "")
    return int(match.group(1)) if match else None


def note_body(note: dict) -> str:
    """One shared note as the desktop reader shows it: passage first, then the rest."""
    parts = []
    quote = " ".join((note.get("quote") or "").split())
    if quote:
        parts.append(f"> {quote}")
    if note.get("question"):
        parts.append(f"問:{note['question']}")
    parts.append((note.get("body") or "").strip())
    parts.append(STAMP)
    return "\n".join(x for x in parts if x)


def file_notes(notes: list[dict]) -> tuple[int, int]:
    """File shared notes against their papers. Idempotent: a second pull adds nothing."""
    added = skipped = 0
    with connect() as conn:
        for note in sorted(notes, key=lambda n: n.get("created") or ""):
            paper_id = note.get("paper")
            if not paper_id or not (note.get("body") or "").strip():
                continue
            if not conn.execute("SELECT 1 FROM papers WHERE id=?", (paper_id,)).fetchone():
                continue
            body = note_body(note)
            if conn.execute(
                "SELECT 1 FROM notes WHERE paper_id=? AND body=?", (paper_id, body)
            ).fetchone():
                skipped += 1
                continue
            page = _page_of(note)
            anchor = anchor_for(paper_id, page, note.get("quote") or "") if page else None
            conn.execute(
                "INSERT INTO notes(paper_id, body, created_at, kind, page, anchor) "
                "VALUES (?,?,?,?,?,?)",
                (
                    paper_id,
                    body,
                    note.get("created") or "",
                    "ask" if note.get("kind") == "ask" else "note",
                    page,
                    json.dumps(anchor) if anchor else None,
                ),
            )
            added += 1
        conn.commit()
    return added, skipped
