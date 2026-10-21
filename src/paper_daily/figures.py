"""Pull the figures and tables out of a paper's PDF.

A deep dive says "Figure 5 shows the ratio diverging around layer 12" and the reader
has to go hunting for Figure 5. These are the authors' own explanatory graphics, so
showing them beside the explanation beats any diagram generated about the paper.

Most ML figures are vector drawings rather than embedded rasters, so extracting
`page.get_images()` misses them entirely. Instead the caption is located in the text
layer and the region next to it is rendered: above for a figure, below for a table,
which is how the two conventionally sit.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily.config import DATA_DIR, ensure_dirs

FIG_DIR = DATA_DIR / "figures"

# Body text says "Figure 1 shows ..."; a real caption says "Figure 1: ..." -- or, in
# Nature journals, "Fig. 1  Total duration of the annotated phases", with no
# punctuation at all. Requiring the colon missed every figure in a Nature paper and
# kept only its tables, so the no-colon form is accepted when the caption continues
# with a capital letter, which is what separates it from "Figure 1 shows".
# The lookahead is case-sensitive even though the rest is not: re.I would let
# "Fig. 2 sample frames" through, which is prose, not a caption.
CAPTION_RE = re.compile(
    r"^(Figure|Fig\.|Table)\s+(\d+[a-z]?)(?:\s*[:.]|\s+(?=(?-i:[A-Z])))", re.I
)

MIN_HEIGHT = 40.0      # anything thinner is a caption wedged against its neighbour
MAX_HEIGHT = 560.0     # stop before a "figure" swallows a column of body text
RENDER_SCALE = 2.0     # 144 dpi: legible when zoomed, still small on disk
MIN_PNG_BYTES = 3_000  # below this the crop came out blank


@dataclass
class Figure:
    paper_id: str
    label: str
    caption: str
    page: int
    path: Path
    kind: str = "figure"
    meta: dict = field(default_factory=dict)


def _safe(paper_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", paper_id)


def _is_prose(text: str) -> bool:
    """A body paragraph, as opposed to table cells or axis labels.

    The boundary of a figure has to be prose, not simply the nearest block: a table's
    own rows are text blocks, so stopping at the nearest one produced a two-pixel
    region and a blank PNG for most tables in the first paper tried.
    """
    words = text.split()
    if len(words) < 12:
        return False
    # Cells and labels are short tokens, often numeric; prose has long words and
    # sentence punctuation.
    letters = sum(c.isalpha() for c in text)
    return letters / max(len(text), 1) > 0.6 and ". " in text


def _region(page, block, blocks, downward: bool):
    """The rectangle holding the graphic that belongs to this caption."""
    x0, y0, x1, y1 = block[:4]
    same_column = [b for b in blocks if not (b[2] < x0 - 6 or b[0] > x1 + 6)]

    if downward:
        candidates = sorted((b for b in same_column if b[1] >= y1 - 2), key=lambda b: b[1])
        edge = page.rect.y1
        for b in candidates:
            if _is_prose(b[4]):
                edge = b[1]
                break
        top, bottom = y1 + 2, min(edge - 2, y1 + MAX_HEIGHT)
    else:
        candidates = sorted(
            (b for b in same_column if b[3] <= y0 - 2), key=lambda b: b[3], reverse=True
        )
        edge = page.rect.y0
        for b in candidates:
            if _is_prose(b[4]):
                edge = b[3]
                break
        top, bottom = max(edge + 2, y0 - MAX_HEIGHT), y0 - 2

    left, right = x0 - 4, x1 + 4
    # A plot legend routinely sits outside the caption's text width, and clipping to
    # the caption cut the legend off every multi-series chart. Widen to whatever is
    # actually drawn inside the band, so the crop follows the graphic, not the prose.
    for item in _drawn_bounds(page):
        ix0, iy0, ix1, iy1 = item
        if iy1 <= top - 4 or iy0 >= bottom + 4:
            continue
        left, right = min(left, ix0 - 2), max(right, ix1 + 2)
    return (
        max(left, page.rect.x0),
        top,
        min(right, page.rect.x1),
        bottom,
    )


def _drawn_bounds(page) -> list[tuple[float, float, float, float]]:
    """Bounding boxes of everything vector-drawn or placed as an image on the page."""
    boxes: list[tuple[float, float, float, float]] = []
    try:
        for drawing in page.get_drawings():
            rect = drawing.get("rect")
            if rect is not None:
                boxes.append((rect.x0, rect.y0, rect.x1, rect.y1))
    except Exception:
        pass
    try:
        for info in page.get_image_info():
            bbox = info.get("bbox")
            if bbox:
                boxes.append(tuple(bbox))
    except Exception:
        pass
    return boxes


def extract(
    paper_id: str, pdf_path: Path, force: bool = False, *, cached_only=False
) -> list[Figure]:
    """Render every figure and table in the paper, newest render cached on disk."""
    ensure_dirs()
    out_dir = FIG_DIR / _safe(paper_id)
    index = out_dir / "index.json"

    if index.exists() and not force:
        stored = json.loads(index.read_text(encoding="utf-8"))
        return [
            Figure(
                paper_id=paper_id, label=f["label"], caption=f["caption"],
                page=f["page"], path=out_dir / f["file"], kind=f["kind"],
                meta={"rect": f.get("rect")},
            )
            for f in stored
            if (out_dir / f["file"]).exists()
        ]

    if cached_only or not pdf_path.exists():
        return []
    try:
        import pymupdf
    except ImportError:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    figures: list[Figure] = []
    manifest = []

    try:
        with pymupdf.open(pdf_path) as doc:
            for pno, page in enumerate(doc):
                blocks = [b for b in page.get_text("blocks") if b[4].strip()]
                for block in blocks:
                    caption = " ".join(block[4].split())
                    match = CAPTION_RE.match(caption)
                    if not match:
                        continue
                    kind = "table" if match.group(1).lower().startswith("table") else "figure"

                    # Tables caption above their body, figures below theirs. Try the
                    # convention first and fall back, since neither is universal.
                    for downward in (kind == "table", kind != "table"):
                        rect = _region(page, block, blocks, downward)
                        if rect[3] - rect[1] >= MIN_HEIGHT:
                            break
                    else:
                        continue
                    if rect[3] - rect[1] < MIN_HEIGHT:
                        continue

                    label = f"{match.group(1).title()} {match.group(2)}"
                    name = f"p{pno + 1:02d}-{_safe(label)}.png"
                    try:
                        pix = page.get_pixmap(
                            matrix=pymupdf.Matrix(RENDER_SCALE, RENDER_SCALE),
                            clip=pymupdf.Rect(*rect),
                        )
                        pix.save(out_dir / name)
                    except Exception:
                        continue

                    # A region that resolved to blank paper compresses to almost
                    # nothing. Showing it would be worse than omitting it.
                    if (out_dir / name).stat().st_size < MIN_PNG_BYTES:
                        (out_dir / name).unlink(missing_ok=True)
                        continue

                    figures.append(
                        Figure(paper_id, label, caption, pno + 1, out_dir / name, kind)
                    )
                    manifest.append(
                        {"label": label, "caption": caption, "page": pno + 1,
                         "file": name, "kind": kind, "rect": list(rect)}
                    )
    except Exception:
        return figures

    index.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return figures
