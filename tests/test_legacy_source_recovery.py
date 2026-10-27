"""Existing un-enrolled research recovers exact original PDFs without enrollment."""

import hashlib
import json
import sqlite3
from contextlib import closing

import pymupdf
import pytest
from test_sync_files import codec as codec_fixture
from test_sync_files import pair as pair_fixture

from paper_daily import research_compound as compound
from paper_daily import research_generation as generation
from paper_daily import store, sync_recovery
from paper_daily import sync_legacy_sources as legacy

pair = pair_fixture
codec = codec_fixture


def pdf_bytes(text="Original research evidence"):
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 50), text)
        return document.tobytes()


def example(tmp_path, *, pdf_root=None):
    root = tmp_path / "workspace"
    root.mkdir()
    database = root / "papers.db"
    pdf_root = pdf_root or root / "pdf"
    pdf_root.mkdir(parents=True)
    pdf = pdf_root / "paper.pdf"
    data = pdf_bytes()
    pdf.write_bytes(data)
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        store.upsert_papers(
            conn,
            [
                {
                    "id": "paper",
                    "title": "Paper",
                    "year": 2026,
                    "venue": "Fixture",
                    "source": "fixture",
                }
            ],
        )
    with closing(generation._connect(database)) as conn:
        context = compound.begin(conn, phase="citations", owner_id="paper")
    context, _, _ = compound.read_text(context, pdf_root=pdf_root, text_root=pdf_root)
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("UPDATE papers SET title='Later title' WHERE id='paper'")
    result = compound.publish(
        context,
        puts=[
            compound.row(context, "one", title="First retained reference", basis="context"),
            compound.row(context, "two", title="Second retained reference", basis="context"),
        ],
    )
    assert result.status == "candidate"
    return database, pdf, data, context


def contents(database):
    with closing(sqlite3.connect(database)) as conn:
        return "\n".join(conn.iterdump())


def test_exact_existing_user_compound_journey_recovers_without_live_changes(tmp_path):
    database, pdf, data, context = example(tmp_path)
    before, file_before = contents(database), database.read_bytes()
    output = tmp_path / "complete.zip"
    manifest = sync_recovery.create(database, output)
    digest = hashlib.sha256(data).hexdigest()
    assert contents(database) == before and database.read_bytes() == file_before
    assert pdf.read_bytes() == data
    assert next(row for row in manifest["tables"] if row["name"] == legacy.TABLE)["count"] == 1
    assert manifest["blobs"] == [{"sha256": digest, "size": len(data)}]
    destination = tmp_path / "detached"
    sync_recovery.restore_detached(output, destination)
    assert (destination / "objects" / digest).read_bytes() == data
    with closing(sqlite3.connect(destination / "papers.db")) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & {
            "research_sync_binding",
            "paperfact_sync_identity",
            "research_document_desired",
            legacy.TABLE,
        }
        row = json.loads(
            conn.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_compound_requests'"
            ).fetchone()[0]
        )
        assert (
            json.loads(row["context_json"])["document"]["sha256"]
            == context.data["document"]["sha256"]
        )
        assert json.loads(row["mutations_json"])["puts"][1]["title"] == "Second retained reference"
        assert conn.execute("SELECT COUNT(*) FROM cites").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["missing", "changed"])
def test_missing_or_changed_original_still_blocks_complete_backup(tmp_path, change):
    database, pdf, data, _ = example(tmp_path)
    before = contents(database)
    if change == "missing":
        pdf.unlink()
    else:
        pdf.write_bytes(pdf_bytes("A different document"))
    output = tmp_path / "incomplete.zip"
    with pytest.raises(ValueError, match="source PDF.*missing|source PDF.*changed"):
        sync_recovery.create(database, output)
    assert not output.exists() and contents(database) == before
    assert data != (pdf.read_bytes() if pdf.exists() else b"")


def test_receipt_path_outside_trusted_roots_is_not_followed_without_explicit_selection(tmp_path):
    database, pdf, data, context = example(tmp_path, pdf_root=tmp_path / "outside-pdfs")
    assert context.data["document"]["path"] == str(pdf.resolve())
    before = contents(database)
    with pytest.raises(ValueError, match="trusted PDF roots"):
        sync_recovery.create(database, tmp_path / "not-authorized.zip")
    output = tmp_path / "explicit-root.zip"
    manifest = sync_recovery.create(database, output, pdf_roots=[pdf.parent])
    assert manifest["blobs"] == [{"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}]
    assert contents(database) == before


def test_same_hash_at_multiple_trusted_paths_is_deduplicated_without_dropping_aliases(tmp_path):
    database, pdf, data, _ = example(tmp_path)
    duplicate = pdf.with_name("duplicate-copy.PDF")
    duplicate.write_bytes(data)
    output = tmp_path / "deduplicated.zip"
    manifest = sync_recovery.create(database, output, pdf_roots=[pdf.parent])
    assert len(manifest["blobs"]) == 1
    assert next(row for row in manifest["tables"] if row["name"] == legacy.TABLE)["count"] == 1
    assert pdf.read_bytes() == duplicate.read_bytes() == data


def test_source_change_between_scan_and_copy_is_detected(tmp_path, monkeypatch):
    database, pdf, _, _ = example(tmp_path)
    original = legacy.LegacySources._scan
    changed = []

    def scan(self):
        original(self)
        if not changed:
            changed.append(True)
            pdf.write_bytes(pdf_bytes("Changed after inventory"))

    monkeypatch.setattr(legacy.LegacySources, "_scan", scan)
    output = tmp_path / "raced.zip"
    with pytest.raises(ValueError, match="changed while staging"):
        sync_recovery.create(database, output)
    assert not output.exists()


@pytest.mark.parametrize("limit", ["MAX_FILE", "MAX_SCAN_BYTES", "MAX_FILES", "MAX_ENTRIES"])
def test_source_inventory_limits_fail_without_truncating_or_enrolling(tmp_path, monkeypatch, limit):
    database, pdf, data, _ = example(tmp_path)
    before = contents(database)
    monkeypatch.setattr(legacy, limit, 1)
    if limit in {"MAX_FILES", "MAX_ENTRIES"}:
        pdf.with_name("second.pdf").write_bytes(data)
    output = tmp_path / "over-limit.zip"
    with pytest.raises(ValueError, match="bound"):
        sync_recovery.create(database, output)
    assert not output.exists() and contents(database) == before and pdf.read_bytes() == data


def test_matching_hash_of_unreadable_pdf_is_not_enough(tmp_path):
    root = tmp_path / "pdf"
    root.mkdir()
    data = b"%PDF-1.7\nnot a readable document"
    (root / "invalid.pdf").write_bytes(data)
    with pytest.raises(ValueError, match="readable"):
        legacy.LegacySources([root], tmp_path).require(hashlib.sha256(data).hexdigest())


def test_generation_pdf_provenance_also_joins_the_same_archive_only_closure(tmp_path):
    from test_research_generation import BODY

    from paper_daily.document_reader import from_workspace

    database, pdf, data, _ = example(tmp_path)
    with closing(generation._connect(database)) as conn:
        context = generation.begin_generation(
            conn, table="close_readings", owner_id="paper", input_reader="target"
        )
    document = from_workspace(database, legacy_root=pdf.parent).resolve("paper")
    context = generation.bind_inputs(context, document=document)
    outcome = generation.publish_generated(
        context, row={"paper_id": "paper", "body": BODY, "written_at": store.now(), "spec": None}
    )
    assert outcome.status == "accepted"
    manifest = sync_recovery.create(database, tmp_path / "generation.zip")
    assert manifest["blobs"] == [{"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}]
    assert next(row for row in manifest["tables"] if row["name"] == legacy.TABLE)["count"] == 1


def test_generated_deck_source_without_revision_receipt_is_adopted(
    pair, codec, tmp_path, monkeypatch
):
    from test_sync_files import LOCAL

    from paper_daily import presentations
    from paper_daily.sync_artifacts import paths
    from paper_daily.sync_deck_publication import observe_deck

    database, client = pair[1].journal.path, pair[1]
    folder = database.parent / "pdf"
    folder.mkdir()
    data = pdf_bytes()
    digest = hashlib.sha256(data).hexdigest()
    (folder / "original.pdf").write_bytes(data)
    value = codec[0]
    value.paper_id = LOCAL
    value.sources[0]["document_hash"] = digest
    presentations.save_deck(
        value,
        observation=observe_deck(LOCAL, "guide"),
        evidence={
            "sources": value.sources,
            "coverage": [],
            "source_hash": value.source_hash,
        },
    )
    with client.journal.transaction() as conn:
        owned_store = paths(conn)[0]
        assert conn.execute("SELECT COUNT(*) FROM research_document_desired").fetchone()[0] == 0
    before = contents(database)
    output = tmp_path / "deck-source.zip"
    manifest = sync_recovery.create(database, output, blob_store=owned_store)
    assert any(row["sha256"] == digest for row in manifest["blobs"])
    assert next(row for row in manifest["tables"] if row["name"] == legacy.TABLE)["count"] == 1
    assert contents(database) == before
    destination = tmp_path / "detached-deck"
    sync_recovery.restore_detached(output, destination)
    assert (destination / "objects" / digest).read_bytes() == data
