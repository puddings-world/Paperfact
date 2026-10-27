"""Reader activation resolves exact immutable documents without legacy fallthrough."""

import sqlite3

import pytest
from test_sync_document_research import document, local_blob, pdf_bytes, target
from test_sync_reading_state_research import PAPER, database, save

from paper_daily import document_reader as reader_module
from paper_daily.document_reader import (
    DocumentReader,
    document_current,
    from_workspace,
    register_document_paths,
)
from paper_daily.sync_blobs import BlobManifest, BlobStore
from paper_daily.sync_documents import bind_verified_document, verify_document

LOCAL = "sync:" + PAPER


def prepared(tmp_path, *, managed=True, quota=1024**3):
    path = tmp_path / "research.db"
    journal = database(path)
    store = BlobStore(tmp_path / "blobs")
    legacy, projection = tmp_path / "pdf", tmp_path / "reader-documents"
    legacy.mkdir()
    data = pdf_bytes()
    alias = legacy / (LOCAL.replace(":", "_") + ".pdf")
    alias.write_bytes(data)
    if managed:
        save(journal, document(data))
        local_blob(store, data)
        wanted = target(path)
        verified = verify_document(store, wanted)
        with journal.transaction() as conn:
            assert bind_verified_document(conn, wanted, verified)
    reader = DocumentReader(
        path,
        blob_store=store,
        projection_root=projection,
        legacy_root=legacy,
        projection_quota_bytes=quota,
    )
    return path, journal, store, reader, alias, data


def register(path, journal, store, reader):
    with store._transaction() as conn:
        conn.execute(
            "CREATE TABLE transfer_binding(id INTEGER PRIMARY KEY,workspace,device,research_path)"
        )
        conn.execute(
            "INSERT INTO transfer_binding VALUES(1,'workspace','device',?)", (str(path.resolve()),)
        )
    with journal.transaction() as conn:
        register_document_paths(
            conn,
            workspace_id="workspace",
            blob_root=store.root,
            projection_root=reader.projection_root,
            legacy_root=reader.legacy_root,
        )


def test_managed_exact_binding_gets_owned_pdf_extension_without_mutating_legacy(tmp_path):
    path, journal, store, reader, alias, data = prepared(tmp_path)
    before = alias.read_bytes()
    assert reader.inspect(LOCAL).status == "unchecked"
    result = reader.resolve(LOCAL)
    assert (
        result.available
        and result.managed
        and result.local_id == LOCAL
        and result.paper_id == PAPER
    )
    assert result.path == reader.projection_root / (target(path)["sha256"] + ".pdf")
    assert result.path.read_bytes() == data and result.path != alias
    assert alias.read_bytes() == before
    assert document_current(result)
    stamp = result.path.stat().st_mtime_ns
    repeated = reader.resolve(PAPER, portable=True)
    assert repeated.path == result.path and repeated.path.stat().st_mtime_ns == stamp
    assert len(list(reader.projection_root.glob("*.pdf"))) == 1
    assert not list(reader.projection_root.glob("*.part"))
    assert reader.inspect(LOCAL).available
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name='document_reader_paths'"
            ).fetchone()
            is None
        )


def test_legacy_resolution_remains_explicit_and_does_not_enroll_documents(tmp_path):
    path, _, _, reader, alias, _ = prepared(tmp_path, managed=False)
    result = reader.resolve(LOCAL)
    assert result.available and not result.managed and result.path == alias
    assert result.sha256 and result.target is None and document_current(result)
    assert not reader.projection_root.exists()
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM research_document_desired").fetchone()[0] == 0


@pytest.mark.parametrize("state", ["unbound", "detached", "missing", "invalid", "unconfigured"])
def test_managed_unavailable_never_falls_through_to_existing_legacy_alias(tmp_path, state):
    path, journal, store, reader, alias, data = prepared(tmp_path)
    wanted = target(path)
    if state == "unbound":
        save(journal, document(pdf_bytes("New version"), op_id="new"))
    elif state == "detached":
        save(journal, document(data, op_id="delete", action="delete"))
    elif state == "unconfigured":
        reader = from_workspace(path, legacy_root=reader.legacy_root)
    else:
        blob = store.verified_path(BlobManifest(wanted["sha256"], wanted["size"]))
        if state == "missing":
            blob.unlink()
        else:
            blob.write_bytes(b"x" * len(data))
    result = reader.resolve(LOCAL)
    assert result.managed and result.status == state and result.path is None
    assert alias.read_bytes() == data


def test_sanitized_local_id_collision_is_visible_before_any_legacy_fetch(tmp_path):
    path, _, _, reader, _, data = prepared(tmp_path, managed=False)
    with sqlite3.connect(path) as conn:
        for identity in ("a:b", "a_b"):
            conn.execute(
                "INSERT INTO papers(id,venue,year,title,title_key,source) "
                "VALUES(?,'',2026,'A','a','fixture')",
                (identity,),
            )
    (reader.legacy_root / "a_b.pdf").write_bytes(data)
    for identity in ("a:b", "a_b"):
        assert reader.inspect(identity).status == "ambiguous"
        assert reader.resolve(identity).path is None


def test_only_an_exact_file_name_match_counts_as_a_collision(tmp_path):
    # The collision lookup is a LIKE search, where "_" matches any character and case
    # is ignored; ids it finds that map to another file name must not count.
    path, _, _, reader, _, _ = prepared(tmp_path, managed=False)
    with sqlite3.connect(path) as conn:
        for identity in ("a:b", "aXb", "A_B"):
            conn.execute(
                "INSERT INTO papers(id,venue,year,title,title_key,source) "
                "VALUES(?,'',2026,'A','a','fixture')",
                (identity,),
            )
    found = reader.inspect_many(["a:b", "aXb", "A_B", "zz"])
    assert [found[i].status == "ambiguous" for i in ("a:b", "aXb", "A_B")] == [False] * 3
    assert found["zz"].status == "missing"


def test_batch_inspection_uses_existing_connection_and_never_verifies_files(tmp_path, monkeypatch):
    path, _, _, reader, _, _ = prepared(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Metadata inspection touched PDF verification or opened another DB")

    monkeypatch.setattr(reader_module, "verify_document", forbidden)
    monkeypatch.setattr(reader_module, "_identity", forbidden)
    monkeypatch.setattr(reader_module, "_connect", forbidden)
    with sqlite3.connect(path) as conn:
        status = reader.inspect_many([LOCAL, "missing"], conn=conn)
    assert status[LOCAL].status == "unchecked" and status[LOCAL].managed
    assert status["missing"].reason == "paper_missing"
    with (
        sqlite3.connect(tmp_path / "other.db") as conn,
        pytest.raises(ValueError, match="another research"),
    ):
        reader.inspect_many([LOCAL], conn=conn)


@pytest.mark.parametrize("event", ["replacement", "close", "paper_removed"])
def test_late_verified_result_cannot_activate_after_context_changed(tmp_path, monkeypatch, event):
    path, journal, _, reader, alias, data = prepared(tmp_path)
    original = reader_module.verify_document

    def interrupted(store, wanted):
        verified = original(store, wanted)
        if event == "replacement":
            save(journal, document(pdf_bytes("New"), op_id="late-new"))
        elif event == "close":
            reader.close()
        else:
            with sqlite3.connect(path) as conn:
                conn.execute("DELETE FROM papers WHERE id=?", (LOCAL,))
        return verified

    monkeypatch.setattr(reader_module, "verify_document", interrupted)
    result = reader.resolve(LOCAL)
    assert result.status == "stale" and not result.available
    assert alias.read_bytes() == data


def test_quota_failure_is_non_destructive_and_retry_can_succeed(tmp_path):
    _, _, _, reader, alias, data = prepared(tmp_path, quota=1)
    assert reader.resolve(LOCAL).status == "quota"
    assert not list(reader.projection_root.glob("*.pdf"))
    assert alias.read_bytes() == data
    reader.projection_quota_bytes = len(data) * 2
    assert reader.resolve(LOCAL).available


def test_interrupted_publication_cleans_only_own_partial_and_retries(tmp_path, monkeypatch):
    _, _, _, reader, alias, data = prepared(tmp_path)
    original = reader_module.os.replace

    def broken(*args):
        raise OSError("interrupted publication")

    monkeypatch.setattr(reader_module.os, "replace", broken)
    assert reader.resolve(LOCAL).status == "invalid"
    assert not list(reader.projection_root.glob("*.part"))
    assert not list(reader.projection_root.glob("*.pdf"))
    assert alias.read_bytes() == data
    monkeypatch.setattr(reader_module.os, "replace", original)
    assert reader.resolve(LOCAL).available


def test_crash_partial_is_recovered_under_projection_lock(tmp_path):
    path, _, _, reader, _, _ = prepared(tmp_path)
    reader.projection_root.mkdir()
    partial = reader.projection_root / (target(path)["sha256"] + ".part")
    partial.write_bytes(b"partial")
    assert reader.resolve(LOCAL).available
    assert not partial.exists()


def test_registered_factory_uses_exact_device_store_binding_and_invalidates_changed_paths(tmp_path):
    path, journal, store, reader, _, _ = prepared(tmp_path)
    register(path, journal, store, reader)
    found = from_workspace(path)
    result = found.resolve(LOCAL)
    assert result.available and found is from_workspace(path)
    with journal.transaction() as conn:
        register_document_paths(
            conn,
            workspace_id="workspace",
            blob_root=store.root,
            projection_root=tmp_path / "next-reader",
            legacy_root=reader.legacy_root,
        )
    assert not document_current(result)
    assert found.resolve(LOCAL).status == "stale"
    assert from_workspace(path).resolve(LOCAL).available
    with store._transaction() as conn:
        conn.execute("UPDATE transfer_binding SET workspace='another'")
    assert from_workspace(path).resolve(LOCAL).status == "invalid"


def test_factory_does_not_create_missing_research_or_blob_database(tmp_path):
    path = tmp_path / "does-not-exist.db"
    empty = from_workspace(path).inspect("legacy-paper")
    assert not empty.managed and empty.status == "unchecked"
    assert not path.exists()
    path, journal, _, reader, _, _ = prepared(tmp_path)
    missing_store = tmp_path / "absent-store"
    with journal.transaction() as conn:
        register_document_paths(
            conn,
            workspace_id="workspace",
            blob_root=missing_store,
            projection_root=reader.projection_root,
            legacy_root=reader.legacy_root,
        )
    assert from_workspace(path).resolve(LOCAL).status == "invalid"
    assert not missing_store.exists()


@pytest.mark.parametrize("database_state", ["absent", "empty", "corrupt", "managed_incomplete"])
def test_legacy_bootstrap_never_creates_database_or_ignores_managed_schema(
    tmp_path, database_state
):
    path, legacy = tmp_path / "research.db", tmp_path / "pdf"
    legacy.mkdir()
    alias = legacy / "legacy.pdf"
    alias.write_bytes(pdf_bytes())
    if database_state == "corrupt":
        path.write_bytes(b"not a database")
    elif database_state in ("empty", "managed_incomplete"):
        with sqlite3.connect(path) as conn:
            if database_state == "managed_incomplete":
                conn.execute("CREATE TABLE research_document_desired(paper_id,target,active)")
    if database_state in ("corrupt", "managed_incomplete"):
        with pytest.raises((ValueError, sqlite3.DatabaseError)):
            from_workspace(path, legacy_root=legacy).resolve("legacy")
    else:
        result = from_workspace(path, legacy_root=legacy).resolve("legacy")
        assert result.available and result.path == alias and not result.managed
        assert document_current(result)
        assert path.exists() == (database_state == "empty")


def test_runtime_helper_uses_current_store_binding_not_config_alias(tmp_path, monkeypatch):
    from paper_daily import config, store

    path, _, _, reader, alias, _ = prepared(tmp_path, managed=False)
    monkeypatch.setattr(store, "DB_PATH", path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "wrong.db")
    result = reader_module.resolve_document(LOCAL, legacy_root=reader.legacy_root)
    assert result.path == alias and result.available
    assert not (tmp_path / "wrong.db").exists()


def test_open_old_revision_remains_intact_but_cannot_reactivate_after_replacement(tmp_path):
    _, journal, _, reader, _, _ = prepared(tmp_path)
    result = reader.resolve(LOCAL)
    assert reader.intact(result) and reader.current(result)
    save(journal, document(pdf_bytes("Replacement"), op_id="replacement"))
    assert reader.intact(result) and not reader.current(result)
    result.path.write_bytes(b"modified")
    assert not reader.intact(result)
    result.path.unlink()
    assert not reader.intact(result)


def test_file_mutation_invalidates_open_result_without_trusting_cached_badge(tmp_path):
    _, _, _, reader, alias, data = prepared(tmp_path)
    result = reader.resolve(LOCAL)
    result.path.write_bytes(b"x" * len(data))
    assert not document_current(result)
    assert reader.resolve(LOCAL).status == "invalid"
    assert alias.read_bytes() == data


def test_unsafe_projection_roots_do_not_overwrite_legacy_or_blob_storage(tmp_path):
    _, _, store, reader, alias, data = prepared(tmp_path)
    for root in (reader.legacy_root, store.root, store.root / "objects"):
        reader.projection_root = root
        assert reader.resolve(LOCAL).status == "invalid"
    assert alias.read_bytes() == data


def test_registration_is_explicit_transactional_and_not_a_workspace_transfer(tmp_path):
    path, journal, store, reader, _, _ = prepared(tmp_path)
    kwargs = dict(
        workspace_id="workspace",
        blob_root=store.root,
        projection_root=reader.projection_root,
        legacy_root=reader.legacy_root,
    )
    with sqlite3.connect(path) as conn, pytest.raises(ValueError, match="transaction"):
        register_document_paths(conn, **kwargs)
    with pytest.raises(RuntimeError), journal.transaction() as conn:
        register_document_paths(conn, **kwargs)
        raise RuntimeError("cancelled")
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name='document_reader_paths'"
            ).fetchone()
            is None
        )
    with journal.transaction() as conn:
        register_document_paths(conn, **kwargs)
        before = conn.total_changes
        register_document_paths(conn, **kwargs)
        assert conn.total_changes == before
    with pytest.raises(ValueError, match="another workspace"), journal.transaction() as conn:
        register_document_paths(conn, **dict(kwargs, workspace_id="another"))
