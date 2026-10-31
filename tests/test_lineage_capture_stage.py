"""Current ownership and read-only controls for inactive corpus capture."""

import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing

import pytest
from test_document_reader import LOCAL, prepared
from test_research_lineage import corpus as corpus
from test_sync_document_research import document, local_blob, pdf_bytes, target
from test_sync_reading_state_research import save

from paper_daily import research_lineage as lineage
from paper_daily.document_reader import document_current
from paper_daily.research_lifecycle import ensure_lifecycle
from paper_daily.sync_documents import bind_verified_document, verify_document


def ready(tmp_path):
    path, journal, blobs, reader, alias, raw = prepared(tmp_path)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
    loaded = reader.resolve(LOCAL)
    assert loaded.available and document_current(loaded)
    return path, journal, blobs, reader, alias, raw, loaded


def capture_loaded(state):
    path, _, _, reader, _, _, loaded = state
    return lineage.capture(path, LOCAL, legacy_root=reader.legacy_root, documents={LOCAL: loaded})


def test_managed_actual_loaded_a_remains_selected_after_desired_b(tmp_path):
    state = ready(tmp_path)
    path, journal, blobs, reader, _, raw_a, loaded_a = state
    raw_b = pdf_bytes("A newer desired version has distinct observations.")
    save(journal, document(raw_b, op_id="desired-b"))
    local_blob(blobs, raw_b)
    wanted = target(path)
    with journal.transaction() as conn:
        assert bind_verified_document(conn, wanted, verify_document(blobs, wanted))
    desired_b = reader.resolve(LOCAL)
    assert desired_b.sha256 != loaded_a.sha256
    assert not document_current(loaded_a) and reader.intact(loaded_a)
    captured = capture_loaded(state)
    assert captured.sources[0]["document_hash"] == hashlib.sha256(raw_a).hexdigest()
    assert captured._documents == (loaded_a,)
    assert lineage.current(captured)
    assert lineage.pages(captured)[0]["pages"] != []
    assert (
        lineage.capture(
            path, LOCAL, legacy_root=reader.legacy_root, documents={LOCAL: desired_b}
        ).sources[0]["id"]
        != captured.focal
    )


def test_capture_current_pages_are_sql_read_only_and_handles_close(corpus, monkeypatch):
    path, root, captured = corpus
    before = path.read_bytes()
    source_bytes = {p.name: p.read_bytes() for p in root.iterdir()}
    statements = []
    connect = lineage.generation._connect

    def observed(database):
        conn = connect(database)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(lineage.generation, "_connect", observed)
    again = lineage.capture(path, "focal", ["prior", "later"], legacy_root=root)
    assert lineage.current(again)
    assert lineage.pages(again) == lineage.pages(captured)
    assert all(s.lstrip().split()[0].upper() in {"SELECT", "BEGIN", "PRAGMA"} for s in statements)
    assert path.read_bytes() == before
    assert {p.name: p.read_bytes() for p in root.iterdir()} == source_bytes
    renamed = path.with_suffix(".closed")
    os.replace(path, renamed)
    os.replace(renamed, path)


def test_uninitialized_lifecycle_is_not_created(corpus):
    path, root, _ = corpus
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("DROP TABLE research_parent_lifecycle")
    before = path.read_bytes()
    with pytest.raises(lineage.LineageError, match="paper_lifecycle_uninitialized"):
        lineage.capture(path, "focal", legacy_root=root)
    assert path.read_bytes() == before
    with closing(sqlite3.connect(path)) as conn:
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='research_parent_lifecycle'"
        ).fetchall()


def test_duplicate_original_records_reject_together_but_never_merge(corpus):
    path, root, first = corpus
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "INSERT INTO papers(id,venue,year,title,title_key,source,doi,arxiv_id,s2_id) "
            "SELECT 'distinct',venue,year,title,title_key,source,doi,arxiv_id,s2_id "
            "FROM papers WHERE id='focal'"
        )
        ensure_lifecycle(conn)
    shutil.copyfile(root / "focal.pdf", root / "distinct.pdf")
    other = lineage.capture(path, "distinct", legacy_root=root)
    assert other.focal == first.focal
    assert json.loads(other._json)["observed"][0]["local_id"] == "distinct"
    assert json.loads(first._json)["observed"][0]["local_id"] == "focal"
    before = path.read_bytes()
    with pytest.raises(lineage.LineageError, match="duplicate_source"):
        lineage.capture(path, "focal", ["distinct"], legacy_root=root)
    assert path.read_bytes() == before


def test_native_database_replacement_during_first_read_is_not_adopted(corpus, monkeypatch):
    path, root, _ = corpus
    replacement = path.with_suffix(".replacement")
    shutil.copyfile(path, replacement)
    connect = lineage.generation._connect
    once = []

    def replacing(database):
        if not once:
            once.append(True)
            os.replace(replacement, path)
        return connect(database)

    monkeypatch.setattr(lineage.generation, "_connect", replacing)
    with pytest.raises(lineage.LineageError, match="database_changed"):
        lineage.capture(path, "focal", legacy_root=root)


def test_current_rejects_actual_replacement_between_admission_and_sql(corpus, monkeypatch):
    path, _, captured = corpus
    replacement = path.with_suffix(".replacement")
    shutil.copyfile(path, replacement)
    connect = lineage.generation._connect
    once = []

    def replacing(database):
        if not once:
            once.append(True)
            os.replace(replacement, path)
        return connect(database)

    monkeypatch.setattr(lineage.generation, "_connect", replacing)
    with pytest.raises(lineage.LineageError, match="database_changed"):
        lineage.current(captured)


@pytest.mark.parametrize("change", ["close", "invalidate", "replace"])
def test_actual_managed_source_lifetime_rejects_but_snapshot_is_retained(tmp_path, change):
    state = ready(tmp_path)
    captured = capture_loaded(state)
    reader, loaded = state[3], state[-1]
    before = lineage.pages(captured)
    if change == "close":
        reader.close()
    elif change == "invalidate":
        reader.invalidate(LOCAL)
    else:
        replacement = loaded.path.with_suffix(".replacement")
        replacement.write_bytes(loaded.path.read_bytes())
        os.replace(replacement, loaded.path)
    with pytest.raises(ValueError, match="source_changed"):
        lineage.current(captured)
    assert lineage.pages(captured) == before


def test_views_are_defensive_and_cancelled_input_keeps_captured_bytes(corpus):
    _, _, captured = corpus
    original = captured.sources
    exposed = captured.sources
    exposed[0]["identity"]["title"] = "Different caller title"
    assert captured.sources == original
    before = lineage.pages(captured)
    with pytest.raises(ValueError, match="cancelled"):
        lineage.pages(captured, cancelled=lambda: True)
    assert lineage.pages(captured) == before


def test_missing_database_is_not_created(tmp_path):
    missing = tmp_path / "absent.sqlite"
    with pytest.raises(lineage.LineageError, match="database_unavailable"):
        lineage.capture(missing, "paper", legacy_root=tmp_path)
    assert not missing.exists()


def test_actual_pdf_per_source_and_aggregate_byte_limits(corpus):
    path, root, _ = corpus
    focal = root / "focal.pdf"
    with focal.open("ab") as stream:
        stream.truncate(32 * 1024**2 + 1)
    with pytest.raises(ValueError, match="pdf_limit"):
        lineage.capture(path, "focal", legacy_root=root)
    with focal.open("r+b") as stream:
        stream.truncate(32 * 1024**2)
    assert lineage.capture(path, "focal", legacy_root=root).sources[0]["page_count"] == 1
    for name in ("prior", "later"):
        with (root / (name + ".pdf")).open("ab") as stream:
            stream.truncate(32 * 1024**2)
    with pytest.raises(lineage.LineageError, match="corpus_byte_limit"):
        lineage.capture(path, "focal", ["prior", "later"], legacy_root=root)


def test_bound_capture_preserves_binding_outbox_and_database(tmp_path):
    from paper_daily.sync_capture import install
    from paper_daily.sync_client import SyncClient
    from paper_daily.sync_research import research_writer

    state = ready(tmp_path)
    path, journal = state[:2]
    client = SyncClient(journal, research_writer)
    with closing(lineage.generation._connect(path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="device")
    before = path.read_bytes()
    pending = client.journal.pending()
    captured = capture_loaded(state)
    assert json.loads(captured._json)["binding"] == {
        "workspace_id": "workspace",
        "device_id": "device",
    }
    assert lineage.current(captured)
    assert client.journal.pending() == pending
    assert path.read_bytes() == before
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("UPDATE research_capture_binding SET device='other-device' WHERE id=1")
    with pytest.raises(lineage.LineageError, match="workspace_changed"):
        lineage.current(captured)


def test_final_source_cancellation_never_returns_completed_capture(corpus, monkeypatch):
    path, root, _ = corpus
    before = path.read_bytes()
    cancelled = [False]
    capture_source = lineage.evidence.capture

    def cancelling(document):
        snapshot = capture_source(document)
        cancelled[0] = True
        return snapshot

    monkeypatch.setattr(lineage.evidence, "capture", cancelling)
    with pytest.raises(ValueError, match="cancelled"):
        lineage.capture(path, "focal", legacy_root=root, cancelled=lambda: cancelled[0])
    assert path.read_bytes() == before
