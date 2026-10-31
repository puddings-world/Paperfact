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

import hashlib
import hmac
import json
import re
import secrets
import tempfile
import threading
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily.config import DATA_DIR, ensure_dirs
from paper_daily.fetch import capture_document, derivative_key, document_current

FIG_DIR = DATA_DIR / "figures"

# Body text says "Figure 1 shows ..."; a real caption says "Figure 1: ..." -- or, in
# Nature journals, "Fig. 1  Total duration of the annotated phases", with no
# punctuation at all. Requiring the colon missed every figure in a Nature paper and
# kept only its tables, so the no-colon form is accepted when the caption continues
# with a capital letter, which is what separates it from "Figure 1 shows".
# The lookahead is case-sensitive even though the rest is not: re.I would let
# "Fig. 2 sample frames" through, which is prose, not a caption.
CAPTION_RE = re.compile(r"^(Figure|Fig\.|Table)\s+(\d+[a-z]?)(?:\s*[:.]|\s+(?=(?-i:[A-Z])))", re.I)

MIN_HEIGHT = 40.0  # anything thinner is a caption wedged against its neighbour
MAX_HEIGHT = 560.0  # stop before a "figure" swallows a column of body text
RENDER_SCALE = 2.0  # 144 dpi: legible when zoomed, still small on disk
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


_LOADED_KEY = secrets.token_bytes(32)


@dataclass(frozen=True)
class _LoadedSource:
    view: object
    document: object
    version: tuple
    data: bytes = field(repr=False)
    _seal: str = field(repr=False)


def _loaded_stamp(view, document, version, data):
    # Immutable byte-object identity is process-only; no serialized cache is authority.
    value = [
        id(view),
        id(document),
        version,
        id(data),
        len(data),
        view.owner._json,
        view.fingerprint,
        str(view.path),
    ]
    return hmac.new(_LOADED_KEY, json.dumps(value, sort_keys=True).encode(), "sha256").hexdigest()


def _check_loaded(view, document, version):
    from paper_daily import audit_inputs, file_change, manual_highlight_ops

    if threading.current_thread() is threading.main_thread():
        raise ValueError("Loaded figure proof verification requires a worker")
    if (
        not isinstance(view.owner._json, str)
        or len(view.owner._json) > manual_highlight_ops.MAX_SNAPSHOT_BYTES
        or len(view.owner._json.encode()) > manual_highlight_ops.MAX_SNAPSHOT_BYTES
    ):
        raise ValueError("Loaded figure owner exceeds its existing snapshot bound")
    state = json.loads(view.owner._json)
    parent = state.get("parent")
    identity = state.get("database_identity")
    if (
        not isinstance(parent, str)
        or not re.fullmatch(r"[0-9a-f]{32}", parent)
        or not isinstance(identity, list)
        or len(identity) != 2
        or any(type(n) is not int for n in identity)
        or identity[0] < 0
        or identity[1] <= 0
    ):
        raise ValueError("Loaded figure owner has no original native identity/lifecycle")
    with closing(audit_inputs._connect(view.owner.database)) as conn:
        conn.execute("BEGIN")
        try:
            view.owner.check(conn)
        except ValueError:
            raise SourceRevoked("Original figure owner changed") from None
    if file_change.version(view.path) != version:
        raise SourceRevoked("Loaded figure source changed")
    if document is not None and not document._owner.intact(document):
        raise SourceRevoked("Loaded figure document context changed")


def loaded_current(source):
    """Worker-only source ownership check; never writer or activation authority."""
    if type(source) is not _LoadedSource or not hmac.compare_digest(
        source._seal,
        _loaded_stamp(source.view, source.document, source.version, source.data),
    ):
        raise ValueError("Figures need an actual loaded source proof")
    _check_loaded(source.view, source.document, source.version)
    return True


def capture_loaded(view, document, native_version, *, cancelled=lambda: False):
    """Read exact original bytes off-GUI, without creating research ownership."""
    from paper_daily import file_change, manual_highlight_ops
    from paper_daily.document_reader import DocumentReader, ResolvedDocument
    from paper_daily.sync_documents import MAX_PDF_BYTES

    if (
        type(view) is not manual_highlight_ops.HighlightView
        or type(view.owner) is not manual_highlight_ops.HighlightOwner
        or native_version is None
    ):
        raise ValueError("Figures need an actual loaded reader view")
    if document is not view.document or (
        document is not None
        and (
            type(document) is not ResolvedDocument
            or not isinstance(document._owner, DocumentReader)
            or document.local_id != view.owner.paper_id
            or document._owner.db_path.resolve() != view.owner.database
            or document.path != view.path
            or document.sha256 != view.fingerprint
        )
    ):
        raise ValueError("Figure source differs from the loaded reader")
    if cancelled():
        raise ValueError("Figure preparation cancelled")
    _check_loaded(view, document, native_version)
    if not 0 < native_version[2] <= MAX_PDF_BYTES:
        raise ValueError("Figure original exceeds the ordinary PDF budget")
    data = bytearray()
    digest = hashlib.sha256()
    with view.path.open("rb") as stream:
        while chunk := stream.read(min(1024 * 1024, MAX_PDF_BYTES + 1 - len(data))):
            if cancelled() or len(data) + len(chunk) > MAX_PDF_BYTES:
                raise ValueError("Figure preparation cancelled or exceeds its PDF budget")
            data.extend(chunk)
            digest.update(chunk)
    if len(data) != native_version[2] or digest.hexdigest() != view.fingerprint:
        raise ValueError("Figure original differs from the loaded PDF")
    data = bytes(data)
    result = _LoadedSource(
        view, document, native_version, data, _loaded_stamp(view, document, native_version, data)
    )
    loaded_current(result)
    if cancelled() or file_change.version(view.path) != native_version:
        raise ValueError("Figure preparation cancelled or changed")
    return result


class SourceRevoked(ValueError):
    """Original ownership/source was disproved; never renew or rehome it."""


class LeaseInterference(ValueError):
    """One bounded read could not establish a stable physical delivery lease."""


@dataclass(frozen=True)
class _SourceLease:
    view: object
    document: object
    version: tuple
    _seal: str = field(repr=False)


@dataclass(frozen=True)
class _FencedLease:
    source: _SourceLease
    fence: tuple
    _seal: str = field(repr=False)


def _lease_stamp(view, document, version):
    value = [
        "figure-source-lease-v1",
        id(view),
        id(document),
        version,
        str(view.owner.database),
        view.owner.paper_id,
        view.owner._json,
        str(view.path),
        view.fingerprint,
    ]
    return hmac.new(_LOADED_KEY, json.dumps(value, sort_keys=True).encode(), "sha256").hexdigest()


def _fence_stamp(source, fence):
    value = ["figure-delivery-v1", source._seal, fence]
    return hmac.new(_LOADED_KEY, json.dumps(value, sort_keys=True).encode(), "sha256").hexdigest()


def loaded_fence(database):
    """Bounded native metadata only; physical drift is interference, not owner loss."""
    from paper_daily import file_change

    before = file_change.version(database)
    wal = Path(str(database) + "-wal")
    observed = file_change.version(wal) if wal.exists() else None
    if observed is not None and observed[2] == 0:
        observed = None
    if file_change.version(database) != before:
        raise LeaseInterference("Figure database changed during observation")
    return before, observed


def retain_loaded_lease(source):
    """Reduce an actual verified byte proof to a process-only original-source lease."""
    loaded_current(source)
    return _SourceLease(
        source.view,
        source.document,
        source.version,
        _lease_stamp(source.view, source.document, source.version),
    )


def _checked_lease(source):
    if type(source) is not _SourceLease or not hmac.compare_digest(
        source._seal, _lease_stamp(source.view, source.document, source.version)
    ):
        raise SourceRevoked("Figure source lease is not an actual original proof")
    return source


def recheck_loaded_lease(source, *, cancelled=lambda: False):
    """One stable RO original-owner/source check; no PDF read, parse or new authority."""
    source = _checked_lease(source)
    if cancelled():
        raise LeaseInterference("Figure source check cancelled")
    before = loaded_fence(source.view.owner.database)
    _check_loaded(source.view, source.document, source.version)
    after = loaded_fence(source.view.owner.database)
    if before != after or cancelled():
        raise LeaseInterference("Figure source check remained unstable")
    return _FencedLease(source, after, _fence_stamp(source, after))


def lease_metadata_current(proof):
    """GUI-safe point-in-time delivery guard: no SQL, source hash or PDF parsing."""
    from paper_daily import file_change

    try:
        if type(proof) is not _FencedLease:
            return False
        source = _checked_lease(proof.source)
        return (
            hmac.compare_digest(proof._seal, _fence_stamp(source, proof.fence))
            and file_change.version(source.view.path) == source.version
            and loaded_fence(source.view.owner.database) == proof.fence
        )
    except (OSError, ValueError, TypeError):
        return False


def _loaded_key(source):
    options = dict(
        min_height=MIN_HEIGHT,
        max_height=MAX_HEIGHT,
        render_scale=RENDER_SCALE,
        min_png_bytes=MIN_PNG_BYTES,
    )
    encoded = json.dumps(options, sort_keys=True, separators=(",", ":"))
    return (
        Path("documents")
        / source.view.fingerprint
        / ("figures-v1-" + hashlib.sha256(encoded.encode()).hexdigest()[:24])
    )


def source_id(sid: str, document_hash: str | None = None) -> str:
    """Keep positional legacy IDs; bind managed evidence to its exact PDF."""
    if not document_hash:
        return sid
    if not re.fullmatch(r"[0-9a-f]{64}", document_hash):
        raise ValueError("Invalid source document hash")
    parts = sid.split(":")
    base_length = 1 if parts[0] == "original" else 2
    if len(parts) == base_length + 1:
        if parts[-1] != document_hash:
            raise ValueError("Source belongs to another document version")
        sid = ":".join(parts[:-1])
        parts = parts[:-1]
    if sid != "original" and (
        len(parts) != 2 or parts[0] not in ("figure", "page") or not parts[1].isdigit()
    ):
        raise ValueError("Invalid managed document source ID")
    return f"{sid}:{document_hash}"


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


def cache_directory(paper_id, *, document=None, root=None, legacy_root=None, cached_only=False):
    """Current source cache directory; unavailable managed documents have no fallback."""
    document = capture_document(
        paper_id, document=document, legacy_root=legacy_root, cached_only=cached_only
    )
    root = Path(root) if root is not None else FIG_DIR
    if document is None:
        return root / _safe(paper_id)
    if not document_current(document):
        return None
    if not document.managed:
        return root / _safe(paper_id)
    return root / derivative_key(
        document,
        "figures-v1",
        {
            "min_height": MIN_HEIGHT,
            "max_height": MAX_HEIGHT,
            "render_scale": RENDER_SCALE,
            "min_png_bytes": MIN_PNG_BYTES,
        },
    )


def image_path(paper_id, item, *, root=None, legacy_root=None, historical=False):
    """Resolve a proven cache entry, or a retained legacy deck asset explicitly."""
    root = Path(root) if root is not None else FIG_DIR
    name = item.get("file")
    if not isinstance(name, str) or Path(name).name != name:
        return None
    if historical:
        if item.get("document_hash"):
            key = item.get("cache_key")
            if not isinstance(key, str):
                return None
            parts = Path(key).parts
            if (
                len(parts) != 3
                or parts[:2] != ("documents", item["document_hash"])
                or not re.fullmatch(r"[0-9a-f]{64}", parts[1])
                or not re.fullmatch(r"figures-v[0-9]+-[0-9a-f]{24}", parts[2])
            ):
                return None
            folder = root / key
        else:
            folder = root / _safe(paper_id)
    else:
        document = capture_document(paper_id, legacy_root=legacy_root, cached_only=True)
        if document is not None and (
            not document_current(document) or item.get("document_hash") != document.sha256
        ):
            return None
        folder = cache_directory(
            paper_id, document=document, root=root, legacy_root=legacy_root, cached_only=True
        )
        if folder is None:
            return None
    path = (folder / name).resolve()
    return path if path.is_relative_to(root.resolve()) and path.is_file() else None


def extract(
    paper_id: str,
    pdf_path: Path,
    force: bool = False,
    *,
    cached_only=False,
    document=None,
    root=None,
    legacy_root=None,
    loaded_source=None,
    cancelled=lambda: False,
) -> list[Figure]:
    """Render every figure and table in the paper, newest render cached on disk."""

    def current():
        return not cancelled() and (
            loaded_current(loaded_source)
            if loaded_source is not None
            else document_current(document)
        )

    root = Path(root) if root is not None else FIG_DIR
    if loaded_source is not None:
        loaded_current(loaded_source)
        if hashlib.sha256(loaded_source.data).hexdigest() != loaded_source.view.fingerprint:
            raise ValueError("Loaded figure bytes differ from their exact original")
        if (
            loaded_source.view.owner.paper_id != paper_id
            or Path(pdf_path).resolve() != loaded_source.view.path
        ):
            raise ValueError("Figure extraction differs from its actual loaded source")
        # Unbound ready callbacks still read this legacy alias. It never becomes
        # managed cache authority; owned loads regenerate exact original bytes.
        if loaded_source.document is not None and loaded_source.document.managed:
            out_dir = root / _loaded_key(loaded_source)
            source = dict(
                document_hash=loaded_source.view.fingerprint,
                cache_key=out_dir.relative_to(root).as_posix(),
            )
        else:
            out_dir = root / _safe(paper_id)
            source = dict(document_hash=loaded_source.view.fingerprint)
    else:
        document = capture_document(
            paper_id, document=document, legacy_root=legacy_root, cached_only=cached_only
        )
        if document is not None and (
            not document_current(document) or Path(pdf_path).resolve() != document.path.resolve()
        ):
            return []
        if root == FIG_DIR:
            ensure_dirs()
        out_dir = cache_directory(
            paper_id, document=document, root=root, legacy_root=legacy_root, cached_only=cached_only
        )
        if out_dir is None:
            return []
        source = (
            {"document_hash": document.sha256, "cache_key": out_dir.relative_to(root).as_posix()}
            if document is not None and document.managed
            else {}
        )
    if not current():
        return []
    index = out_dir / "index.json"

    if index.exists() and not force and loaded_source is None:
        stored = json.loads(index.read_text(encoding="utf-8"))
        found = [
            Figure(
                paper_id=paper_id,
                label=f["label"],
                caption=f["caption"],
                page=f["page"],
                path=out_dir / f["file"],
                kind=f["kind"],
                meta={"rect": f.get("rect"), **source},
            )
            for f in stored
            if Path(f["file"]).name == f["file"]
            and (out_dir / f["file"]).exists()
            and (not source or f.get("document_hash") == source["document_hash"])
        ]
        return found if current() else []

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
        with (
            pymupdf.open(stream=loaded_source.data, filetype="pdf")
            if loaded_source is not None
            else pymupdf.open(pdf_path)
        ) as doc:
            for pno, page in enumerate(doc):
                if not current():
                    return []
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
                    if not current():
                        return []
                    try:
                        pix = page.get_pixmap(
                            matrix=pymupdf.Matrix(RENDER_SCALE, RENDER_SCALE),
                            clip=pymupdf.Rect(*rect),
                        )
                        asset = {}
                        encoded = pix.tobytes("png") if loaded_source is not None else None
                        if encoded is not None:
                            if len(encoded) < MIN_PNG_BYTES:
                                continue
                            asset = dict(asset_sha256=hashlib.sha256(encoded).hexdigest())
                        if source:
                            temporary = None
                            try:
                                with tempfile.NamedTemporaryFile(
                                    dir=out_dir, suffix=".png", delete=False
                                ) as handle:
                                    temporary = Path(handle.name)
                                if encoded is not None:
                                    temporary.write_bytes(encoded)
                                else:
                                    pix.save(temporary)
                                if not current():
                                    return []
                                temporary.replace(out_dir / name)
                            finally:
                                if temporary is not None:
                                    temporary.unlink(missing_ok=True)
                        else:
                            pix.save(out_dir / name)
                    except Exception:
                        continue

                    # A region that resolved to blank paper compresses to almost
                    # nothing. Showing it would be worse than omitting it.
                    if loaded_source is None and (out_dir / name).stat().st_size < MIN_PNG_BYTES:
                        (out_dir / name).unlink(missing_ok=True)
                        continue

                    figures.append(
                        Figure(
                            paper_id,
                            label,
                            caption,
                            pno + 1,
                            out_dir / name,
                            kind,
                            {"rect": list(rect), **source, **asset},
                        )
                    )
                    manifest.append(
                        {
                            "label": label,
                            "caption": caption,
                            "page": pno + 1,
                            "file": name,
                            "kind": kind,
                            "rect": list(rect),
                            **source,
                            **asset,
                        }
                    )
    except Exception:
        return figures if current() else []

    if not current():
        return []
    if source:
        from paper_daily.presentations import _atomic_json

        _atomic_json(index, manifest)
    else:
        index.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return figures if current() else []
