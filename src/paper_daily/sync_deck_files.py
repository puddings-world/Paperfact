"""Portable editable deck codec; asset identifiers never become remote paths."""

from __future__ import annotations

from copy import deepcopy

from paper_daily.sync_files import canonical_json, closed, descriptor, digest, read_json, text

SOURCE_FIELDS = {"id", "label", "kind", "page", "url", "document_hash", "text"}
FIGURE_FIELDS = {"id", "label", "caption", "page", "document_hash", "asset_id"}
DECK_FIELDS = {
    "paper_id",
    "paper_title",
    "title",
    "mode",
    "audience",
    "minutes",
    "slides",
    "sources",
    "figures",
    "coverage",
    "created_at",
    "deck_id",
    "source_hash",
    "generation",
    "edited",
    "version",
}
SLIDE_FIELDS = {
    "title",
    "section",
    "takeaway",
    "bullets",
    "speaker_notes",
    "sources",
    "figure",
    "elements",
}


def _source(row, *, figure=False):
    allowed = FIGURE_FIELDS if figure else SOURCE_FIELDS
    required = {"id", "label", "asset_id"} if figure else {"id", "label", "kind"}
    if not isinstance(row, dict) or not required <= set(row) <= allowed:
        raise ValueError("Unsupported deck source fields")
    for key, maximum in (
        ("id", 250),
        ("label", 2000),
        ("kind", 30),
        ("caption", 10000),
        ("text", 200 * 1024),
        ("asset_id", 250),
    ):
        if key in row:
            text(row[key], maximum, empty=key in {"caption", "text"})
    if row.get("page") is not None and (
        type(row["page"]) is not int or not 1 <= row["page"] <= 1_000_001
    ):
        raise ValueError("Invalid deck source page")
    digest(row.get("document_hash"), nullable=True)
    if row.get("url") is not None:
        from urllib.parse import urlsplit

        text(row["url"], 4096)
        url = urlsplit(row["url"])
        if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
            raise ValueError("Source URLs require credential-free HTTP(S)")


def _layout(elements):
    if elements is None:
        return
    if not isinstance(elements, list) or len(elements) > 60:
        raise ValueError("Invalid deck layout")
    for row in elements:
        if not isinstance(row, dict) or row.get("kind") not in {"text", "figure", "table"}:
            raise ValueError("Invalid layout object")
        required = {"kind", "x", "y", "w", "h"}
        extra = {
            "text": {"text", "size", "color", "bold", "align"},
            "figure": {"figure"},
            "table": {"rows", "size", "header"},
        }[row["kind"]]
        if not required <= set(row) <= required | extra | {"role"}:
            raise ValueError("Unsupported layout fields")
        for key in ("bold", "header"):
            if key in row and type(row[key]) is not bool:
                raise ValueError("Layout switches must be booleans")
        if "role" in row and row["role"] not in {"title", "section", "takeaway", "bullets"}:
            raise ValueError("Invalid layout role")


def validate_body(body, payload):
    from paper_daily.presentations import deck_from_dict
    from paper_daily.slide_layout import used_figures

    closed(body, {"version", "deck", "evidence_asset"})
    if type(body["version"]) is not int or body["version"] != 1:
        raise ValueError("Unsupported deck body version")
    deck = body["deck"]
    closed(deck, DECK_FIELDS)
    if deck["paper_id"] != payload["paper_id"] or deck["mode"] != payload["slot"]:
        raise ValueError("Deck does not match its manifest")
    if type(deck["version"]) is not int or type(deck["edited"]) is not bool:
        raise ValueError("Invalid deck version/edited flag")
    for key in ("sources", "figures", "coverage"):
        if not isinstance(deck[key], list) or len(deck[key]) > 1000:
            raise ValueError("Deck index exceeds its bound")
    for source in deck["sources"]:
        _source(source)
    for figure in deck["figures"]:
        _source(figure, figure=True)
    for label in deck["coverage"]:
        text(label, 4000, empty=True)
    generation = deck["generation"]
    if not isinstance(generation, dict) or not set(generation) <= {"inputs", "backend", "model"}:
        raise ValueError("Execution receipts and account settings are not portable")
    if "inputs" in generation:
        if not isinstance(generation["inputs"], list) or len(generation["inputs"]) > 30:
            raise ValueError("Invalid deck input labels")
        for value in generation["inputs"]:
            text(value, 100)
    for key in ("backend", "model"):
        if key in generation:
            text(generation[key], 200, empty=True)
    if not isinstance(deck["slides"], list):
        raise ValueError("Deck slides must be a list")
    for slide in deck["slides"]:
        closed(slide, SLIDE_FIELDS)
        _layout(slide["elements"])
    parsed = deck_from_dict(deepcopy(deck))
    if used_figures(parsed) != {f["id"] for f in deck["figures"]}:
        raise ValueError("Portable decks declare exactly the used figures")
    declared = {a["id"]: a for a in payload["assets"]}
    refs = set()
    for figure in deck["figures"]:
        reference = figure["asset_id"]
        if reference not in declared or declared[reference]["role"] != "figure":
            raise ValueError("Deck figure has no declared PNG")
        refs.add(reference)
    evidence = body["evidence_asset"]
    if evidence is not None:
        if (
            not isinstance(evidence, str)
            or evidence not in declared
            or declared[evidence]["role"] != "evidence"
        ):
            raise ValueError("Deck evidence has no declared snapshot")
        refs.add(evidence)
    if refs != set(declared):
        raise ValueError("Undeclared or unused artifact assets")
    return parsed


def validate_png(data):
    import struct

    import pymupdf

    if len(data) > 8_000_000 or len(data) < 33 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid deck PNG")
    if data[12:16] != b"IHDR" or struct.unpack(">I", data[8:12])[0] != 13:
        raise ValueError("Missing PNG image header")
    width, height = struct.unpack(">II", data[16:24])
    if not width or not height or width > 16384 or height > 16384 or width * height > 40_000_000:
        raise ValueError("Deck PNG dimensions exceed bounds")
    import zlib

    offset, ended, has_data = 8, False, False
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("Truncated PNG chunk")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("Truncated PNG payload")
        kind = data[offset + 4 : offset + 8]
        if (kind == b"IHDR" and offset != 8) or (
            not kind[0] & 32 and kind not in {b"IHDR", b"PLTE", b"IDAT", b"IEND"}
        ):
            raise ValueError("Unsupported or duplicate critical PNG chunk")
        expected = struct.unpack(">I", data[end - 4 : end])[0]
        if zlib.crc32(data[offset + 4 : end - 4]) & 0xFFFFFFFF != expected:
            raise ValueError("Corrupt PNG chunk")
        if kind == b"IDAT":
            has_data = True
        if kind == b"IEND":
            if length or end != len(data):
                raise ValueError("Invalid PNG end marker")
            ended = True
        offset = end
    if not ended or not has_data:
        raise ValueError("Incomplete PNG")
    try:
        pixmap = pymupdf.Pixmap(data)
        if pixmap.width != width or pixmap.height != height:
            raise ValueError("PNG decode dimensions disagree")
        _ = pixmap.samples
    except Exception as exc:
        raise ValueError("Deck PNG cannot be decoded safely") from exc


def validate_deck_closure(payload, blobs):
    body = read_json(blobs[payload["body"]["sha256"]])
    validate_body(body, payload)
    for asset in payload["assets"]:
        data = blobs[asset["sha256"]]
        if asset["role"] == "figure":
            validate_png(data)
        elif asset["role"] == "evidence":
            evidence = read_json(data)
            closed(evidence, {"version", "sources", "coverage", "source_hash"})
            if evidence["version"] != 1 or type(evidence["version"]) is not int:
                raise ValueError("Unsupported evidence format")
            if not isinstance(evidence["sources"], list) or len(evidence["sources"]) > 1000:
                raise ValueError("Invalid evidence sources")
            for row in evidence["sources"]:
                _source(row)
            if not isinstance(evidence["coverage"], list) or len(evidence["coverage"]) > 1000:
                raise ValueError("Invalid evidence coverage")
            for value in evidence["coverage"]:
                text(value, 4000, empty=True)
            text(evidence["source_hash"], 100, empty=True)
        else:
            raise ValueError("Deck does not support source_text assets")
    return body


def encode_deck(deck, paper_id, *, input_versions, source_document_hash=None, evidence=None):
    """Copy, strip device-only fields and pin only used images; never mutate editor."""
    from paper_daily.presentations import figure_bytes
    from paper_daily.slide_layout import used_figures
    from paper_daily.sync_files import validate_closure

    raw = deepcopy(deck.to_dict())
    raw["paper_id"] = paper_id
    raw["generation"] = {
        k: v
        for k, v in raw["generation"].items()
        if k in {"inputs", "backend", "model"} and v is not None
    }
    assets, blobs, figures = [], {}, []
    for figure in raw["figures"]:
        if figure["id"] not in used_figures(deck):
            continue
        data = figure_bytes(deck, figure["id"])
        description = descriptor(data, "image/png")
        assets.append({"id": figure["id"], "role": "figure", **description})
        blobs[description["sha256"]] = data
        row = {k: v for k, v in figure.items() if k in FIGURE_FIELDS}
        row["asset_id"] = figure["id"]
        figures.append(row)
    raw["figures"] = figures
    raw["sources"] = [
        {k: v for k, v in row.items() if k in SOURCE_FIELDS} for row in raw["sources"]
    ]
    body = {"version": 1, "deck": raw, "evidence_asset": None}
    if evidence is not None:
        snapshot = {
            "version": 1,
            "sources": [
                {k: v for k, v in row.items() if k in SOURCE_FIELDS} for row in evidence["sources"]
            ],
            "coverage": deepcopy(evidence["coverage"]),
            "source_hash": evidence["source_hash"],
        }
        data = canonical_json(snapshot)
        description = descriptor(data, "application/json")
        reference = "evidence:" + description["sha256"]
        assets.append({"id": reference, "role": "evidence", **description})
        blobs[description["sha256"]] = data
        body["evidence_asset"] = reference
    data = canonical_json(body)
    description = descriptor(data, "application/json")
    blobs[description["sha256"]] = data
    payload = {
        "paper_id": paper_id,
        "feature": "deck",
        "slot": deck.mode,
        "format_version": 1,
        "source_document_hash": source_document_hash,
        "input_versions": input_versions,
        "body": description,
        "assets": assets,
    }
    validate_closure(payload, lambda row: blobs[row["sha256"]])
    return payload, blobs
