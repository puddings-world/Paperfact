"""Which earlier and later work in a paper's lineage comes from its own team.

OpenAlex lists every work's authors and their institutions with stable ids, so
"the same group" is a shared author id or institution id, not a guess from names.
Lookups go through the cached HTTP client: a list opened again costs nothing.
"""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Callable

from paper_daily.http import fetch_text
from paper_daily.sources.openalex import API, MAILTO, same_paper

SELECT = "id,doi,display_name,authorships"
BATCH = 50
MAX_AGE = 30 * 86400


def _works(filter_expr: str, per_page: int = BATCH) -> list[dict]:
    query = urllib.parse.urlencode(
        {"filter": filter_expr, "per-page": per_page, "select": SELECT, "mailto": MAILTO}
    )
    try:
        payload = json.loads(fetch_text(f"{API}?{query}", max_age=MAX_AGE, retries=3))
    except Exception:  # noqa: BLE001 - one failed lookup leaves that work unknown, not an error
        return []
    return payload.get("results") or []


def _doi(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        value = value.removeprefix(prefix)
    return value or None


def _work_id(value: str | None) -> str | None:
    value = (value or "").strip().rsplit("/", 1)[-1].upper()
    return value if value.startswith("W") and value[1:].isdigit() else None


def people(work: dict) -> dict[str, dict[str, str]]:
    """{"authors": {id: name}, "institutions": {id: name}} of one OpenAlex work."""
    authors, institutions = {}, {}
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        if author.get("id"):
            authors[author["id"]] = author.get("display_name") or author["id"]
        for place in authorship.get("institutions") or []:
            if place.get("id"):
                institutions[place["id"]] = place.get("display_name") or place["id"]
    return {"authors": authors, "institutions": institutions}


def _by_title(title: str | None) -> dict | None:
    if not title or not title.strip():
        return None
    for work in _works(f"title.search:{title.replace(',', ' ')}", per_page=5):
        if same_paper(title, work.get("display_name", "")):
            return work
    return None


def lookup(items: list[dict], progress: Callable[[int, int], None] = lambda _d, _t: None):
    """OpenAlex's people for each item ({"doi", "work_id", "title"}), by position;
    None where the work could not be found."""
    found: list[dict | None] = [None] * len(items)
    by_doi: dict[str, list[int]] = {}
    by_id: dict[str, list[int]] = {}
    for i, item in enumerate(items):
        if wid := _work_id(item.get("work_id")):
            by_id.setdefault(wid, []).append(i)
        elif doi := _doi(item.get("doi")):
            by_doi.setdefault(doi, []).append(i)
    done, total = 0, len(items)
    for key, index, field in (
        ("ids.openalex", by_id, lambda w: _work_id(w.get("id"))),
        ("doi", by_doi, lambda w: _doi(w.get("doi"))),
    ):
        names = list(index)
        for start in range(0, len(names), BATCH):
            batch = names[start : start + BATCH]
            for work in _works(f"{key}:{'|'.join(batch)}"):
                for i in index.get(field(work), []):
                    found[i] = people(work)
            done += sum(len(index[name]) for name in batch)
            progress(done, total)
    # Only a reference with neither id is looked up by its title, one at a time.
    for i, item in enumerate(items):
        if found[i] is None and not _work_id(item.get("work_id")) and not _doi(item.get("doi")):
            work = _by_title(item.get("title"))
            found[i] = people(work) if work else None
            done += 1
            progress(done, total)
    return found


def own(title: str | None, doi: str | None) -> dict | None:
    """The paper's own people, by DOI when it has one."""
    return lookup([{"doi": doi, "title": title}])[0]


def shared(mine: dict, theirs: dict | None) -> dict[str, list[str]] | None:
    """The authors and institutions two works share, by name; None when neither."""
    if not theirs:
        return None
    authors = [mine["authors"][a] for a in mine["authors"] if a in theirs["authors"]]
    places = [
        mine["institutions"][p] for p in mine["institutions"] if p in theirs["institutions"]
    ]
    return {"authors": authors, "institutions": places} if authors or places else None


def team(paper: dict, refs: list[dict], later: list[dict], progress=lambda _d, _t: None):
    """Which references and later works share an author or institution with the
    paper: {"refs": {ref_key: shared}, "later": {work_id: shared}, "known": n,
    "total": n} -- `known` counts the works OpenAlex could identify."""
    mine = own(paper.get("title"), paper.get("doi"))
    items = [{"doi": r.get("doi"), "title": r.get("title")} for r in refs] + [
        {"work_id": r.get("work_id"), "doi": r.get("doi"), "title": r.get("title")} for r in later
    ]
    if mine is None:
        return {"refs": {}, "later": {}, "known": 0, "total": len(items), "own": False}
    found = lookup(items, progress)
    out = {"refs": {}, "later": {}, "known": sum(1 for f in found if f), "total": len(items)}
    for r, theirs in zip(refs, found[: len(refs)], strict=True):
        if r.get("ref_key") and (match := shared(mine, theirs)):
            out["refs"][r["ref_key"]] = match
    for r, theirs in zip(later, found[len(refs) :], strict=True):
        if r.get("work_id") and (match := shared(mine, theirs)):
            out["later"][r["work_id"]] = match
    out["own"] = True
    return out
