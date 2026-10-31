"""Explicit appraisal UI never spends from reads and retains completed work on close."""

import threading
import time
from contextlib import closing
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QPlainTextEdit, QWidget
from test_audit_appraisal import response
from test_claim_jobs import claims as claims_fixture
from test_claim_jobs import job as claim_job
from test_claim_jobs import ready as ready_fixture
from test_claim_jobs import workspace as workspace_fixture

from paper_daily import audit_inputs, llm, manual_highlight_ops
from paper_daily.desktop.appraisal_dialog import TEXT, AppraisalDialog

workspace = workspace_fixture
ready = ready_fixture
claims = claims_fixture


def wait(app, condition, seconds=20):
    end = time.monotonic() + seconds
    while not condition() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert condition()


@pytest.fixture
def view(claims, monkeypatch, tmp_path):
    claim_job(claims).run()
    database = claims[0][0]
    document = claims[0][2]
    owner = manual_highlight_ops.capture_owner(database, "paper")
    captured = audit_inputs.AuditCapture.capture(database, "paper", document=document, owner=owner)
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    question = QLineEdit("Unsent question", parent)
    note = QPlainTextEdit("Unsent note", parent)
    active = [database, "paper", document]
    calls = []

    def complete(prompt, **kw):
        calls.append(1)
        return response(prompt, **kw)

    monkeypatch.setattr(llm, "complete_result", complete)
    dialog = AppraisalDialog(
        captured,
        owner=owner,
        current_view=lambda: tuple(active),
        archive_root=tmp_path / "derived-cache",
        language="en",
        parent=parent,
    )
    dialog.show()
    wait(app, lambda: not dialog.busy and dialog.status.text() != TEXT["en"]["loading"])
    yield SimpleNamespace(
        d=dialog,
        app=app,
        parent=parent,
        active=active,
        capture=captured,
        calls=calls,
        question=question,
        note=note,
        complete=complete,
    )
    if dialog.busy:
        dialog.cancel()
        wait(app, lambda: not dialog.busy)
    if dialog.unsaved is not None:
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Discard
        )
    dialog.close()
    parent.close()
    dialog.deleteLater()
    parent.deleteLater()
    app.processEvents()


def test_open_and_load_are_free_then_one_review_is_saved_and_reopens_without_ai(view):
    d = view.d
    assert view.calls == [] and d.status.text() == TEXT["en"]["empty"]
    assert d.review_button.isEnabled()
    assert d.review() and not d.review()
    wait(view.app, lambda: not d.busy)
    assert view.calls == [1] and d.report is not None and d.unsaved is None
    report = d.report
    assert d.status.text() == TEXT["en"]["ready"]
    d.load()
    wait(view.app, lambda: not d.busy)
    assert d.report == report and view.calls == [1]
    assert view.question.text() == "Unsent question" and view.note.toPlainText() == "Unsent note"


def test_empty_selection_never_starts_a_job(view):
    for check in view.d.checks.values():
        check.setChecked(False)
    assert not view.d.review_button.isEnabled() and view.d.review() is False
    assert view.calls == []


def test_failed_model_keeps_existing_review_and_retry_is_explicit(view, monkeypatch):
    from paper_daily.ai_types import Completion

    d = view.d
    d.review()
    wait(view.app, lambda: not d.busy)
    old = d.report
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **kw: Completion(None, reason="private failure details")
    )
    d.review()
    wait(view.app, lambda: not d.busy)
    assert d.report is old and d.status.text() == TEXT["en"]["failed"]
    assert "private failure details" not in d.status.text()
    monkeypatch.setattr(llm, "complete_result", view.complete)
    d.review()
    wait(view.app, lambda: not d.busy)
    assert len(view.calls) == 2 and d.report is not old


@pytest.mark.parametrize("scope", ["cancel", "close", "switch", "saved-change"])
def test_inflight_cancel_close_or_changed_context_retains_original_report_without_more_calls(
    view, monkeypatch, scope
):
    entered, release = threading.Event(), threading.Event()
    d = view.d

    def pending(prompt, **kw):
        entered.set()
        release.wait(10)
        return view.complete(prompt, **kw)

    monkeypatch.setattr(llm, "complete_result", pending)
    try:
        assert d.review()
        wait(view.app, entered.is_set)
        if scope == "cancel":
            d.cancel()
        elif scope == "close":
            assert d.close() is False and not d.disposed
        elif scope == "switch":
            view.active[1] = "another"
        else:
            from paper_daily import research_generation

            with closing(research_generation._connect(view.capture.database)) as conn, conn:
                conn.execute(
                    "INSERT INTO notes(paper_id,body,kind,created_at) "
                    "VALUES('paper','A newly saved research note','note',"
                    "'2026-10-30T00:00:00+00:00')"
                )
        release.set()
        wait(view.app, lambda: not d.busy)
        assert len(view.calls) == 1 and d.report is not None and d.unsaved is None
        assert d.report["source"] == view.capture.snapshot.source
        assert len(d.archive._files()) == 1
        if scope == "close":
            assert d.disposed
        assert (
            view.question.text() == "Unsent question" and view.note.toPlainText() == "Unsent note"
        )
    finally:
        release.set()


def test_failed_local_save_can_retry_without_another_model_call_or_implicit_discard(
    view, monkeypatch
):
    d = view.d
    actual = d.archive.save
    monkeypatch.setattr(
        d.archive, "save", lambda *a, **kw: (_ for _ in ()).throw(OSError("fixture full disk"))
    )
    d.review()
    wait(view.app, lambda: not d.busy)
    assert d.unsaved is not None and d.report is d.unsaved and len(view.calls) == 1
    assert not d.review_button.isEnabled() and d.save_button.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Cancel)
    assert not d.close() and not d.disposed
    monkeypatch.setattr(d.archive, "save", actual)
    assert d.save()
    wait(view.app, lambda: not d.busy)
    assert d.unsaved is None and len(view.calls) == 1 and d.status.text() == TEXT["en"]["ready"]


def test_task_picker_is_explicit_and_scoped_to_audit(view, monkeypatch):
    from paper_daily.desktop import ai_picker

    scopes = []

    class Picker:
        def __init__(self, parent, *, task):
            scopes.append(task)

        def exec(self):
            return 0

        def deleteLater(self):
            pass

    monkeypatch.setattr(ai_picker, "AIPickerDialog", Picker)
    view.d.settings()
    assert scopes == ["audit"] and view.calls == []


@pytest.mark.parametrize("change", ["none", "paper"])
def test_source_navigation_rechecks_real_owner_and_rejects_late_view(view, monkeypatch, change):
    from paper_daily.desktop import appraisal_dialog

    d = view.d
    navigated = []
    d.source_callback = lambda value: navigated.append(value) or True
    d.review()
    wait(view.app, lambda: not d.busy)
    assert d.source_buttons
    passage = next(
        p for f in d.report["findings"] for p in f["evidence"] if p["state"] == "located"
    )
    verify = appraisal_dialog.verify_source
    observations = []
    entered, release = threading.Event(), threading.Event()

    def pending(*args):
        entered.set()
        assert release.wait(10)
        before = d.capture.current()
        value = verify(*args)
        observations.append((before, value, d.capture.current()))
        return value

    monkeypatch.setattr(appraisal_dialog, "verify_source", pending)
    try:
        assert d.open_source(passage) and not d.open_source(passage)
        wait(view.app, entered.is_set)
        if change == "paper":
            view.active[1] = "another"
        release.set()
        wait(view.app, lambda: not d.busy)
        if change == "none":
            assert len(navigated) == 1, (observations, d.status.text(), d._invalid)
            assert navigated[0]["document_hash"] == d.report["source"]["document_hash"]
            assert navigated[0]["anchor"] == passage["anchor"]
        else:
            assert navigated == [] and d.status.text() == TEXT["en"]["source_failed"]
        assert view.calls == [1]
        assert view.question.text() == "Unsent question"
        assert view.note.toPlainText() == "Unsent note"
    finally:
        release.set()


def test_evidence_parent_reuses_child_and_drains_active_review_before_close(view, monkeypatch):
    from paper_daily.desktop import appraisal_dialog
    from paper_daily.desktop.research_audit import AuditDialog

    monkeypatch.setattr(appraisal_dialog, "default_root", lambda: view.d.archive.root)
    parent = AuditDialog(
        view.capture.database,
        "paper",
        document=view.capture.snapshot._origin,
        owner=view.d.owner,
        current_view=lambda: tuple(view.active),
        language="en",
        capture=lambda *a, **kw: view.capture,
    )
    child = None
    entered, release = threading.Event(), threading.Event()

    def pending(prompt, **kw):
        entered.set()
        assert release.wait(10)
        return view.complete(prompt, **kw)

    monkeypatch.setattr(llm, "complete_result", pending)
    try:
        parent.show()
        wait(view.app, lambda: parent.report is not None and not parent.busy)
        assert parent.appraisal_button.isEnabled() and view.calls == []
        child = parent.open_appraisal()
        assert child is parent.open_appraisal()
        wait(
            view.app,
            lambda: not child.busy and child.status.text() != TEXT["en"]["loading"],
        )
        assert view.calls == []
        assert child.review()
        wait(view.app, entered.is_set)
        assert parent.close() is False and not parent.disposed and not child.disposed
        release.set()
        wait(view.app, lambda: parent.disposed and child.disposed)
        assert len(view.calls) == 1 and child.unsaved is None
        assert len(child.archive._files()) == 1
        assert view.question.text() == "Unsent question"
        assert view.note.toPlainText() == "Unsent note"
    finally:
        release.set()
        if child is not None and child.busy:
            wait(view.app, lambda: not child.busy)
        parent.close()
        parent.deleteLater()
        view.app.processEvents()


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_compact_bilingual_claim_disclosure_is_keyboard_operable_and_free(view, language):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    d = AppraisalDialog(
        view.capture,
        owner=view.d.owner,
        language=language,
        archive_root=view.d.archive.root,
    )
    try:
        d.resize(440, 760)
        d.show()
        wait(view.app, lambda: not d.busy and d.status.text() != TEXT[language]["loading"])
        assert d.width() == 440
        assert d.selection.body.isVisible()
        d.selection.button.setFocus()
        QTest.keyClick(d.selection.button, Qt.Key.Key_Return)
        assert not d.selection.body.isVisible()
        QTest.keyClick(d.selection.button, Qt.Key.Key_Return)
        assert d.selection.body.isVisible()
        assert d.review_button.isEnabled() and view.calls == []
        assert d.selection.button.text() == TEXT[language]["selection"]
    finally:
        d.close()
        d.deleteLater()
        view.app.processEvents()
