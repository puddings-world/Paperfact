"""Content-only proposals preserve full scientific closure; never writer authority."""

import copy
import hashlib
import json
import socket
import sqlite3
import subprocess
from pathlib import Path

import pymupdf
import pytest
from test_sync_files import deck as deck_fixture
from test_sync_files import png

from paper_daily import llm
from paper_daily import portable_deck_proposal as codec
from paper_daily.sync_files import canonical_json, descriptor


def pdf(label):
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 40), label)
        return document.tobytes()


@pytest.fixture
def scientific():
    deck = deck_fixture()
    deck.figures.append(
        dict(
            id="figure:3",
            label="Unused",
            caption="Full unused caption",
            file="C:/private/cache.png",
            cache_key="private-cache-key",
        )
    )
    images = {
        "figure:1": png("red"),
        "figure:2": png("blue"),
        "figure:3": pymupdf.Pixmap(pymupdf.csRGB, 2, 2, b"\x11\x78\x24" * 4, False).tobytes("png"),
    }
    source_a, current_b = pdf("Original A"), pdf("Current B is not original A")
    sha = hashlib.sha256(source_a).hexdigest()
    for row in deck.sources + deck.figures:
        row["document_hash"] = sha
        row["page"] = 1
    deck.generation.update(
        inputs=["Source study"],
        backend="fixture",
        profile="private-account",
        request_id="local-writer-secret",
    )
    evidence = dict(
        sources=copy.deepcopy(deck.sources),
        figures=copy.deepcopy(deck.figures),
        coverage=["Reported observations"],
        source_hash="input-digest-not-a-PDF",
        paper=dict(
            id="ref:study-a", title="Scientific title", year=2026, authors_json='["Researcher"]'
        ),
    )
    return deck, evidence, images, {sha: source_a}, sha, current_b


def encoded(scientific):
    deck, evidence, images, originals, sha, _b = scientific
    return codec.encode(deck, evidence, images, originals, source_document_hash=sha)


def read(manifest, blobs):
    return codec.decode(manifest, lambda row: blobs[row["sha256"]])


def changed_research(manifest, blobs, change):
    value = json.loads(blobs[manifest["research"]["sha256"]])
    change(value)
    data = canonical_json(value)
    new = copy.deepcopy(manifest)
    new["research"] = descriptor(data, "application/json")
    return new, {**blobs, new["research"]["sha256"]: data}


def test_scientific_round_trip_preserves_all_metadata_original_a_and_unused_images(scientific):
    deck, evidence, images, originals, sha, current_b = scientific
    before = copy.deepcopy((deck.to_dict(), evidence, images, originals))
    manifest, blobs = encoded(scientific)
    value = read(manifest, blobs)
    assert codec.CAPABILITY == "deck_proposals"
    assert set(value) == {
        "deck",
        "evidence",
        "image_bytes",
        "original_bytes",
        "source_document_hash",
    }
    assert value["deck"]["slides"] == deck.to_dict()["slides"]
    assert value["deck"]["figures"][-1]["caption"] == "Full unused caption"
    assert value["evidence"]["paper"] == evidence["paper"]
    assert value["evidence"]["coverage"] == evidence["coverage"]
    assert value["image_bytes"] == images and value["original_bytes"] == originals
    assert value["source_document_hash"] == sha
    assert hashlib.sha256(current_b).hexdigest() not in value["original_bytes"]
    assert (deck.to_dict(), evidence, images, originals) == before
    serialized = canonical_json(manifest) + b"".join(blobs.values())
    assert b"private-account" not in serialized and b"local-writer-secret" not in serialized
    assert b"private/cache" not in serialized and b"private-cache-key" not in serialized
    assert value["deck"]["generation"] == dict(
        inputs=["Source study"], backend="fixture", model="fixture"
    )
    assert "publish" not in value and "binding" not in manifest and "observation" not in manifest


def test_evidence_only_fourth_png_and_its_original_are_preserved_without_catalog_mutation(
    scientific,
):
    deck, evidence, images, originals, _sha, _b = scientific
    fourth = pymupdf.Pixmap(pymupdf.csRGB, 2, 2, b"\x12\x34\x56" * 4, False).tobytes("png")
    evidence["figures"].append(
        dict(
            id="evidence:four",
            label="Evidence only",
            caption="Not in deck",
            page=1,
            document_hash=None,
        )
    )
    images["evidence:four"] = fourth
    before = copy.deepcopy(deck.to_dict())
    manifest, blobs = codec.encode(deck, evidence, images, originals)
    result = read(manifest, blobs)
    assert result["image_bytes"]["evidence:four"] == fourth
    assert len(result["image_bytes"]) == 4
    assert [row["id"] for row in result["deck"]["figures"]] == [row["id"] for row in deck.figures]
    assert result["evidence"]["figures"][-1]["caption"] == "Not in deck"
    assert deck.to_dict() == before


def test_null_sources_do_not_require_or_accept_current_primary_substitution(scientific):
    deck, evidence, images, _originals, _sha, current_b = scientific
    for row in deck.sources + deck.figures + evidence["sources"] + evidence["figures"]:
        row["document_hash"] = None
    manifest, blobs = codec.encode(deck, evidence, images, {})
    result = read(manifest, blobs)
    assert result["source_document_hash"] is None and result["original_bytes"] == {}
    with pytest.raises(ValueError, match="exact declared"):
        codec.encode(deck, evidence, images, {hashlib.sha256(current_b).hexdigest(): current_b})


@pytest.mark.parametrize("mode", ["missing-a", "substitute-b", "extra-b", "wrong-key"])
def test_original_set_must_match_all_declared_hashes(scientific, mode):
    deck, evidence, images, originals, sha, b = scientific
    if mode == "missing-a":
        originals = {}
    elif mode == "substitute-b":
        originals = {hashlib.sha256(b).hexdigest(): b}
    elif mode == "extra-b":
        originals = {**originals, hashlib.sha256(b).hexdigest(): b}
    else:
        originals = {sha: b}
    with pytest.raises(ValueError):
        codec.encode(deck, evidence, images, originals)


def test_explicit_envelope_original_and_evidence_only_original_are_in_exact_closure(scientific):
    deck, evidence, images, originals, sha, b = scientific
    sha_b = hashlib.sha256(b).hexdigest()
    evidence["sources"].append(
        dict(id="evidence:source-b", label="Another original", kind="paper", document_hash=sha_b)
    )
    with pytest.raises(ValueError):
        codec.encode(deck, evidence, images, originals)
    manifest, blobs = codec.encode(
        deck, evidence, images, {**originals, sha_b: b}, source_document_hash=sha_b
    )
    result = read(manifest, blobs)
    assert set(result["original_bytes"]) == {sha, sha_b} and result["source_document_hash"] == sha_b


def test_manifest_is_stable_deduplicated_and_defensive(scientific):
    scientific[2]["figure:3"] = scientific[2]["figure:1"]
    manifest, blobs = encoded(scientific)
    before = copy.deepcopy(manifest)
    seen = []

    def callback(row):
        sha = row["sha256"]
        seen.append(sha)
        row["size"] = 0
        return blobs[sha]

    value = codec.decode(manifest, callback)
    assert len(seen) == len(set(seen)) and len(seen) == len(blobs)
    assert len(manifest["images"]) == 3 and len({row["sha256"] for row in manifest["images"]}) == 2
    value["deck"]["slides"][0]["title"] = "Changed defensive view"
    value["evidence"]["paper"]["title"] = "Changed evidence"
    value["image_bytes"].clear()
    assert manifest == before and read(manifest, blobs)["image_bytes"] == scientific[2]
    assert read(manifest, blobs)["deck"]["slides"][0]["title"] == scientific[0].slides[0].title
    again, again_blobs = encoded(scientific)
    assert codec.fingerprint(again) == codec.fingerprint(manifest) and again_blobs == blobs
    changed = copy.deepcopy(manifest)
    changed["source_document_hash"] = None
    assert codec.fingerprint(changed) != codec.fingerprint(manifest)


@pytest.mark.parametrize(
    "mode",
    [
        "extra-field",
        "version-bool",
        "unknown-version",
        "image-duplicate",
        "image-unsorted",
        "original-duplicate",
        "bad-media",
        "size-bool",
        "oversize-body",
        "oversize-png",
        "oversize-pdf",
        "bad-digest",
        "authority",
    ],
)
def test_malformed_manifest_refuses_before_reading_bytes(scientific, mode):
    manifest, _blobs = encoded(scientific)
    bad = copy.deepcopy(manifest)
    if mode == "extra-field":
        bad["future"] = True
    elif mode == "version-bool":
        bad["version"] = True
    elif mode == "unknown-version":
        bad["version"] = 99
    elif mode == "image-duplicate":
        bad["images"].append(copy.deepcopy(bad["images"][0]))
    elif mode == "image-unsorted":
        bad["images"].reverse()
    elif mode == "original-duplicate":
        bad["originals"].append(copy.deepcopy(bad["originals"][0]))
    elif mode == "bad-media":
        bad["images"][0]["media_type"] = "application/x-command"
    elif mode == "size-bool":
        bad["research"]["size"] = True
    elif mode == "oversize-body":
        bad["research"]["size"] = codec.MAX_METADATA_BYTES + 1
    elif mode == "oversize-png":
        bad["images"][0]["size"] = codec.MAX_PNG_BYTES + 1
    elif mode == "oversize-pdf":
        bad["originals"][0]["size"] = codec.MAX_PDF_BYTES + 1
    elif mode == "bad-digest":
        bad["research"]["sha256"] = "A" * 64
    else:
        bad["observation"] = {"database": "C:/private/db.sqlite"}

    def deny(_row):
        raise AssertionError("Invalid manifest must be rejected before blob read")

    with pytest.raises(ValueError):
        codec.decode(bad, deny)
    with pytest.raises(ValueError):
        codec.fingerprint(bad)


@pytest.mark.parametrize(
    "mode", ["extra-image", "missing-unused", "bad-png", "bad-pdf", "mutable-bytes"]
)
def test_invalid_input_bytes_or_image_set_reject_entire_batch(scientific, mode):
    deck, evidence, images, originals, sha, _b = scientific
    if mode == "extra-image":
        images["not-declared"] = png("blue")
    elif mode == "missing-unused":
        images.pop("figure:3")
    elif mode == "bad-png":
        images["figure:3"] = b"not a PNG"
    elif mode == "bad-pdf":
        value = b"not a PDF"
        new = hashlib.sha256(value).hexdigest()
        originals = {new: value}
        for row in deck.sources + deck.figures + evidence["sources"] + evidence["figures"]:
            row["document_hash"] = new
    else:
        images["figure:3"] = bytearray(images["figure:3"])
    with pytest.raises(ValueError):
        codec.encode(deck, evidence, images, originals)


@pytest.mark.parametrize(
    "mode",
    [
        "unknown-paper",
        "unknown-execution",
        "unknown-slide",
        "duplicate-source",
        "duplicate-evidence",
        "missing-evidence",
        "invalid-evidence",
        "nonfinite",
        "metadata-budget",
        "bad-json-type",
    ],
)
def test_unsupported_scientific_metadata_is_not_silently_discarded(scientific, mode):
    deck, evidence, images, originals, _sha, _b = scientific
    value = deck.to_dict()
    if mode == "unknown-paper":
        evidence["paper"]["private_path"] = "C:/secret"
    elif mode == "unknown-execution":
        value["generation"]["api_key"] = "private-credential"
    elif mode == "unknown-slide":
        value["slides"][0]["new_scientific_field"] = "must not discard"
    elif mode == "duplicate-source":
        value["sources"].append(copy.deepcopy(value["sources"][0]))
    elif mode == "duplicate-evidence":
        evidence["figures"].append(copy.deepcopy(evidence["figures"][0]))
    elif mode == "missing-evidence":
        evidence = {}
    elif mode == "invalid-evidence":
        evidence = None
        value["edited"] = "yes"
    elif mode == "nonfinite":
        evidence["paper"]["year"] = float("nan")
    elif mode == "metadata-budget":
        value["title"] = "x" * (codec.MAX_METADATA_BYTES + 1)
    else:
        evidence["paper"]["authors_json"] = ("tuple", "not plain JSON")
    with pytest.raises(ValueError):
        codec.encode(value, evidence, images, originals)


@pytest.mark.parametrize("mode", ["corrupt", "missing", "wrong-type"])
def test_blob_read_must_return_exact_bytes(scientific, mode):
    manifest, blobs = encoded(scientific)

    def bad(row):
        if mode == "missing":
            return b""
        if mode == "wrong-type":
            return bytearray(blobs[row["sha256"]])
        return blobs[row["sha256"]] + b"modified"

    with pytest.raises(ValueError):
        codec.decode(manifest, bad)


def test_duplicate_noncanonical_json_and_local_cache_in_incoming_body_refuse(scientific):
    manifest, blobs = encoded(scientific)
    for raw in [b'{"deck":{},"deck":{}}', b'{"deck": NaN}', b'{"deck": {}, "evidence": null}']:
        modified = copy.deepcopy(manifest)
        modified["research"] = descriptor(raw, "application/json")
        with pytest.raises(ValueError):
            read(modified, {**blobs, modified["research"]["sha256"]: raw})
    modified, objects = changed_research(
        manifest, blobs, lambda value: value["deck"]["generation"].update(profile="local")
    )
    with pytest.raises(ValueError, match="local execution"):
        read(modified, objects)


def test_aggregate_limits_and_seventeen_originals_are_not_truncated(scientific, monkeypatch):
    manifest, blobs = encoded(scientific)
    total = sum(row["size"] for row in {row["sha256"]: row for row in manifest["images"]}.values())
    with monkeypatch.context() as m:
        m.setattr(codec, "MAX_IMAGE_BYTES", total - 1)
        with pytest.raises(ValueError, match="64 MiB"):
            read(manifest, blobs)
    with monkeypatch.context() as m:
        m.setattr(codec, "MAX_ORIGINAL_BYTES", manifest["originals"][0]["size"] - 1)
        with pytest.raises(ValueError, match="512 MiB"):
            read(manifest, blobs)
    value = copy.deepcopy(manifest)
    value["originals"] = [
        dict(
            sha256=hashlib.sha256(str(n).encode()).hexdigest(), size=1, media_type="application/pdf"
        )
        for n in range(17)
    ]
    with pytest.raises(ValueError, match="16 originals"):
        codec.fingerprint(value)


def test_empty_optional_evidence_and_no_originals_or_images_are_valid(scientific):
    deck = scientific[0].to_dict()
    deck["figures"] = []
    for source in deck["sources"]:
        source["document_hash"] = None
    slide = deck["slides"][0]
    slide["figure"] = None
    slide["elements"] = None
    manifest, blobs = codec.encode(deck, None, {}, {})
    result = read(manifest, blobs)
    assert result["evidence"] is None and result["original_bytes"] == result["image_bytes"] == {}


def test_codec_has_no_sql_filesystem_network_or_model_work(scientific, monkeypatch):
    manifest, blobs = encoded(scientific)

    def deny(*_args, **_kwargs):
        raise AssertionError("Pure codec attempted external work")

    for name in ("open", "read_bytes", "write_bytes", "mkdir"):
        monkeypatch.setattr(Path, name, deny)
    monkeypatch.setattr(sqlite3, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(llm, "complete_result", deny)
    again, objects = encoded(scientific)
    value = read(manifest, blobs)
    assert value["original_bytes"] == scientific[3] and again == manifest and objects == blobs


def test_explicit_envelope_only_original_is_required_and_never_invented(scientific):
    deck, evidence, images, originals, sha_a, pdf_b = scientific
    sha_b = hashlib.sha256(pdf_b).hexdigest()
    with pytest.raises(ValueError):
        codec.encode(deck, evidence, images, originals, source_document_hash=sha_b)
    manifest, blobs = codec.encode(
        deck, evidence, images, {**originals, sha_b: pdf_b}, source_document_hash=sha_b
    )
    value = read(manifest, blobs)
    assert set(value["original_bytes"]) == {sha_a, sha_b}
    assert value["source_document_hash"] == sha_b
    assert all(
        row.get("document_hash") != sha_b
        for row in value["deck"]["sources"] + value["deck"]["figures"]
    )
    with pytest.raises(ValueError):
        codec.encode(deck, evidence, images, {**originals, sha_b: pdf_b})


def test_input_digest_is_not_a_pdf_document_identity(scientific):
    deck, evidence, images, originals, _sha, pdf_b = scientific
    input_digest = hashlib.sha256(pdf_b).hexdigest()
    deck.source_hash = input_digest
    evidence["source_hash"] = input_digest
    manifest, blobs = codec.encode(deck, evidence, images, originals)
    value = read(manifest, blobs)
    assert input_digest not in value["original_bytes"]
    assert value["deck"]["source_hash"] == value["evidence"]["source_hash"] == input_digest


@pytest.mark.parametrize("extra", ["image", "original"])
def test_decode_refuses_undeclared_actual_objects_without_returning_partial_content(
    scientific, extra
):
    manifest, blobs = encoded(scientific)
    if extra == "image":
        data = pymupdf.Pixmap(pymupdf.csRGB, 2, 2, b"\x55\x66\x77" * 4, False).tobytes("png")
        row = descriptor(data, "image/png")
        manifest["images"].append(dict(id="unused:undeclared", **row))
        manifest["images"].sort(key=lambda item: item["id"])
    else:
        data = scientific[-1]
        row = descriptor(data, "application/pdf")
        manifest["originals"].append(row)
        manifest["originals"].sort(key=lambda item: item["sha256"])
    blobs[row["sha256"]] = data
    with pytest.raises(ValueError):
        read(manifest, blobs)


def test_combined_metadata_budget_refuses_before_any_blob_callback(scientific, monkeypatch):
    manifest, _blobs = encoded(scientific)
    size = len(canonical_json(manifest)) + manifest["research"]["size"]
    monkeypatch.setattr(codec, "MAX_METADATA_BYTES", size - 1)

    def deny(_row):
        raise AssertionError("Overbudget metadata must not be read")

    with pytest.raises(ValueError, match="combined"):
        codec.decode(manifest, deny)
