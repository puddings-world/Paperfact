"""Real public enrolled import retains general proposals atomically and never auto-applies."""

import hashlib
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pymupdf
import pytest
from test_local_blob_binding import no_external as no_external
from test_local_deck_proposals import local as local
from test_local_deck_proposals import native
from test_package_import import enroll_capture
from test_portable_deck_proposal import scientific as scientific
from test_proposal_evidence_only import package_content
from test_sync_files import side

from paper_daily import bundle, presentations, store
from paper_daily import enrolled_deck_proposals as general
from paper_daily import local_deck_proposals as catalog
from paper_daily import portable_deck_proposal as codec
from paper_daily.fetch import _safe_name
from paper_daily.package_import import PackageImporter
from paper_daily.research_review import ResearchReview
from paper_daily.sync_artifacts import desired_file
from paper_daily.sync_files import file_id
from paper_daily.workspace_service import Cancelled, Ticket


@pytest.fixture
def union_package(local, scientific, monkeypatch):
    database, _old_manifest, _old_blobs, saved, before = local
    with store.connect() as conn:
        conn.execute("UPDATE notes SET created_at='2026-11-01T00:00:00+00:00'")
    deck, evidence, images, originals, sha, primary_b = scientific
    fourth = pymupdf.Pixmap(pymupdf.csRGB, 3, 2, b"\x23\x57\x89" * 6, False).tobytes("png")
    evidence["figures"].append(
        dict(
            id="evidence:fourth", label="Evidence-only plate", caption="Keep full fourth caption",
            page=1, document_hash=sha,
        )
    )
    images["evidence:fourth"] = fourth
    manifest, blobs = codec.encode(
        deck, evidence, images, originals, source_document_hash=sha
    )
    request = catalog.prepare(
        database, "local-paper", manifest, lambda item: blobs[item["sha256"]],
        request_id="public-union", expected_native=native(database),
    )
    identity = catalog.retain(request)
    expected = catalog.read(database, identity, expected_native=native(database)).content
    pdfs = database.parent / "pdf"
    pdfs.mkdir()
    (pdfs / (_safe_name("local-paper") + ".pdf")).write_bytes(primary_b)
    monkeypatch.setattr(bundle, "DATA_DIR", database.parent)
    monkeypatch.setattr(bundle, "PDF_DIR", pdfs)
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO lists(id,name,note,created_at) VALUES(?,?,?,?)",
            ("union-list", "Complete union", None, "2026-11-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES(?,?,?,?)",
            ("union-list", "local-paper", 0, "2026-11-01T00:00:00+00:00"),
        )
    path = database.parent / "union.zip"
    bundle.export("union-list", path)
    receiver = side(database.parent, "union-receiver")
    enroll_capture(receiver)
    destination = database.parent / "union-import"
    destination.mkdir()
    importer = PackageImporter(receiver.journal.path, destination)
    return SimpleNamespace(
        archive=path, sender_db=database, sender_id=identity, expected=expected,
        receiver=receiver, importer=importer, destination=destination, saved=saved,
        saved_before=before, original_sha=sha,
    )


def general_rows(database):
    with closing(sqlite3.connect(database)) as conn:
        if not general._schema(conn):
            return []
        return conn.execute("SELECT proposal_id FROM " + general.TABLE).fetchall()


def snapshot(receiver):
    with closing(sqlite3.connect(receiver.journal.path)) as conn:
        return {
            name: conn.execute("SELECT * FROM " + name).fetchall()
            for name in ("papers", "lists", "list_papers", "notes")
        }, receiver.journal.pending()


def test_public_general_package_import_retains_full_catalog_and_exact_retry_is_readonly(
    union_package
):
    case = union_package
    report = case.importer.apply(case.importer.prepare(case.archive))
    assert report["deck_proposals"] == 1 and len(report["proposal_ids"]) == 1
    identity = report["proposal_ids"][0]
    assert general_rows(case.receiver.journal.path) == [(identity,)]
    value = general.read(
        case.receiver, case.importer.store, identity,
        expected_native=native(case.receiver.journal.path),
    )
    assert value.current_parent and value.content == case.expected
    mapped = report["identity_mapping"]["local-paper"]
    with case.receiver.journal.transaction() as conn:
        assert desired_file(conn, file_id(mapped["portable_id"], "deck", "guide")) is None
    before = snapshot(case.receiver)
    again = case.importer.apply(case.importer.prepare(case.archive))
    assert again["replayed"] and again["proposal_ids"] == [identity]
    assert snapshot(case.receiver) == before
    assert case.saved.read_bytes() == case.saved_before
    reader = ResearchReview(case.receiver.journal.path)
    try:
        rows = reader.page()["items"]
        assert len(rows) == 1 and rows[0]["origin"] == "enrolled_deck"
        view = reader.preview("enrolled_deck", identity).data
        assert not view["apply"] and view["retained"] == case.expected["deck"]
        assert view["retained_evidence"] == case.expected["evidence"]
        assert {item["id"] for item in view["image_manifest"]} == set(case.expected["image_bytes"])
        assert [item["sha256"] for item in view["original_manifest"]] == [case.original_sha]
    finally:
        reader.close()


@pytest.mark.parametrize("fault", ["sql", "cancel"])
def test_general_adoption_and_research_rollback_together_then_public_retry(
    union_package, monkeypatch, fault
):
    case, ticket = union_package, Ticket()
    prior = snapshot(case.receiver)
    original = general._insert

    def fail(*args, **kwargs):
        identity = original(*args, **kwargs)
        assert identity
        if fault == "cancel":
            ticket.cancel()
        else:
            raise sqlite3.OperationalError("Synthetic general package failure after adoption")
        return identity

    prepared = case.importer.prepare(case.archive)
    monkeypatch.setattr(general, "_insert", fail)
    with pytest.raises(Cancelled if fault == "cancel" else sqlite3.OperationalError):
        case.importer.apply(prepared, ticket=ticket)
    assert snapshot(case.receiver) == prior
    assert general_rows(case.receiver.journal.path) == []
    monkeypatch.setattr(general, "_insert", original)
    report = case.importer.apply(case.importer.prepare(case.archive))
    assert general_rows(case.receiver.journal.path) == [(report["proposal_ids"][0],)]
    value = general.read(
        case.receiver, case.importer.store, report["proposal_ids"][0],
        expected_native=native(case.receiver.journal.path),
    )
    assert value.content == case.expected and case.saved.read_bytes() == case.saved_before


def test_local_no_pdf_export_refuses_to_include_private_proposal_originals(union_package):
    case = union_package
    before = case.archive.read_bytes()
    with pytest.raises(ValueError, match="exact original PDFs"):
        bundle.export("union-list", case.archive, with_pdfs=False)
    assert case.archive.read_bytes() == before


def test_enrolled_reexport_is_full_and_no_pdf_refusal_preserves_destination(
    union_package, monkeypatch
):
    case = union_package
    report = case.importer.apply(case.importer.prepare(case.archive))
    monkeypatch.setattr(store, "DB_PATH", case.receiver.journal.path)
    monkeypatch.setattr(bundle, "DATA_DIR", case.destination)
    monkeypatch.setattr(bundle, "PDF_DIR", case.destination / "pdf")
    monkeypatch.setattr(presentations, "DECK_DIR", case.destination / "presentations")
    path = case.destination / "complete-again.zip"
    bundle.export(report["list"], path)
    _manifest, _tables, _proposal, value = package_content(path)
    assert value == case.expected
    old = path.read_bytes()
    with pytest.raises(ValueError, match="exact original PDFs"):
        bundle.export(report["list"], path, with_pdfs=False)
    assert path.read_bytes() == old
    digest = hashlib.sha256(value["original_bytes"][case.original_sha]).hexdigest()
    assert digest == case.original_sha


def test_missing_owned_index_is_not_recreated_by_preview_or_export(union_package, monkeypatch):
    case = union_package
    report = case.importer.apply(case.importer.prepare(case.archive))
    index = case.importer.store.root / "index.sqlite"
    index.unlink()
    reader = ResearchReview(case.receiver.journal.path)
    try:
        with pytest.raises(ValueError):
            reader.preview("enrolled_deck", report["proposal_ids"][0])
        assert not index.exists()
    finally:
        reader.close()
    monkeypatch.setattr(store, "DB_PATH", case.receiver.journal.path)
    monkeypatch.setattr(bundle, "DATA_DIR", case.destination)
    monkeypatch.setattr(bundle, "PDF_DIR", case.destination / "pdf")
    with pytest.raises(ValueError):
        bundle.export(report["list"], case.destination / "missing-index.zip")
    assert not index.exists()


def test_recreated_mapped_parent_after_general_preview_cannot_adopt_old_request(union_package):
    from uuid import uuid4

    from test_sync_files import paper_payload

    from paper_daily import sync_capture

    case = union_package
    portable = str(uuid4())
    case.receiver.save(case.receiver.new_graph_operation("paper", portable, paper_payload()))
    with case.receiver.journal.transaction() as conn:
        local_id = conn.execute(
            "SELECT local_id FROM research_paper_identity WHERE sync_id=?", (portable,)
        ).fetchone()[0]
    prepared = case.importer.prepare(
        case.archive, paper_mapping={"local-paper": local_id}, confirmed_mapping=True
    )
    with case.receiver.journal.transaction() as conn, sync_capture.suppress_capture(conn):
        row = conn.execute("SELECT * FROM papers WHERE id=?", (local_id,)).fetchone()
        conn.execute("DELETE FROM papers WHERE id=?", (local_id,))
        conn.execute("INSERT INTO papers VALUES (" + ",".join("?" for _ in row) + ")", row)
    before = snapshot(case.receiver)
    with pytest.raises(ValueError, match="lifecycle"):
        case.importer.apply(prepared)
    assert snapshot(case.receiver) == before and general_rows(case.receiver.journal.path) == []


@pytest.mark.parametrize("replace", [False, True])
def test_confirmed_existing_general_target_preserves_or_updates_only_approved_metadata(
    union_package, replace
):
    from uuid import uuid4

    from test_sync_files import paper_payload

    case = union_package
    portable = str(uuid4())
    payload = {**paper_payload(), "title": "Receiver curated title"}
    case.receiver.save(case.receiver.new_graph_operation("paper", portable, payload))
    with case.receiver.journal.transaction() as conn:
        local_id = conn.execute(
            "SELECT local_id FROM research_paper_identity WHERE sync_id=?", (portable,)
        ).fetchone()[0]
    options = dict(paper_mapping={"local-paper": local_id}, confirmed_mapping=True, replace=replace)
    report = case.importer.apply(case.importer.prepare(case.archive, **options))
    assert report["identity_mapping"]["local-paper"] == {
        "local_id": local_id, "portable_id": portable
    }
    identity = report["proposal_ids"][0]
    value = general.read(
        case.receiver, case.importer.store, identity,
        expected_native=native(case.receiver.journal.path),
    )
    assert value.content == case.expected
    import json

    captured = json.loads(value.record["captured_json"])
    adopted = json.loads(value.record["owner_json"])["target"]
    expected_title = "Local receiver" if replace else "Receiver curated title"
    assert captured["paper"]["title"] == "Receiver curated title"
    assert adopted["paper"]["title"] == expected_title
    assert captured["parent_token"] == adopted["parent_token"]
    with case.receiver.journal.transaction() as conn:
        assert conn.execute("SELECT title FROM papers WHERE id=?", (local_id,)).fetchone()[0] == (
            expected_title
        )
        assert desired_file(conn, file_id(portable, "deck", "guide")) is None
    reader = ResearchReview(case.receiver.journal.path)
    try:
        view = reader.prepare_file(reader.preview("enrolled_deck", identity)).data
        assert view["target"]["id"] == local_id and view["target"]["title"] == expected_title
        assert view["retained"] == case.expected["deck"] and view["apply"]
    finally:
        reader.close()
    before_replay = snapshot(case.receiver)
    again = case.importer.apply(case.importer.prepare(case.archive, **options))
    assert again["replayed"] and again["proposal_ids"] == [identity]
    assert snapshot(case.receiver) == before_replay
