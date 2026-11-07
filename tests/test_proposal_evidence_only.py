"""Public package/review journey for a genuine evidence-only fourth image."""

import copy
import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing

import pymupdf
import pytest
from test_local_blob_binding import no_external as no_external
from test_local_deck_proposals import local as _local
from test_local_deck_proposals import native
from test_package_import import enroll_capture
from test_portable_deck_proposal import scientific as scientific
from test_sync_files import side

from paper_daily import bundle, presentations, store
from paper_daily import deck_proposal_packages as carrier
from paper_daily import local_deck_proposals as catalog
from paper_daily import portable_deck_proposal as codec
from paper_daily.fetch import _safe_name
from paper_daily.package_import import PackageImporter
from paper_daily.research_review import ResearchReview
from paper_daily.sync_artifacts import desired_file
from paper_daily.sync_files import file_id

source_local = _local


@pytest.fixture
def local(source_local):
    # The generic local-only fixture uses date-only notes; enrolled v2 timestamps
    # require a timezone. Keep the note body and all science/assertions unchanged.
    with store.connect() as conn:
        conn.execute("UPDATE notes SET created_at='2026-11-01T00:00:00+00:00'")
    return source_local


def package_content(path):
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        tables = json.loads(archive.read("tables.json"))
        row = tables[carrier.TABLE][0]
        scientific = codec.decode(
            row["manifest"],
            lambda item: archive.read(
                "files/" + carrier.relative(row["paper_id"], item["sha256"]).as_posix()
            ),
        )
    return manifest, tables, row, scientific


def receiver_state(receiver):
    with closing(sqlite3.connect(receiver.journal.path)) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        counts = {
            table: conn.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0]
            for table in (
                "papers",
                "list_papers",
                "notes",
                "research_file_drafts",
                "research_file_candidates",
                "research_local_deck_proposals",
                "package_import_receipts",
            )
            if table in tables
        }
    return dict(pending=receiver.journal.pending(), counts=counts)


def test_public_enrolled_import_review_preserves_evidence_only_fourth_png_without_catalog_merge(
    local, scientific, monkeypatch
):
    database, _old_manifest, _old_blobs, saved, saved_before = local
    deck, evidence, images, originals, original_a, current_b = scientific
    fourth = pymupdf.Pixmap(pymupdf.csRGB, 3, 2, b"\x13\x57\x9b" * 6, False).tobytes("png")
    evidence["figures"].append(
        dict(
            id="evidence:fourth",
            label="Evidence-only plate",
            caption="A complete scientific caption that is not a slide figure",
            page=1,
            document_hash=original_a,
        )
    )
    images["evidence:fourth"] = fourth
    declared_before = copy.deepcopy((deck.to_dict(), evidence, images, originals))
    manifest, blobs = codec.encode(
        deck, evidence, images, originals, source_document_hash=original_a
    )
    expected = codec.decode(manifest, lambda row: blobs[row["sha256"]])
    prepared = catalog.prepare(
        database,
        "local-paper",
        manifest,
        lambda row: blobs[row["sha256"]],
        request_id="evidence-four",
        expected_native=native(database),
    )
    identity = catalog.retain(prepared)
    sender = catalog.read(database, identity, expected_native=native(database))
    assert len(sender.content["deck"]["figures"]) == 3
    assert len(sender.content["evidence"]["figures"]) == 4
    assert (
        sender.content["image_bytes"] == images
        and sender.content["evidence"] == expected["evidence"]
    )
    assert (deck.to_dict(), evidence, images, originals) == declared_before

    # Genuine local-only source, including ordinary primary B and proposal-owned A.
    pdfs = database.parent / "pdf"
    pdfs.mkdir()
    primary = pdfs / (_safe_name("local-paper") + ".pdf")
    primary.write_bytes(current_b)
    monkeypatch.setattr(bundle, "DATA_DIR", database.parent)
    monkeypatch.setattr(bundle, "PDF_DIR", pdfs)
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO lists(id,name,note,created_at) VALUES(?,?,?,?)",
            ("evidence-list", "Evidence-only content", None, "2026-11-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES(?,?,?,?)",
            ("evidence-list", "local-paper", 0, "2026-11-01T00:00:00+00:00"),
        )
    archive = database.parent / "evidence-only.zip"
    exported = bundle.export("evidence-list", archive)
    package_manifest, tables, row, packed = package_content(archive)
    assert exported["deck_proposals"] == 1 and exported["pdf_packed"] == 1
    assert package_manifest["capabilities"] == ["deck_proposals"]
    assert packed == expected
    assert {item["id"] for item in row["manifest"]["images"]} == set(images)
    assert packed["image_bytes"]["evidence:fourth"] == fourth
    assert set(packed["original_bytes"]) == {original_a}
    assert hashlib.sha256(primary.read_bytes()).hexdigest() != original_a
    assert saved.read_bytes() == saved_before
    with closing(sqlite3.connect(database)) as conn:
        names = {item[0] for item in conn.execute("SELECT name FROM sqlite_master")}
        assert "research_sync_binding" not in names and "paperfact_sync_identity" not in names
    archive_before = archive.read_bytes()

    # Separate real enrolled fixture: no sender journal/observation is replayed.
    receiver = side(database.parent, "evidence-receiver")
    enroll_capture(receiver)
    destination = database.parent / "enrolled-receiver-files"
    destination.mkdir()
    importer = PackageImporter(receiver.journal.path, destination)
    before = receiver_state(receiver)
    stage = "prepare"
    observed = dict(
        source_kind="actual unenrolled local catalog",
        receiver_kind="actual enrolled fixture",
        sender_proposal_id=identity,
        source_original_a=original_a,
        current_primary_b=hashlib.sha256(current_b).hexdigest(),
        scientific_deck_figure_ids=[r["id"] for r in expected["deck"]["figures"]],
        scientific_evidence_figure_ids=[r["id"] for r in expected["evidence"]["figures"]],
        actual_package_images={
            k: hashlib.sha256(v).hexdigest() for k, v in packed["image_bytes"].items()
        },
        package_capabilities=package_manifest["capabilities"],
        before=before,
    )
    try:
        imported = importer.prepare(archive)
        stage = "apply"
        report = importer.apply(imported)
    except Exception as error:
        observed.update(
            failed_stage=stage,
            error_type=type(error).__name__,
            error=str(error),
            after=receiver_state(receiver),
            archive_unchanged=archive.read_bytes() == archive_before,
            sender_science_unchanged=catalog.read(
                database, identity, expected_native=native(database)
            ).content
            == expected,
            sender_saved_deck_unchanged=saved.read_bytes() == saved_before,
        )
        (database.parent / "evidence-only-observed.json").write_text(json.dumps(observed, indent=2))
        raise
    assert report["deck_proposals"] == 1
    mapped = report["identity_mapping"]["local-paper"]
    after_import = receiver.journal.pending()
    review = ResearchReview(receiver.journal.path, presentation_root=destination / "presentations")
    try:
        entries = review.page(limit=100)["items"]
        assert len(entries) == 1
        view = review.prepare_file(review.preview(entries[0]["origin"], entries[0]["id"]))
        assert view.data["apply"] and view.data["requires_confirmation"]
        assert view.data["retained"]["figures"] == expected["deck"]["figures"]
    finally:
        review.close()
    assert receiver.journal.pending() == after_import
    with receiver.journal.transaction() as conn:
        assert desired_file(conn, file_id(mapped["portable_id"], "deck", "guide")) is None
    # Re-export is the public way to verify all retained bytes/metadata without
    # assuming a particular new enrolled catalog table or replaying its writer.
    monkeypatch.setattr(store, "DB_PATH", receiver.journal.path)
    monkeypatch.setattr(bundle, "DATA_DIR", destination)
    monkeypatch.setattr(bundle, "PDF_DIR", destination / "pdf")
    monkeypatch.setattr(presentations, "DECK_DIR", destination / "presentations")
    reexport = destination / "reviewed-content.zip"
    bundle.export(report["list"], reexport)
    _m, _t, _r, received = package_content(reexport)
    assert received["image_bytes"] == images and received["original_bytes"] == originals
    assert received["evidence"] == expected["evidence"]
    assert {k: v for k, v in received["deck"].items() if k not in {"paper_id", "deck_id"}} == {
        k: v for k, v in expected["deck"].items() if k not in {"paper_id", "deck_id"}
    }
    assert len(received["deck"]["figures"]) == 3 and len(received["evidence"]["figures"]) == 4
    assert archive.read_bytes() == archive_before and saved.read_bytes() == saved_before
