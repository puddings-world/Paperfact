"""Public local-only import retains research proposals without enabling synchronization."""

import copy
import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing

import pytest
from test_deck_proposal_packages import case as case
from test_deck_proposal_packages import codec as codec
from test_deck_proposal_packages import no_external as no_external
from test_deck_proposal_packages import original as original
from test_deck_proposal_packages import package as _package
from test_rescue_deck_import import TARGET

from paper_daily import bundle, presentations, store
from paper_daily import local_deck_proposals as catalog
from paper_daily.fetch import _safe_name
from paper_daily.research_review import ResearchReview

package = _package


def empty_receiver(package, monkeypatch):
    root = package.case["root"] / "local-only"
    root.mkdir()
    database = root / "papers.db"
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(bundle, "DATA_DIR", root)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    monkeypatch.setattr(presentations, "DECK_DIR", root / "presentations")
    store.init_db()
    return root, database


def test_public_local_import_review_apply_and_reimport_keep_primary_and_all_science(
    package, monkeypatch
):
    root, database = empty_receiver(package, monkeypatch)
    report = bundle.import_(package.archive, pdfs=False)
    assert report["deck_proposals"] == 1
    assert presentations.load_deck(TARGET, "guide") is None
    reader = ResearchReview(database)
    try:
        rows = [row for row in reader.page(limit=100)["items"] if row["origin"] == "local_deck"]
        assert len(rows) == 1
        identity = rows[0]["id"]
        info = database.stat()
        content = catalog.read(
            database, identity, expected_native=(info.st_dev, info.st_ino)
        ).content
        assert content["image_bytes"] == package.case["images"]
        assert set(content["original_bytes"]) == {package.original_a}
        assert content["deck"]["figures"][-1]["caption"] == "Complete unused scientific caption"
        primary = root / "pdf" / (_safe_name(TARGET) + ".pdf")
        assert hashlib.sha256(primary.read_bytes()).hexdigest() == package.primary["sha256"]
        view = reader.prepare_file(reader.preview("local_deck", identity))
        assert reader.decide(view, request_id="local-package-apply", confirm_target=True) == {
            "decision": "applied",
            "operation_id": None,
        }
        loaded = presentations.load_deck(TARGET, "guide")
        assert loaded.slides[0].speaker_notes == package.case["sender"].slides[0].speaker_notes
        for key, data in package.case["images"].items():
            assert presentations.figure_bytes(loaded, key) == data
        before = presentations._path(TARGET, "guide").read_bytes()
        again = bundle.import_(package.archive, pdfs=False)
        assert again["deck_proposals"] == 0 and again["proposal_replayed"] == 1
        assert again["proposal_ids"] == [identity]
        assert presentations._path(TARGET, "guide").read_bytes() == before
        assert (
            len([row for row in reader.page(limit=100)["items"] if row["origin"] == "local_deck"])
            == 1
        )
        assert hashlib.sha256(primary.read_bytes()).hexdigest() == package.primary["sha256"]
    finally:
        reader.close()
    with closing(sqlite3.connect(database)) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert "research_sync_binding" not in names and "paperfact_sync_identity" not in names


def test_local_import_catalog_failure_rolls_back_research_and_files_then_retries(
    package, monkeypatch
):
    root, database = empty_receiver(package, monkeypatch)
    with closing(sqlite3.connect(database)) as conn:
        before = {
            name: conn.execute("SELECT * FROM " + name).fetchall()
            for name in ("papers", "lists", "list_papers")
        }
    actual = catalog._Grant.adopt

    def failed(grant):
        values = actual(grant)
        assert values
        raise sqlite3.OperationalError("Synthetic local import failure after private adoption")

    monkeypatch.setattr(catalog._Grant, "adopt", failed)
    with pytest.raises(sqlite3.OperationalError):
        bundle.import_(package.archive, pdfs=False)
    with closing(sqlite3.connect(database)) as conn:
        for name, rows in before.items():
            assert conn.execute("SELECT * FROM " + name).fetchall() == rows
        assert conn.execute("SELECT count(*) FROM " + catalog.TABLE).fetchone() == (0,)
    assert not list((root / "pdf").glob("*.pdf"))
    monkeypatch.setattr(catalog._Grant, "adopt", actual)
    assert bundle.import_(package.archive, pdfs=False)["deck_proposals"] == 1


@pytest.mark.parametrize("replace", [False, True])
def test_existing_local_paper_import_preserves_notes_and_requires_explicit_slide_apply(
    package, monkeypatch, replace
):
    root, database = empty_receiver(package, monkeypatch)
    with zipfile.ZipFile(package.archive) as archive:
        incoming = next(
            row for row in json.loads(archive.read("tables.json"))["papers"] if row["id"] == TARGET
        )
    existing = {**incoming, "title": "Receiver's curated paper title"}
    with closing(sqlite3.connect(database)) as conn:
        store.upsert_papers(conn, [existing])
        conn.execute(
            "INSERT INTO notes(paper_id,body,kind,created_at) VALUES(?,?,?,?)",
            (TARGET, "Receiver's manually written note", "note", "2026-11-01"),
        )
        conn.commit()
        prior_notes = conn.execute("SELECT * FROM notes").fetchall()
    old = copy.deepcopy(package.case["sender"])
    old.paper_id = TARGET
    old.title = "Receiver's edited slides"
    old._revision_figures = package.case["images"]
    saved = presentations.save_deck(old)
    prior_slides = saved.read_bytes()
    report = bundle.import_(package.archive, pdfs=False, replace=replace)
    assert report["deck_proposals"] == 1 and len(report["proposal_ids"]) == 1
    expected_title = incoming["title"] if replace else existing["title"]
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT title FROM papers WHERE id=?", (TARGET,)).fetchone() == (
            expected_title,
        )
        assert conn.execute("SELECT * FROM notes").fetchall() == prior_notes
    assert saved.read_bytes() == prior_slides
    info = database.stat()
    value = catalog.read(
        database, report["proposal_ids"][0], expected_native=(info.st_dev, info.st_ino)
    )
    captured = json.loads(value.record["captured_json"])
    owner = json.loads(value.record["owner_json"])
    assert captured["paper"]["title"] == existing["title"]
    assert owner["paper"]["title"] == expected_title
    assert owner["parent_token"] == captured["parent_token"]
    assert value.content["image_bytes"] == package.case["images"]
    assert set(value.content["original_bytes"]) == {package.original_a}
    reader = ResearchReview(database)
    try:
        view = reader.prepare_file(reader.preview("local_deck", report["proposal_ids"][0]))
        assert view.data["apply"]
        assert saved.read_bytes() == prior_slides
        result = reader.decide(view, request_id="existing-paper-apply", confirm_target=True)
        assert result["decision"] == "applied"
        loaded = presentations.load_deck(TARGET, "guide")
        assert loaded.title == package.case["sender"].title
        after_apply = saved.read_bytes()
        again = bundle.import_(package.archive, pdfs=False, replace=replace)
        assert again["deck_proposals"] == 0 and again["proposal_replayed"] == 1
        assert again["proposal_ids"] == report["proposal_ids"]
        assert saved.read_bytes() == after_apply
    finally:
        reader.close()


def test_confirmed_replacement_and_proposal_adoption_roll_back_together_then_retry(
    package, monkeypatch
):
    root, database = empty_receiver(package, monkeypatch)
    with zipfile.ZipFile(package.archive) as archive:
        incoming = next(
            row for row in json.loads(archive.read("tables.json"))["papers"] if row["id"] == TARGET
        )
    existing = {**incoming, "title": "Before confirmed replacement"}
    with closing(sqlite3.connect(database)) as conn:
        store.upsert_papers(conn, [existing])
        conn.commit()
        prior_papers = conn.execute("SELECT * FROM papers ORDER BY id").fetchall()
    actual = catalog._Grant.adopt

    def fail_after_adoption(grant):
        identities = actual(grant)
        assert identities
        raise sqlite3.OperationalError("Synthetic failure after confirmed replacement")

    monkeypatch.setattr(catalog._Grant, "adopt", fail_after_adoption)
    with pytest.raises(sqlite3.OperationalError):
        bundle.import_(package.archive, pdfs=False, replace=True)
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT * FROM papers ORDER BY id").fetchall() == prior_papers
        assert conn.execute("SELECT count(*) FROM " + catalog.TABLE).fetchone() == (0,)
    assert not list((root / "pdf").glob("*.pdf"))
    monkeypatch.setattr(catalog._Grant, "adopt", actual)
    report = bundle.import_(package.archive, pdfs=False, replace=True)
    assert report["deck_proposals"] == 1
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT title FROM papers WHERE id=?", (TARGET,)).fetchone() == (
            incoming["title"],
        )
