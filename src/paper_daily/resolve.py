"""Find the original of a paper we only know the title of.

Four sources, tried in order of how likely each is to have this kind of paper and how
good the answer is when it does:

1. **CVF** for CVPR / ICCV / WACV -- the publisher's own PDF, no intermediary.
2. **arXiv** -- the preprint, which for ML work is usually the same paper.
3. **OpenAlex** -- ~250M works across every publisher, and the only source here that
   carries a direct link to a legally free copy of a journal paper.

Semantic Scholar is not in this list because it runs earlier, on the citation itself.
What this module does is fill the holes S2 left.

The order matters less than the fact that all of them are tried. Two of these APIs
throttle by refusing outright -- Semantic Scholar with 429, arXiv with 406 -- so a
lookup that fails today is not a paper that cannot be found, and `resolve_missing`
exists to try again tomorrow.
"""

from __future__ import annotations

import json

from paper_daily.sources import arxiv, cvf, openalex
from paper_daily.sources.openalex import _norm
from paper_daily.store import title_key


def fill_gaps(row: dict) -> tuple[dict, list[str]]:
    """Fill in whatever the row is missing. Returns (row, what was found)."""
    found: list[str] = []
    title = row.get("title")
    if not title:
        return row, found

    if not row.get("pdf_url") and not row.get("arxiv_id"):
        url = cvf.pdf_url(title, row.get("venue"), row.get("year"))
        if url:
            row["pdf_url"] = url
            found.append("cvf")
        else:
            aid = arxiv.match_title(title)
            if aid:
                row["arxiv_id"] = aid
                found.append("arxiv")

    # OpenAlex is asked whenever anything is still missing, not only the PDF: an entry
    # that failed to match anywhere is left reading "unknown 0", and the venue and year
    # are what make it a citation rather than a string.
    wants_pdf = not row.get("pdf_url") and not row.get("arxiv_id")
    wants_meta = not row.get("venue") or row.get("venue") == "unknown" or not row.get("year")
    if wants_pdf or wants_meta:
        alt = openalex.match_title(title)
        if alt:
            if wants_pdf and alt.get("pdf_url"):
                row["pdf_url"] = alt["pdf_url"]
                found.append("openalex-pdf")
            for field in ("doi", "page_url", "abstract", "citation_count"):
                if not row.get(field) and alt.get(field):
                    row[field] = alt[field]
            if wants_meta:
                if alt.get("venue"):
                    row["venue"] = alt["venue"][:120]
                if alt.get("year"):
                    row["year"] = int(alt["year"])
                found.append("openalex-meta")
            if alt.get("authors") and row.get("authors_json") in (None, "", "[]"):
                row["authors_json"] = json.dumps(alt["authors"], ensure_ascii=False)
            # A citation that paraphrased the title is how the match failed in the
            # first place. Adopt the real one, so the row says what the paper is
            # called; the list keeps the citation as written, next to it.
            if alt.get("title") and _norm(alt["title"]) != _norm(row.get("title", "")):
                row["title"] = alt["title"]
                row["title_key"] = title_key(alt["title"])
                found.append("retitled")
    return row, found
