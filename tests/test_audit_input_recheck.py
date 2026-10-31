"""A new worker proof can renew exact research; old strict captures never change."""

import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_research_evidence import source as source_fixture

from paper_daily import audit_input_recheck as rechecks
from paper_daily import audit_inputs, llm, manual_highlight_ops, research_audit, store
from paper_daily import research_generation as generation
from paper_daily.desktop import ui_state
from paper_daily.document_reader import DocumentReader

source = source_fixture


def work(call, *args, **kwargs):
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(call, *args, **kwargs).result(timeout=20)


def rows(path):
    with closing(audit_inputs._connect(path)) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {
            name: [tuple(r) for r in conn.execute('SELECT * FROM "' + name + '"')] for name in names
        }


@pytest.fixture(autouse=True)
def no_agent_or_account_access(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Read-only recheck touched model/provider routing")

    monkeypatch.setattr(llm, "complete_result", forbidden)
    monkeypatch.setattr(llm, "capture_connections", forbidden)
    monkeypatch.setattr(llm, "settings", forbidden)


@pytest.fixture
def loaded(source, monkeypatch):
    database = source._owner.db_path
    monkeypatch.setattr(store, "DB_PATH", database)
    with store.connect(path=database) as conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,kind,created_at) "
            "VALUES('paper','50 participants','note','2026-01-01T00:00:00+00:00')"
        )
    owner = manual_highlight_ops.capture_owner(database, "paper")
    capture = audit_inputs.AuditCapture.capture(database, "paper", document=source, owner=owner)
    return SimpleNamespace(database=database, source=source, owner=owner, capture=capture)


def renew(value, **kwargs):
    return work(
        rechecks.recheck,
        value.capture,
        document=value.source,
        owner=value.owner,
        current=kwargs.pop("current", lambda: True),
        cancelled=kwargs.pop("cancelled", lambda: False),
        **kwargs,
    )


def opened(value):
    ui_state.save("ui.paper.opened:" + value.capture.paper_id, "2026-10-31T00:00:00+00:00")
    assert ui_state.flush()
    with closing(audit_inputs._connect(value.database)) as conn:
        assert (
            store.get_kv(conn, "ui.paper.opened:" + value.capture.paper_id)
            == "2026-10-31T00:00:00+00:00"
        )


def immutable(capture):
    return (
        capture.database,
        capture.paper_id,
        capture._state_json,
        capture._items_json,
        capture._versions,
        capture.snapshot,
        capture.snapshot._bytes,
    )


def test_current_control_returns_actual_fresh_capture_and_preserves_inputs_and_rows(loaded):
    before = immutable(loaded.capture), rows(loaded.database)
    fresh = renew(loaded)
    assert type(fresh) is audit_inputs.AuditCapture and fresh is not loaded.capture
    assert fresh.current() and loaded.capture.current()
    assert fresh._state_json == loaded.capture._state_json
    assert fresh._items_json == loaded.capture._items_json
    assert fresh.snapshot._origin is loaded.source
    assert fresh.snapshot._bytes == loaded.capture.snapshot._bytes
    assert (immutable(loaded.capture), rows(loaded.database)) == before


def test_actual_persisted_opened_at_admits_only_new_proof_and_old_guard_stays_strict(loaded):
    original = immutable(loaded.capture)
    opened(loaded)
    assert not loaded.capture.current()
    before = rows(loaded.database)
    fresh = renew(loaded)
    assert fresh.current() and not loaded.capture.current()
    assert fresh._versions != loaded.capture._versions
    assert fresh._state_json == loaded.capture._state_json
    assert fresh._items_json == loaded.capture._items_json
    assert immutable(loaded.capture) == original
    assert rows(loaded.database) == before


def test_gui_thread_refuses_before_callbacks_sql_or_hash(loaded, monkeypatch):
    called = []
    monkeypatch.setattr(audit_inputs.AuditCapture, "capture", lambda *a, **k: called.append(True))
    with pytest.raises(research_audit.AuditError, match="audit_recheck_worker_required"):
        rechecks.recheck(
            loaded.capture,
            document=loaded.source,
            owner=loaded.owner,
            current=lambda: called.append("scope"),
            cancelled=lambda: False,
        )
    assert called == []


@pytest.mark.parametrize("kind", ["note", "reference", "highlight"])
def test_actual_saved_content_changes_reject_with_identical_original_source(loaded, kind):
    with store.connect(path=loaded.database) as conn:
        if kind == "note":
            conn.execute("UPDATE notes SET body='70 participants' WHERE id=1")
        elif kind == "reference":
            conn.execute(
                "INSERT INTO cites(paper_id,ref_key,title,year,purpose,gist,"
                "verdict,why,written_at) VALUES('paper','ref1','Saved reference',2026,"
                "'Purpose','Gist','unsure','Reason','2026-01-01T00:00:00+00:00')"
            )
        else:
            conn.execute(
                "INSERT INTO pdf_highlights(paper_id,document_hash,quote,anchor,created_at) "
                "VALUES('paper',?,'Original quote',?,'2026-01-01')",
                (loaded.source.sha256, json.dumps(dict(p0=0, o0=0, p1=0, o1=1))),
            )
    before = rows(loaded.database)
    with pytest.raises(research_audit.AuditError):
        renew(loaded)
    assert rows(loaded.database) == before
    assert not loaded.capture.current()


def test_parent_delete_recreate_cannot_be_reattached_even_with_same_local_source(loaded):
    old = json.loads(loaded.owner._json)["parent"]
    with store.connect(path=loaded.database) as conn:
        conn.execute("DELETE FROM papers WHERE id='paper'")
        store.upsert_papers(
            conn,
            [
                dict(
                    id="paper",
                    title="Study",
                    title_key="study",
                    year=2026,
                    venue="Fixture",
                    source="fixture",
                )
            ],
        )
    newer_owner = manual_highlight_ops.capture_owner(loaded.database, "paper")
    assert json.loads(newer_owner._json)["parent"] != old
    with pytest.raises(research_audit.AuditError):
        renew(loaded)
    with pytest.raises(research_audit.AuditError):
        work(
            rechecks.recheck,
            loaded.capture,
            document=loaded.source,
            owner=newer_owner,
            current=lambda: True,
            cancelled=lambda: False,
        )


@pytest.mark.parametrize(
    "change", ["bytes", "same_bytes_new_native_version", "replacement", "resolver_closed"]
)
def test_source_changes_never_renew_original_document_authority(loaded, change):
    path = loaded.source.path
    if change == "bytes":
        path.write_bytes(b"changed source")
    elif change == "same_bytes_new_native_version":
        path.write_bytes(path.read_bytes())
    elif change == "replacement":
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(path.read_bytes())
        os.replace(replacement, path)
    else:
        loaded.source._owner.close()
    before = rows(loaded.database)
    with pytest.raises(research_audit.AuditError):
        renew(loaded)
    assert rows(loaded.database) == before


@pytest.mark.parametrize(
    "change", ["copy_object", "new_resolver", "wrong_owner", "missing_owner", "wire_dict"]
)
def test_typed_source_and_owner_identity_cannot_be_replaced_by_equal_hashes(loaded, change):
    cap, doc, owner = loaded.capture, loaded.source, loaded.owner
    if change == "copy_object":
        doc = replace(doc)
    elif change == "new_resolver":
        doc = DocumentReader(
            loaded.database, projection_root=None, legacy_root=doc.path.parent
        ).resolve("paper")
        assert doc.sha256 == loaded.source.sha256
    elif change == "wrong_owner":
        with store.connect(path=loaded.database) as conn:
            store.upsert_papers(
                conn,
                [dict(id="other", title="Other", year=2026, venue="Fixture", source="fixture")],
            )
        owner = manual_highlight_ops.capture_owner(loaded.database, "other")
    elif change == "missing_owner":
        owner = None
    else:
        cap = dict(database=cap.database, paper_id=cap.paper_id)
    with pytest.raises(research_audit.AuditError):
        work(
            rechecks.recheck,
            cap,
            document=doc,
            owner=owner,
            current=lambda: True,
            cancelled=lambda: False,
        )


def test_same_content_native_database_replacement_rejects_without_repair(loaded):
    original = loaded.database.read_bytes()
    replacement = loaded.database.with_suffix(".replacement")
    replacement.write_bytes(original)
    old_identity = generation._identity(loaded.database)
    os.replace(replacement, loaded.database)
    assert generation._identity(loaded.database) != old_identity
    assert loaded.database.read_bytes() == original
    with pytest.raises(research_audit.AuditError):
        renew(loaded)
    assert loaded.database.read_bytes() == original


@pytest.mark.parametrize("mode", ["cancel", "scope"])
def test_scope_and_cancellation_reject_before_any_fresh_factory(loaded, monkeypatch, mode):
    calls = []
    monkeypatch.setattr(audit_inputs.AuditCapture, "capture", lambda *a, **k: calls.append(True))
    with pytest.raises(
        research_audit.AuditError, match="cancelled" if mode == "cancel" else "stale_context"
    ):
        renew(loaded, current=lambda: mode != "scope", cancelled=lambda: mode == "cancel")
    assert calls == []


@pytest.mark.parametrize("mode", ["cancel", "scope", "resolver", "late_private_write"])
def test_change_after_real_fresh_capture_rejects_instead_of_retrying(loaded, monkeypatch, mode):
    original = audit_inputs.AuditCapture.capture
    state = dict(cancel=False, current=True)
    calls = []

    def fresh(*args, **kwargs):
        calls.append(True)
        actual = original(*args, **kwargs)
        if mode == "cancel":
            state["cancel"] = True
        elif mode == "scope":
            state["current"] = False
        elif mode == "resolver":
            loaded.source._owner.close()
        else:
            opened(loaded)
        return actual

    monkeypatch.setattr(audit_inputs.AuditCapture, "capture", fresh)
    with pytest.raises(research_audit.AuditError):
        renew(loaded, current=lambda: state["current"], cancelled=lambda: state["cancel"])
    assert calls == [True]


def test_continued_interference_during_real_stable_reads_has_one_explicit_error(
    loaded, monkeypatch
):
    original = audit_inputs.read_items
    reads = []

    def read(conn, paper_id):
        value = original(conn, paper_id)
        reads.append(True)
        if len(reads) == 2:
            opened(loaded)
        return value

    monkeypatch.setattr(audit_inputs, "read_items", read)
    with pytest.raises(research_audit.AuditError, match="recheck_interference"):
        renew(loaded)
    assert len(reads) == 2


@pytest.mark.parametrize("kind", ["text", "rows"])
def test_new_oversized_corpus_rejects_using_existing_bounds(loaded, kind):
    with store.connect(path=loaded.database) as conn:
        if kind == "text":
            conn.execute(
                "UPDATE notes SET body=? WHERE id=1", ("x" * (research_audit.MAX_TEXT + 1),)
            )
        else:
            conn.executemany(
                "INSERT INTO notes(paper_id,body,kind,created_at) VALUES('paper',?,'note','now')",
                [("bounded",)] * research_audit.MAX_ITEMS,
            )
    before = rows(loaded.database)
    with pytest.raises(research_audit.AuditError):
        renew(loaded)
    assert rows(loaded.database) == before


def test_missing_original_parent_cannot_be_retro_certified_by_later_owner(source):
    cap = audit_inputs.AuditCapture.capture(source._owner.db_path, "paper", document=source)
    assert json.loads(cap._state_json)["parent"] is None
    owner = manual_highlight_ops.capture_owner(source._owner.db_path, "paper")
    before = rows(source._owner.db_path)
    with pytest.raises(research_audit.AuditError, match="unknown_owner"):
        work(
            rechecks.recheck,
            cap,
            document=source,
            owner=owner,
            current=lambda: True,
            cancelled=lambda: False,
        )
    assert rows(source._owner.db_path) == before


def test_unknown_original_native_identity_never_becomes_known(loaded):
    state = json.loads(loaded.capture._state_json)
    state["identity"] = [0, 0]
    unknown = replace(loaded.capture, _state_json=json.dumps(state))
    with pytest.raises(research_audit.AuditError, match="unknown_database_identity"):
        work(
            rechecks.recheck,
            unknown,
            document=loaded.source,
            owner=loaded.owner,
            current=lambda: True,
            cancelled=lambda: False,
        )


def test_helper_does_not_issue_any_sql_writes(loaded, monkeypatch):
    original = sqlite3.connect
    rejected = []
    writes = {
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_UPDATE,
        sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_CREATE_TABLE,
        sqlite3.SQLITE_CREATE_TRIGGER,
        sqlite3.SQLITE_ALTER_TABLE,
        sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_DROP_TRIGGER,
        sqlite3.SQLITE_ATTACH,
        sqlite3.SQLITE_DETACH,
    }

    def connect(*args, **kwargs):
        conn = original(*args, **kwargs)

        def allow(action, first, second, database, trigger):
            if action in writes:
                rejected.append(action)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        conn.set_authorizer(allow)
        return conn

    before = rows(loaded.database)
    monkeypatch.setattr(sqlite3, "connect", connect)
    assert renew(loaded).current()
    assert not rejected and rows(loaded.database) == before


@pytest.fixture
def enrolled(tmp_path, monkeypatch):
    from test_document_reader import LOCAL, prepared

    from paper_daily import sync_capture
    from paper_daily.sync_client import SyncClient
    from paper_daily.sync_research import research_writer

    database, journal, _blobs, resolver, _alias, _data = prepared(tmp_path)
    SyncClient(journal, research_writer)
    with closing(generation._connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="device")
        conn.commit()
    document = resolver.resolve(LOCAL)
    owner = manual_highlight_ops.capture_owner(database, LOCAL)
    captured = audit_inputs.AuditCapture.capture(database, LOCAL, document=document, owner=owner)
    monkeypatch.setattr(store, "DB_PATH", database)
    return SimpleNamespace(
        database=database, journal=journal, source=document, owner=owner, capture=captured
    )


def test_enrolled_opened_at_recheck_preserves_actual_outbox_binding_and_rows(enrolled):
    opened(enrolled)
    old = immutable(enrolled.capture)
    before = rows(enrolled.database), enrolled.journal.pending()
    fresh = renew(enrolled)
    assert fresh.current() and not enrolled.capture.current()
    assert json.loads(fresh._state_json)["binding"] == dict(
        workspace_id="workspace", device_id="device"
    )
    assert fresh._items_json == enrolled.capture._items_json
    assert immutable(enrolled.capture) == old
    assert (rows(enrolled.database), enrolled.journal.pending()) == before


def test_loaded_historical_A_remains_original_when_desired_primary_is_B(enrolled):
    from test_sync_document_research import document as operation
    from test_sync_document_research import pdf_bytes
    from test_sync_reading_state_research import save

    document = enrolled.source
    original_bytes = enrolled.capture.snapshot._bytes
    save(enrolled.journal, operation(pdf_bytes("Desired newer B"), op_id="new-b"))
    assert not document._owner.current(document)
    assert document._owner.intact(document)
    assert not enrolled.capture.current()
    before = rows(enrolled.database), enrolled.journal.pending()
    fresh = renew(enrolled)
    assert fresh.current() and not enrolled.capture.current()
    assert fresh.snapshot._origin is document
    assert fresh.snapshot._bytes == original_bytes
    assert fresh.snapshot._source_json == enrolled.capture.snapshot._source_json
    assert json.loads(fresh.snapshot._source_json)["document_hash"] == document.sha256
    assert not document._owner.current(document) and document._owner.intact(document)
    assert (rows(enrolled.database), enrolled.journal.pending()) == before


@pytest.mark.parametrize("field", ["workspace", "device"])
def test_changed_enrolled_binding_rejects_without_rebinding(enrolled, field):
    with closing(sqlite3.connect(enrolled.database)) as conn, conn:
        conn.execute(f"UPDATE research_capture_binding SET {field}='other'")
    before = rows(enrolled.database), enrolled.journal.pending()
    with pytest.raises(research_audit.AuditError):
        renew(enrolled)
    assert (rows(enrolled.database), enrolled.journal.pending()) == before


def test_io_failure_is_safe_and_does_not_create_missing_database(loaded):
    loaded.database.unlink()
    with pytest.raises(research_audit.AuditError, match="recheck_unavailable"):
        renew(loaded)
    assert not loaded.database.exists()
