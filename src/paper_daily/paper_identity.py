"""Find records in the library that are the same paper.

Two copies of one paper split its research: notes and analysis sit on one record,
the list membership on the other. They arise when a roster and Semantic Scholar file
one paper under different years, when a bibliography is imported twice, or when two
devices each add a paper before their workspaces are joined.

This module only proposes. Nothing here changes the database: a wrong merge hands
the reader another paper's notes and analysis, so merging stays an explicit step.

- **same**: the records share an identifier (DOI, arXiv id or Semantic Scholar id)
  and their titles agree.
- **likely**: nothing contradicts it, and either the titles are identical once
  normalised, or they agree under `openalex.same_paper` and the first authors share
  a surname. `same_paper` alone is built to forgive a bibliography's paraphrase, so
  between two real titles it pairs "Language Modeling Is Compression" with "Proxy
  Compression for Language Modeling". Only papers in a reading list are compared by
  title: that is where a duplicate costs the reader something.
- **check**: the records share an identifier but their titles disagree, so one of
  the identifiers is probably wrong. Shown, never merged without a look.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from paper_daily.pdf_sources import arxiv_id
from paper_daily.sources.openalex import _norm, _tokens, same_paper

# Tables holding the reader's own work on a paper: what a merge must carry over, and
# what decides which copy is the one to keep.
RESEARCH_TABLES = (
    "list_papers",
    "notes",
    "dives",
    "close_readings",
    "chat",
    "pdf_highlights",
    "pdf_ai_highlights",
    "pins",
    "reading_log",
    "paper_context",
)
# Published versions are routinely a year or two after the preprint.
YEAR_GAP = 2


@dataclass(frozen=True)
class Paper:
    id: str
    title: str
    year: int | None
    doi: str | None
    arxiv: str | None
    s2: str | None
    surname: str | None = None
    key: str = ""
    words: frozenset[str] = frozenset()
    head: str | None = None


@dataclass
class Group:
    kind: str
    papers: list[str]
    reasons: list[str] = field(default_factory=list)
    research: dict[str, int] = field(default_factory=dict)

    @property
    def keep(self) -> str:
        """The copy holding the most of the reader's work; the rest would merge into it."""
        return self.papers[0]


def doi_key(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", "", value.strip(), flags=re.I)
    return value.lower() if value.startswith("10.") else None


def arxiv_key(value: str | None) -> str | None:
    found = arxiv_id(value) if value else None
    return re.sub(r"v\d+$", "", found).lower() if found else None


def paper(row) -> Paper:
    doi = doi_key(row["doi"])
    arxiv = arxiv_key(row["arxiv_id"])
    if doi and doi.startswith("10.48550/arxiv."):
        arxiv = arxiv or arxiv_key(doi)
        doi = None
    return Paper(
        id=row["id"],
        title=row["title"] or "",
        year=row["year"],
        doi=doi,
        arxiv=arxiv,
        s2=(row["s2_id"] or "").strip().lower() or None,
        surname=_surname(row["authors_json"]),
        key=_norm(row["title"] or ""),
        words=frozenset(_tokens(row["title"] or "")),
        head=_head(row["title"] or ""),
    )


def _head(title: str) -> str | None:
    """The method name before a colon, kept with its symbols: PredRNN is not PredRNN++."""
    head, colon, _ = title.partition(":")
    return head.strip().lower() if colon and len(head.split()) <= 2 else None


def _surname(authors_json: str | None) -> str | None:
    try:
        names = json.loads(authors_json or "[]")
    except ValueError:
        return None
    first = names[0] if names and isinstance(names[0], str) else ""
    words = re.findall(r"[^\W\d_]+", first.lower())
    return words[-1] if words else None


def load(conn: sqlite3.Connection) -> list[Paper]:
    conn.row_factory = sqlite3.Row
    return [
        paper(r)
        for r in conn.execute(
            "SELECT id, title, year, doi, arxiv_id, s2_id, authors_json FROM papers"
        )
    ]


class _Sets:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def join(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)


def _identifiers(p: Paper) -> list[tuple[str, str]]:
    return [(label, v) for label, v in (("DOI", p.doi), ("arXiv", p.arxiv), ("S2", p.s2)) if v]


def _compatible(a: Paper, b: Paper) -> bool:
    """Nothing on record says these are different papers."""
    if a.arxiv and b.arxiv and a.arxiv != b.arxiv:
        return False
    if a.doi and b.doi and a.doi != b.doi:
        return False
    return not (a.year and b.year and abs(a.year - b.year) > YEAR_GAP)


def _shared(group: list[Paper]) -> list[str]:
    seen: dict[tuple[str, str], int] = defaultdict(int)
    for p in group:
        for ident in _identifiers(p):
            seen[ident] += 1
    return [f"{label} {value}" for (label, value), n in seen.items() if n > 1]


def _titles_agree(group: list[Paper]) -> bool:
    first = group[0].title
    return all(same_paper(first, p.title) or same_paper(p.title, first) for p in group[1:])


def _strong(papers: list[Paper]) -> list[list[Paper]]:
    sets = _Sets()
    owner: dict[tuple[str, str], str] = {}
    for p in papers:
        for ident in _identifiers(p):
            if ident in owner:
                sets.join(p.id, owner[ident])
            else:
                owner[ident] = p.id
    members: dict[str, list[Paper]] = defaultdict(list)
    for p in papers:
        if p.id in sets.parent:
            members[sets.find(p.id)].append(p)
    return [g for g in members.values() if len(g) > 1]


def _alike(a: Paper, b: Paper) -> bool:
    # Normalising drops symbols, so the method names are compared first.
    if a.head and b.head and a.head != b.head:
        return False
    if a.key == b.key:
        return True
    # Beyond an identical title, a match must look like one paper filed twice, not
    # the same author's follow-up: same first author, same year give or take the
    # preprint, the same method name.
    if not (a.surname and a.surname == b.surname):
        return False
    if a.year and b.year and abs(a.year - b.year) > 1:
        return False
    small = min(len(a.words), len(b.words))
    if not small or len(a.words & b.words) / small < 0.4:
        return False
    return same_paper(a.title, b.title) or same_paper(b.title, a.title)


def _likely(papers: list[Paper], seeds: Iterable[str], grouped: set[str]) -> list[list[Paper]]:
    by_id = {p.id: p for p in papers}
    exact: dict[str, list[str]] = defaultdict(list)
    by_surname: dict[str, list[str]] = defaultdict(list)
    for p in papers:
        exact[p.key].append(p.id)
        if p.surname:
            by_surname[p.surname].append(p.id)
    found: list[list[Paper]] = []
    taken: set[str] = set(grouped)
    for seed in seeds:
        a = by_id.get(seed)
        if a is None or a.id in taken or not a.key:
            continue
        candidates = set(exact[a.key]) | set(by_surname.get(a.surname or "", ()))
        group = [a]
        for cid in sorted(candidates):
            b = by_id[cid]
            if cid == a.id or cid in taken:
                continue
            if _alike(a, b) and all(_compatible(b, other) for other in group):
                group.append(b)
        if len(group) > 1:
            found.append(group)
            taken.update(p.id for p in group)
    return found


def _research(conn: sqlite3.Connection, ids: list[str]) -> dict[str, int]:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    counts = dict.fromkeys(ids, 0)
    marks = ",".join("?" * len(ids))
    for table in RESEARCH_TABLES:
        if table not in tables:
            continue
        for pid, n in conn.execute(
            f"SELECT paper_id, COUNT(*) FROM {table} WHERE paper_id IN ({marks}) GROUP BY paper_id",
            ids,
        ):
            counts[pid] += n
    return counts


def _group(conn, kind: str, members: list[Paper], reasons: list[str]) -> Group:
    research = _research(conn, [p.id for p in members])
    # Most of the reader's work first, then the earlier record, so a merge moves least.
    ordered = sorted(members, key=lambda p: (-research[p.id], p.year or 9999, p.id))
    return Group(kind, [p.id for p in ordered], reasons, research)


def find(conn: sqlite3.Connection, within: Iterable[str] | None = None) -> list[Group]:
    """Every proposed duplicate group, or only those touching `within` (paper ids).

    Title comparison starts from `within`, or from every paper in a reading list.
    """
    papers = load(conn)
    if within is None:
        seeds = [r[0] for r in conn.execute("SELECT DISTINCT paper_id FROM list_papers")]
    else:
        seeds = list(dict.fromkeys(within))
    wanted = set(seeds) if within is not None else None

    groups: list[Group] = []
    grouped: set[str] = set()
    for members in _strong(papers):
        ids = {p.id for p in members}
        grouped |= ids
        if wanted is not None and not ids & wanted:
            continue
        kind = "same" if _titles_agree(members) else "check"
        groups.append(_group(conn, kind, members, _shared(members)))
    for members in _likely(papers, seeds, grouped):
        groups.append(_group(conn, "likely", members, ["title"]))
    order = {"same": 0, "check": 1, "likely": 2}
    groups.sort(key=lambda g: (order[g.kind], -sum(g.research.values()), g.keep))
    return groups
