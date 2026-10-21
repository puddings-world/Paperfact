"""Where the disk goes, and what can be given back.

The database is not what grows: the conference catalogue adds a few tens of MB a
year and everything a reader writes is a few MB. What grows is files -- PDFs, figure
crops and the HTTP cache, which never expires on its own. Only files that can be
fetched or rebuilt again are ever offered for pruning: the cache, and the PDF,
figures and extracted text of papers nobody claims. A paper is claimed when it is
in a list, in the queue (not skipped), pinned, or carries anything a reader or an
analysis produced: notes, highlights, a deep dive, citations, chat, a close reading.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import bundle
from paper_daily.config import DATA_DIR, HTTP_CACHE, PDF_DIR, TEXT_DIR
from paper_daily.fetch import _safe_name

CACHE_DAYS = 30
FIGURES_DIR = DATA_DIR / "figures"

# Each source of a claim; a paper in any one of them keeps its files.
_CLAIMS = (
    "SELECT paper_id FROM list_papers",
    "SELECT paper_id FROM queue WHERE state != 'skipped'",
    "SELECT paper_id FROM pins",
    "SELECT paper_id FROM notes",
    "SELECT paper_id FROM pdf_highlights",
    "SELECT paper_id FROM pdf_ai_highlights",
    "SELECT paper_id FROM dives",
    "SELECT paper_id FROM cites",
    "SELECT paper_id FROM chat",
    "SELECT paper_id FROM close_readings",
)


def _size(path: Path) -> tuple[int, int]:
    """(bytes, files) under a file or folder."""
    if path.is_file():
        return path.stat().st_size, 1
    files = [p for p in path.rglob("*") if p.is_file()]
    return sum(p.stat().st_size for p in files), len(files)


def folders(data_dir: Path = DATA_DIR) -> list[tuple[str, int, int]]:
    """(name, bytes, files) for each top-level entry of the data folder, largest first.
    The database and its WAL side files count as one entry."""
    sizes: dict[str, list[int]] = {}
    for entry in data_dir.iterdir():
        name = "papers.db" if entry.name.startswith("papers.db") else entry.name
        size, count = _size(entry)
        total = sizes.setdefault(name, [0, 0])
        total[0] += size
        total[1] += count
    return sorted(((n, s, c) for n, (s, c) in sizes.items()), key=lambda r: -r[1])


def claimed(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute(" UNION ".join(_CLAIMS))}


def _paper_bytes(paper_id: str) -> int:
    paths = [PDF_DIR / f"{_safe_name(paper_id)}.pdf"]
    paths += [DATA_DIR / p for p in bundle._paper_files(paper_id)]
    return sum(p.stat().st_size for p in paths if p.is_file())


def by_list(conn: sqlite3.Connection) -> list[tuple[str, int, int]]:
    """(name, papers, bytes of their files) for the queue and each list. A paper in
    two lists counts in both: this answers what a list costs to keep or to share."""
    groups = [("main queue", "SELECT paper_id FROM queue WHERE state != 'skipped'", ())]
    for row in conn.execute("SELECT id, name FROM lists ORDER BY created_at"):
        groups.append((row[1], "SELECT paper_id FROM list_papers WHERE list_id = ?", (row[0],)))
    out = []
    for name, query, params in groups:
        ids = [r[0] for r in conn.execute(query, params)]
        out.append((name, len(ids), sum(_paper_bytes(i) for i in ids)))
    return out


@dataclass
class Plan:
    """What `prune` would delete. Paths are under the data folder only."""

    cache: list[Path] = field(default_factory=list)
    papers: dict[str, list[Path]] = field(default_factory=dict)

    @property
    def paths(self) -> list[Path]:
        return [*self.cache, *(p for ps in self.papers.values() for p in ps)]

    @property
    def cache_bytes(self) -> int:
        return sum(_size(p)[0] for p in self.cache)

    @property
    def paper_bytes(self) -> int:
        return sum(_size(p)[0] for ps in self.papers.values() for p in ps)


def plan(conn: sqlite3.Connection, cache_days: int = CACHE_DAYS, now: float | None = None) -> Plan:
    now = time.time() if now is None else now
    result = Plan()
    if HTTP_CACHE.is_dir():
        cutoff = now - cache_days * 86400
        result.cache = sorted(
            p for p in HTTP_CACHE.rglob("*") if p.is_file() and p.stat().st_mtime < cutoff
        )
    keep = {_safe_name(i) for i in claimed(conn)}
    # File names are the only link back to a paper; a name no claimed paper maps to
    # is unclaimed.
    found: dict[str, list[Path]] = {}
    for path in PDF_DIR.glob("*.pdf") if PDF_DIR.is_dir() else ():
        found.setdefault(path.stem, []).append(path)
    for path in TEXT_DIR.glob("*.txt") if TEXT_DIR.is_dir() else ():
        found.setdefault(path.stem, []).append(path)
    for path in FIGURES_DIR.iterdir() if FIGURES_DIR.is_dir() else ():
        if path.is_dir():
            found.setdefault(path.name, []).append(path)
    result.papers = {name: paths for name, paths in sorted(found.items()) if name not in keep}
    return result


def prune(conn: sqlite3.Connection, chosen: Plan, vacuum: bool = False) -> int:
    """Delete what `chosen` lists; returns the bytes freed. Checks every path is
    still under the data folder and still unclaimed, since the plan may be stale."""
    keep = {_safe_name(i) for i in claimed(conn)}
    allowed = [HTTP_CACHE.resolve(), PDF_DIR.resolve(), TEXT_DIR.resolve(), FIGURES_DIR.resolve()]
    freed = 0
    targets = list(chosen.cache)
    targets += [p for name, ps in chosen.papers.items() if name not in keep for p in ps]
    for path in targets:
        resolved = path.resolve()
        if not any(resolved.is_relative_to(root) for root in allowed) or not path.exists():
            continue
        freed += _size(path)[0]
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    if vacuum:
        conn.commit()
        conn.execute("VACUUM")
    return freed


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB"):
        if value < 1024:
            return f"{value:.0f} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"
