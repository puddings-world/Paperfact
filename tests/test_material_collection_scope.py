"""Material reads keep the actual loaded PDF and explicit workspace roots."""

import hashlib
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from types import SimpleNamespace

import pytest
from test_managed_reader_ui import workspace as managed_fixture
from test_materials import paper as paper

from paper_daily import figures, file_change, llm, materials, store, sync_capture
from paper_daily import manual_highlight_ops as ops
from paper_daily.document_reader import from_workspace

managed = managed_fixture


def native(path):
    info = path.stat()
    return info.st_dev, info.st_ino


def sql(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        return list(conn.iterdump())


def files(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file() and not p.name.endswith(("-wal", "-shm"))
    }


def loaded(database, document):
    def capture():
        owner = ops.observe_owner(database, document.local_id, expected_native=native(database))
        view = ops.load(owner, document.path, document.sha256, document=document, readonly=True)
        return figures.capture_loaded(view, document, file_change.version(document.path))

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(capture).result(timeout=15)


def collect(source, database, paths, **kwargs):
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(
            materials.collect,
            source.view.owner.paper_id,
            document=source.document,
            database=database,
            loaded_source=source,
            paths=paths,
            **kwargs,
        ).result(timeout=15)


@pytest.fixture
def scoped(paper, monkeypatch):
    database = store.DB_PATH
    with closing(sqlite3.connect(database)) as conn, conn:
        store._migrate(conn)
    # ReaderPage.load normally establishes this actual parent before a read request.
    ops.capture_owner(database, paper)
    paths = materials.MaterialPaths.capture()
    document = from_workspace(database, legacy_root=paths.pdf).resolve(paper)
    assert document.available
    source = loaded(database, document)

    def deny(*_args, **_kwargs):
        pytest.fail("Collecting saved materials must not invoke accounts/models")

    monkeypatch.setattr(llm, "complete_result", deny)
    monkeypatch.setattr(llm, "capture_connections", deny)
    return SimpleNamespace(database=database, paths=paths, document=document, source=source)


def test_actual_loaded_collection_ignores_other_global_workspace_and_paths(
    scoped, tmp_path, monkeypatch
):
    s = scoped
    other = tmp_path / "other-workspace"
    other.mkdir()
    foreign = other / "papers.sqlite"
    with closing(sqlite3.connect(foreign)) as conn:
        conn.execute("CREATE TABLE untouched(value TEXT)")
        conn.execute("INSERT INTO untouched VALUES('Other private workspace')")
        conn.commit()
    monkeypatch.setattr(store, "DB_PATH", foreign)
    for field in ("DATA_DIR", "PDF_DIR", "TEXT_DIR", "FIG_DIR"):
        monkeypatch.setattr(materials, field, other / field)
    monkeypatch.setattr(materials.paper_highlights, "CACHE_DIR", other / "highlights")
    before_sql, before_other = sql(s.database), files(other)
    result = collect(s.source, s.database, s.paths)
    assert len(result.headings) >= 2
    assert all(item["document_hash"] == s.document.sha256 for item in result.headings)
    assert any(item["rect"] and item["navigation_available"] for item in result.headings)
    assert sql(s.database) == before_sql and files(other) == before_other
    assert (s.paths.data / "material-positions" / s.document.sha256).is_dir()


def test_material_source_same_byte_change_is_refused_without_relabel_or_rewrite(scoped):
    s = scoped
    info = s.document.path.stat()
    s.document.path.write_bytes(s.document.path.read_bytes())
    os.utime(s.document.path, ns=(info.st_atime_ns, info.st_mtime_ns))
    before_sql, before_files = sql(s.database), files(s.database.parent)
    with pytest.raises(ValueError):
        collect(s.source, s.database, s.paths)
    assert sql(s.database) == before_sql and files(s.database.parent) == before_files


def test_material_collection_cancellation_checks_before_source_or_database_access(
    scoped, monkeypatch
):
    s = scoped

    def deny(*_args, **_kwargs):
        pytest.fail("Cancelled material work must not start source/database observation")

    monkeypatch.setattr(materials, "_source_document", deny)
    with pytest.raises(ValueError, match="cancelled"):
        collect(s.source, s.database, s.paths, cancelled=lambda: True)


def test_actual_retained_managed_a_is_collected_when_desired_primary_is_b(managed):
    w = managed
    w.attach("1 Original A Method\nAlpha evidence.\n2 Original A Results", "collection-a")
    database = w.side.journal.path
    # The general managed-reader fixture intentionally omits desktop writer setup.
    # Install the actual local capture binding, as the full desktop workspace does.
    with closing(ops.generation._connect(database)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id=w.side.journal.workspace_id,
                             device_id=w.side.journal.device_id)
    ops.capture_owner(database, w.widget.paper.id)
    document = from_workspace(database).resolve(w.widget.paper.id)
    source = loaded(database, document)
    paths = materials.MaterialPaths(
        w.root, w.root / "pdf", w.root / "text", w.root / "figures", w.root / "highlights"
    )
    newer = w.attach("1 Current B Method\nBeta evidence.\n2 Current B Results", "collection-b")
    assert not document._owner.current(document) and document._owner.intact(document)
    before = sql(database)
    result = collect(source, database, paths)
    assert [item["text"] for item in result.headings] == [
        "1 Original A Method",
        "2 Original A Results",
    ]
    assert all(item["document_hash"] == document.sha256 for item in result.headings)
    assert document.sha256 != newer.sha256 and sql(database) == before


def test_loaded_material_source_cannot_read_close_notes_from_foreign_database(scoped, tmp_path):
    s = scoped
    other = tmp_path / "unrelated.sqlite"
    with closing(sqlite3.connect(other)) as conn:
        conn.execute("CREATE TABLE untouched(value TEXT)")
    before_sql, before_other = sql(s.database), other.read_bytes()
    with pytest.raises(ValueError, match="captured research database"):
        collect(s.source, other, s.paths)
    assert sql(s.database) == before_sql and other.read_bytes() == before_other
