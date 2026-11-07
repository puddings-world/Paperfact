"""Reviewed note passages: exact words plus the extractor that selected them.

Legacy positions remain readable. Only explicit human selection creates evidence;
the editable note body is never treated as a quotation from its source.
"""

from __future__ import annotations

import re

MAX_QUOTE = 32 * 1024
MAX_PAGES = 100
COORDINATES = {"p0", "o0", "p1", "o1", "document_hash"}


def validate(anchor):
    from paper_daily.sync_content import _hash, _text, validate_anchor

    if anchor is None:
        return
    if not isinstance(anchor, dict) or "selection" not in anchor:
        validate_anchor(anchor)
        return
    if set(anchor) != COORDINATES | {"selection"}:
        raise ValueError("Invalid reviewed note position fields")
    validate_anchor({key: anchor[key] for key in COORDINATES})
    _hash(anchor["document_hash"])
    selection = anchor["selection"]
    if not isinstance(selection, dict) or set(selection) != {"version", "quote", "extractor"}:
        raise ValueError("Invalid reviewed note passage")
    if type(selection["version"]) is not int or selection["version"] != 1:
        raise ValueError("Unsupported reviewed note passage version")
    _text(selection["quote"], MAX_QUOTE, nullable=False, nonempty=True)
    extractor = selection["extractor"]
    if (
        not isinstance(extractor, dict)
        or set(extractor) != {"name", "engine", "version"}
        or extractor["name"] != "paperfact.level_words"
        or extractor["engine"] != "pymupdf"
        or not isinstance(extractor["version"], str)
        or not re.fullmatch(r"[0-9A-Za-z.+_-]{1,80}", extractor["version"])
        or anchor["p1"] - anchor["p0"] >= MAX_PAGES
    ):
        raise ValueError("Invalid or unbounded note passage extractor")


def passage(document, anchor, *, cancelled=lambda: False):
    from paper_daily.pdf_selection_text import level_words, validate_range

    # Selection from a native viewer supplies only geometry, never a forged quote.
    geometry = {key: anchor[key] for key in COORDINATES if key in anchor}
    validate_range(document, geometry)
    if geometry["p1"] - geometry["p0"] >= MAX_PAGES:
        raise ValueError("Select at most 100 PDF pages for one note passage")
    words, used = [], 0
    for page in range(geometry["p0"], geometry["p1"] + 1):
        if cancelled():
            raise InterruptedError("Note source selection cancelled")
        for order, word in level_words(document[page]):
            if (page, order) < (geometry["p0"], geometry["o0"]) or (page, order) > (
                geometry["p1"],
                geometry["o1"],
            ):
                continue
            used += len(word[4].encode("utf-8")) + bool(words)
            if used > MAX_QUOTE:
                raise ValueError("Select a shorter note passage (32 KiB maximum)")
            words.append(word[4])
    result = " ".join(words)
    if not result.strip():
        raise ValueError("The selected PDF passage has no selectable text")
    return result


def select(document, anchor, document_hash, *, cancelled=lambda: False):
    import pymupdf

    from paper_daily.sync_content import validate_anchor

    validate_anchor(anchor)
    if anchor is None or anchor.get("document_hash") not in (None, document_hash):
        raise ValueError("Select a passage in the inspected original")
    result = {**anchor, "document_hash": document_hash}
    result["selection"] = {
        "version": 1,
        "quote": passage(document, result, cancelled=cancelled),
        "extractor": {
            "name": "paperfact.level_words",
            "engine": "pymupdf",
            "version": pymupdf.VersionBind,
        },
    }
    validate(result)
    return result


def verify(document, anchor):
    validate(anchor)
    if "selection" not in anchor:
        from paper_daily.pdf_selection_text import validate_range

        validate_range(document, anchor)
        return
    quote = passage(document, anchor)
    if "selection" in anchor and " ".join(quote.split()) != " ".join(
        anchor["selection"]["quote"].split()
    ):
        raise ValueError("PDF word order or selected passage changed; select the passage again")
