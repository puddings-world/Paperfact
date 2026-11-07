"""Bounded scientific deck proposals, without writer or source-owner authority.

All inputs/outputs are in-memory content. Callers must separately prove ownership
of originals and bind an explicit receiver before retention or reviewed Apply.
A fingerprint identifies this content manifest, never a paper or workspace.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from paper_daily.pending_deck_result import _research_snapshot
from paper_daily.sync_deck_files import SLIDE_FIELDS, _layout, validate_png
from paper_daily.sync_documents import MAX_PDF_BYTES
from paper_daily.sync_files import (
    MAX_ASSETS,
    MAX_BODY,
    canonical_json,
    closed,
    descriptor,
    digest,
    read_json,
    text,
)
from paper_daily.sync_legacy_sources import validate_pdf

CAPABILITY = "deck_proposals"
FORMAT = "paperfact.deck-proposal"
VERSION = 1
MAX_METADATA_BYTES = MAX_BODY
MAX_IMAGE_BYTES = MAX_ASSETS
MAX_PNG_BYTES = 8_000_000
MAX_IMAGES = 512  # Two maintained catalogs, each bounded to 256 entries.
MAX_ORIGINALS = 16
MAX_ORIGINAL_BYTES = 512 * 1024**2
_FIELDS = {"format", "version", "research", "images", "originals", "source_document_hash"}
_DESCRIPTOR = {"sha256", "size", "media_type"}


def _plain(value, *, depth=0):
    if depth > 32:
        raise ValueError("Proposal metadata nesting exceeds 32 levels")
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise ValueError("Proposal metadata keys must be strings")
        for child in value.values():
            _plain(child, depth=depth + 1)
    elif isinstance(value, list):
        for child in value:
            _plain(child, depth=depth + 1)
    elif value is not None and type(value) not in (str, int, float, bool):
        raise ValueError("Proposal metadata requires plain JSON values")


def _encoded(value):
    _plain(value)
    try:
        result = canonical_json(value)
    except (TypeError, OverflowError, RecursionError) as error:
        raise ValueError("Invalid proposal metadata") from error
    if len(result) > MAX_METADATA_BYTES:
        raise ValueError("Proposal metadata exceeds 8 MiB")
    return result


def _research(deck, evidence):
    if evidence is not None and (
        not isinstance(evidence, dict)
        or not {"sources", "coverage", "source_hash"} <= set(evidence)
    ):
        raise ValueError("Scientific evidence is incomplete")
    value = dict(deck=deck, evidence=evidence)
    _encoded(value)
    snapshot = _research_snapshot(deck, evidence)
    raw = snapshot["deck"]
    if type(raw["version"]) is not int or raw["version"] != 1 or type(raw["edited"]) is not bool:
        raise ValueError("Invalid proposal deck version or edited flag")
    for slide in raw["slides"]:
        closed(slide, SLIDE_FIELDS)
        _layout(slide["elements"])
    for key in ("coverage",):
        if len(raw[key]) > 1000:
            raise ValueError("Proposal coverage exceeds its bound")
        for label in raw[key]:
            text(label, 4000, empty=True)
    generation = raw["generation"]
    if "inputs" in generation:
        if not isinstance(generation["inputs"], list) or len(generation["inputs"]) > 30:
            raise ValueError("Invalid scientific input labels")
        for label in generation["inputs"]:
            text(label, 100)
    for key in ("backend", "model"):
        if key in generation:
            text(generation[key], 200, empty=True)
    if evidence is not None:
        if not {"sources", "coverage", "source_hash"} <= set(evidence):
            raise ValueError("Scientific evidence is incomplete")
        if not isinstance(evidence["coverage"], list) or len(evidence["coverage"]) > 1000:
            raise ValueError("Invalid scientific evidence coverage")
        for label in evidence["coverage"]:
            text(label, 4000, empty=True)
        text(evidence["source_hash"], 100, empty=True)
    catalogs = [raw["sources"], raw["figures"]]
    if snapshot["evidence"] is not None:
        catalogs.extend([snapshot["evidence"]["sources"], snapshot["evidence"].get("figures", [])])
    for rows in catalogs:
        ids = [row["id"] for row in rows]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate scientific catalog identities")
    return snapshot


def _figure_ids(research):
    evidence = research["evidence"] or {}
    return {row["id"] for row in research["deck"]["figures"] + evidence.get("figures", [])}


def _original_hashes(research, source_document_hash):
    digest(source_document_hash, nullable=True)
    deck, evidence = research["deck"], research["evidence"] or {}
    rows = (
        deck["sources"]
        + deck["figures"]
        + evidence.get("sources", [])
        + evidence.get("figures", [])
    )
    result = {row["document_hash"] for row in rows if row.get("document_hash") is not None}
    if source_document_hash is not None:
        result.add(source_document_hash)
    if len(result) > MAX_ORIGINALS:
        raise ValueError("Proposal declares more than 16 originals")
    return result


def _check_descriptor(row, media_type, maximum):
    closed(row, _DESCRIPTOR)
    digest(row["sha256"])
    if type(row["size"]) is not int or not 0 < row["size"] <= maximum:
        raise ValueError("Proposal object exceeds its declared byte bound")
    if row["media_type"] != media_type:
        raise ValueError("Unsupported proposal media type")


def _manifest(value):
    encoded = _encoded(value)
    result = json.loads(encoded)
    closed(result, _FIELDS)
    if (
        result["format"] != FORMAT
        or type(result["version"]) is not int
        or result["version"] != VERSION
    ):
        raise ValueError("Unsupported portable proposal format")
    digest(result["source_document_hash"], nullable=True)
    _check_descriptor(result["research"], "application/json", MAX_METADATA_BYTES)
    if len(encoded) + result["research"]["size"] > MAX_METADATA_BYTES:
        raise ValueError("Proposal metadata exceeds combined 8 MiB bound")
    images, originals = result["images"], result["originals"]
    if not isinstance(images, list) or len(images) > MAX_IMAGES:
        raise ValueError("Proposal image catalog exceeds its bound")
    if not isinstance(originals, list) or len(originals) > MAX_ORIGINALS:
        raise ValueError("Proposal declares more than 16 originals")
    ids, image_objects, all_objects = [], {}, {result["research"]["sha256"]: result["research"]}
    for item in images:
        closed(item, _DESCRIPTOR | {"id"})
        text(item["id"], 250)
        row = {key: item[key] for key in _DESCRIPTOR}
        _check_descriptor(row, "image/png", MAX_PNG_BYTES)
        ids.append(item["id"])
        image_objects[row["sha256"]] = row
        previous = all_objects.setdefault(row["sha256"], row)
        if previous != row:
            raise ValueError("Conflicting proposal object descriptors")
    if ids != sorted(set(ids)):
        raise ValueError("Proposal image identities must be unique and sorted")
    if sum(row["size"] for row in image_objects.values()) > MAX_IMAGE_BYTES:
        raise ValueError("Proposal images exceed 64 MiB")
    hashes = []
    for row in originals:
        _check_descriptor(row, "application/pdf", MAX_PDF_BYTES)
        hashes.append(row["sha256"])
        previous = all_objects.setdefault(row["sha256"], row)
        if previous != row:
            raise ValueError("Conflicting proposal object descriptors")
    if hashes != sorted(set(hashes)):
        raise ValueError("Proposal original hashes must be unique and sorted")
    if sum(row["size"] for row in originals) > MAX_ORIGINAL_BYTES:
        raise ValueError("Proposal originals exceed 512 MiB")
    if result["source_document_hash"] is not None and result["source_document_hash"] not in hashes:
        raise ValueError("Explicit original source bytes are missing")
    return result


def fingerprint(manifest):
    """Stable structural content identity; decode separately verifies scientific closure."""
    return hashlib.sha256(canonical_json(_manifest(manifest))).hexdigest()


def encode(deck, evidence, images, originals, *, source_document_hash=None):
    """Validate a whole scientific proposal; byte maps never resolve file paths."""
    from paper_daily.presentations import Deck

    if isinstance(deck, Deck):
        deck = deck.to_dict()
    if (
        not isinstance(deck, dict)
        or not isinstance(images, dict)
        or not isinstance(originals, dict)
    ):
        raise ValueError("Proposal requires a scientific deck and explicit byte maps")
    research = _research(deck, evidence)
    if set(images) != _figure_ids(research):
        raise ValueError("Missing or undeclared proposal image bytes")
    if set(originals) != _original_hashes(research, source_document_hash):
        raise ValueError("Original bytes differ from exact declared source hashes")
    content = _encoded(research)
    manifest = dict(
        format=FORMAT,
        version=VERSION,
        research=descriptor(content, "application/json"),
        images=[],
        originals=[],
        source_document_hash=source_document_hash,
    )
    blobs = {manifest["research"]["sha256"]: content}
    for key, data in sorted(images.items()):
        if type(data) is not bytes:
            raise ValueError("Proposal images must be immutable bytes")
        row = descriptor(data, "image/png")
        manifest["images"].append(dict(id=key, **row))
        blobs[row["sha256"]] = data
    for key, data in sorted(originals.items()):
        if type(data) is not bytes:
            raise ValueError("Proposal originals must be immutable bytes")
        row = descriptor(data, "application/pdf")
        if row["sha256"] != key:
            raise ValueError("Original bytes differ from their declared source hash")
        manifest["originals"].append(row)
        blobs[key] = data
    manifest = _manifest(manifest)
    decode(manifest, lambda row: blobs[row["sha256"]])
    return manifest, blobs


def decode(manifest, read_blob):
    """Defensive content only. Supplied bytes are not proof of target ownership."""
    manifest = _manifest(manifest)
    objects = {}

    def read(row):
        key = row["sha256"]
        if key not in objects:
            data = read_blob(deepcopy({name: row[name] for name in _DESCRIPTOR}))
            if (
                type(data) is not bytes
                or len(data) != row["size"]
                or hashlib.sha256(data).hexdigest() != key
            ):
                raise ValueError("Proposal object bytes differ from their manifest")
            objects[key] = data
        return objects[key]

    research = read_json(read(manifest["research"]))
    closed(research, {"deck", "evidence"})
    checked = _research(research["deck"], research["evidence"])
    if checked != research:
        raise ValueError("Portable proposal contains local execution or cache fields")
    if {row["id"] for row in manifest["images"]} != _figure_ids(research):
        raise ValueError("Missing or undeclared proposal image bytes")
    if {row["sha256"] for row in manifest["originals"]} != _original_hashes(
        research, manifest["source_document_hash"]
    ):
        raise ValueError("Original bytes differ from exact declared source hashes")
    images, originals = {}, {}
    for row in manifest["images"]:
        data = read(row)
        validate_png(data)
        images[row["id"]] = data
    for row in manifest["originals"]:
        data = read(row)
        validate_pdf(data)
        originals[row["sha256"]] = data
    return {
        **deepcopy(research),
        "image_bytes": images,
        "original_bytes": originals,
        "source_document_hash": manifest["source_document_hash"],
    }
