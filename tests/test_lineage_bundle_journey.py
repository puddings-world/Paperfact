"""Public list packages retain full Lineage reports and exact receiver originals."""

import json
import sqlite3
import zipfile
from contextlib import closing

import pytest
from test_lineage_jobs import work
from test_lineage_recovery import published
from test_research_lineage import corpus as corpus
from test_sync_files import codec as codec
from test_sync_files import pair as pair

from paper_daily import bundle, bundle_files, lineage_import_originals, lineage_sets, llm, store
from paper_daily import research_generation as generation
from paper_daily.manual_highlight_ops import observe_owner


def select(monkeypatch, database):
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(bundle, "DATA_DIR", database.parent)
    monkeypatch.setattr(bundle, "PDF_DIR", database.parent / "pdf")


def dump(database):
    with closing(sqlite3.connect(database)) as conn:
        return list(conn.iterdump())


@pytest.fixture
def shared(corpus, monkeypatch, tmp_path):
    published(corpus, monkeypatch)
    select(monkeypatch, corpus[0])
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO lists(id,name,created_at) VALUES('lineage','My research','fixture')"
        )
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
            "VALUES('lineage','focal',0,'fixture')"
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) "
            "VALUES('prior','Private peer note','fixture')"
        )
    before = dump(corpus[0])
    path = tmp_path / "research.zip"
    made = bundle.export("lineage", path)
    assert made["paper_lineage_sets"] == 1 and made["cited_papers"] == 2
    assert dump(corpus[0]) == before
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        tables = json.loads(archive.read("tables.json"))
        originals = {
            record["paper_id"]: archive.read("files/" + record["path"])
            for record in manifest["lineage_sources"]
        }
        assert {p["id"] for p in tables["papers"]} == {"focal"}
        assert {p["id"] for p in tables["cited_papers"]} == {"prior", "later"}
        assert not tables["notes"]
        assert not any(name.startswith("research_") for name in tables)
    target = tmp_path / "receiver" / "papers.db"
    target.parent.mkdir()
    select(monkeypatch, target)
    store.init_db()

    def unexpected(*_args, **_kwargs):
        pytest.fail("Package sharing must not invoke a model or network request")

    monkeypatch.setattr(llm, "complete_result", unexpected)
    monkeypatch.setattr(bundle, "fetch", unexpected)
    return path, target, originals, tables["paper_lineage_sets"]


def assert_originals(database, rows, originals):
    owner = observe_owner(database, "focal", expected_native=generation._identity(database))
    saved = lineage_sets.saved(database, "focal")
    assert saved == rows
    for binding, source in zip(
        lineage_sets.decode(saved[0]["body_json"])["bindings"],
        lineage_sets.decode(saved[0]["body_json"])["report"]["sources"],
        strict=True,
    ):
        snapshot = work(lineage_import_originals.prepare, owner, saved[0], source["id"])
        assert (
            lineage_import_originals.for_delivery(snapshot, owner, saved[0], source["id"])
            == originals[binding["paper_id"]]
        )


def test_public_export_import_reexport_and_third_receiver_read_exact_originals(
    shared, monkeypatch, tmp_path
):
    path, database, originals, rows = shared
    report = bundle.import_(path)
    assert report["lineage_reports"] == 1 and report["lineage_state"] == "imported"
    assert report["papers"] == 1 and report["cited_papers"] == 2
    again = bundle.import_(path, pdfs=False)
    assert again["lineage_state"] == "already_imported" and again["joined_list"] == 0
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT paper_id FROM list_papers").fetchall() == [("focal",)]
        assert conn.execute("SELECT COUNT(*) FROM research_lineage_imports").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM research_local_source_owners").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0
    assert_originals(database, rows, originals)
    output = tmp_path / "again.zip"
    bundle.export("lineage", output)
    third = tmp_path / "third" / "papers.db"
    third.parent.mkdir()
    select(monkeypatch, third)
    store.init_db()
    assert bundle.import_(output, pdfs=False)["lineage_reports"] == 1
    assert_originals(third, rows, originals)


def test_late_file_install_failure_rolls_back_list_research_and_source_receipts(
    shared, monkeypatch
):
    path, database, _originals, _rows = shared
    before = dump(database)
    original = bundle_files.StagedFiles.install

    def fail(_self):
        raise OSError("fixture failed file publication")

    monkeypatch.setattr(bundle_files.StagedFiles, "install", fail)
    with pytest.raises(OSError, match="file publication"):
        bundle.import_(path, pdfs=False)
    assert dump(database) == before
    monkeypatch.setattr(bundle_files.StagedFiles, "install", original)
    assert bundle.import_(path, pdfs=False)["lineage_state"] == "imported"


@pytest.mark.parametrize("change", ["missing-source", "missing-peer"])
def test_invalid_public_package_changes_no_research(shared, tmp_path, change):
    path, database, _originals, _rows = shared
    changed = tmp_path / "broken.zip"
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(changed, "w") as dest:
        manifest = json.loads(source.read("manifest.json"))
        for name in source.namelist():
            if (
                change == "missing-source"
                and name == "files/" + manifest["lineage_sources"][0]["path"]
            ):
                continue
            data = source.read(name)
            if change == "missing-peer" and name == "tables.json":
                tables = json.loads(data)
                tables["cited_papers"].pop()
                data = json.dumps(tables).encode()
            dest.writestr(name, data)
    before = dump(database)
    with pytest.raises(ValueError):
        bundle.import_(changed, pdfs=False)
    assert dump(database) == before


def test_concurrent_public_retries_commit_one_list_and_native_import(shared):
    from concurrent.futures import ThreadPoolExecutor

    path, database, originals, rows = shared
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(bundle.import_, path, pdfs=False) for _ in range(2)]
        results = [future.result(timeout=60) for future in futures]
    assert sorted(result["lineage_state"] for result in results) == ["already_imported", "imported"]
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM list_papers").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM research_lineage_imports").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM research_local_source_owners").fetchone()[0] == 3
    assert_originals(database, rows, originals)


def test_enrolled_public_import_refuses_invalid_membership_time_before_changes(
    shared, pair, monkeypatch
):
    from test_package_import import enroll_capture

    path, _database, _originals, _rows = shared
    client = pair[1]
    enroll_capture(client)
    select(monkeypatch, client.journal.path)
    before, pending = dump(client.journal.path), client.journal.pending()
    # The historical fixture contains an invalid membership timestamp. Native
    # imports support complete Lineage, but must still reject malformed metadata.
    with pytest.raises(ValueError, match="Membership added_at must be an ISO timestamp"):
        bundle.import_(path, pdfs=False)
    assert dump(client.journal.path) == before
    assert client.journal.pending() == pending


def test_changed_original_during_export_preserves_previous_package(shared, monkeypatch, tmp_path):
    from paper_daily import source_snapshots

    path, database, _originals, _rows = shared
    bundle.import_(path, pdfs=False)
    output = tmp_path / "previous.zip"
    previous = b"Previous independently saved package"
    output.write_bytes(previous)
    validate = bundle._validated

    def changed(archive):
        result = validate(archive)
        with closing(sqlite3.connect(database)) as conn:
            row = conn.execute(
                "SELECT request_id,owner_json,sha256,size,media_type "
                "FROM research_local_source_owners LIMIT 1"
            ).fetchone()
        original = dict(
            zip(("request_id", "owner_json", "sha256", "size", "media_type"), row, strict=True)
        )
        source_snapshots.source_path(database, original).write_bytes(b"Changed during export")
        return result

    monkeypatch.setattr(bundle, "_validated", changed)
    with pytest.raises(ValueError, match="Lineage original ownership changed"):
        bundle.export("lineage", output)
    assert output.read_bytes() == previous


def test_existing_science_requires_explicit_replacement_and_retains_displaced_row(shared):
    path, database, _originals, rows = shared
    old = dict(rows[0])
    old["written_at"] = "2026-11-12T00:00:00+00:00"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(lineage_sets.SCHEMA)
        conn.execute(
            "INSERT INTO paper_lineage_sets VALUES(?,?,?,?,?,?)",
            [old[key] for key in lineage_sets.COLUMNS.split()],
        )
    before = dump(database)
    with pytest.raises(ValueError, match="conflicts with saved research"):
        bundle.import_(path, pdfs=False)
    assert dump(database) == before
    assert bundle.import_(path, replace=True, pdfs=False)["lineage_reports"] == 1
    with closing(sqlite3.connect(database)) as conn:
        action = json.loads(
            conn.execute("SELECT body_json FROM research_lineage_imports").fetchone()[0]
        )
    assert json.loads(action["records"][0]["before_json"]) == old
    assert lineage_sets.saved(database, "focal") == rows


def test_completed_public_import_cannot_replay_over_a_later_local_edit(shared):
    path, database, _originals, _rows = shared
    bundle.import_(path, pdfs=False)
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("UPDATE paper_lineage_sets SET written_at='2026-11-13T00:00:00+00:00'")
    before = dump(database)
    with pytest.raises(ValueError, match="request was reused"):
        bundle.import_(path, pdfs=False)
    assert dump(database) == before


def test_workspace_switch_during_import_preserves_both_databases(shared, monkeypatch, tmp_path):
    path, database, _originals, _rows = shared
    other = tmp_path / "other" / "papers.db"
    other.parent.mkdir()
    with closing(sqlite3.connect(other)) as conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        conn.commit()
    before, before_other = dump(database), dump(other)
    check = bundle._check_workspace_aliases
    switched = False

    def switch(conn, owners):
        nonlocal switched
        check(conn, owners)
        if not switched:
            switched = True
            monkeypatch.setattr(store, "DB_PATH", other)

    monkeypatch.setattr(bundle, "_check_workspace_aliases", switch)
    with pytest.raises(ValueError, match="another database"):
        bundle.import_(path, pdfs=False)
    assert dump(database) == before
    assert dump(other) == before_other


@pytest.mark.parametrize("owner", ["focal", "prior"])
@pytest.mark.parametrize("change", ["title", "doi"])
def test_same_id_different_paper_requires_review_even_with_replacement(shared, owner, change):
    path, database, _originals, _rows = shared
    title = {"focal": "Focal Study", "prior": "Prior Study"}[owner]
    doi = "10.0000/" + owner
    if change == "title":
        title = "A different research paper"
    else:
        doi = "10.0000/a-different-paper"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            "INSERT INTO papers(id,title,title_key,doi,venue,year,source) "
            "VALUES(?,?,?,?,'Fixture',2026,'fixture')",
            (owner, title, owner, doi),
        )
    before = dump(database)
    with pytest.raises(ValueError, match="ID collision.*reviewed mapping"):
        bundle.import_(path, replace=True, pdfs=False)
    assert dump(database) == before


def test_compatible_existing_peer_keeps_its_local_notes_and_native_epoch(shared):
    from paper_daily.research_lifecycle import ensure_lifecycle, parent_lifecycle

    path, database, originals, rows = shared
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
        conn.execute(
            "INSERT INTO papers(id,title,title_key,doi,venue,year,source) "
            "VALUES('prior','Prior Study','prior','https://doi.org/10.0000/prior',"
            "'Fixture',2026,'fixture')"
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) VALUES('prior','My note','fixture')"
        )
        epoch = parent_lifecycle(conn, "paper", "prior")
    bundle.import_(path, pdfs=False)
    with closing(sqlite3.connect(database)) as conn:
        assert parent_lifecycle(conn, "paper", "prior") == epoch
        assert conn.execute("SELECT body FROM notes WHERE paper_id='prior'").fetchall() == [
            ("My note",)
        ]
    assert_originals(database, rows, originals)
