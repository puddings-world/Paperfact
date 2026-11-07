"""Actual shared list-package entry preserves recorded A independently of current B."""

import hashlib
import zipfile
from contextlib import closing

import pytest
from test_later_outcome_packages import exported
from test_research_generation import pdf
from test_research_generation import workspace as workspace

from paper_daily import bundle, config, store
from paper_daily import later_outcome_packages as packages
from paper_daily import later_outcomes as outcomes
from paper_daily import local_source_owners as owners
from paper_daily import research_generation as generation

STAMP = "2026-11-01T00:00:00Z"


def source(workspace, monkeypatch, tmp_path, available=True):
    database, document, tables, manifest, output, proof = exported(
        workspace, monkeypatch, available
    )
    monkeypatch.setattr(bundle, "DATA_DIR", database.parent)
    monkeypatch.setattr(bundle, "PDF_DIR", document.path.parent)
    monkeypatch.setattr(bundle, "fetch", lambda *a, **kw: pytest.fail("Package attempted network"))
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO lists(id,name,created_at) VALUES('reading','Reading',?)", (STAMP,)
        )
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
            "VALUES('reading','paper',0,?)",
            (STAMP,),
        )
    return database, document, tmp_path / "research.zip"


def receiver(tmp_path, monkeypatch):
    root = tmp_path / "receiver"
    root.mkdir()
    database = root / "papers.db"
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(bundle, "DATA_DIR", root)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    monkeypatch.setattr(config, "PDF_DIR", root / "pdf")
    store.init_db()
    (root / "pdf").mkdir()
    return database


@pytest.mark.parametrize("available", [False, True])
def test_actual_list_package_import_both_source_states_and_exact_retry(
    workspace, monkeypatch, tmp_path, available
):
    database, document, archive = source(workspace, monkeypatch, tmp_path, available)
    bundle.export("reading", archive)
    with zipfile.ZipFile(archive) as zipped:
        manifest, tables, declared = bundle._validated(zipped)
        assert manifest["capabilities"] == ["later_outcome"]
        row = tables[outcomes.TABLE][0]
        assert row["document_hash"] == (document.sha256 if available else None)
        if available:
            item = manifest["later_sources"][0]
            assert (
                hashlib.sha256(zipped.read("files/" + item["path"])).hexdigest() == document.sha256
            )
            assert declared[item["path"]] == "paper"
    destination = receiver(tmp_path, monkeypatch)
    first = bundle.import_(archive, pdfs=False)
    assert first["later_outcomes"] == 1
    if available:
        primary = destination.parent / "pdf/paper.pdf"
        assert hashlib.sha256(primary.read_bytes()).hexdigest() == document.sha256
        primary.unlink()  # Actual missing-primary control; retained A remains owned.
    with closing(generation._connect(destination)) as conn:
        assert outcomes.settled(conn, "paper") is (
            not available
        )  # Explicit missing-primary control; pdfs=False does not remove included bytes.
        assert packages.read(conn, "paper")["document_hash"] == row["document_hash"]
        assert len(owners.records(conn)) == int(available)
    assert bundle.import_(archive, pdfs=False)["later_outcomes"] == 0
    with closing(generation._connect(destination)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM paper_later_outcomes").fetchone()[0] == 1
        assert len(owners.records(conn)) == int(available)
        assert outcomes.settled(conn, "paper")
    if available:
        assert (
            hashlib.sha256((destination.parent / "pdf/paper.pdf").read_bytes()).hexdigest()
            == document.sha256
        )


def test_actual_unbound_keeps_receiver_primary_c_and_retained_original_a(
    workspace, monkeypatch, tmp_path
):
    _database, document, archive = source(workspace, monkeypatch, tmp_path)
    pdf(document.path, "Current sharer B differs from recorded source A")
    bundle.export("reading", archive)
    destination = receiver(tmp_path, monkeypatch)
    with store.connect() as conn:
        store.upsert_papers(
            conn, [dict(id="paper", title="Paper", venue="Fixture", year=2026, source="fixture")]
        )
    path = destination.parent / "pdf/paper.pdf"
    pdf(path, "Receiver C must remain current")
    current = path.read_bytes()
    result = bundle.import_(archive)
    assert result["later_outcomes"] == 1 and path.read_bytes() == current
    with closing(generation._connect(destination)) as conn:
        assert packages.read(conn, "paper")["document_hash"] == document.sha256
        assert not outcomes.settled(conn, "paper")
        receipt = owners.records(conn)[0]
        from paper_daily.source_snapshots import source_path

        assert (
            hashlib.sha256(source_path(destination, receipt).read_bytes()).hexdigest()
            == document.sha256
        )
        assert conn.execute("SELECT COUNT(*) FROM list_papers").fetchone()[0] == 1


def test_actual_source_bound_light_package_refuses_before_url_lookup(
    workspace, monkeypatch, tmp_path
):
    _database, _document, archive = source(workspace, monkeypatch, tmp_path)
    monkeypatch.setattr(
        bundle, "pdf_record", lambda *a, **kw: pytest.fail("Source-bound no-PDF refusal was late")
    )
    with pytest.raises(ValueError, match="Include"):
        bundle.export("reading", archive, with_pdfs=False)
    assert not archive.exists()


def test_actual_full_included_primary_a_settles_after_explicit_import(
    workspace, monkeypatch, tmp_path
):
    _database, document, archive = source(workspace, monkeypatch, tmp_path, True)
    bundle.export("reading", archive)
    destination = receiver(tmp_path, monkeypatch)
    assert bundle.import_(archive, pdfs=False)["later_outcomes"] == 1
    primary = destination.parent / "pdf/paper.pdf"
    assert hashlib.sha256(primary.read_bytes()).hexdigest() == document.sha256
    with closing(generation._connect(destination)) as conn:
        assert outcomes.settled(conn, "paper")
        assert len(owners.records(conn)) == 1
