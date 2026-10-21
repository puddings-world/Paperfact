"""Where a paper was published: said briefly, and found when only a preprint is known.

A reading list for a field you want to publish in is partly a map of where work in
that field lands. The rows said "International Conference on Medical Image Computing
and Computer-Assisted Intervention 2025", "Lecture notes in computer science 2026" and
"arXiv.org 2025" side by side, and "arXiv" was often stale: Semantic Scholar keeps the
preprint as the paper's venue long after publication, which is how SASVi (IJCARS
2025) and GLSFormer (MICCAI 2023) came to be listed as preprints.

OpenAlex keeps a separate location for the published version, so a preprint-only row
is checked there; an LNCS chapter is named by its proceedings through Crossref, since
"Lecture Notes in Computer Science" is a series, not a venue.
"""

from __future__ import annotations

import json
import re
import urllib.parse

from paper_daily.http import fetch_text
from paper_daily.sources import crossref, openalex

PREPRINT_HOSTS = ("arxiv", "biorxiv", "medrxiv", "techrxiv", "research square", "ssrn")

# Lower-case fragment of the full name -> how people in the field say it.
SHORT = (
    ("miccai", "MICCAI"),
    ("medical image computing and computer", "MICCAI"),
    ("information processing in computer-assisted interventions", "IPCAI"),
    ("international symposium on biomedical imaging", "ISBI"),
    ("transactions on medical imaging", "TMI"),
    ("medical image analysis", "MedIA"),
    ("computer assisted radiology and surgery", "IJCARS"),
    ("journal of biomedical and health informatics", "JBHI"),
    ("transactions on biomedical engineering", "TBME"),
    ("scientific data", "Sci Data"),
    ("biomedical signal processing and control", "BSPC"),
    ("translational vision science", "TVST"),
    ("nature communications", "Nat Commun"),
    ("computer vision and pattern recognition", "CVPR"),
    ("international conference on computer vision", "ICCV"),
    ("european conference on computer vision", "ECCV"),
    ("winter conference on applications of computer vision", "WACV"),
    ("neural information processing systems", "NeurIPS"),
    ("international conference on machine learning", "ICML"),
    ("learning representations", "ICLR"),
    ("lecture notes in computer science", "LNCS"),
)


# How a surgical-video reading list groups by venue: where the user means to publish
# first, then the journals that venue feeds, then the general vision and ML venues.
TIERS = (
    "MICCAI", "IPCAI", "IJCARS", "MedIA", "TMI", "ISBI", "JBHI", "TBME",
    "CVPR", "ICCV", "ECCV", "NeurIPS", "ICML", "ICLR", "WACV", "Sci Data",
)


def group_key(venue: str | None, year: int | None) -> tuple:
    """Sort key that groups papers by venue: the tiers above in order, any other
    venue after them alphabetically, preprints last; newest first within a venue."""
    name = short(venue)
    rank = TIERS.index(name) if name in TIERS else len(TIERS)
    return (is_preprint(venue), rank, name.lower(), -(year or 0))


def is_preprint(venue: str | None) -> bool:
    low = (venue or "").lower()
    return not low or any(host in low for host in PREPRINT_HOSTS)


def short(venue: str | None) -> str:
    if is_preprint(venue):
        return "arXiv" if "arxiv" in (venue or "").lower() else (venue or "未發表")
    low = venue.lower()
    for fragment, name in SHORT:
        if fragment in low:
            return name
    return venue if len(venue) <= 28 else venue[:26].rstrip() + "…"


def label(venue: str | None, year: int | None) -> str:
    """"MICCAI 2025", or "arXiv 2025 · 預印本" for a paper not published yet."""
    name = short(venue)
    text = f"{name} {year}" if year and str(year) not in name else name
    return f"{text} · 預印本" if is_preprint(venue) else text


def _plain(title: str) -> str:
    """OpenAlex keeps LaTeX from the publisher: "$$\\textsf{GLSFormer}$$: Gated…"."""
    title = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", title or "")
    return title.replace("$", "")


def _proceedings(doi: str) -> str | None:
    """The proceedings an LNCS chapter belongs to, e.g. "... MICCAI 2023"."""
    url = f"{crossref.API}/{urllib.parse.quote(doi)}?mailto={crossref.MAILTO}"
    try:
        message = json.loads(fetch_text(url, max_age=30 * 86400, retries=3))["message"]
    except Exception:
        return None
    names = [t for t in message.get("container-title") or [] if "lecture notes" not in t.lower()]
    return names[0] if names else None


def published(title: str) -> dict | None:
    """{venue, year, doi} of the published version of `title`, if OpenAlex knows one."""
    query = urllib.parse.urlencode({
        "search": _plain(title), "per-page": 5, "mailto": openalex.MAILTO,
        "select": "display_name,publication_year,doi,locations",
    })
    try:
        works = json.loads(
            fetch_text(f"{openalex.API}?{query}", max_age=7 * 86400, retries=3)
        ).get("results") or []
    except Exception:
        return None
    for work in works:
        if not openalex.same_paper(title, _plain(work.get("display_name") or "")):
            continue
        for loc in work.get("locations") or []:
            source = loc.get("source") or {}
            name = source.get("display_name") or ""
            if not name or source.get("type") == "repository" or is_preprint(name):
                continue
            doi = (work.get("doi") or "").replace("https://doi.org/", "") or None
            if "lecture notes" in name.lower() and doi:
                name = _proceedings(doi) or name
            return {"venue": name, "year": work.get("publication_year"), "doi": doi}
    return None


def refresh(conn, paper_ids: list[str], log=print) -> int:
    """Replace a preprint or bare-series venue with where the paper was published."""
    changed = 0
    for pid in paper_ids:
        row = conn.execute(
            "SELECT title, venue, year, doi FROM papers WHERE id=?", (pid,)
        ).fetchone()
        if row is None or not (is_preprint(row["venue"]) or short(row["venue"]) == "LNCS"):
            continue
        found = published(row["title"])
        if not found:
            log(f"  still a preprint  {row['title'][:60]}")
            continue
        # A DOI minted by arXiv names the preprint; the published one supersedes it.
        doi = row["doi"]
        if found["doi"] and (not doi or doi.lower().startswith("10.48550/")):
            doi = found["doi"]
        conn.execute(
            "UPDATE papers SET venue=?, year=?, doi=? WHERE id=?",
            (found["venue"], found["year"] or row["year"], doi, pid),
        )
        log(f"  {label(found['venue'], found['year']):18s} {row['title'][:60]}")
        changed += 1
    return changed
