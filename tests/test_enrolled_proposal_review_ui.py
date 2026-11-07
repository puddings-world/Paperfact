"""Actual general-proposal Qt source view, explicit Apply, rollback and closed worker."""

import sqlite3
import threading
import time
from contextlib import closing
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from test_enrolled_proposal_packages import union_package as union_package
from test_local_blob_binding import no_external as no_external
from test_local_deck_proposals import local as local
from test_local_deck_proposals import native
from test_portable_deck_proposal import scientific as scientific

from paper_daily import enrolled_deck_proposals as catalog
from paper_daily import enrolled_deck_review as helper
from paper_daily import presentations, store
from paper_daily.desktop.review_dialog import ReviewDialog
from paper_daily.research_review import ResearchReview, validate_receipt
from paper_daily.sync_artifacts import applied_file
from paper_daily.sync_files import file_id


def settle(app, predicate, timeout=20):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert predicate()


@pytest.fixture
def actual_ui(union_package, monkeypatch):
    case = union_package
    report = case.importer.apply(case.importer.prepare(case.archive))
    monkeypatch.setattr(store, "DB_PATH", case.receiver.journal.path)
    monkeypatch.setattr(presentations, "DECK_DIR", case.destination / "presentations")
    app = QApplication.instance() or QApplication([])
    dialogs = []
    yield SimpleNamespace(case=case, report=report, app=app, dialogs=dialogs)
    for dialog in reversed(dialogs):
        if not dialog.disposed:
            settle(app, lambda dialog=dialog: not dialog.busy and not dialog.jobs)
            dialog.close()
        else:
            settle(app, lambda dialog=dialog: all(job[0].done() for job in dialog.jobs))
        dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def open_review(state, language="en"):
    service = ResearchReview(state.case.receiver.journal.path)
    dialog = ReviewDialog(service=service, language=language)
    state.dialogs.append(dialog)
    dialog.show()
    settle(state.app, lambda: dialog.preview is not None and not dialog.jobs)
    assert dialog.selection_key == ("enrolled_deck", state.report["proposal_ids"][0])
    return dialog


def verify(state, dialog):
    dialog.refresh.click()
    settle(state.app, lambda: dialog.preview is not None and not dialog.jobs)
    assert dialog.apply.isEnabled(), dialog.status.text()


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_actual_general_review_shows_full_evidence_cancel_then_applies_one_shared_operation(
    actual_ui, monkeypatch, language
):
    state, case = actual_ui, actual_ui.case
    dialog = open_review(state, language)
    assert "Local receiver" in dialog.list.currentItem().text()
    assert dialog.evidence.isReadOnly() and dialog.tabs.isTabVisible(dialog.evidence_index)
    assert "Keep full fourth caption" in dialog.evidence.toPlainText()
    assert case.original_sha[:12] in dialog.evidence.toPlainText()
    assert not dialog.apply.isEnabled()
    before = case.receiver.journal.pending()
    verify(state, dialog)
    assert dialog.words["pdf_mismatch"] in dialog.source.text()
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Cancel
    )
    dialog.apply.click()
    assert case.receiver.journal.pending() == before and dialog.apply.isEnabled()
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes
    )
    for _ in range(25):
        dialog.apply.click()
    settle(state.app, lambda: not dialog.busy and not dialog.jobs)
    assert dialog.status.text() == dialog.words["saved"]
    assert len(case.receiver.journal.pending()) == len(before) + 1
    mapped = state.report["identity_mapping"]["local-paper"]
    with case.receiver.journal.transaction() as conn:
        active = applied_file(conn, file_id(mapped["portable_id"], "deck", "guide"))
        assert active["payload"]["source_document_hash"] == case.original_sha
        conn.row_factory = sqlite3.Row
        records = [dict(row) for row in conn.execute("SELECT * FROM research_review_receipts")]
        assert len(records) == 1 and validate_receipt(records[0])
    loaded = presentations.load_deck(mapped["local_id"], "guide")
    assert loaded.title == case.expected["deck"]["title"]
    assert loaded.slides[0].speaker_notes == case.expected["deck"]["slides"][0]["speaker_notes"]
    image = presentations.figure_bytes(loaded, "figure:1")
    assert image == case.expected["image_bytes"]["figure:1"]
    retained = catalog.read(
        case.receiver, case.importer.store, state.report["proposal_ids"][0],
        expected_native=native(case.receiver.journal.path),
    )
    assert retained.content == case.expected
    assert "Keep full fourth caption" in dialog.evidence.toPlainText()


def test_actual_general_review_sql_failure_preserves_research_then_retry_once(
    actual_ui, monkeypatch
):
    state, case = actual_ui, actual_ui.case
    dialog = open_review(state)
    verify(state, dialog)
    before = case.receiver.journal.pending()
    receipt = dialog.service._receipt

    def fail(*args, **kwargs):
        receipt(*args, **kwargs)
        raise sqlite3.OperationalError("Synthetic native receipt failure after actual insert")

    monkeypatch.setattr(dialog.service, "_receipt", fail)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes
    )
    dialog.apply.click()
    settle(state.app, lambda: not dialog.busy and not dialog.jobs)
    assert "Synthetic native receipt failure" in dialog.status.text()
    assert case.receiver.journal.pending() == before and dialog.apply.isEnabled()
    with closing(sqlite3.connect(case.receiver.journal.path)) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_review_receipts'"
        ).fetchone()
        assert not exists or conn.execute(
            "SELECT count(*) FROM research_review_receipts"
        ).fetchone() == (0,)
    monkeypatch.setattr(dialog.service, "_receipt", receipt)
    dialog.apply.click()
    settle(state.app, lambda: not dialog.busy and not dialog.jobs)
    assert dialog.status.text() == dialog.words["saved"]
    assert len(case.receiver.journal.pending()) == len(before) + 1


def test_closing_during_real_general_apply_materialization_does_not_publish(actual_ui, monkeypatch):
    state, case = actual_ui, actual_ui.case
    dialog = open_review(state)
    verify(state, dialog)
    before = case.receiver.journal.pending()
    admitted, release = threading.Event(), threading.Event()
    materialize = helper.materialize

    def held(*args, **kwargs):
        admitted.set()
        assert release.wait(20)
        return materialize(*args, **kwargs)

    monkeypatch.setattr(helper, "materialize", held)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes
    )
    dialog.apply.click()
    try:
        settle(state.app, admitted.is_set)
        assert dialog.busy
        jobs = [job[0] for job in dialog.jobs]
        dialog.close()
        assert dialog.disposed and dialog.service.closed
    finally:
        release.set()
    settle(state.app, lambda: all(future.done() for future in jobs))
    assert case.receiver.journal.pending() == before
    value = catalog.read(
        case.receiver, case.importer.store, state.report["proposal_ids"][0],
        expected_native=native(case.receiver.journal.path),
    )
    assert value.content == case.expected
