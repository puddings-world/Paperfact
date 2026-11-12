"""Real highlight fields, owned original reader and confirmed shared saves."""

import json
import threading

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from test_archived_draft_resume_ui import answer
from test_highlight_draft_verification import ready as ready
from test_highlight_draft_verification import scene as scene
from test_highlight_draft_verification import source_pair as source_pair
from test_highlight_draft_verification import workspace as workspace
from test_research_generation import rows
from test_review_dialog import app as app
from test_review_dialog import wait

from paper_daily.document_reader import DocumentReader

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


def editor(app, value, language="en"):
    from paper_daily.desktop.highlight_draft_dialog import HighlightDraftDialog

    dialog = HighlightDraftDialog(
        value["path"], "generation", value["original"].data["id"], language=language
    )
    dialog.show()
    wait(app, lambda: not dialog.busy, timeout=20)
    if dialog.preview is None:
        assert dialog.targets.count() == 2, dialog.status.text()
        dialog.targets.setCurrentIndex(1)
        dialog.choose.click()
        wait(app, lambda: dialog.preview is not None and not dialog.busy, timeout=20)
    return dialog


def close(app, dialog):
    dialog.close()
    wait(app, lambda: dialog.disposed, timeout=20)


def save(app, dialog):
    dialog.save.click()
    wait(app, lambda: not dialog.busy and not dialog.dirty, timeout=20)


def verify(app, dialog):
    dialog.verify.click()
    wait(app, lambda: not dialog.busy, timeout=20)
    assert dialog.verified, dialog.status.text()


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_real_fields_private_save_read_a_cancel_apply_continue_and_reopen(
    source_pair, app, language
):
    value = source_pair
    dialog = editor(app, value, language)
    try:
        assert not dialog.apply.isEnabled()
        assert "body_json" not in dialog.current.toPlainText()
        dialog.fields.reason.setPlainText("Human account of why the original comparison matters.")
        dialog.fields.role.setCurrentIndex(dialog.fields.role.findData("limitation"))
        for _ in range(10):
            dialog.save.click()
        wait(app, lambda: not dialog.busy and not dialog.dirty, timeout=20)
        drafts = rows(value["path"], "SELECT body FROM research_review_drafts")
        assert len(drafts) == 1
        assert json.loads(drafts[0]["body"])["items"][0]["kind"] == "limitation"
        before = rows(value["path"], "SELECT * FROM paper_highlight_analysis")
        # Independent original reading works before verification and never grants Apply.
        for _ in range(8):
            dialog.originals.button.click()
        wait(app, lambda: dialog.originals.viewer is not None, timeout=20)
        viewer = dialog.originals.viewer
        assert viewer.snapshot.document_hash == value["preview"].data["source_hash"]
        assert viewer.snapshot.data == value["original_bytes"]
        assert not dialog.apply.isEnabled()
        viewer.close()
        wait(app, lambda: dialog.originals.viewer is None, timeout=20)
        verify(app, dialog)
        assert dialog.apply.isEnabled()
        assert rows(value["path"], "SELECT * FROM paper_highlight_analysis") == before
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Cancel))
        dialog.apply.click()
        assert rows(value["path"], "SELECT * FROM paper_highlight_analysis") == before
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        dialog.apply.click()
        for _ in range(10):
            dialog.apply.click()
        wait(app, lambda: not dialog.busy, timeout=20)
        body = json.loads(
            rows(value["path"], "SELECT body_json FROM paper_highlight_analysis")[0]["body_json"]
        )
        assert body["items"][0]["reason"] == "Human account of why the original comparison matters."
        assert body["items"][0]["kind"] == "limitation"
        assert len(rows(value["path"], "SELECT * FROM research_review_receipts")) == 1
        assert not dialog.apply.isEnabled()
        # Application may advance the private CAS; later typing must still save.
        dialog.fields.reason.setPlainText(
            "Further private appraisal after accepting this revision."
        )
        save(app, dialog)
        assert len(rows(value["path"], "SELECT * FROM research_review_drafts")) == 1
        assert (
            DocumentReader.from_workspace(value["path"]).resolve("paper").sha256
            == value["current"].sha256
        )
    finally:
        close(app, dialog)
    reopened = editor(app, value, language)
    try:
        assert (
            reopened.fields.reason.toPlainText()
            == "Further private appraisal after accepting this revision."
        )
        assert not reopened.apply.isEnabled()
    finally:
        close(app, reopened)


def test_held_autosave_keeps_later_typing_and_close_drains_latest_words(
    source_pair, app, monkeypatch
):
    dialog = editor(app, source_pair)
    entered, release = threading.Event(), threading.Event()
    real = dialog.service.save_highlight_draft

    def held(*a, **k):
        entered.set()
        assert release.wait(20)
        return real(*a, **k)

    monkeypatch.setattr(dialog.service, "save_highlight_draft", held)
    try:
        dialog.fields.reason.setPlainText("First admitted private appraisal.")
        dialog.save.click()
        wait(app, entered.is_set)
        dialog.fields.reason.setPlainText(
            "Later typing must outlive an earlier save acknowledgment."
        )
        dialog.close()
        assert not dialog.disposed
        release.set()
        wait(app, lambda: dialog.disposed, timeout=20)
        body = json.loads(
            rows(source_pair["path"], "SELECT body FROM research_review_drafts")[0]["body"]
        )
        assert (
            body["items"][0]["reason"]
            == "Later typing must outlive an earlier save acknowledgment."
        )
    finally:
        release.set()
        if not dialog.disposed:
            close(app, dialog)


@pytest.mark.parametrize("closing", [False, True], ids=["cancel", "close"])
def test_held_verification_cancel_or_close_never_enables_late_apply(
    source_pair, app, monkeypatch, closing
):
    dialog = editor(app, source_pair)
    save(app, dialog)
    entered, release = threading.Event(), threading.Event()
    real = dialog.service.verify_highlight_draft

    def held(*a, **k):
        entered.set()
        assert release.wait(20)
        return real(*a, **k)

    monkeypatch.setattr(dialog.service, "verify_highlight_draft", held)
    before = rows(source_pair["path"], "SELECT * FROM paper_highlight_analysis")
    try:
        dialog.verify.click()
        wait(app, entered.is_set)
        if closing:
            dialog.close()
            assert not dialog.disposed
        else:
            dialog.cancel.click()
        release.set()
        wait(app, lambda: dialog.disposed if closing else not dialog.busy, timeout=20)
        assert not dialog.verified
        assert rows(source_pair["path"], "SELECT * FROM paper_highlight_analysis") == before
    finally:
        release.set()
        if not dialog.disposed:
            close(app, dialog)


def test_failed_private_save_retains_words_and_window_until_retry(source_pair, app, monkeypatch):
    dialog = editor(app, source_pair)
    try:
        dialog.fields.reason.setPlainText("Unsaved research judgment must remain available.")
        with monkeypatch.context() as patch:

            def failure(*a, **k):
                raise OSError("synthetic disk full")

            patch.setattr(dialog.service, "save_highlight_draft", failure)
            dialog.close()
            wait(app, lambda: not dialog.busy)
            assert not dialog.disposed and dialog.dirty
            assert "disk full" in dialog.status.text()
            assert (
                dialog.fields.reason.toPlainText()
                == "Unsaved research judgment must remain available."
            )
        close(app, dialog)
        assert (
            json.loads(
                rows(source_pair["path"], "SELECT body FROM research_review_drafts")[0]["body"]
            )["items"][0]["reason"]
            == "Unsaved research judgment must remain available."
        )
    finally:
        if not dialog.disposed:
            close(app, dialog)


def test_missing_quote_is_shown_as_unresolved_and_cannot_apply(source_pair, app):
    dialog = editor(app, source_pair)
    try:
        dialog.fields.quote.setPlainText("An invented conclusion absent from the actual original.")
        save(app, dialog)
        dialog.verify.click()
        wait(app, lambda: not dialog.busy, timeout=20)
        assert not dialog.apply.isEnabled()
        assert dialog.words["loc_missing"] in dialog.verification.toPlainText()
        assert (
            dialog.fields.quote.toPlainText()
            == "An invented conclusion absent from the actual original."
        )
        assert not rows(
            source_pair["path"],
            "SELECT name FROM sqlite_master WHERE name='research_review_receipts'",
        )
    finally:
        close(app, dialog)


def test_native_text_copy_paste_undo_select_all_and_explicit_occurrence(source_pair, app):
    dialog = editor(app, source_pair)
    try:
        target = dialog.fields.reason
        target.setFocus()
        original = target.toPlainText()
        QTest.keyClick(target, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(target, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        assert QApplication.clipboard().text() == original
        QTest.keyClicks(target, "Revised using native editing keys.")
        QTest.keyClick(target, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert target.toPlainText() == original
        QApplication.clipboard().setText("Pasted human research rationale.")
        QTest.keyClick(target, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(target, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        assert target.toPlainText() == "Pasted human research rationale."
        QTest.keyClick(target, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(target, Qt.Key.Key_Delete)
        assert target.toPlainText() == ""
        QTest.keyClick(target, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert target.toPlainText() == "Pasted human research rationale."
        QTest.keyClick(target, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        assert target.toPlainText() == ""
        QTest.keyClick(target, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        assert target.toPlainText() == "Pasted human research rationale."
        save(app, dialog)
        verify(app, dialog)
        report = dialog.service.highlight_draft_report(dialog.preview)
        anchor = report["marks"][0]["anchor"]
        unresolved = json.loads(json.dumps(report))
        unresolved["items"][0]["location"].update(
            state="ambiguous", candidates=[anchor], anchor=None
        )
        dialog.fields.set_report(unresolved)
        dialog.fields.occurrences.setCurrentIndex(1)
        assert dialog.fields.draft()["items"][0]["anchor"] == anchor
        save(app, dialog)
        verify(app, dialog)
        assert dialog.apply.isEnabled()
    finally:
        close(app, dialog)


def test_parent_review_has_named_highlight_entry_and_local_decision_refresh(source_pair, app):
    from paper_daily.desktop.review_dialog import ReviewDialog

    dialog = ReviewDialog(source_pair["path"], language="zh-TW")
    dialog.show()
    try:
        wait(app, lambda: dialog.preview is not None and not dialog.busy)
        found = next(
            i
            for i in range(dialog.list.count())
            if dialog.list.item(i).data(Qt.ItemDataRole.UserRole)[1]
            == source_pair["original"].data["id"]
        )
        dialog.list.setCurrentRow(found)
        wait(
            app,
            lambda: (
                not dialog.busy and dialog.selection_key[1] == source_pair["original"].data["id"]
            ),
        )
        assert dialog.resume_button.isVisible() and "重點" in dialog.resume_button.text()
        for _ in range(8):
            dialog.resume_button.click()
        wait(app, lambda: dialog.claim_editor is not None and not dialog.claim_editor.busy)
        child = dialog.claim_editor
        child.targets.setCurrentIndex(1)
        child.choose.click()
        wait(app, lambda: child.preview is not None and not child.busy)
        save(app, child)
        verify(app, child)
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        child.apply.click()
        wait(app, lambda: not child.busy)
        close(app, child)
        wait(app, lambda: dialog.words["decision_applied"] in dialog.list.item(found).text())
        assert dialog.list.currentRow() == found
    finally:
        dialog.close()
        wait(app, lambda: dialog.disposed)


def test_invalid_new_item_remains_editable_and_removal_restores_saving(source_pair, app):
    dialog = editor(app, source_pair)
    try:
        save(app, dialog)
        before = rows(source_pair["path"], "SELECT * FROM research_review_drafts")
        dialog.fields.add_item.click()
        assert len(dialog.fields.draft()["items"]) == 3
        dialog.fields.reason.setPlainText(
            "An incomplete new quotation is still private unsaved work."
        )
        dialog.save.click()
        wait(app, lambda: not dialog.busy)
        assert dialog.dirty and not dialog.apply.isEnabled()
        assert rows(source_pair["path"], "SELECT * FROM research_review_drafts") == before
        dialog.fields.remove_item.click()
        assert len(dialog.fields.draft()["items"]) == 2
        save(app, dialog)
    finally:
        close(app, dialog)


def test_late_original_after_manual_edit_cannot_open_or_lose_words(source_pair, app, monkeypatch):
    from paper_daily.desktop import original_version

    dialog = editor(app, source_pair)
    save(app, dialog)
    entered, release = threading.Event(), threading.Event()
    prepare = original_version.prepare_highlight_draft_read

    def held(*a, **k):
        entered.set()
        assert release.wait(20)
        return prepare(*a, **k)

    monkeypatch.setattr(original_version, "prepare_highlight_draft_read", held)
    try:
        dialog.originals.button.click()
        wait(app, entered.is_set)
        assert dialog.progress.isVisible() and dialog.cancel.isEnabled()
        dialog.fields.reason.setPlainText("New text while original A was being prepared.")
        release.set()
        wait(app, lambda: not dialog.jobs and not dialog.busy, timeout=20)
        assert dialog.originals.viewer is None
        assert not dialog.verified and not dialog.apply.isEnabled()
        assert dialog.fields.reason.toPlainText() == "New text while original A was being prepared."
    finally:
        release.set()
        close(app, dialog)


@pytest.mark.parametrize("closing", [False, True], ids=["cancel", "close"])
def test_held_confirmed_apply_can_cancel_without_writing_research(
    source_pair, app, monkeypatch, closing
):
    dialog = editor(app, source_pair)
    save(app, dialog)
    verify(app, dialog)
    entered, release = threading.Event(), threading.Event()
    apply = dialog.service.apply_highlight_draft
    before = rows(source_pair["path"], "SELECT * FROM paper_highlight_analysis")
    drafts = rows(source_pair["path"], "SELECT * FROM research_review_drafts")

    def held(*a, **k):
        entered.set()
        assert release.wait(20)
        return apply(*a, **k)

    monkeypatch.setattr(dialog.service, "apply_highlight_draft", held)
    try:
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        dialog.apply.click()
        wait(app, entered.is_set)
        assert dialog.cancel.isEnabled()
        if closing:
            dialog.close()
            assert not dialog.disposed
        else:
            dialog.cancel.click()
        release.set()
        wait(app, lambda: dialog.disposed if closing else not dialog.busy, timeout=20)
        assert rows(source_pair["path"], "SELECT * FROM paper_highlight_analysis") == before
        assert rows(source_pair["path"], "SELECT * FROM research_review_drafts") == drafts
        assert not rows(
            source_pair["path"],
            "SELECT name FROM sqlite_master WHERE name='research_review_receipts'",
        )
    finally:
        release.set()
        if not dialog.disposed:
            close(app, dialog)


def test_failed_group_receipt_keeps_exact_editor_and_allows_same_request_retry(
    source_pair, app, monkeypatch
):
    from paper_daily.research_review import ResearchReview

    dialog = editor(app, source_pair)
    try:
        dialog.fields.reason.setPlainText(
            "Keep this exact reviewed content through a failed commit."
        )
        save(app, dialog)
        verify(app, dialog)
        before = rows(source_pair["path"], "SELECT * FROM paper_highlight_analysis")
        with monkeypatch.context() as patch:

            def failure(*a, **k):
                raise OSError("decision disk full")

            patch.setattr(ResearchReview, "_receipt", staticmethod(failure))
            QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
            dialog.apply.click()
            wait(app, lambda: not dialog.busy, timeout=20)
            assert rows(source_pair["path"], "SELECT * FROM paper_highlight_analysis") == before
            assert "disk full" in dialog.status.text() and dialog.apply.isEnabled()
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        dialog.apply.click()
        wait(app, lambda: not dialog.busy, timeout=20)
        saved = json.loads(
            rows(source_pair["path"], "SELECT body_json FROM paper_highlight_analysis")[0][
                "body_json"
            ]
        )
        assert (
            saved["items"][0]["reason"]
            == "Keep this exact reviewed content through a failed commit."
        )
        assert len(rows(source_pair["path"], "SELECT * FROM research_review_receipts")) == 1
    finally:
        close(app, dialog)


@pytest.mark.parametrize(
    "language,width", [("en", 980), ("en", 620), ("zh-TW", 980), ("zh-TW", 620)]
)
def test_real_editor_layout_labels_and_actions_fit_both_widths(source_pair, app, language, width):
    import os
    from pathlib import Path

    dialog = editor(app, source_pair, language)
    try:
        dialog.resize(width, 840)
        save(app, dialog)
        verify(app, dialog)
        app.processEvents()
        assert dialog.width() <= width
        for button in (
            dialog.save,
            dialog.verify,
            dialog.apply,
            dialog.copy,
            dialog.close_button,
            dialog.originals.button,
        ):
            assert button.isVisible()
            position = button.mapTo(dialog, button.rect().center())
            assert dialog.rect().contains(position), button.text()
        assert dialog.fields.quote.isVisible() and dialog.fields.reason.isVisible()
        assert dialog.apply.isEnabled()
        capture = os.environ.get("PAPERFACT_UI_CAPTURE")
        if capture:
            destination = Path(capture)
            destination.mkdir(parents=True, exist_ok=True)
            assert dialog.grab().save(str(destination / f"highlight-editor-{language}-{width}.png"))
    finally:
        close(app, dialog)


def test_highlight_original_gui_admission_is_native_only_and_cannot_be_a_claim_grant(
    source_pair, monkeypatch
):
    import copy
    import sqlite3

    from paper_daily.desktop import original_version

    value = source_pair
    snapshot = original_version.prepare_highlight_draft_read(
        value["review"], value["preview"], value["preview"].data["source_hash"]
    )
    assert snapshot is not None and snapshot.data == value["original_bytes"]
    with monkeypatch.context() as patch:

        def forbidden(*a, **k):
            pytest.fail("GUI admission performed SQL or PDF parsing")

        patch.setattr(sqlite3, "connect", forbidden)
        patch.setattr(original_version.pymupdf, "open", forbidden)
        for _ in range(12):
            assert original_version.metadata_current(snapshot)
            assert original_version.highlight_read_status(snapshot) == "ready"
            assert original_version.claim_read_status(snapshot) == "revoked"
    forged = copy.copy(snapshot)
    object.__setattr__(forged, "claim_read_proof", snapshot.highlight_read_proof)
    object.__setattr__(forged, "highlight_read_proof", None)
    assert not original_version.metadata_current(forged)
    assert original_version.claim_read_status(forged) == "revoked"


def test_deleted_mark_requires_an_explicit_restore_control_before_native_apply(source_pair, app):
    from test_highlight_generation import change_mark

    value = source_pair
    change_mark(value["path"], delete=True)
    dialog = editor(app, value)
    try:
        save(app, dialog)
        verify(app, dialog)
        assert dialog.restore.isVisible() and not dialog.restore.isChecked()
        assert not dialog.apply.isEnabled()
        dialog.restore.setChecked(True)
        assert dialog.apply.isEnabled()
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        dialog.apply.click()
        wait(app, lambda: not dialog.busy, timeout=20)
        assert len(rows(value["path"], "SELECT * FROM pdf_ai_highlights")) == 2
        assert len(rows(value["path"], "SELECT * FROM research_review_receipts")) == 1
    finally:
        close(app, dialog)


def test_cancel_original_read_shows_activity_then_drains_without_a_viewer(
    source_pair, app, monkeypatch
):
    from paper_daily.desktop import original_version

    dialog = editor(app, source_pair)
    save(app, dialog)
    entered, release = threading.Event(), threading.Event()
    prepare = original_version.prepare_highlight_draft_read

    def held(*a, **k):
        entered.set()
        assert release.wait(20)
        return prepare(*a, **k)

    monkeypatch.setattr(original_version, "prepare_highlight_draft_read", held)
    try:
        dialog.originals.button.click()
        wait(app, entered.is_set)
        assert dialog.progress.isVisible() and dialog.cancel.isEnabled()
        dialog.cancel.click()
        assert not dialog.cancel.isEnabled()
        release.set()
        wait(app, lambda: not dialog.jobs and not dialog.originals.opening, timeout=20)
        assert dialog.originals.viewer is None and not dialog.progress.isVisible()
        assert dialog.words["cancelled"] in dialog.status.text()
        assert not dialog.apply.isEnabled()
    finally:
        release.set()
        close(app, dialog)


def test_successful_apply_carries_private_revision_without_a_post_commit_read(
    source_pair, app, monkeypatch
):
    dialog = editor(app, source_pair)
    try:
        save(app, dialog)
        verify(app, dialog)
        with monkeypatch.context() as patch:

            def no_post_read(*a, **k):
                raise OSError("A successful commit must not depend on a second read")

            patch.setattr(dialog.service, "load_highlight_draft", no_post_read)
            QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
            dialog.apply.click()
            wait(app, lambda: not dialog.busy, timeout=20)
            assert dialog.status.text() == dialog.words["applied"]
        actual = rows(source_pair["path"], "SELECT revision FROM research_review_drafts")[0][
            "revision"
        ]
        assert dialog.persisted["revision"] == actual
        dialog.fields.reason.setPlainText(
            "Private changes can continue after the atomic acknowledgment."
        )
        save(app, dialog)
        assert (
            json.loads(
                rows(source_pair["path"], "SELECT body FROM research_review_drafts")[0]["body"]
            )["items"][0]["reason"]
            == "Private changes can continue after the atomic acknowledgment."
        )
    finally:
        close(app, dialog)
