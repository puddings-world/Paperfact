"""Persistent reading highlights, tied to the exact PDF that was selected."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from paper_daily.store import connect, now

# Opening a paper asks for its PDF's hash several times (highlights, slide
# materials, their positions), each a read of the whole file; a file that has not
# changed keeps its hash.
_hashes: dict[tuple[str, int, int], str] = {}


def document_hash(path: Path) -> str:
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _hashes:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if len(_hashes) > 256:
            _hashes.clear()
        _hashes[key] = digest
    return _hashes[key]


def list_marks(paper_id: str, fingerprint: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, anchor, quote FROM pdf_highlights WHERE paper_id=? AND document_hash=? "
            "ORDER BY id",
            (paper_id, fingerprint),
        ).fetchall()
    with connect() as conn:
        auto = conn.execute(
            "SELECT id, anchor, quote, reason FROM pdf_ai_highlights "
            "WHERE paper_id=? AND document_hash=? AND hidden=0 ORDER BY id",
            (paper_id, fingerprint),
        ).fetchall()
    return [
        dict(id=row["id"], anchor=json.loads(row["anchor"]), quote=row["quote"], origin="manual")
        for row in rows
    ] + [
        dict(
            id=-row["id"],
            anchor=json.loads(row["anchor"]),
            quote=row["quote"],
            origin="ai",
            reason=row["reason"],
        )
        for row in auto
    ]


def add(paper_id: str, fingerprint: str, anchor: dict, quote: str) -> None:
    keys = ("p0", "o0", "p1", "o1")
    if (
        not fingerprint
        or not quote.strip()
        or any(type(anchor.get(k)) is not int or anchor[k] < 0 for k in keys)
        or (anchor["p1"], anchor["o1"]) < (anchor["p0"], anchor["o0"])
    ):
        raise ValueError("無效的原文選取範圍")
    encoded = json.dumps({k: anchor[k] for k in keys}, sort_keys=True)
    with connect() as conn:
        conn.execute(
            "INSERT INTO pdf_highlights(paper_id, document_hash, anchor, quote, created_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(paper_id, document_hash, anchor) DO NOTHING",
            (paper_id, fingerprint, encoded, quote, now()),
        )


def remove(paper_id: str, fingerprint: str, ids: list[int]) -> None:
    with connect() as conn:
        conn.executemany(
            "DELETE FROM pdf_highlights WHERE paper_id=? AND document_hash=? AND id=?",
            [(paper_id, fingerprint, ident) for ident in ids if ident > 0],
        )

        conn.executemany(
            "UPDATE pdf_ai_highlights SET hidden=1 WHERE paper_id=? AND document_hash=? AND id=?",
            [(paper_id, fingerprint, -ident) for ident in ids if ident < 0],
        )


def sync_ai(paper_id: str, path: Path, analysis: dict) -> dict:
    """Locate full verified quotes; never approximate using only their opening words."""
    import pymupdf

    from paper_daily.paper_highlights import normalize

    fingerprint = document_hash(path)
    marks, unmatched = [], []
    with pymupdf.open(path) as doc:
        page_words = {}
        for item in analysis["items"]:
            page = item.get("page")
            if type(page) is not int or not 1 <= page <= len(doc):
                unmatched.append(item)
                continue
            if page not in page_words:
                page_words[page] = doc[page - 1].get_text("words")
            words = page_words[page]
            # Compact normalization matches ligatures, line wrapping and word spacing.
            # Positions refer to the same raw word order used by SelectionOverlay.
            parts, positions = [], []
            for order, word in enumerate(words):
                piece = "".join(normalize(word[4]).split())
                if piece.endswith("-") and order + 1 < len(words):
                    nxt = words[order + 1]
                    if word[5:7] != nxt[5:7] and nxt[4][:1].islower():
                        piece = piece[:-1]
                parts.append(piece)
                positions.extend([order] * len(piece))
            haystack = "".join(parts)
            needle = "".join(normalize(item["text"]).split())
            start = haystack.find(needle)
            if start < 0 or not needle:
                unmatched.append(item)
                continue
            anchor = dict(
                p0=page - 1, o0=positions[start], p1=page - 1, o1=positions[start + len(needle) - 1]
            )
            key = hashlib.sha256(f"{page}:{item['text']}".encode()).hexdigest()
            marks.append((key, anchor, item))
    if fingerprint != document_hash(path):
        raise ValueError("定位期間 PDF 已變更，請重試。")
    with connect() as conn:
        for key, anchor, item in marks:
            conn.execute(
                "INSERT INTO pdf_ai_highlights(paper_id,document_hash,source_key,analysis_hash,"
                "anchor,quote,reason) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(paper_id,document_hash,source_key) DO UPDATE SET "
                "analysis_hash=excluded.analysis_hash, anchor=excluded.anchor, "
                "quote=excluded.quote, reason=excluded.reason",
                (
                    paper_id,
                    fingerprint,
                    key,
                    analysis["source_hash"],
                    json.dumps(anchor),
                    item["text"],
                    item["reason"],
                ),
            )
        keys = {key for key, _anchor, _item in marks}
        stale = conn.execute(
            "SELECT id,source_key FROM pdf_ai_highlights WHERE paper_id=? AND document_hash=?",
            (paper_id, fingerprint),
        ).fetchall()
        conn.executemany(
            "DELETE FROM pdf_ai_highlights WHERE id=?",
            [(row["id"],) for row in stale if row["source_key"] not in keys],
        )
    return dict(
        mapped=len(marks),
        total=len(analysis["items"]),
        unmatched=unmatched,
        document_hash=fingerprint,
    )
