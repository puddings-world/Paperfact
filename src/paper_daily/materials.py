"""素材: what a slide most often needs from a paper, assembled per paper.

A deck is built from prose sources, but what a presenter reaches for is the paper's
own exhibits, its section headings, and a handful of sentences worth quoting with a
page number. These already exist in pieces: figures.py renders every figure and table,
the 逐節精讀 reproduces results tables as Markdown and marks which exhibit it is
discussing, and the PDF text layer holds the headings and claims. This module reads
those pieces into one list the deck editor can offer for picking or dragging, so a
slide can carry a clean editable table rather than a crop of one.

Exhibit IDs follow presentations.collect_evidence (position plus managed PDF hash)
so a material dropped on a slide cites the same evidence entry a generated deck would.
"""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import closing
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from paper_daily import paper_highlights, pdf_highlights
from paper_daily.closeread import MARKER
from paper_daily.config import DATA_DIR, PDF_DIR, TEXT_DIR
from paper_daily.fetch import _safe_name, capture_document, document_current
from paper_daily.figures import FIG_DIR, cache_directory
from paper_daily.presentations import _atomic_json
from paper_daily.store import connect

MAX_PAGES = 120
MAX_TABLE_ROWS, MAX_TABLE_COLS = 30, 12

HEADING = re.compile(r"^([1-9]\d?(?:\.\d{1,2}){0,2})\.?\s+([A-Z][^\n]{2,90})$")
SMALL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "via",
    "with",
}
TABLE_REF = r"\b(?:Table|表)\s*{number}\b"


@dataclass
class Materials:
    paper_id: str
    exhibits: list[dict] = field(default_factory=list)
    headings: list[dict] = field(default_factory=list)
    sentences: list[dict] = field(default_factory=list)
    highlights: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)



@dataclass(frozen=True)
class MaterialPaths:
    data: Path
    pdf: Path
    text: Path
    figures: Path
    highlights: Path
    database: Path | None = None

    @classmethod
    def capture(cls):
        return cls(*(Path(p).absolute() for p in (
            DATA_DIR, PDF_DIR, TEXT_DIR, FIG_DIR, paper_highlights.CACHE_DIR,
        )))


def _source_document(paper_id, document, loaded_source, paths):
    if loaded_source is None:
        if paths.database is not None:
            from paper_daily.document_reader import from_workspace

            if document is None:
                return from_workspace(paths.database, legacy_root=paths.pdf).resolve(paper_id)
            if Path(document._owner.db_path).resolve() != paths.database.resolve():
                raise ValueError("Material document belongs to another research database")
        return capture_document(paper_id, document=document, legacy_root=paths.pdf)
    from paper_daily import figures

    figures.loaded_current(loaded_source)
    if (loaded_source.view.owner.paper_id != paper_id
            or loaded_source.document is not document):
        raise ValueError("Material source differs from the actual loaded paper")
    return document


def _source_current(document, loaded_source=None):
    if loaded_source is None:
        return document_current(document)
    from paper_daily import figures

    return figures.loaded_current(loaded_source)


def _read_scope(database):
    if database is None:
        return connect()
    from paper_daily.manual_highlight_ops import _readonly_connection

    return closing(_readonly_connection(database))


def exhibit_key(label: str) -> str:
    """Fig. 3, figure 3 and Figure 3 name the same exhibit."""
    kind, _, number = label.strip().partition(" ")
    kind = "table" if kind.lower().startswith("tab") else "figure"
    return f"{kind} {number.strip().lower()}"


def figure_entries(paper_id: str, *, document=None, loaded_source=None, paths=None,
                   cancelled=lambda: False) -> list[dict]:
    paths = paths or MaterialPaths.capture()
    document = _source_document(paper_id, document, loaded_source, paths)
    if loaded_source is not None:
        from paper_daily import figures

        # Legacy aliases must not overwrite a previous version's material images.
        root = paths.figures if document is not None and document.managed else (
            paths.figures / "materials" / loaded_source.view.fingerprint
        )
        found = figures.extract(
            paper_id, loaded_source.view.path, document=document,
            root=root, loaded_source=loaded_source, cancelled=cancelled,
        )
        return [dict(
            id=figures.source_id(f"figure:{i + 1}", loaded_source.view.fingerprint),
            file=figure.path.name, label=figure.label, caption=figure.caption,
            page=figure.page, kind=figure.kind, **{k: v for k, v in figure.meta.items()
                if k not in {"cache_key", "document_hash"}},
            cache_key=figure.path.parent.relative_to(paths.figures).as_posix(),
            document_hash=loaded_source.view.fingerprint,
        ) for i, figure in enumerate(found[:60])]
    folder = cache_directory(paper_id, document=document, root=paths.figures, legacy_root=paths.pdf)
    if folder is None:
        return []
    index_path = folder / "index.json"
    if not index_path.exists() and document is not None and document_current(document):
        from paper_daily.figures import extract

        extract(paper_id, document.path, document=document, root=paths.figures,
                legacy_root=paths.pdf, cancelled=cancelled)
    if not index_path.exists():
        return []
    manifest = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, list):
        raise ValueError("Invalid paper figure index")
    entries = []
    for i, item in enumerate(manifest[:60]):
        if not isinstance(item, dict):
            continue
        if document is not None and item.get("document_hash") != document.sha256:
            continue
        name = item.get("file")
        if not isinstance(name, str) or Path(name).name != name:
            continue
        from paper_daily.figures import source_id

        sid = source_id(f"figure:{i + 1}", document.sha256 if document else None)
        entries.append(
            {
                "id": sid,
                "file": name,
                "label": item.get("label") or sid,
                "caption": item.get("caption", ""),
                "page": item.get("page"),
                "kind": item.get("kind", "figure"),
                "rect": item.get("rect"),
                **(
                    {
                        "document_hash": document.sha256,
                        "cache_key": folder.relative_to(paths.figures).as_posix(),
                    }
                    if document is not None
                    else {}
                ),
            }
        )
    return entries if document_current(document) else []


def markdown_tables(text: str) -> list[tuple[int, list[list[str]]]]:
    """Every Markdown table in the text, as (first line index, rows)."""
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        if not lines[i].lstrip().startswith("|"):
            i += 1
            continue
        start, rows = i, []
        while i < len(lines) and lines[i].lstrip().startswith("|"):
            cells = [c.strip().replace("**", "") for c in lines[i].strip().strip("|").split("|")]
            i += 1
            if cells and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            rows.append(cells)
        if len(rows) >= 2:
            width = min(max(map(len, rows)), MAX_TABLE_COLS)
            rows = [(r + [""] * width)[:width] for r in rows[:MAX_TABLE_ROWS]]
            out.append((start, rows))
    return out


def close_reading_sections(body: str) -> list[tuple[str, int]]:
    """(heading, first line index) for each ``##`` or ``###`` section, in order."""
    return [
        (line.lstrip("#").strip(), i)
        for i, line in enumerate(body.splitlines())
        if line.startswith(("## ", "### "))
    ]


def _section_at(sections: list[tuple[str, int]], line: int) -> str:
    current = ""
    for heading, start in sections:
        if start <= line:
            current = heading
        else:
            break
    return current


def place_exhibits(exhibits: list[dict], body: str | None) -> None:
    """Give each exhibit the close-reading section discussing it and, for a table,
    the rows the reading reproduced."""
    if not body:
        return
    lines = body.splitlines()
    sections = close_reading_sections(body)
    markers: dict[str, int] = {}
    for i, line in enumerate(lines):
        hit = MARKER.match(line)
        if hit:
            markers.setdefault(exhibit_key(hit.group(1)), i)
    tables = markdown_tables(body)
    taken: set[int] = set()
    for item in exhibits:
        key = exhibit_key(item["label"])
        marker = markers.get(key)
        if marker is not None:
            item["section"] = _section_at(sections, marker)
        if item.get("kind") != "table":
            continue
        chosen = None
        if marker is not None:
            section = _section_at(sections, marker)
            same = [
                (abs(start - marker), start, rows)
                for start, rows in tables
                if start not in taken and _section_at(sections, start) == section
            ]
            if same:
                chosen = min(same)[1:]
        if chosen is None:
            number = re.escape(key.split(" ", 1)[1])
            mention = re.compile(TABLE_REF.format(number=number), re.I)
            for start, rows in tables:
                above = "\n".join(lines[max(0, start - 8) : start])
                if start not in taken and mention.search(above):
                    chosen = (start, rows)
                    break
        if chosen is not None:
            taken.add(chosen[0])
            item["rows"] = chosen[1]
            item.setdefault("section", _section_at(sections, chosen[0]))


# Reading a PDF's text holds the interpreter, which stalls the window even from a
# worker thread; an unchanged file (same path, mtime and size) is not read again.


def _pages(paper_id: str, *, document=None, loaded_source=None, paths=None,
           cancelled=lambda: False) -> list[tuple[int | None, str]]:
    paths = paths or MaterialPaths.capture()
    document = _source_document(paper_id, document, loaded_source, paths)
    if loaded_source is not None:
        import pymupdf

        with pymupdf.open(stream=loaded_source.data, filetype="pdf") as pdf:
            result = []
            for index in range(min(len(pdf), MAX_PAGES)):
                if cancelled():
                    raise ValueError("Material collection cancelled")
                result.append((index + 1, pdf[index].get_text()))
        _source_current(document, loaded_source)
        return result
    if document is not None and not document_current(document):
        return []
    pdf_path = (document.path if document is not None else
                paths.pdf / (_safe_name(paper_id) + ".pdf"))
    if pdf_path.exists():
        from paper_daily import pdf_text

        try:
            text = pdf_text.pages(pdf_path)
            pages = [(i + 1, t) for i, t in enumerate(text[:MAX_PAGES])]
            return pages if document_current(document) else []
        except (RuntimeError, ValueError, OSError):
            pass
    if document is not None:
        return []
    cached = paths.text / (_safe_name(paper_id) + ".txt")
    if cached.exists():
        return [(None, cached.read_text(encoding="utf-8"))]
    return []


def _title_case(title: str) -> bool:
    """A heading capitalises its words; a wrapped sentence that happens to start
    with a number does not."""
    words = [w for w in title.split() if w.lower() not in SMALL_WORDS]
    capitals = sum(w[0].isupper() or not w[0].isalpha() for w in words)
    return bool(words) and capitals / len(words) >= 0.6


def headings_from_pages(pages: list[tuple[int | None, str]]) -> list[dict]:
    out, seen, major = [], set(), 0
    for page, text in pages:
        for line in text.splitlines():
            hit = HEADING.match(line.strip())
            if not hit:
                continue
            number, title = hit.groups()
            title = " ".join(title.split())
            if (
                len(title.split()) > 8
                or title.endswith((".", ",", ";"))
                or title in seen
                or not _title_case(title)
                or int(number.split(".")[0]) < major
            ):
                continue
            seen.add(title)
            major = int(number.split(".")[0])
            out.append({"text": f"{number} {title}", "level": number.count(".") + 1, "page": page})
    return out


def headings_from_close_reading(body: str | None) -> list[dict]:
    if not body:
        return []
    return [
        {"text": line.lstrip("#").strip(), "level": len(line) - len(line.lstrip("#")) - 1}
        for line in body.splitlines()
        if line.startswith(("## ", "### "))
    ]


def _saved_analysis(paper_id: str, document, *, current=None, database=None,
                    pdf_dir=None) -> dict | None:
    """The saved highlight analysis, only when it was made from the PDF in use."""
    from paper_daily import annotation_content

    with _read_scope(database) as conn:
        row = conn.execute(
            "SELECT * FROM paper_highlight_analysis WHERE paper_id=?", (paper_id,)
        ).fetchone()
    if row is None:
        return None
    row = dict(row)
    if current is None:
        if document is not None:
            current = document.sha256 if document_current(document) else None
        else:
            path = (pdf_dir or PDF_DIR) / (_safe_name(paper_id) + ".pdf")
            current = pdf_highlights.document_hash(path) if path.exists() else None
    if current is None or row["document_hash"] != current:
        return None
    try:
        annotation_content.validate_row("highlight_analysis", row)
        body = annotation_content.decode("highlight_analysis", row["body_json"])
    except ValueError:
        return None
    items = [dict(item, document_hash=row["document_hash"]) for item in body.get("items", [])]
    return {**body, "items": items, "paper_id": paper_id, "source_hash": row["source_hash"]}


def collect(paper_id: str, *, document=None, database=None, loaded_source=None,
            paths=None, cancelled=lambda: False) -> Materials:
    if cancelled():
        raise ValueError("Material collection cancelled")
    scoped = paths is not None or database is not None or loaded_source is not None
    paths = paths or MaterialPaths.capture()
    if database is not None:
        paths = replace(paths, database=Path(database).absolute())
    document = _source_document(paper_id, document, loaded_source, paths)
    source_hash = (loaded_source.view.fingerprint if loaded_source is not None
                   else getattr(document, "sha256", None))
    if loaded_source is not None and (
        database is None or Path(database).resolve() != loaded_source.view.owner.database
    ):
        raise ValueError("Material collection requires its captured research database")
    with _read_scope(database) as conn:
        row = conn.execute(
            "SELECT body FROM close_readings WHERE paper_id=?", (paper_id,)
        ).fetchone()
    close = row["body"] if row else None
    options = dict(document=document)
    if scoped:
        options.update(loaded_source=loaded_source, paths=paths, cancelled=cancelled)
    exhibits = figure_entries(paper_id, **options)
    if document is None and loaded_source is None:
        place_exhibits(exhibits, close)
    pages = _pages(paper_id, **options)
    headings = headings_from_pages(pages)
    if source_hash is not None and _source_current(document, loaded_source):
        for item in headings:
            item["document_hash"] = source_hash
    if len(headings) < 2:
        headings = headings_from_close_reading(close)
    _locate_materials(paper_id, exhibits + headings, **options)
    cache_options = {"cache_root": paths.highlights} if scoped else {}
    # 分析／補上標註 saves its analysis in the research database; the file cache below
    # only holds what the older 挑選原文重點 wrote. Without this the panel said 尚未分析
    # right after an analysis had finished.
    current = (
        source_hash
        if source_hash is not None and _source_current(document, loaded_source)
        else None
    )
    highlights = _saved_analysis(
        paper_id, document, current=current, database=database, pdf_dir=paths.pdf
    ) or (
        paper_highlights.cached(
            paper_id,
            **cache_options,
            pages=[
                {"page": page, "text": paper_highlights.normalize(text)} for page, text in pages
            ],
        )
        if source_hash is not None
        else paper_highlights.cached(paper_id, **cache_options)
    )
    sentences = [dict(item, origin="ai") for item in highlights["items"]] if highlights else []
    path = loaded_source.view.path if loaded_source is not None else (
        (document.path if _source_current(document, loaded_source) else None)
        if source_hash is not None
        else (paths.pdf / (_safe_name(paper_id) + ".pdf"))
    )
    if source_hash is not None:
        for item in sentences:
            if (item.get("document_hash") != source_hash
                    or not _source_current(document, loaded_source)):
                item.pop("anchor", None)
                item.pop("rect", None)
                item.update(
                    navigation_available=False, navigation_reason="source_document_mismatch"
                )
    if path is not None and path.exists():
        fingerprint = (
            source_hash if source_hash is not None else pdf_highlights.document_hash(path)
        )
        mark_options = {"database": database} if database else {}
        marks = (loaded_source.view.marks if loaded_source is not None else
                 pdf_highlights.list_marks(paper_id, fingerprint, **mark_options))
        for mark in marks:
            page = mark["anchor"]["p0"] + 1
            if mark["origin"] == "manual":
                item = dict(text=mark["quote"], page=page, origin="manual", reason="")
                sentences.append(item)
            else:
                item = next(
                    (s for s in sentences if s.get("page") == page and s["text"] == mark["quote"]),
                    None,
                )
            if item is not None:
                item.update(anchor=mark["anchor"], mark_id=mark["id"])
                if source_hash is not None:
                    item.update(document_hash=fingerprint, navigation_available=True)
    if source_hash is not None and not _source_current(document, loaded_source):
        for item in exhibits + headings + sentences:
            item.pop("rect", None)
            item.pop("anchor", None)
            item.update(navigation_available=False, navigation_reason="document_unavailable")
    if cancelled():
        raise ValueError("Material collection cancelled")
    _source_current(document, loaded_source)
    return Materials(paper_id, exhibits, headings, sentences, highlights)


def _locate_materials(paper_id, items, *, document=None, loaded_source=None, paths=None,
                      cancelled=lambda: False):
    paths = paths or MaterialPaths.capture()
    document = _source_document(paper_id, document, loaded_source, paths)
    if document is not None and not _source_current(document, loaded_source):
        for item in items:
            item.pop("rect", None)
            item.pop("anchor", None)
            item.update(navigation_available=False, navigation_reason="document_unavailable")
        return
    path = (loaded_source.view.path if loaded_source is not None else
            document.path if document is not None else paths.pdf / (_safe_name(paper_id) + ".pdf"))
    if not path.exists() or not items:
        return
    fingerprint = (loaded_source.view.fingerprint if loaded_source is not None else
                   document.sha256 if document is not None else pdf_highlights.document_hash(path))
    eligible = []
    for item in items:
        # Supplied geometry is not evidence of source identity. Never relabel old
        # coordinates, or automatically reanchor unproven managed analysis text.
        proven = item.get("document_hash") == fingerprint
        if (((document is not None or loaded_source is not None) and not proven)
                or (item.get("rect") and not proven)):
            item.pop("rect", None)
            item.pop("anchor", None)
            item.update(navigation_available=False, navigation_reason="source_document_mismatch")
            continue
        eligible.append(item)
    keys = [f"{i.get('page')}:{i.get('caption') or i.get('text', '')}" for i in eligible]
    signature = hashlib.sha256(
        json.dumps(
            ["positions-v2", fingerprint, keys, [item.get("rect") for item in eligible]]
        ).encode()
    ).hexdigest()
    dest = (
        paths.data / "material-positions"
        / (hashlib.sha256(paper_id.encode()).hexdigest() + ".json")
    )
    if document is not None or loaded_source is not None:
        dest = paths.data / "material-positions" / fingerprint / (signature + ".json")
    positions = {}
    try:
        saved = json.loads(dest.read_text(encoding="utf-8"))
        if saved.get("signature") == signature:
            positions = saved["positions"]
    except (OSError, ValueError, KeyError):
        pass
    if not positions and eligible:
        import pymupdf

        with (pymupdf.open(stream=loaded_source.data, filetype="pdf")
              if loaded_source is not None else pymupdf.open(path)) as doc:
            for key, item in zip(keys, eligible, strict=True):
                if cancelled():
                    raise ValueError("Material collection cancelled")
                page = item.get("page")
                if type(page) is not int or not 1 <= page <= len(doc):
                    continue
                rect = item.get("rect")
                if not rect:
                    query = item.get("caption") or item.get("text", "")
                    matches = doc[page - 1].search_for(query)
                    if matches:
                        box = matches[0]
                        for other in matches[1:]:
                            box |= other
                        rect = list(box)
                positions[key] = rect
        if _source_current(document, loaded_source):
            _atomic_json(dest, dict(signature=signature, positions=positions))
    if not _source_current(document, loaded_source):
        for item in eligible:
            item.pop("rect", None)
            item.pop("anchor", None)
            item.update(navigation_available=False, navigation_reason="document_unavailable")
        return
    for key, item in zip(keys, eligible, strict=True):
        item.update(rect=positions.get(key), document_hash=fingerprint)
        if document is not None or loaded_source is not None:
            item["navigation_available"] = bool(item["rect"])
