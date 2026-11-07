"""Actual package proposal guards: retry, malformed data and caller-transaction rollback."""

import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from types import SimpleNamespace

import pytest
from test_package_import import enroll_capture
from test_rescue_deck_import import RECEIVER, TARGET, attach, export_file, pdf_bytes, target
from test_rescue_deck_import import case as _case
from test_rescue_deck_import import codec as _codec
from test_rescue_deck_import import no_external as _no_external
from test_rescue_deck_import import original as _original

from paper_daily import bundle
from paper_daily import deck_proposal_packages as carrier
from paper_daily import rescue_deck_import as rescue
from paper_daily.document_reader import register_document_paths
from paper_daily.package_import import PackageImporter
from paper_daily.research_review import ResearchReview
from paper_daily.sync_schema_v2 import membership_id
from paper_daily.sync_source_files import publish as publish_source
from paper_daily.workspace_service import Cancelled, Ticket

case, codec, no_external, original = _case, _codec, _no_external, _original


@pytest.fixture
def package(case, monkeypatch):
    client = case["a"]
    with client.journal.transaction() as conn:
        register_document_paths(
            conn,
            workspace_id="workspace",
            blob_root=case["transfer"].store.root,
            projection_root=case["root"] / "reader",
            legacy_root=case["root"] / "pdf",
        )
        parent = client._optimistic_graph(conn)[0][("paper", RECEIVER)]["incarnation"]
    content = pdf_bytes("Declared historical original A")
    sha = hashlib.sha256(content).hexdigest()
    source = case["root"] / "source-a.pdf"
    source.write_bytes(content)
    publish_source(
        client,
        RECEIVER,
        source,
        document_hash=sha,
        parent_incarnation=parent,
        store=case["transfer"].store,
        version_root=case["transfer"].root,
        request_id="proposal-a",
    )
    primary = attach(client, case["transfer"].store, RECEIVER, pdf_bytes("Current B"), "primary-b")
    rescue_file = export_file(case, monkeypatch, source_hash=sha)
    result = rescue.run(rescue.prepare(target(case), rescue.inspect_file(rescue_file)))
    assert result.durable
    listing = "proposal-list"
    client.save(client.new_graph_operation("list", listing, {"name": "Proposals", "note": None}))
    client.save(
        client.new_graph_operation(
            "membership",
            membership_id(listing, RECEIVER),
            {
                "list_id": listing,
                "paper_id": RECEIVER,
                "citation": None,
                "added_at": "2026-11-01T00:00:00+00:00",
            },
        )
    )
    monkeypatch.setattr(bundle, "DATA_DIR", case["root"])
    monkeypatch.setattr(bundle, "PDF_DIR", case["root"] / "pdf")
    archive = case["root"] / "proposals.zip"
    bundle.export(listing, archive)
    enroll_capture(case["b"])
    destination = case["root"] / "receiver"
    destination.mkdir()
    importer = PackageImporter(case["b"].journal.path, destination)
    return SimpleNamespace(
        case=case,
        archive=archive,
        importer=importer,
        original_a=sha,
        primary=primary,
        listing=listing,
        source=rescue_file,
    )


def catalog(database):
    review = ResearchReview(database)
    try:
        return [row for row in review.page(limit=100)["items"] if row["origin"] == "file_draft"]
    finally:
        review.close()


def test_enrolled_retry_does_not_duplicate_private_proposals_or_publish_active_decks(package):
    first = package.importer.apply(package.importer.prepare(package.archive))
    before = package.case["b"].journal.pending()
    entries = catalog(package.case["b"].journal.path)
    assert first["deck_proposals"] == 1 and len(entries) == 1
    again = package.importer.apply(package.importer.prepare(package.archive))
    assert again["replayed"] and again["state"] == "previously_applied"
    assert catalog(package.case["b"].journal.path) == entries
    assert package.case["b"].journal.pending() == before
    assert first["proposal_ids"] == [entries[0]["id"]]


@pytest.mark.parametrize("fault", ["receipt", "cancel"])
def test_failure_after_proposal_adoption_rolls_back_research_outbox_and_catalog(
    package, monkeypatch, fault
):
    receiver = package.case["b"]
    before = receiver.journal.pending()
    with closing(sqlite3.connect(receiver.journal.path)) as conn:
        papers = conn.execute("SELECT * FROM papers ORDER BY id").fetchall()
    prepared = package.importer.prepare(package.archive)
    actual = carrier.adopt_in
    ticket = Ticket()

    def fail(conn, client, value):
        result = actual(conn, client, value)
        assert conn.execute(
            "SELECT 1 FROM research_file_drafts WHERE candidate_id=?", (result,)
        ).fetchone()
        if fault == "cancel":
            ticket.cancel()
        else:
            raise sqlite3.OperationalError("Synthetic import failure after proposal staging")
        return result

    monkeypatch.setattr(carrier, "adopt_in", fail)
    with pytest.raises(Cancelled if fault == "cancel" else sqlite3.OperationalError):
        package.importer.apply(prepared, ticket=ticket)
    assert receiver.journal.pending() == before
    assert catalog(receiver.journal.path) == []
    with closing(sqlite3.connect(receiver.journal.path)) as conn:
        assert conn.execute("SELECT * FROM papers ORDER BY id").fetchall() == papers
    monkeypatch.setattr(carrier, "adopt_in", actual)
    result = package.importer.apply(package.importer.prepare(package.archive))
    assert result["deck_proposals"] == 1 and len(catalog(receiver.journal.path)) == 1


def rewrite(package, change):
    with zipfile.ZipFile(package.archive) as source:
        values = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(values["manifest.json"])
    tables = json.loads(values["tables.json"])
    change(manifest, tables, values)
    values["manifest.json"] = json.dumps(manifest).encode()
    values["tables.json"] = json.dumps(tables).encode()
    changed = package.case["root"] / "changed.zip"
    with zipfile.ZipFile(changed, "w") as output:
        for name, data in values.items():
            output.writestr(name, data)
    return changed


@pytest.mark.parametrize("fault", ["capability", "extra-field", "missing-object", "changed-pdf"])
def test_invalid_proposal_package_refuses_before_receiver_mutation(package, fault):
    def change(manifest, tables, values):
        row = tables["deck_proposals"][0]
        if fault == "capability":
            manifest["capabilities"] = []
        elif fault == "extra-field":
            row["writer"] = {"device": "not-authority"}
        else:
            item = row["manifest"]["originals"][0]
            path = "files/" + carrier.relative(row["paper_id"], item["sha256"]).as_posix()
            if fault == "missing-object":
                del values[path]
            else:
                values[path] = pdf_bytes("A different original must not substitute A")

    archive = rewrite(package, change)
    receiver = package.case["b"]
    before = receiver.journal.pending()
    with pytest.raises(ValueError):
        package.importer.prepare(archive)
    assert receiver.journal.pending() == before and not catalog(receiver.journal.path)


def test_export_without_declared_originals_does_not_replace_previous_package(package):
    before = package.archive.read_bytes()
    pending = package.case["a"].journal.pending()
    with pytest.raises(ValueError, match="exact original PDFs"):
        bundle.export(package.listing, package.archive, with_pdfs=False)
    assert package.archive.read_bytes() == before
    assert package.case["a"].journal.pending() == pending


def test_old_reader_rejects_required_proposal_capability_before_import(package, monkeypatch):
    """The previous capability resolver cannot admit a new-capability archive."""
    old = bundle._required_capabilities
    monkeypatch.setattr(
        bundle,
        "_required_capabilities",
        lambda tables: old(
            {key: value for key, value in tables.items() if key != "deck_proposals"}
        ),
    )
    before = package.case["b"].journal.pending()
    with pytest.raises(ValueError, match="capabilities"):
        package.importer.prepare(package.archive)
    assert not catalog(package.case["b"].journal.path)
    assert package.case["b"].journal.pending() == before


def test_fresh_enrolled_store_can_import_and_review_without_a_transfer_session(package):
    from test_sync_files import side

    receiver = side(package.case["root"], "fresh-no-transfer")
    enroll_capture(receiver)
    root = package.case["root"] / "fresh-store"
    root.mkdir()
    importer = PackageImporter(receiver.journal.path, root)
    with importer.store._transaction() as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='transfer_binding'"
        ).fetchone()
    report = importer.apply(importer.prepare(package.archive))
    assert report["deck_proposals"] == 1 and report["remote_sync"] == "not_requested"
    rows = catalog(receiver.journal.path)
    assert len(rows) == 1
    review = ResearchReview(receiver.journal.path)
    try:
        verified = review.prepare_file(review.preview("file_draft", rows[0]["id"]))
        assert verified.data["apply"] and verified.data["requires_confirmation"]
    finally:
        review.close()


def test_receiver_recreated_after_import_preview_refuses_without_research_changes(package):
    from test_sync_files import LOCAL

    from paper_daily import sync_capture
    from paper_daily.research_lifecycle import parent_lifecycle

    receiver = package.case["b"]
    prepared = package.importer.prepare(
        package.archive, paper_mapping={TARGET: LOCAL}, confirmed_mapping=True
    )
    with receiver.journal.transaction() as conn, sync_capture.suppress_capture(conn):
        before = parent_lifecycle(conn, "paper", LOCAL)
        row = conn.execute("SELECT * FROM papers WHERE id=?", (LOCAL,)).fetchone()
        conn.execute("DELETE FROM papers WHERE id=?", (LOCAL,))
        conn.execute("INSERT INTO papers VALUES (" + ",".join("?" for _ in row) + ")", row)
        assert parent_lifecycle(conn, "paper", LOCAL) != before
    pending = receiver.journal.pending()
    with pytest.raises(ValueError, match="lifecycle"):
        package.importer.apply(prepared)
    assert receiver.journal.pending() == pending and catalog(receiver.journal.path) == []


def test_replaced_blob_index_after_preview_refuses_before_sql_or_activation(package):
    import os

    from paper_daily.sync_blobs import BlobStore

    receiver = package.case["b"]
    prepared = package.importer.prepare(package.archive)
    before = receiver.journal.pending()
    other = BlobStore(package.case["root"] / "other-index")
    os.replace(other.root / "index.sqlite", package.importer.store.root / "index.sqlite")
    with pytest.raises(ValueError, match="index"):
        package.importer.apply(prepared)
    assert receiver.journal.pending() == before and catalog(receiver.journal.path) == []
