"""Real unenrolled proposal catalog, native ownership and caller-owned import atomicity."""

import copy
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing

import pytest
from test_local_blob_binding import no_external as no_external
from test_portable_deck_proposal import scientific as scientific

from paper_daily import local_deck_proposals as proposals
from paper_daily import portable_deck_proposal as codec
from paper_daily import presentations, store
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.sync_blobs import BlobStore


def native(path):
    info = path.stat()
    return info.st_dev, info.st_ino


@pytest.fixture
def local(tmp_path, monkeypatch, scientific):
    database = tmp_path / "papers.sqlite"
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        store.upsert_papers(
            conn,
            [
                dict(
                    id="local-paper",
                    title="Local receiver",
                    venue="Fixture",
                    year=2026,
                    source="fixture",
                )
            ],
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,kind,created_at) "
            "VALUES('local-paper','Preserve prior note','note','2026-11-01')"
        )
        conn.commit()
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(presentations, "DECK_DIR", tmp_path / "decks")
    old = copy.deepcopy(scientific[0])
    old.paper_id = "local-paper"
    old.title = "Prior saved deck"
    old._revision_figures = scientific[2]
    saved = presentations.save_deck(old)
    manifest, blobs = codec.encode(*scientific[:4], source_document_hash=scientific[4])
    return database, manifest, blobs, saved, saved.read_bytes()


def prepared(local, *, request="intent-one", paper="local-paper", **kwargs):
    database, manifest, blobs, _saved, _before = local
    return proposals.prepare(
        database,
        paper,
        manifest,
        lambda row: blobs[row["sha256"]],
        request_id=request,
        expected_native=native(database),
        **kwargs,
    )


def rows(database):
    with closing(sqlite3.connect(database)) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (proposals.TABLE,)
        ).fetchone():
            return []
        return conn.execute(
            "SELECT proposal_id FROM " + proposals.TABLE + " ORDER BY proposal_id"
        ).fetchall()


def prior_unchanged(local):
    database, _manifest, _blobs, saved, before = local
    assert saved.read_bytes() == before
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT body FROM notes WHERE paper_id='local-paper'").fetchall() == [
            ("Preserve prior note",)
        ]
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert "research_sync_binding" not in names and "paperfact_sync_identity" not in names


def test_explicit_local_prepare_retain_restart_read_is_complete_and_never_activates(
    local, scientific
):
    database, manifest, blobs, _saved, _before = local
    job = prepared(local)
    assert rows(database) == [] and not job.expected_absent
    proposal = proposals.retain(job)
    assert proposal == job.proposal_id and rows(database) == [(proposal,)]
    assert proposals.retain(job) == proposal
    repeated = prepared(local)
    assert proposals.retain(repeated) == proposal and rows(database) == [(proposal,)]
    before = database.read_bytes()
    value = proposals.read(database, proposal, expected_native=native(database))
    assert value.current_parent and value.native_current()
    assert value.content["image_bytes"] == scientific[2]
    assert value.content["original_bytes"] == scientific[3]
    assert value.content["evidence"]["figures"][-1]["caption"] == "Full unused caption"
    assert value.content["source_document_hash"] == scientific[4]
    assert all(
        path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == path.name
        for path, _v in value.witnesses
    )
    value.content["deck"]["title"] = "Altered defensive view"
    assert (
        proposals.read(database, proposal, expected_native=native(database)).content["deck"][
            "title"
        ]
        == scientific[0].title
    )
    with closing(sqlite3.connect(database)) as conn:
        assert proposals.assert_current_in(conn, value)
        assert proposals.record(conn, proposal)["paper_id"] == "local-paper"
    assert database.read_bytes() == before
    prior_unchanged(local)


def test_local_storage_preserves_evidence_only_fourth_image(local, scientific):
    import pymupdf

    database, _manifest, _blobs, _saved, _before = local
    deck, evidence, images, originals, sha, _b = scientific
    data = pymupdf.Pixmap(pymupdf.csRGB, 2, 2, b"\x21\x43\x65" * 4, False).tobytes("png")
    images["evidence:only"] = data
    evidence["figures"].append(
        dict(
            id="evidence:only",
            label="Evidence-only",
            caption="Full extra material",
            document_hash=None,
        )
    )
    manifest, blobs = codec.encode(deck, evidence, images, originals, source_document_hash=sha)
    job = prepared((database, manifest, blobs, local[3], local[4]))
    value = proposals.read(database, proposals.retain(job), expected_native=native(database))
    assert value.content["image_bytes"]["evidence:only"] == data
    assert len(value.content["deck"]["figures"]) == 3
    assert value.content["evidence"]["figures"][-1]["caption"] == "Full extra material"
    prior_unchanged(local)


def test_actual_local_parent_recreation_keeps_readonly_content_but_refuses_retention_apply(local):
    database = local[0]
    job = prepared(local)
    identity = proposals.retain(job)
    with closing(sqlite3.connect(database)) as conn, conn:
        before = parent_lifecycle(conn, "paper", "local-paper")
        # Controlled local SQL repair, no claim of supported graph deletion.
        conn.execute("DELETE FROM papers WHERE id='local-paper'")
        store.upsert_papers(
            conn,
            [
                dict(
                    id="local-paper",
                    title="New local incarnation",
                    year=2026,
                    source="fixture",
                    venue="Fixture",
                )
            ],
        )
        assert parent_lifecycle(conn, "paper", "local-paper") != before
    preview = proposals.read(database, identity, expected_native=native(database))
    assert not preview.current_parent and preview.content["image_bytes"]
    with closing(sqlite3.connect(database)) as conn, pytest.raises(ValueError):
        proposals.assert_current_in(conn, preview)
    with pytest.raises(ValueError):
        proposals.retain(job)
    assert rows(database) == [(identity,)]


def test_request_identity_refuses_changed_content_or_target(local):
    database, manifest, blobs, saved, before = local
    original = prepared(local)
    proposals.retain(original)
    with closing(sqlite3.connect(database)) as conn, conn:
        store.upsert_papers(
            conn, [dict(id="other", title="Other", venue="Fixture", year=2026, source="fixture")]
        )
    with pytest.raises(ValueError):
        proposals.retain(prepared(local, paper="other"))
    raw = json.loads(blobs[manifest["research"]["sha256"]])
    raw["deck"]["title"] = "Another proposal"
    changed = dict(manifest)
    value = codec.canonical_json(raw)
    changed["research"] = codec.descriptor(value, "application/json")
    new = prepared(
        (database, changed, {**blobs, changed["research"]["sha256"]: value}, saved, before)
    )
    with pytest.raises(ValueError):
        proposals.retain(new)
    assert rows(database) == [(original.proposal_id,)]
    prior_unchanged(local)


def test_caller_transaction_adoption_never_commits_and_rollback_removes_only_new_state(local):
    database = local[0]
    job = prepared(local)
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO notes(paper_id,body,kind,created_at) "
            "VALUES('local-paper','Caller pending note','note','fixture')"
        )
        assert proposals.adopt_in(conn, job) == job.proposal_id
        assert conn.in_transaction and rows(database) == []
        conn.rollback()
    assert rows(database) == []
    assert proposals.retain(job) == job.proposal_id
    prior_unchanged(local)


def test_new_target_requires_real_before_insert_grant_and_is_retry_safe(local):
    database = local[0]
    with pytest.raises(ValueError):
        prepared(local, paper="missing")
    job = prepared(local, paper="new-paper", allow_absent=True)
    assert job.expected_absent
    with pytest.raises(ValueError):
        proposals.retain(job)
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with proposals.import_targets_in(conn, [job]) as grant:
            store.upsert_papers(
                conn,
                [
                    dict(
                        id="new-paper",
                        title="Explicit imported receiver",
                        venue="Fixture",
                        year=2026,
                        source="fixture",
                    )
                ],
            )
            assert grant.adopt() == [job.proposal_id]
            assert grant.adopt() == [job.proposal_id]
            assert rows(database) == [] and conn.in_transaction
        with pytest.raises(ValueError):
            grant.adopt()
        assert conn.in_transaction
        conn.commit()
    assert proposals.retain(job) == job.proposal_id
    value = proposals.read(database, job.proposal_id, expected_native=native(database))
    assert value.current_parent
    record = value.record
    assert json.loads(record["captured_json"])["paper"] is None
    assert json.loads(record["owner_json"])["paper"]["title"] == "Explicit imported receiver"
    prior_unchanged(local)


@pytest.mark.parametrize(
    "change", ["appeared", "replaced", "cancelled", "not-adopted", "late-parent-change"]
)
def test_import_grant_refuses_stale_absence_and_rolls_back_caller_scope(local, change):
    database = local[0]
    alive = [True]
    job = prepared(local, paper="new-paper", allow_absent=True)
    if change == "appeared":
        with closing(sqlite3.connect(database)) as conn, conn:
            store.upsert_papers(
                conn,
                [
                    dict(
                        id="new-paper",
                        title="External row",
                        venue="Fixture",
                        year=2026,
                        source="fixture",
                    )
                ],
            )
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO notes(paper_id,body,kind,created_at) "
            "VALUES('local-paper','Outer pending note','note','fixture')"
        )
        with (
            pytest.raises(ValueError),
            proposals.import_targets_in(conn, [job], current=lambda: alive[0]) as grant,
        ):
            store.upsert_papers(
                conn,
                [
                    dict(
                        id="new-paper",
                        title="Imported row",
                        venue="Fixture",
                        year=2026,
                        source="fixture",
                    )
                ],
            )
            if change == "replaced":
                conn.execute("DELETE FROM papers WHERE id='local-paper'")
                alive[0] = False
            if change != "not-adopted":
                grant.adopt()
            if change == "cancelled":
                alive[0] = False
            if change == "late-parent-change":
                conn.execute(
                    "UPDATE papers SET title='Changed after adoption' WHERE id='new-paper'"
                )
        assert conn.in_transaction
        assert (
            conn.execute("SELECT COUNT(*) FROM notes WHERE body='Outer pending note'").fetchone()[0]
            == 1
        )
        found = conn.execute("SELECT title FROM papers WHERE id='new-paper'").fetchone()
        assert found == (("External row",) if change == "appeared" else None)
        conn.rollback()
    assert rows(database) == []
    prior_unchanged(local)


@pytest.mark.parametrize(
    "marker",
    [
        "research_sync_binding",
        "paperfact_sync_identity",
        "research_capture_binding",
        "recovery_identity",
    ],
)
def test_present_empty_partial_or_enrolled_marker_never_opts_out_to_local_mode(local, marker):
    database = local[0]
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("CREATE TABLE " + marker + "(incomplete TEXT)")
    before = database.read_bytes()
    with pytest.raises(ValueError):
        prepared(local)
    assert database.read_bytes() == before and rows(database) == []


@pytest.mark.parametrize("phase", ["immediate", "reader", "begin", "append", "finalize"])
def test_cancellation_retains_no_catalog_or_active_research(local, monkeypatch, phase):
    database, manifest, blobs, _saved, _before = local
    alive = [phase != "immediate"]

    def read(row):
        return blobs[row["sha256"]]

    if phase == "reader":

        def read(row):
            alive[0] = False
            return blobs[row["sha256"]]

    if phase in {"begin", "append", "finalize"}:
        original = getattr(BlobStore, phase)

        def cancelled(self, *args, **kwargs):
            value = original(self, *args, **kwargs)
            alive[0] = False
            return value

        monkeypatch.setattr(BlobStore, phase, cancelled)
    with pytest.raises(ValueError):
        proposals.prepare(
            database,
            "local-paper",
            manifest,
            read,
            request_id="cancel",
            expected_native=native(database),
            current=lambda: alive[0],
        )
    assert rows(database) == []
    prior_unchanged(local)


@pytest.mark.parametrize("operation", ["begin", "append", "finalize"])
def test_real_blob_failure_has_no_catalog_authority_and_exact_retry_works(
    local, monkeypatch, operation
):
    database = local[0]

    def fail(*_args, **_kwargs):
        raise OSError("Synthetic local CAS failure")

    with monkeypatch.context() as m:
        m.setattr(BlobStore, operation, fail)
        with pytest.raises(OSError):
            prepared(local)
    assert rows(database) == []
    job = prepared(local)
    assert proposals.retain(job) == job.proposal_id
    assert rows(database) == [(job.proposal_id,)]
    prior_unchanged(local)


def test_sql_denial_rolls_back_catalog_and_preserves_prior_caller_research(local):
    database = local[0]
    job = prepared(local)
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            "CREATE TRIGGER block_proposals BEFORE INSERT ON "
            + proposals.TABLE
            + " BEGIN SELECT RAISE(ABORT,'fixture denial'); END"
        )
    with pytest.raises(ValueError):
        proposals.retain(job)
    assert rows(database) == []
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("DROP TRIGGER block_proposals")
    assert proposals.retain(job) == job.proposal_id
    prior_unchanged(local)


@pytest.mark.parametrize("target", ["pdf", "index", "root"])
def test_native_cas_or_source_change_refuses_adoption_and_preview(local, monkeypatch, target):
    database = local[0]
    job = prepared(local)
    data = job.data
    root = proposals._root(database, native(database))
    if target == "pdf":
        row = data["manifest"]["originals"][0]
        path = root / "objects" / row["sha256"]
        path.write_bytes(path.read_bytes() + b"changed")
    elif target == "index":
        path = root / "index.sqlite"
        other = root / "new-index.sqlite"
        shutil.copyfile(path, other)
        old = native(path)
        os.replace(other, path)
        assert native(path) != old
    else:
        previous = root.with_name("old-blobs")
        root.rename(previous)
        root.mkdir()
    with pytest.raises((ValueError, OSError)):
        proposals.retain(job)
    assert rows(database) == []
    prior_unchanged(local)


def test_actual_database_replacement_between_capture_and_staging_is_not_adopted(local, monkeypatch):
    database = local[0]
    old = native(database)
    real = codec.decode
    acted = []

    def changed(*args, **kwargs):
        result = real(*args, **kwargs)
        if not acted:
            acted.append(True)
            replacement = database.with_name("new.sqlite")
            shutil.copyfile(database, replacement)
            os.replace(replacement, database)
            assert native(database) != old
        return result

    monkeypatch.setattr(codec, "decode", changed)
    with pytest.raises(ValueError):
        prepared(local)
    assert acted and rows(database) == []


def test_readonly_catalog_access_does_not_create_schema_and_native_preview_has_no_sql(
    local, monkeypatch
):
    database = local[0]
    before = database.read_bytes()
    with closing(sqlite3.connect(database)) as conn:
        assert proposals.record(conn, "missing") is None
    assert database.read_bytes() == before
    job = prepared(local)
    identity = proposals.retain(job)
    preview = proposals.read(database, identity, expected_native=native(database))

    def deny(*_args, **_kwargs):
        raise AssertionError("Metadata-only witness attempted SQL")

    monkeypatch.setattr(proposals, "_connect", deny)
    assert preview.native_current() and preview.content["image_bytes"]


def test_catalog_bounds_and_unknown_schema_refuse_without_weakening_old_data(local, monkeypatch):
    database = local[0]
    first = prepared(local)
    proposals.retain(first)
    second = prepared(local, request="two")
    monkeypatch.setattr(proposals, "MAX_RECORDS", 1)
    with pytest.raises(ValueError, match="capacity"):
        proposals.retain(second)
    assert rows(database) == [(first.proposal_id,)]
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("ALTER TABLE " + proposals.TABLE + " ADD COLUMN unknown TEXT")
    before = database.read_bytes()
    with pytest.raises(ValueError):
        prepared(local, request="three")
    assert database.read_bytes() == before


def test_manifest_and_preparation_are_immutable_across_reader_callback(local):
    database, manifest, blobs, saved, before = local
    expected = copy.deepcopy(manifest)
    acted = []

    def reader(row):
        if not acted:
            acted.append(True)
            manifest["source_document_hash"] = None
        return blobs[row["sha256"]]

    job = proposals.prepare(
        database,
        "local-paper",
        manifest,
        reader,
        request_id="immutable",
        expected_native=native(database),
    )
    assert job.manifest == expected
    job.data["captured"]["paper_id"] = "altered"
    assert proposals.retain(job) == job.proposal_id
    assert (
        proposals.read(database, job.proposal_id, expected_native=native(database)).content[
            "source_document_hash"
        ]
        == expected["source_document_hash"]
    )
    assert saved.read_bytes() == before


def test_actual_sql_authorizer_denial_rolls_back_only_proposal_adoption(local):
    database = local[0]
    job = prepared(local)
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO notes(paper_id,body,kind,created_at) VALUES(?,?,?,?)",
            ("local-paper", "Caller work before refused proposal", "note", "fixture"),
        )

        def authorize(action, first, _second, _db, _trigger):
            return (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and first == proposals.TABLE
                else sqlite3.SQLITE_OK
            )

        conn.set_authorizer(authorize)
        with pytest.raises(sqlite3.DatabaseError):
            proposals.adopt_in(conn, job)
        conn.set_authorizer(None)
        assert conn.in_transaction
        assert conn.execute("SELECT COUNT(*) FROM " + proposals.TABLE).fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM notes WHERE body='Caller work before refused proposal'"
            ).fetchone()[0]
            == 1
        )
        conn.rollback()
    assert rows(database) == []
    assert proposals.retain(job) == job.proposal_id
    prior_unchanged(local)


def test_actual_reparse_cas_root_refuses_old_proposal_without_following_bytes(local):
    database = local[0]
    job = prepared(local)
    identity = proposals.retain(job)
    root = proposals._root(database, native(database))
    moved = root.with_name("retained-original-root")
    root.rename(moved)
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(moved), str(root))
    else:
        root.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError):
        proposals.read(database, identity, expected_native=native(database))
    with pytest.raises(ValueError):
        proposals.retain(job)
    assert rows(database) == [(identity,)]
    prior_unchanged(local)


def test_retained_same_lifetime_rename_remains_reviewable_with_fresh_display_scope(local):
    database = local[0]
    job = prepared(local)
    identity = proposals.retain(job)
    with closing(sqlite3.connect(database)) as conn, conn:
        token = parent_lifecycle(conn, "paper", "local-paper")
        store.upsert_papers(
            conn,
            [
                dict(
                    id="local-paper",
                    title="Ordinary renamed study",
                    venue="Fixture",
                    year=2026,
                    source="fixture",
                )
            ],
        )
        assert parent_lifecycle(conn, "paper", "local-paper") == token
    preview = proposals.read(database, identity, expected_native=native(database))
    assert preview.current_parent
    with closing(sqlite3.connect(database)) as conn:
        assert proposals.assert_current_in(conn, preview)
    assert preview.content["deck"]["paper_title"] != "Ordinary renamed study"
    assert proposals.retain(job) == identity


def test_pending_preparation_cannot_adopt_a_newly_renamed_row_without_fresh_review(local):
    database = local[0]
    job = prepared(local)
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            "UPDATE papers SET title='Changed during pending preparation' WHERE id='local-paper'"
        )
    with pytest.raises(ValueError):
        proposals.retain(job)
    assert rows(database) == []
    prior_unchanged(local)


def test_confirmed_import_updates_same_epoch_metadata_without_relabeling_source(local):
    database = local[0]
    job = prepared(local)
    before = job.data["captured"]
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with proposals.import_targets_in(conn, [job], allow_updates=True) as grant:
            conn.execute(
                "UPDATE papers SET title='Confirmed imported metadata' WHERE id='local-paper'"
            )
            assert grant.adopt() == [job.proposal_id]
            saved = proposals.record(conn, job.proposal_id)
            assert json.loads(saved["captured_json"])["paper"] == before["paper"]
            assert (
                json.loads(saved["owner_json"])["paper"]["title"] == "Confirmed imported metadata"
            )
            assert json.loads(saved["owner_json"])["parent_token"] == before["parent_token"]
            assert rows(database) == [] and conn.in_transaction
        conn.commit()
    preview = proposals.read(database, job.proposal_id, expected_native=native(database))
    assert (
        preview.current_parent
        and preview.content["deck"]["paper_title"] != "Confirmed imported metadata"
    )
    assert rows(database) == [(job.proposal_id,)]
    prior_unchanged(local)


def test_confirmed_import_update_rollback_and_exact_prepared_retry(local):
    database = local[0]
    job = prepared(local)
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with (
            pytest.raises(OSError),
            proposals.import_targets_in(conn, [job], allow_updates=True) as grant,
        ):
            conn.execute(
                "UPDATE papers SET title='Rollback this imported metadata' WHERE id='local-paper'"
            )
            grant.adopt()
            raise OSError("Controlled failure after actual catalog insert")
        assert conn.in_transaction
        assert (
            conn.execute("SELECT title FROM papers WHERE id='local-paper'").fetchone()[0]
            == "Local receiver"
        )
        assert conn.execute("SELECT COUNT(*) FROM " + proposals.TABLE).fetchone()[0] == 0
        with proposals.import_targets_in(conn, [job], allow_updates=True) as retry:
            conn.execute(
                "UPDATE papers SET title='Successful retry metadata' WHERE id='local-paper'"
            )
            assert retry.adopt() == [job.proposal_id]
        conn.commit()
    assert rows(database) == [(job.proposal_id,)]
    prior_unchanged(local)


def test_import_update_flag_never_refreshes_a_row_changed_before_entry(local):
    database = local[0]
    job = prepared(local)
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            "UPDATE papers SET title='Changed before grant admission' WHERE id='local-paper'"
        )
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with (
            pytest.raises(ValueError),
            proposals.import_targets_in(conn, [job], allow_updates=True),
        ):
            pytest.fail("Stale prepared row must refuse before caller paper SQL")
        assert (
            conn.in_transaction
            and conn.execute("SELECT COUNT(*) FROM " + proposals.TABLE).fetchone()[0] == 0
        )
        conn.rollback()
    with pytest.raises(ValueError):
        proposals.retain(job)
    assert rows(database) == []
    prior_unchanged(local)


def test_import_update_flag_cannot_adopt_delete_recreated_parent(local):
    database = local[0]
    job = prepared(local)
    old = job.data["captured"]["parent_token"]
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with (
            pytest.raises(ValueError),
            proposals.import_targets_in(conn, [job], allow_updates=True) as grant,
        ):
            # Real local DELETE/INSERT repair, not invented protocol REPLACE behavior.
            conn.execute("DELETE FROM papers WHERE id='local-paper'")
            store.upsert_papers(
                conn,
                [
                    dict(
                        id="local-paper",
                        title="Another lifetime",
                        venue="Fixture",
                        year=2026,
                        source="fixture",
                    )
                ],
            )
            assert parent_lifecycle(conn, "paper", "local-paper") != old
            grant.adopt()
        assert parent_lifecycle(conn, "paper", "local-paper") == old
        assert (
            conn.execute("SELECT title FROM papers WHERE id='local-paper'").fetchone()[0]
            == "Local receiver"
        )
        conn.rollback()
    assert rows(database) == []
    prior_unchanged(local)


def test_default_import_and_standalone_adoption_keep_exact_prepared_row_guard(local):
    database = local[0]
    job = prepared(local)
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with (
            pytest.raises(ValueError),
            proposals.import_targets_in(conn, [job], allow_updates=False) as grant,
        ):
            conn.execute("UPDATE papers SET title='Not explicitly allowed' WHERE id='local-paper'")
            grant.adopt()
        assert (
            conn.execute("SELECT title FROM papers WHERE id='local-paper'").fetchone()[0]
            == "Local receiver"
        )
        conn.execute("UPDATE papers SET title='Standalone still strict' WHERE id='local-paper'")
        with pytest.raises(ValueError):
            proposals.adopt_in(conn, job)
        assert conn.execute("SELECT COUNT(*) FROM " + proposals.TABLE).fetchone()[0] == 0
        conn.rollback()
    assert rows(database) == []
    prior_unchanged(local)


def test_owned_published_replay_is_epoch_bound_and_keeps_original_catalog_metadata(local):
    database = local[0]
    job = prepared(local)
    proposals.retain(job)
    with closing(sqlite3.connect(database)) as conn:
        before = proposals.record(conn, job.proposal_id)
        conn.execute("BEGIN IMMEDIATE")
        with proposals.import_targets_in(conn, [job], allow_updates=True) as grant:
            conn.execute(
                "UPDATE papers SET title='New same-lifetime import metadata' WHERE id='local-paper'"
            )
            assert grant.adopt() == [job.proposal_id]
        assert proposals.record(conn, job.proposal_id) == before
        conn.commit()
    assert proposals.read(
        database, job.proposal_id, expected_native=native(database)
    ).current_parent
    assert rows(database) == [(job.proposal_id,)]
    prior_unchanged(local)


@pytest.mark.parametrize("value", [None, 1, "yes"])
def test_import_metadata_update_override_is_explicit_boolean(local, value):
    database = local[0]
    job = prepared(local)
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with (
            pytest.raises(ValueError),
            proposals.import_targets_in(conn, [job], allow_updates=value),
        ):
            pytest.fail("Nonboolean option must not admit caller SQL")
        assert conn.in_transaction and rows(database) == []
        conn.rollback()


def test_allowed_import_still_rejects_metadata_changed_after_its_adopt_boundary(local):
    database = local[0]
    job = prepared(local)
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with (
            pytest.raises(ValueError),
            proposals.import_targets_in(conn, [job], allow_updates=True) as grant,
        ):
            conn.execute("UPDATE papers SET title='Reviewed import update' WHERE id='local-paper'")
            grant.adopt()
            conn.execute("UPDATE papers SET title='Unexpected later update' WHERE id='local-paper'")
        assert conn.execute("SELECT COUNT(*) FROM " + proposals.TABLE).fetchone()[0] == 0
        assert (
            conn.execute("SELECT title FROM papers WHERE id='local-paper'").fetchone()[0]
            == "Local receiver"
        )
        conn.rollback()
    prior_unchanged(local)


def test_allow_updates_preserves_real_observed_absence_for_new_target_import(local):
    database = local[0]
    fresh = prepared(
        local, paper="new-with-update-option", request="fresh-with-option", allow_absent=True
    )
    stale = prepared(
        local, paper="appeared-after-capture", request="stale-with-option", allow_absent=True
    )
    with closing(sqlite3.connect(database)) as conn, conn:
        store.upsert_papers(
            conn,
            [
                dict(
                    id="appeared-after-capture",
                    title="External row",
                    venue="Fixture",
                    year=2026,
                    source="fixture",
                )
            ],
        )
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with (
            pytest.raises(ValueError),
            proposals.import_targets_in(conn, [stale], allow_updates=True),
        ):
            pytest.fail(
                "allow_updates must not grant a parent observed absent "
                "before another actor created it"
            )
        with proposals.import_targets_in(conn, [fresh], allow_updates=True) as grant:
            store.upsert_papers(
                conn,
                [
                    dict(
                        id="new-with-update-option",
                        title="New explicit receiver",
                        venue="Fixture",
                        year=2026,
                        source="fixture",
                    )
                ],
            )
            assert grant.adopt() == [fresh.proposal_id]
            record = proposals.record(conn, fresh.proposal_id)
            assert json.loads(record["captured_json"])["paper"] is None
            assert json.loads(record["owner_json"])["parent_token"] == parent_lifecycle(
                conn, "paper", "new-with-update-option"
            )
        conn.commit()
    assert rows(database) == [(fresh.proposal_id,)]
    prior_unchanged(local)
