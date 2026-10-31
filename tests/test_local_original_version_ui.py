"""Unenrolled generated/imported A opens read-only while current B stays intact."""

import hashlib
import os
import sqlite3
import threading
from contextlib import closing
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QWidget
from test_claim_evidence_ui import claims as claims_fixture
from test_claim_evidence_ui import view as view_fixture
from test_claim_evidence_ui import wait
from test_local_source_owners import receiver as receiver_fixture
from test_original_version_ui import historical as historical_fixture
from test_original_version_ui import open_original
from test_original_version_ui import ready as ready_fixture
from test_package_import import package as package_fixture
from test_package_import import rich_package as rich_package_fixture
from test_research_generation import workspace as workspace_fixture

from paper_daily import (
    annotation_reader,
    bundle,
    llm,
    manual_highlight_ops,
    source_snapshots,
    store,
)
from paper_daily import local_source_owners as owners
from paper_daily.desktop import original_version
from paper_daily.desktop.claim_evidence import TEXT, ClaimEvidenceDialog
from paper_daily.document_reader import from_workspace

claims, view, ready, historical = claims_fixture, view_fixture, ready_fixture, historical_fixture
package, rich_package, receiver = package_fixture, rich_package_fixture, receiver_fixture


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    return workspace_fixture.__wrapped__(tmp_path, monkeypatch, SimpleNamespace(param=False))


@pytest.fixture
def imported(rich_package, receiver):
    database, root = receiver
    report = bundle.import_(rich_package[0], pdfs=False)
    assert report["owned_originals"] == 1
    document = from_workspace(database, legacy_root=root / "pdf").resolve("ref:example")
    assert document.available and document.sha256 == rich_package[1]
    owner = manual_highlight_ops.capture_owner(database, "ref:example")
    app, parent = QApplication.instance() or QApplication([]), QWidget()
    question, note = (
        QLineEdit("Unsent imported question", parent),
        QPlainTextEdit("Unsent imported note", parent),
    )
    active = [database, "ref:example", 1, document]
    dialog = ClaimEvidenceDialog(
        database,
        "ref:example",
        parent,
        legacy_root=root / "pdf",
        owner=owner,
        document=document,
        current_path=lambda: active[0],
        current_view=lambda: tuple(active),
        language="en",
    )
    dialog.show()
    wait(app, lambda: not dialog.busy and dialog.saved is not None)
    item = SimpleNamespace(
        d=dialog,
        app=app,
        parent=parent,
        question=question,
        note=note,
        database=database,
        current=document,
        active=active,
        source_hash=rich_package[2],
        root=root,
        report=report,
    )
    yield item
    dialog.close()
    wait(app, lambda: dialog.disposed)
    dialog.deleteLater()
    parent.close()
    parent.deleteLater()
    app.processEvents()


def database_state(database):
    with closing(sqlite3.connect(database)) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        return {
            table: conn.execute('SELECT * FROM "' + table.replace('"', '""') + '"').fetchall()
            for table in tables
        }


def deny_ai(*_args, **_kwargs):
    pytest.fail("Read-only local source accessed account/model routing")


def test_generated_private_original_is_read_only_without_schema_identity_or_ai(
    historical, monkeypatch
):
    h = historical
    before, current = database_state(h.ready[0]), h.current.path.read_bytes()
    monkeypatch.setattr(llm, "capture_connections", deny_ai)
    monkeypatch.setattr(llm, "complete_result", deny_ai)
    viewer = open_original(h)
    snapshot = viewer.snapshot
    assert snapshot.local_proof is not None and snapshot.portable_id is None
    assert snapshot.data is snapshot.local_proof.data
    assert snapshot.document_hash == h.source_hash
    assert hashlib.sha256(snapshot.data).hexdigest() == h.source_hash
    assert original_version.metadata_current(snapshot)
    assert database_state(h.ready[0]) == before and h.current.path.read_bytes() == current
    assert len(h.claims[2]) == 1 and not h.jumps
    assert h.question.text() == "Unsent question" and h.note.toPlainText() == "Unsent notes"


def test_imported_owned_original_opens_without_enrollment_or_receipt_changes(imported, monkeypatch):
    h = imported
    before, current = database_state(h.database), h.current.path.read_bytes()
    monkeypatch.setattr(llm, "capture_connections", deny_ai)
    monkeypatch.setattr(llm, "settings", deny_ai)
    viewer = open_original(h)
    assert viewer.snapshot.local_proof is not None and viewer.snapshot.portable_id is None
    assert viewer.snapshot.document_hash == h.source_hash != h.current.sha256
    assert hashlib.sha256(viewer.snapshot.data).hexdigest() == h.source_hash
    assert database_state(h.database) == before and h.current.path.read_bytes() == current
    assert (
        h.question.text() == "Unsent imported question"
        and h.note.toPlainText() == "Unsent imported note"
    )
    for _ in range(10):
        assert not h.d.open_original()
    assert h.d._original_viewer is viewer


def test_generated_matching_cache_without_receipt_is_denied_then_repaired(
    historical,
):
    h = historical
    proof = owners.prepare(h.d.owner, h.d.saved)
    records = [
        row for row in source_snapshots.list_owned(h.ready[0]) if row["sha256"] == h.source_hash
    ]
    assert len(records) == 1
    receipt = source_snapshots.receipt_path(h.ready[0], records[0])
    original_receipt = receipt.read_bytes()
    receipt.unlink()
    assert hashlib.sha256(proof.source.read_bytes()).hexdigest() == h.source_hash
    before = database_state(h.ready[0])
    assert h.d.open_original()
    wait(h.app, lambda: not h.d.busy)
    assert h.d._original_viewer is None and h.d.status.text() == TEXT["en"]["original_unavailable"]
    assert database_state(h.ready[0]) == before
    receipt.write_bytes(original_receipt)
    assert open_original(h).snapshot.document_hash == h.source_hash
    assert len(h.claims[2]) == 1


def test_imported_cache_filename_and_claim_without_receiver_receipt_grant_no_read_authority(
    imported,
):
    h = imported
    proof = owners.prepare(h.d.owner, h.d.saved)
    with store.connect() as conn:
        conn.execute("DELETE FROM " + owners.TABLE)
    assert hashlib.sha256(proof.source.read_bytes()).hexdigest() == h.source_hash
    before = database_state(h.database)
    assert h.d.open_original()
    wait(h.app, lambda: not h.d.busy)
    assert h.d._original_viewer is None and h.d.status.text() == TEXT["en"]["original_unavailable"]
    assert database_state(h.database) == before and owners.list_owned(h.database) == []
    assert h.d.saved["report"]


@pytest.mark.parametrize("changed", ["paper", "workspace", "cancel", "close"])
def test_local_pending_prepare_switch_cancel_and_close_discard_late_result(
    historical, monkeypatch, changed
):
    h = historical
    entered, release = threading.Event(), threading.Event()
    prepare = owners.prepare

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return prepare(*args, **kwargs)

    monkeypatch.setattr(owners, "prepare", blocked)
    assert h.d.open_original() and not h.d.open_original()
    wait(h.app, entered.is_set)
    if changed == "paper":
        h.active[1] = "different-paper"
        h.d._check()
    elif changed == "workspace":
        h.active[0] = h.ready[0].with_name("different.sqlite")
        h.d._check()
    elif changed == "cancel":
        h.d.cancel()
    else:
        assert not h.d.close()
    release.set()
    wait(h.app, lambda: not h.d.busy)
    assert h.d._original_viewer is None and not h.jumps and len(h.claims[2]) == 1


def test_import_receipt_retired_after_worker_verification_rejects_open(imported, monkeypatch):
    h = imported
    prepare = owners.prepare

    def retired(*args, **kwargs):
        proof = prepare(*args, **kwargs)
        with store.connect() as conn:
            conn.execute("DELETE FROM " + owners.TABLE)
        return proof

    monkeypatch.setattr(owners, "prepare", retired)
    assert h.d.open_original()
    wait(h.app, lambda: not h.d.busy)
    assert h.d._original_viewer is None and owners.list_owned(h.database) == []
    assert h.d.status.text() == TEXT["en"]["original_unavailable"]


@pytest.mark.parametrize("changed", ["claim", "receipt"])
def test_open_local_original_closes_when_claim_or_receipt_changes(imported, changed):
    h = imported
    viewer = open_original(h)
    with store.connect() as conn:
        if changed == "receipt":
            conn.execute("DELETE FROM " + owners.TABLE)
        else:
            conn.execute("UPDATE paper_claim_sets SET written_at='2026-10-31T00:00:00+00:00'")
    viewer.check()
    wait(h.app, lambda: viewer.disposed)
    assert h.d._original_viewer is None and h.d.status.text() == TEXT["en"]["original_changed"]
    assert annotation_reader.saved(h.database, h.d.paper_id, "claims") == h.d.saved


def test_restored_mtime_local_source_change_after_service_verifies_is_rejected(
    historical, monkeypatch
):
    h = historical
    prepare = owners.prepare

    def changed(*args, **kwargs):
        proof = prepare(*args, **kwargs)
        info = proof.source.stat()
        raw = proof.source.read_bytes()
        proof.source.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        os.utime(proof.source, ns=(info.st_atime_ns, info.st_mtime_ns))
        return proof

    monkeypatch.setattr(owners, "prepare", changed)
    current = h.current.path.read_bytes()
    assert h.d.open_original()
    wait(h.app, lambda: not h.d.busy)
    assert h.d._original_viewer is None and h.current.path.read_bytes() == current
    assert h.d.status.text() == TEXT["en"]["original_unavailable"]


def test_local_pdf_parse_and_fallback_render_stay_off_gui_and_close_safely(historical, monkeypatch):
    h = historical
    factory, parse = original_version.OriginalVersionDialog, original_version.pymupdf.open
    monkeypatch.setattr(
        original_version,
        "OriginalVersionDialog",
        lambda *args, **kwargs: factory(*args, **kwargs, native=False),
    )
    threads = []

    def parsed(*args, **kwargs):
        threads.append(QThread.currentThread() != h.app.thread())
        return parse(*args, **kwargs)

    monkeypatch.setattr(original_version.pymupdf, "open", parsed)
    viewer = open_original(h)
    viewer.page.setValue(2)
    wait(h.app, lambda: not viewer.busy and viewer._rendered_page == 1)
    assert threads and all(threads)
    assert viewer.snapshot.local_proof is not None
    h.d.close()
    wait(h.app, lambda: h.d.disposed)
    assert h.d.disposed and viewer.disposed and len(h.claims[2]) == 1
