"""Crossref: the reference list, with the numbers the paper printed.

Semantic Scholar and OpenAlex both say which works a paper cites. Neither says which
one is reference 12, and that is the only thing that connects "automate skill
assessment4-8" to a title. Nature's own PDF often omits the reference list from the
text layer entirely, so for a Data Descriptor there is nothing else to read.

Crossref keys each reference as `<suffix>_CR<n>`, where n is the number in the paper.
With that, a superscript becomes a title, a year and a DOI.
"""

from __future__ import annotations

import json
import re
import urllib.parse

from paper_daily.http import fetch_text

API = "https://api.crossref.org/works"

# Crossref asks for a contact address in the User-Agent and serves the polite pool in
# return. http.py sets its own; the mailto parameter does the same job on the query.
MAILTO = "paper-daily@users.noreply.github.com"

_KEY_NUM = re.compile(r"(?:CR|ref|R|B)?(\d{1,3})\s*$", re.I)


def _title(ref: dict) -> str | None:
    """The cited work's own title, never the journal it appeared in.

    `journal-title` is the container, so preferring it gives every IEEE reference the
    title "IEEE Transactions on Medical Imaging". It is the last resort, not the first.
    """
    for field in ("article-title", "volume-title"):
        if ref.get(field):
            return str(ref[field])[:300]

    raw = str(ref.get("unstructured") or "").strip()
    if raw:
        # "Ma, L. et al. Simulation of postoperative facial appearances ..." -- drop
        # the author block when it is clearly marked, and keep everything otherwise:
        # a full citation string is still a usable answer, an empty one is not.
        trimmed = re.sub(r"^.{0,90}?\bet al\.\s*", "", raw).strip()
        return (trimmed or raw)[:300]

    return str(ref["journal-title"])[:300] if ref.get("journal-title") else None


def reference_list(doi: str) -> dict[str, dict]:
    """Reference number -> {title, year, doi}, as the paper numbers them."""
    if not doi:
        return {}
    url = f"{API}/{urllib.parse.quote(doi)}?mailto={MAILTO}"
    try:
        payload = json.loads(fetch_text(url, max_age=30 * 86400, retries=3))
    except Exception:
        return {}

    refs = (payload.get("message") or {}).get("reference") or []
    out: dict[str, dict] = {}
    for position, ref in enumerate(refs, 1):
        m = _KEY_NUM.search(str(ref.get("key") or ""))
        # The key is authoritative where it carries a number; otherwise the array
        # order is the paper's order, which is the same thing for every publisher
        # that numbers its references.
        number = m.group(1) if m else str(position)
        title = _title(ref)
        if not title:
            continue
        out[number] = {
            "title": title,
            "year": ref.get("year"),
            "doi": ref.get("DOI"),
        }
    return out
