"""Actual ZIP-to-receiver remapping and stale-target checks; no import grants."""

import shutil
import sqlite3
import zipfile
from contextlib import closing
from dataclasses import replace

import pytest
from lineage_package_fixture import copy_archive
from lineage_package_fixture import lineage_archive as lineage_archive
from test_lineage_jobs import work

from paper_daily import lineage_package_targets as targets
from paper_daily import lineage_sets, store
from paper_daily.research_lifecycle import ensure_lifecycle


@pytest.fixture
def incoming(lineage_archive, tmp_path):
    path = tmp_path / "sender.zip"
    manifest, tables = copy_archive(lineage_archive, path)
    papers = tables["papers"] + tables["cited_papers"]
    receiver = tmp_path / "receiver.sqlite"
    mapping = {p["id"]: "receiver-" + p["id"] for p in papers}
    with closing(sqlite3.connect(receiver)) as conn:
        conn.executescript(store.SCHEMA)
        conn.execute("BEGIN IMMEDIATE")
        for paper in papers:
            fields = list(paper)
            row = dict(paper, id=mapping[paper["id"]])
            conn.execute(
                "INSERT INTO papers("
                + ",".join(fields)
                + ") VALUES("
                + ",".join("?" for _ in fields)
                + ")",
                [row[k] for k in fields],
            )
        ensure_lifecycle(conn)
        conn.commit()
    return receiver, mapping, path, manifest, tables


def observe(incoming, **options):
    database, mapping, path, manifest, tables = incoming
    with zipfile.ZipFile(path) as archive:
        return work(targets.observe, database, archive, manifest, tables, mapping, **options)


def insert(conn, row):
    conn.execute(lineage_sets.SCHEMA)
    conn.execute(
        "INSERT INTO paper_lineage_sets VALUES(?,?,?,?,?,?)",
        [row[k] for k in lineage_sets.COLUMNS.split()],
    )


def test_actual_package_remaps_only_bindings_and_preserves_research_without_writes(incoming):
    database, mapping, _path, manifest, tables = incoming
    before = database.read_bytes()
    observed = observe(incoming)
    row = observed.rows[0]
    original = tables["paper_lineage_sets"][0]
    body = lineage_sets.decode(row["body_json"])
    sender = lineage_sets.decode(original["body_json"])
    assert row["paper_id"] == mapping[original["paper_id"]]
    assert body["report"] == sender["report"]
    assert body["generation"] == sender["generation"]
    assert body["inputs"] == sender["inputs"]
    assert body["corpus_id"] == sender["corpus_id"]
    assert body["bindings"] == [
        dict(b, paper_id=mapping[b["paper_id"]]) for b in sender["bindings"]
    ]
    assert {k: v for k, v in row.items() if k not in ("paper_id", "body_json")} == {
        k: v for k, v in original.items() if k not in ("paper_id", "body_json")
    }
    assert observed.sources == manifest["lineage_sources"]
    assert observed.before == [None] and observed.conflicts == []
    assert database.read_bytes() == before
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE papers SET abstract='unrelated draft' WHERE id='receiver-later'")
        # A changed observed paper must refuse without committing earlier caller work.
        with pytest.raises(ValueError, match="receiver changed"):
            targets.check_in(conn, observed)
        assert conn.in_transaction
        conn.rollback()
        conn.execute("BEGIN IMMEDIATE")
        assert targets.check_in(conn, observed) == observed.rows
        assert targets.check_in(conn, observed) == observed.rows
        conn.execute("UPDATE papers SET abstract='caller draft' WHERE id='receiver-later'")
        conn.rollback()
    assert database.read_bytes() == before
    altered = observed.rows
    altered[0]["paper_id"] = "foreign"
    mutated = observed.paper_map
    mutated["focal"] = "foreign"
    assert observed.rows[0]["paper_id"] == "receiver-focal"
    assert observed.paper_map == mapping
    assert b"caller draft" not in database.read_bytes()


@pytest.mark.parametrize("change", ["missing", "extra", "same-owner", "empty", "wrong-type"])
def test_mapping_must_explicitly_cover_distinct_selected_owners(incoming, change):
    database, mapping, path, manifest, tables = incoming
    if change == "missing":
        mapping.pop("prior")
    elif change == "extra":
        mapping["not-selected"] = "other"
    elif change == "same-owner":
        mapping["later"] = mapping["prior"]
    elif change == "empty":
        mapping["focal"] = ""
    else:
        mapping = list(mapping.items())
    before = database.read_bytes()
    with zipfile.ZipFile(path) as archive, pytest.raises(ValueError):
        work(targets.observe, database, archive, manifest, tables, mapping)
    assert database.read_bytes() == before


@pytest.mark.parametrize("change", ["missing-paper", "no-lifetime", "view", "bound"])
def test_actual_receiver_owners_are_required_before_observation(incoming, change):
    database = incoming[0]
    with closing(sqlite3.connect(database)) as conn, conn:
        if change == "missing-paper":
            conn.execute("DELETE FROM papers WHERE id='receiver-prior'")
        elif change == "no-lifetime":
            conn.execute(
                "UPDATE research_parent_lifecycle SET active=0 WHERE entity_id='receiver-prior'"
            )
        elif change == "view":
            conn.execute(
                "CREATE VIEW paper_lineage_sets AS SELECT "
                + ",".join("NULL AS " + k for k in lineage_sets.COLUMNS.split())
                + " WHERE 0"
            )
        else:
            conn.execute("CREATE TABLE paperfact_sync_identity(workspace TEXT,device TEXT)")
            conn.execute("INSERT INTO paperfact_sync_identity VALUES('bound','device')")
    before = database.read_bytes()
    with pytest.raises(ValueError):
        observe(incoming)
    assert database.read_bytes() == before


@pytest.mark.parametrize("change", ["rename", "delete", "rebirth", "added", "edited", "removed"])
def test_receiver_change_after_observation_refuses_without_touching_current_content(
    incoming, change
):
    database = incoming[0]
    first = observe(incoming)
    if change in ("edited", "removed"):
        with closing(sqlite3.connect(database)) as conn, conn:
            insert(conn, first.rows[0])
    observed = observe(incoming)
    with closing(sqlite3.connect(database)) as conn, conn:
        if change == "rename":
            conn.execute("UPDATE papers SET title='Locally renamed' WHERE id='receiver-prior'")
        elif change == "delete":
            conn.execute("DELETE FROM papers WHERE id='receiver-prior'")
        elif change == "rebirth":
            row = conn.execute("SELECT * FROM papers WHERE id='receiver-prior'").fetchone()
            conn.execute("DELETE FROM papers WHERE id='receiver-prior'")
            conn.execute("INSERT INTO papers VALUES(" + ",".join("?" for _ in row) + ")", row)
        elif change == "added":
            insert(conn, observed.rows[0])
        elif change == "edited":
            conn.execute("UPDATE paper_lineage_sets SET written_at='2026-10-01T00:00:00+00:00'")
        else:
            conn.execute("DELETE FROM paper_lineage_sets")
    with closing(sqlite3.connect(database)) as conn:
        before = list(conn.iterdump())
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError):
            targets.check_in(conn, observed)
        assert conn.in_transaction and list(conn.iterdump()) == before
        conn.rollback()


def test_current_conflicting_row_is_returned_for_review_and_never_replaced(incoming):
    database = incoming[0]
    first = observe(incoming)
    saved = dict(first.rows[0], written_at="2026-10-01T00:00:00+00:00")
    with closing(sqlite3.connect(database)) as conn, conn:
        insert(conn, saved)
    observed = observe(incoming)
    assert observed.before == [saved]
    assert observed.conflicts == [dict(incoming=observed.rows[0], receiver=saved)]
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        targets.check_in(conn, observed)
        assert (
            conn.execute("SELECT written_at FROM paper_lineage_sets").fetchone()[0]
            == saved["written_at"]
        )
        conn.rollback()


def test_native_proof_rejects_forgery_other_database_and_replaced_native_file(incoming, tmp_path):
    database = incoming[0]
    observed = observe(incoming)
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="native observed"):
            targets.check_in(conn, replace(observed, _json="{}"))
        conn.rollback()
        with pytest.raises(ValueError, match="caller transaction"):
            targets.check_in(conn, observed)
    other = tmp_path / "copy.sqlite"
    shutil.copyfile(database, other)
    with closing(sqlite3.connect(other)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="receiver changed"):
            targets.check_in(conn, observed)
        conn.rollback()
    # Handles above are closed; replacement has equal content and different native identity.
    other.replace(database)
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="receiver changed"):
            targets.check_in(conn, observed)
        conn.rollback()


def test_early_and_post_observation_cancellation_leave_no_grants(incoming, monkeypatch):
    database = incoming[0]
    before = database.read_bytes()
    with pytest.raises(ValueError, match="cancelled"):
        observe(incoming, cancelled=lambda: True)
    read = targets._read_in
    done = False

    def cancel_after_observation(*args):
        nonlocal done
        result = read(*args)
        done = True
        return result

    monkeypatch.setattr(targets, "_read_in", cancel_after_observation)
    with pytest.raises(ValueError, match="cancelled"):
        observe(incoming, cancelled=lambda: done)
    assert database.read_bytes() == before
    assert not (database.parent / ".lineage-import").exists()


def test_receiver_metadata_budget_refuses_without_truncation(incoming, monkeypatch):
    from paper_daily import lineage_packages

    # Verification is not bypassed: shrink only after the actual package validator returns.
    verify = lineage_packages.validate_package

    def shrink_after_validation(*args, **kwargs):
        result = verify(*args, **kwargs)
        monkeypatch.setattr(lineage_packages, "MAX_METADATA", 1)
        return result

    monkeypatch.setattr(lineage_packages, "validate_package", shrink_after_validation)
    with pytest.raises(ValueError, match="observation budget"):
        observe(incoming)


def test_caller_mutation_cannot_change_admitted_mapping_or_source_descriptors(
    incoming, monkeypatch
):
    _database, mapping, _path, manifest, _tables = incoming
    expected_map = dict(mapping)
    expected_sources = [dict(r) for r in manifest["lineage_sources"]]
    read = targets._read_in

    def mutate_caller_after_read(*args):
        result = read(*args)
        mapping["focal"] = "foreign-after-observation"
        manifest["lineage_sources"][0]["path"] = "foreign-after-verification.pdf"
        return result

    monkeypatch.setattr(targets, "_read_in", mutate_caller_after_read)
    prepared = observe(incoming)
    assert prepared.paper_map == expected_map
    assert prepared.sources == expected_sources
    assert prepared.rows[0]["paper_id"] == "receiver-focal"
