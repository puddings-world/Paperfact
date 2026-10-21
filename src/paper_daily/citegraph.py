"""The 引用 tab as a map: a paper, what it rests on, what builds on it, and how those
cite one another.

The lists say what each neighbour is to this paper. What they cannot show is the
shape around it: that three of the references are one line of work citing each other,
or that the later papers split into two camps that never cite across. That shape is
in the neighbours' own reference lists, which Semantic Scholar's batch endpoint
returns for up to 500 papers a request, so finding it costs a few requests and no
model call. It is fetched once per paper and kept (kv `citegraph.<paper id>`), as the
lists are, and every node and edge drawn comes from rows already stored.

An edge points from the cited paper to the paper citing it, the way an idea travels:
older on the left, newer on the right.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from paper_daily import followups
from paper_daily.http import FetchError, post_json
from paper_daily.store import connect, get_kv, now, set_kv, title_key

Log = Callable[[str], None]

BATCH = "https://api.semanticscholar.org/graph/v1/paper/batch"
# A famous paper's reference list runs to hundreds of ids; a smaller batch keeps one
# answer from being megabytes when only the ids inside this map are wanted.
CHUNK = 100

SIDES = ("ref", "center", "later")


@dataclass
class Node:
    key: str
    title: str
    side: str  # "ref", "center" or "later"
    year: int | None = None
    venue: str | None = None
    citations: int | None = None
    verdict: str | None = None
    # What it is to the paper at the centre: 與原文的關係, from the lists.
    relation: str | None = None
    # 這篇在做什麼, for a reference; the citing sentence, from either side.
    gist: str | None = None
    quote: str | None = None
    why: str | None = None
    influential: bool = False
    doi: str | None = None
    # How Semantic Scholar's batch endpoint can name it, if at all.
    lookup: str | None = None
    here: dict | None = None
    label: str = ""
    links: int = 0

    @property
    def radius(self) -> float:
        """Influence as area: a log scale, or a 30k-cite classic swallows the map."""
        r = 9.0 + 5.2 * math.log10(1 + (self.citations or 0))
        return max(r, 24.0) if self.side == "center" else r

    @property
    def label_px(self) -> float:
        """The label's size inside the circle; under 7.5 it is set beneath instead."""
        r = self.radius
        return min(r * 0.62, 2.2 * r / max(len(self.label), 1))

    @property
    def label_below(self) -> bool:
        return self.label_px < 7.5


@dataclass
class Graph:
    nodes: list[Node]
    # (cited, citing) node keys.
    edges: list[tuple[str, str]]
    checked: str | None = None
    # Neighbours Semantic Scholar could not place, so their edges among the others
    # are unknown rather than absent.
    unplaced: int = 0
    hidden: dict[str, int] = field(default_factory=dict)
    # References left off because the text never cites them (see neighbours).
    unconfirmed: int = 0


_STOP = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
    "via",
    "with",
    "is",
    "are",
    "by",
    "at",
    "as",
    "its",
    "your",
    "we",
    "how",
    "what",
    "towards",
}


_CJK = re.compile(r"[㐀-鿿]")


def label(title: str) -> str:
    """One or two words standing for a paper inside its circle.

    Papers are mostly called by the name before the colon -- "GPTQ", "Cataract-1K" --
    and a title without one by its initials, which is how people abbreviate it anyway.
    """
    title = (title or "").strip()
    if not title:
        return "?"
    if _CJK.match(title):
        return title[:2]
    head = title.split(":")[0].strip()
    if head != title and len(head.split()) <= 2 and len(head) <= 14:
        return head if len(head) <= 9 else head[:8] + "…"
    # "Cataract-1K Dataset for ...", "LensID: ..." -- a first word with a digit or an
    # inner capital is a name, not prose.
    first = title.split()[0].rstrip(",.;")
    if len(first) <= 12 and re.search(r"\d|.[A-Z]", first):
        return first
    words = [w for w in re.split(r"[^A-Za-z0-9]+", title) if w and w.lower() not in _STOP]
    if not words:
        return title[:3]
    if len(words) == 1:
        return words[0][:8]
    return "".join(w[0].upper() for w in words[:4])


def _lookup(
    *, s2: str | None = None, doi: str | None = None, arxiv: str | None = None
) -> str | None:
    if s2:
        return s2.removeprefix("S2:")
    if arxiv:
        return f"ARXIV:{arxiv}"
    if doi:
        return f"DOI:{doi}"
    return None


def _center(conn, paper_id: str) -> Node | None:
    row = conn.execute(
        "SELECT id, title, year, venue, doi, s2_id, arxiv_id, citation_count "
        "FROM papers WHERE id=?",
        (paper_id,),
    ).fetchone()
    if row is None:
        return None
    return Node(
        key=f"center:{paper_id}",
        title=row["title"],
        side="center",
        year=row["year"],
        venue=row["venue"],
        citations=row["citation_count"],
        doi=row["doi"],
        lookup=_lookup(s2=row["s2_id"], arxiv=row["arxiv_id"], doi=row["doi"]),
        here={"id": paper_id, "read": False},
    )


def neighbours(conn, paper_id: str) -> tuple[list[Node], int]:
    """The paper and every stored work on either side of it, one node per work, and
    how many references were left off as unconfirmed.

    The reference side of the list also carries Semantic Scholar's reference list
    for the paper, matched by title, for entries the text was never seen to cite.
    That list is where the mistakes are -- on SASVi it offered "Uncle" and a
    paper on intracranial haemorrhage -- and a map draws every entry as an equal
    circle with an arrow into the paper, with no room for the list's "文中未抓到
    引用句". So once the text has been read, only references it cites are drawn;
    before that, the graph's entries are all there is, and they are drawn.
    """
    centre = _center(conn, paper_id)
    if centre is None:
        return [], 0
    nodes = [centre]
    seen = {title_key(centre.title)}
    refs = followups.references(conn, paper_id)
    read = any(r.get("basis") == "context" for r in refs)
    unconfirmed = 0
    for r in refs:
        if not r.get("title") or title_key(r["title"]) in seen:
            continue
        if read and r.get("basis") != "context":
            unconfirmed += 1
            continue
        seen.add(title_key(r["title"]))
        corpus = r.get("corpus_id")
        s2 = r.get("s2_id")
        # A marker the analysis could not identify stays in the list with a note in
        # prose ("從引用句看不出來…") where the title would be; on a map it would be
        # a circle standing for nothing.
        if not (s2 or corpus or r.get("doi")) and _CJK.search(r["title"]):
            continue
        if corpus and not s2:
            got = conn.execute(
                "SELECT s2_id, arxiv_id, doi, citation_count FROM papers WHERE id=?", (corpus,)
            ).fetchone()
            if got:
                s2 = got["s2_id"]
                r = {
                    **r,
                    "citations": r.get("citations") or got["citation_count"],
                    "doi": r.get("doi") or got["doi"],
                }
        nodes.append(
            Node(
                key=f"ref:{r.get('ref_key') or corpus}",
                title=r["title"],
                side="ref",
                year=r.get("year"),
                venue=r.get("venue"),
                citations=r.get("citations"),
                verdict=r.get("verdict"),
                relation=r.get("purpose"),
                gist=r.get("gist"),
                quote=(r.get("contexts") or [None])[0],
                why=r.get("why"),
                influential=bool(r.get("influential")),
                doi=r.get("doi"),
                lookup=_lookup(s2=s2, doi=r.get("doi")),
                here=followups.in_corpus(conn, r.get("doi"), r["title"], corpus),
            )
        )
    for r in followups.for_paper(conn, paper_id):
        if title_key(r["title"]) in seen:
            continue
        seen.add(title_key(r["title"]))
        wid = r["work_id"]
        nodes.append(
            Node(
                key=f"later:{wid}",
                title=r["title"],
                side="later",
                year=r.get("year"),
                venue=r.get("venue"),
                citations=r.get("citations"),
                verdict=r.get("verdict"),
                relation=r.get("relation"),
                quote=(r.get("contexts") or [None])[0],
                why=r.get("why"),
                doi=r.get("doi"),
                lookup=_lookup(
                    s2=wid if wid.startswith("S2:") else None,
                    arxiv=r.get("arxiv_id"),
                    doi=r.get("doi"),
                ),
                here=followups.in_corpus(conn, r.get("doi"), r["title"]),
            )
        )
    for n in nodes:
        n.label = label(n.title)
    return nodes, unconfirmed


def build(conn, paper_id: str) -> Graph:
    """Everything the map draws, from stored rows only."""
    nodes, unconfirmed = neighbours(conn, paper_id)
    if not nodes:
        return Graph([], [])
    centre = nodes[0]
    edges: set[tuple[str, str]] = set()
    for n in nodes[1:]:
        edges.add((n.key, centre.key) if n.side == "ref" else (centre.key, n.key))

    stored = get_kv(conn, f"citegraph.{paper_id}") or {}
    by_lookup = {n.lookup: n.key for n in nodes if n.lookup}
    for cited, citing in stored.get("edges") or []:
        a, b = by_lookup.get(cited), by_lookup.get(citing)
        if a and b and a != b:
            edges.add((a, b))
    for n in nodes:
        if not n.citations and n.lookup in (stored.get("citations") or {}):
            n.citations = stored["citations"][n.lookup]

    # Papers already here are linked by the corpus graph too, at no cost.
    by_corpus = {n.here["id"]: n.key for n in nodes if n.here}
    if len(by_corpus) > 1:
        marks = ",".join("?" * len(by_corpus))
        for r in conn.execute(
            f"SELECT paper_id, ref_paper_id FROM refs "
            f"WHERE paper_id IN ({marks}) AND ref_paper_id IN ({marks})",
            (*by_corpus, *by_corpus),
        ):
            edges.add((by_corpus[r["ref_paper_id"]], by_corpus[r["paper_id"]]))

    keyed = {n.key: n for n in nodes}
    for a, b in edges:
        if centre.key not in (a, b):
            keyed[a].links += 1
            keyed[b].links += 1
    unplaced = stored.get("unplaced", 0) if stored else 0
    return Graph(nodes, sorted(edges), stored.get("checked"), unplaced, unconfirmed=unconfirmed)


def links(paper_id: str, log: Log = lambda _m: None) -> int:
    """Find which neighbours cite which, and keep it. Returns the number of links."""
    with connect() as conn:
        nodes, _unconfirmed = neighbours(conn, paper_id)
    named = [n.lookup for n in nodes if n.lookup]
    ids = list(dict.fromkeys(named))
    resolved: dict[str, str] = {}
    cites_of: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for i in range(0, len(ids), CHUNK):
        chunk = ids[i : i + CHUNK]
        try:
            answer = post_json(
                f"{BATCH}?fields=paperId,citationCount,references.paperId", {"ids": chunk}
            )
        except FetchError as e:
            log(f"  Semantic Scholar refused: {e}")
            return -1
        for wanted, record in zip(chunk, answer or [], strict=False):
            if not record:
                continue
            resolved[record["paperId"]] = wanted
            cites_of[wanted] = [
                x["paperId"] for x in record.get("references") or [] if x.get("paperId")
            ]
            if record.get("citationCount") is not None:
                counts[wanted] = record["citationCount"]
    edges = sorted(
        {
            (resolved[cited], citing)
            for citing, refs in cites_of.items()
            for cited in refs
            if cited in resolved and resolved[cited] != citing
        }
    )
    unplaced = len(nodes) - 1 - sum(1 for n in nodes[1:] if n.lookup in cites_of)
    with connect() as conn:
        set_kv(
            conn,
            f"citegraph.{paper_id}",
            {
                "checked": now(),
                "edges": [list(e) for e in edges],
                "citations": counts,
                "unplaced": unplaced,
            },
        )
        conn.commit()
    log(
        f"  {len(edges)} citation link(s) among {len(cites_of)} placed papers, "
        f"{unplaced} not found on Semantic Scholar"
    )
    return len(edges)


# ---- placing it on a page ---------------------------------------------------------
def pick(graph: Graph, limit: int | None) -> Graph:
    """The most telling neighbours on each side, when there are too many to read.

    Worth-reading verdicts first, then papers linked to other neighbours -- they carry
    the shape the map is for -- then citations.
    """
    if limit is None:
        return graph
    rank = followups.VERDICT_RANK
    keep: set[str] = set()
    hidden: dict[str, int] = {}
    for side in ("ref", "later"):
        group = [n for n in graph.nodes if n.side == side]
        group.sort(
            key=lambda n: (min(rank.get(n.verdict or "", 4), 2), -n.links, -(n.citations or 0))
        )
        keep.update(n.key for n in group[:limit])
        hidden[side] = max(0, len(group) - limit)
    nodes = [n for n in graph.nodes if n.side == "center" or n.key in keep]
    kept = {n.key for n in nodes}
    edges = [(a, b) for a, b in graph.edges if a in kept and b in kept]
    return Graph(nodes, edges, graph.checked, graph.unplaced, hidden, graph.unconfirmed)


GAP_X = 34.0
GAP_Y = 14.0
SIDE_GAP = 70.0
PER_COLUMN = 9
LABEL_H = 15.0


def layout(graph: Graph) -> tuple[dict[str, tuple[float, float]], list[tuple[float, str]]]:
    """Node centres, and a heading per column: references by year on the left, the
    paper in the middle, later work by year on the right.

    Each column is centred on the paper, biggest first and alternating above and
    below, so the influential neighbours sit nearest the line of sight. A year with
    more papers than fit in one column takes several, side by side.
    """
    columns: list[tuple[str, list[Node]]] = []
    for side in SIDES:
        group = [n for n in graph.nodes if n.side == side]
        years = sorted({n.year for n in group if n.year}) + (
            [None] if any(not n.year for n in group) else []
        )
        for year in years:
            members = [n for n in group if n.year == year]
            members.sort(key=lambda n: (-(n.citations or 0), n.title))
            for i in range(0, len(members), PER_COLUMN):
                columns.append((side, members[i : i + PER_COLUMN]))
    pos: dict[str, tuple[float, float]] = {}
    heads: list[tuple[float, str]] = []
    x = 0.0
    previous_side = None
    previous_year: object = ()
    for side, members in columns:
        width = 2 * max(n.radius for n in members)
        if previous_side is not None:
            x += SIDE_GAP if side != previous_side else GAP_X
        cx = x + width / 2
        year = members[0].year
        if (side, year) != previous_year:
            heads.append((cx, str(year) if year else "年份不明"))
        previous_year = (side, year)
        above = below = 0.0
        for i, n in enumerate(members):
            # A label set beneath its circle takes room from the next one down.
            under = LABEL_H if n.label_below else 0.0
            if i == 0:
                pos[n.key] = (cx, 0.0)
                above, below = n.radius, n.radius + under
            elif i % 2:
                pos[n.key] = (cx, below + GAP_Y + n.radius)
                below += GAP_Y + 2 * n.radius + under
            else:
                pos[n.key] = (cx, -(above + GAP_Y + n.radius + under))
                above += GAP_Y + 2 * n.radius + under
        x += width
        previous_side = side
    return pos, heads
