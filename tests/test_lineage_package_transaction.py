"""Fresh paper mappings stay inside their real caller transaction; no source grant."""

import sqlite3
import zipfile
from contextlib import closing
from dataclasses import replace

import pytest
from lineage_package_fixture import copy_archive
from lineage_package_fixture import lineage_archive as lineage_archive
from test_lineage_jobs import work

from paper_daily import lineage_package_targets as targets
from paper_daily import research_evidence, research_generation, store
from paper_daily.research_lifecycle import ensure_lifecycle, parent_lifecycle


@pytest.fixture
def fresh(lineage_archive, tmp_path):
    path = tmp_path / "source.zip"
    manifest, tables = copy_archive(lineage_archive, path)
    papers = tables["papers"] + tables["cited_papers"]
    with zipfile.ZipFile(path) as archive:
        verified = work(targets.validate, archive, manifest, tables)
    receiver = tmp_path / "empty.sqlite"
    with closing(sqlite3.connect(receiver)) as conn:
        conn.executescript(store.SCHEMA)
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
        conn.commit()
    mapping = {p["id"]: "new-" + p["id"] for p in papers}
    native = research_generation._identity(receiver)
    return receiver, native, papers, mapping, verified


def seed_in(conn, papers, mapping):
    for paper in papers:
        values = dict(paper, id=mapping[paper["id"]])
        fields = list(values)
        conn.execute(
            "INSERT INTO papers("
            + ",".join(fields)
            + ") VALUES("
            + ",".join("?" for _ in fields)
            + ")",
            [values[k] for k in fields],
        )


def apply(fresh, *, rollback=False):
    database, native, papers, mapping, verified = fresh
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        seed_in(conn, papers, mapping)
        conn.execute(
            "INSERT INTO lists(id,name,created_at) VALUES('fixture-list','Reading','2026-11-13')"
        )
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
            "VALUES('fixture-list','new-focal',0,'2026-11-13')"
        )
        prepared = targets.observe_in(conn, verified, mapping, expected_native=native)
        assert targets.check_in(conn, prepared) == prepared.rows
        assert prepared.rows[0]["paper_id"] == "new-focal"
        assert {b["id"] for b in targets.checked(prepared)["observed"]["papers"]} == set(
            mapping.values()
        )
        with closing(sqlite3.connect(database)) as outside:
            assert outside.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
            assert outside.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 0
        assert conn.in_transaction
        if rollback:
            conn.rollback()
        else:
            conn.commit()
    return prepared


def test_new_papers_and_list_are_observed_without_an_intermediate_commit(fresh, monkeypatch):
    monkeypatch.setattr(
        research_evidence, "_extract", lambda *_a, **_k: pytest.fail("No PDF parsing under SQL")
    )
    prepared = work(apply, fresh)
    with closing(sqlite3.connect(fresh[0])) as conn:
        assert conn.execute("SELECT id FROM papers ORDER BY id").fetchall() == [
            ("new-focal",),
            ("new-later",),
            ("new-prior",),
        ]
        assert conn.execute("SELECT paper_id FROM list_papers").fetchall() == [("new-focal",)]
        # This phase itself creates no report, source association, AI receipt or outbox.
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not names & {
            "paper_lineage_sets",
            "research_local_source_owners",
            "research_generation_requests",
        }
        conn.execute("BEGIN")
        assert targets.check_in(conn, prepared) == prepared.rows
        conn.rollback()


def test_rollback_discards_all_new_owners_and_invalidates_reused_local_ids(fresh):
    prepared = work(apply, fresh, rollback=True)
    database, _native, papers, mapping, _verified = fresh
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM research_parent_lifecycle").fetchone()[0] == 0
        conn.execute("BEGIN IMMEDIATE")
        seed_in(conn, papers, mapping)
        with pytest.raises(ValueError, match="receiver changed"):
            targets.check_in(conn, prepared)
        assert conn.in_transaction
        conn.rollback()


@pytest.mark.parametrize(
    "bad", ["seal", "bytes", "wrong-proof", "native", "transaction", "cancelled", "bound"]
)
def test_refusal_never_commits_earlier_caller_work(fresh, bad):
    database, native, papers, mapping, verified = fresh

    def run():
        with closing(sqlite3.connect(database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            seed_in(conn, papers, mapping)
            before = list(conn.iterdump())
            prepared = verified
            expected = native

            def cancelled():
                return bad == "cancelled"

            if bad == "seal":
                prepared = replace(verified, _json="{}")
            elif bad == "bytes":
                prepared = replace(verified, _files=((verified.files[0][0], b"changed"),))
            elif bad == "wrong-proof":
                prepared = targets.Targets(verified._json, verified._seal)
            elif bad == "native":
                expected = [-1, native[1]]
            elif bad == "transaction":
                conn.rollback()
            elif bad == "bound":
                conn.execute("CREATE TABLE paperfact_sync_identity(workspace TEXT,device TEXT)")
                conn.execute("INSERT INTO paperfact_sync_identity VALUES('bound','fixture')")
                before = list(conn.iterdump())
            with pytest.raises(ValueError):
                targets.observe_in(
                    conn, prepared, mapping, expected_native=expected, cancelled=cancelled
                )
            if bad != "transaction":
                assert conn.in_transaction and list(conn.iterdump()) == before
            conn.rollback()
        with closing(sqlite3.connect(database)) as check:
            assert check.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0

    work(run)


def test_missing_native_lifetimes_cannot_be_invented_during_observation(fresh):
    database, native, papers, mapping, verified = fresh

    def run():
        with closing(sqlite3.connect(database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            seed_in(conn, papers, mapping)
            conn.execute(
                "UPDATE research_parent_lifecycle SET active=0 WHERE entity_id='new-prior'"
            )
            with pytest.raises(ValueError, match="native paper lifetimes"):
                targets.observe_in(conn, verified, mapping, expected_native=native)
            assert parent_lifecycle(conn, "paper", "new-prior") is None
            conn.rollback()

    work(run)


def test_post_observation_cancel_preserves_uncommitted_papers_for_caller_rollback(
    fresh, monkeypatch
):
    database, native, papers, mapping, verified = fresh
    original = targets._read_in
    done = False

    def after(*args):
        nonlocal done
        data = original(*args)
        done = True
        return data

    monkeypatch.setattr(targets, "_read_in", after)

    def run():
        with closing(sqlite3.connect(database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            seed_in(conn, papers, mapping)
            with pytest.raises(ValueError, match="cancelled"):
                targets.observe_in(
                    conn, verified, mapping, expected_native=native, cancelled=lambda: done
                )
            assert conn.in_transaction
            assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 3
            conn.rollback()

    work(run)


def test_retained_pdf_bytes_are_immutable_and_archive_independent(fresh, monkeypatch):
    import hashlib

    verified = fresh[-1]
    content = targets._validated(verified)
    expected = {r["path"]: r for r in content["sources"]}
    assert len(verified.files) == len(expected) == 3
    for path, data in verified.files:
        assert type(data) is bytes
        assert len(data) == expected[path]["size"]
        assert hashlib.sha256(data).hexdigest() == expected[path]["sha256"]
    # The ZIP is closed and removed before the transaction phase.
    (fresh[0].parent / "source.zip").unlink()
    monkeypatch.setattr(
        research_evidence, "_extract", lambda *_a, **_k: pytest.fail("No PDF parsing under SQL")
    )
    prepared = work(apply, fresh, rollback=True)
    assert prepared.rows[0]["paper_id"] == "new-focal"


def test_byte_retention_rechecks_actual_bytes_after_pdf_validation(
    lineage_archive, monkeypatch, tmp_path
):
    import io

    from paper_daily import lineage_packages

    path = tmp_path / "retention.zip"
    manifest, tables = copy_archive(lineage_archive, path)
    original = lineage_packages.validate_package
    validated = False

    def verify(*args, **kwargs):
        nonlocal validated
        result = original(*args, **kwargs)
        validated = True
        return result

    monkeypatch.setattr(lineage_packages, "validate_package", verify)
    with zipfile.ZipFile(path) as archive:
        opened = archive.open

        def changed(name, *args, **kwargs):
            if validated and isinstance(name, str) and name.startswith("files/"):
                return io.BytesIO(b"different bytes after actual PDF verification")
            return opened(name, *args, **kwargs)

        monkeypatch.setattr(archive, "open", changed)
        with pytest.raises(ValueError, match="changed before byte retention"):
            work(targets.validate, archive, manifest, tables)


def test_empty_package_and_early_cancel_do_not_create_receiver_state(tmp_path):
    import json

    path = tmp_path / "empty.zip"
    manifest = {"format": 2, "capabilities": [], "pdfs_included": True, "file_hashes": {}}
    tables = {"papers": [], "cited_papers": []}
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("tables.json", json.dumps(tables))
    with zipfile.ZipFile(path) as archive:
        verified = work(targets.validate, archive, manifest, tables)
    assert verified.files == ()
    database = tmp_path / "empty.sqlite"
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript(store.SCHEMA)
    native = research_generation._identity(database)

    def run():
        with closing(sqlite3.connect(database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            assert targets.observe_in(conn, verified, {}, expected_native=native) is None
            assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
            assert conn.in_transaction
            conn.rollback()

    work(run)
    with pytest.raises(ValueError, match="cancelled"):
        work(targets.validate, None, {}, {}, cancelled=lambda: True)


def test_existing_and_new_paper_owners_share_one_transaction_without_recreating_existing(fresh):
    database, native, papers, mapping, verified = fresh

    def run():
        with closing(sqlite3.connect(database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            seed_in(conn, [p for p in papers if p["id"] == "prior"], mapping)
            conn.commit()
            old_parent = parent_lifecycle(conn, "paper", "new-prior")
            conn.execute("BEGIN IMMEDIATE")
            seed_in(conn, [p for p in papers if p["id"] != "prior"], mapping)
            prepared = targets.observe_in(conn, verified, mapping, expected_native=native)
            assert targets.check_in(conn, prepared) == prepared.rows
            assert parent_lifecycle(conn, "paper", "new-prior") == old_parent
            with closing(sqlite3.connect(database)) as outside:
                assert outside.execute("SELECT id FROM papers").fetchall() == [("new-prior",)]
            conn.rollback()
            assert conn.execute("SELECT id FROM papers").fetchall() == [("new-prior",)]
            assert parent_lifecycle(conn, "paper", "new-prior") == old_parent
            conn.execute("BEGIN")
            with pytest.raises(ValueError, match="receiver paper is missing"):
                targets.check_in(conn, prepared)
            conn.rollback()

    work(run)
