"""Real claim fields, private writes and confirmed application, no paid providers."""

import json
import threading

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMessageBox
from test_archived_draft_resume_ui import answer
from test_claim_draft_application import claims as claims
from test_claim_draft_application import ready as ready
from test_claim_draft_application import receiver as receiver
from test_claim_draft_application import scene as scene
from test_claim_draft_application import source_pair as source_pair
from test_claim_draft_application import workspace as workspace
from test_claim_draft_storage import rows
from test_review_dialog import app as app
from test_review_dialog import opened, wait

from paper_daily.desktop.claim_draft_dialog import ClaimDraftDialog
from paper_daily.document_reader import DocumentReader

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


def editor(app, value, language="en"):
    dialog = ClaimDraftDialog(
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


def closed(app, dialog):
    dialog.close()
    wait(app, lambda: dialog.disposed, timeout=20)


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_fields_save_verify_original_cancel_confirm_apply_and_reopen(source_pair, app, language):
    value = source_pair
    dialog = editor(app, value, language)
    try:
        assert not dialog.apply.isEnabled()
        assert "body_json" not in dialog.current.toPlainText()
        dialog.fields.assertion.setPlainText("Human claim edited through real fields.")
        dialog.fields.reason.setPlainText("Its comparator is useful but support needs appraisal.")
        for _ in range(10):
            dialog.save.click()
        wait(app, lambda: not dialog.busy and not dialog.dirty, timeout=20)
        saved = rows(value["path"], "SELECT body FROM research_review_drafts")
        assert len(saved) == 1
        assert (
            json.loads(saved[0]["body"])["claims"][0]["text"]
            == "Human claim edited through real fields."
        )
        before = rows(value["path"], "SELECT * FROM paper_claim_sets")
        for _ in range(10):
            dialog.verify.click()
        wait(app, lambda: not dialog.busy, timeout=25)
        assert dialog.apply.isEnabled(), dialog.status.text()
        assert rows(value["path"], "SELECT * FROM paper_claim_sets") == before
        assert dialog.words["not_semantic"] in dialog.verification.toPlainText()
        assert dialog.originals.widget.isVisible()
        dialog.originals.button.click()
        wait(app, lambda: dialog.originals.viewer is not None, timeout=20)
        assert dialog.originals.viewer.snapshot.document_hash == value["source_hash"]
        assert (
            DocumentReader.from_workspace(value["path"]).resolve("paper").sha256
            == value["current"].sha256
        )
        dialog.originals.viewer.close()
        wait(app, lambda: dialog.originals.viewer is None, timeout=20)
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Cancel))
        dialog.apply.click()
        assert rows(value["path"], "SELECT * FROM paper_claim_sets") == before
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        dialog.apply.click()
        for _ in range(10):
            dialog.apply.click()
        wait(app, lambda: not dialog.busy, timeout=20)
        body = json.loads(
            rows(value["path"], "SELECT body_json FROM paper_claim_sets")[0]["body_json"]
        )
        assert body["report"]["claims"][0]["text"] == "Human claim edited through real fields."
        assert body["generation"]["backend"] == "manual"
        assert rows(value["path"], "SELECT count(*) AS n FROM research_review_receipts") == [
            dict(n=1)
        ]
        assert not dialog.apply.isEnabled()
    finally:
        closed(app, dialog)
    reopened = editor(app, value, language)
    try:
        assert reopened.fields.assertion.toPlainText() == "Human claim edited through real fields."
        assert not reopened.apply.isEnabled()
    finally:
        closed(app, reopened)


def test_private_save_failure_keeps_window_and_text_until_retry(source_pair, app, monkeypatch):
    value = source_pair
    dialog = editor(app, value)
    save = dialog.service.save_claim_draft
    try:
        dialog.fields.assertion.setPlainText("Do not lose these unsaved words.")
        with monkeypatch.context() as patch:
            patch.setattr(
                dialog.service,
                "save_claim_draft",
                lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
            )
            dialog.close()
            wait(app, lambda: not dialog.busy)
            assert not dialog.disposed and dialog.isVisible()
            assert "disk full" in dialog.status.text()
            assert dialog.fields.assertion.toPlainText() == "Do not lose these unsaved words."
            assert dialog.dirty
        assert dialog.service.save_claim_draft == save
        closed(app, dialog)
        assert (
            json.loads(rows(value["path"], "SELECT body FROM research_review_drafts")[0]["body"])[
                "claims"
            ][0]["text"]
            == "Do not lose these unsaved words."
        )
    finally:
        if not dialog.disposed:
            closed(app, dialog)


def test_close_waits_for_admitted_private_save_and_retains_it(source_pair, app, monkeypatch):
    dialog = editor(app, source_pair)
    entered, release = threading.Event(), threading.Event()
    save = dialog.service.save_claim_draft

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(20)
        return save(*args, **kwargs)

    monkeypatch.setattr(dialog.service, "save_claim_draft", held)
    try:
        dialog.fields.assertion.setPlainText("Admitted private work must finish.")
        dialog.save.click()
        wait(app, entered.is_set)
        dialog.close()
        assert not dialog.disposed
        release.set()
        wait(app, lambda: dialog.disposed, timeout=20)
        assert (
            json.loads(
                rows(source_pair["path"], "SELECT body FROM research_review_drafts")[0]["body"]
            )["claims"][0]["text"]
            == "Admitted private work must finish."
        )
    finally:
        release.set()
        if not dialog.disposed:
            closed(app, dialog)


@pytest.mark.parametrize("closing", [False, True], ids=["cancel", "close"])
def test_held_verification_is_cancelled_without_late_apply(source_pair, app, monkeypatch, closing):
    dialog = editor(app, source_pair)
    entered, release = threading.Event(), threading.Event()
    verify = dialog.service.verify_claim_draft

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(20)
        return verify(*args, **kwargs)

    monkeypatch.setattr(dialog.service, "verify_claim_draft", held)
    before = rows(source_pair["path"], "SELECT * FROM paper_claim_sets")
    try:
        dialog.verify.click()
        wait(app, entered.is_set)
        assert not dialog.choose.isEnabled() and not dialog.apply.isEnabled()
        if closing:
            dialog.close()
            assert not dialog.disposed
        else:
            dialog.cancel.click()
        release.set()
        wait(app, lambda: dialog.disposed if closing else not dialog.busy, timeout=20)
        assert rows(source_pair["path"], "SELECT * FROM paper_claim_sets") == before
        assert not dialog.apply.isEnabled()
    finally:
        release.set()
        if not dialog.disposed:
            closed(app, dialog)


def test_review_entry_opens_one_typed_editor_and_host_close_drains_it(source_pair, app):
    value = source_pair
    host = opened(app, value["path"])
    try:
        identity = value["original"].data["id"]
        index = next(
            i
            for i in range(host.list.count())
            if tuple(host.list.item(i).data(Qt.ItemDataRole.UserRole)) == ("generation", identity)
        )
        host.list.setCurrentRow(index)
        wait(app, lambda: host.preview is not None and host.preview.data["id"] == identity)
        assert host.claim_button.isEnabled()
        for _ in range(10):
            host.claim_button.click()
        dialog = host.claim_editor
        wait(app, lambda: not dialog.busy, timeout=20)
        assert host.findChildren(ClaimDraftDialog) == [dialog]
        host.close()
        wait(app, lambda: host.disposed and dialog.disposed, timeout=20)
    finally:
        host.close()


def test_typing_during_background_private_save_preserves_later_words(source_pair, app, monkeypatch):
    dialog = editor(app, source_pair)
    entered, release = threading.Event(), threading.Event()
    save = dialog.service.save_claim_draft

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(20)
        return save(*args, **kwargs)

    monkeypatch.setattr(dialog.service, "save_claim_draft", held)
    try:
        dialog.fields.assertion.setPlainText("First words entering the pending save.")
        dialog.save.click()
        wait(app, entered.is_set)
        assert dialog.fields.isEnabled()
        dialog.fields.assertion.setPlainText("Later words typed while saving must survive.")
        release.set()
        wait(app, lambda: not dialog.busy and not dialog.dirty, timeout=20)
        saved = rows(source_pair["path"], "SELECT body,revision FROM research_review_drafts")
        assert len(saved) == 1 and saved[0]["revision"] == 2
        assert (
            json.loads(saved[0]["body"])["claims"][0]["text"]
            == "Later words typed while saving must survive."
        )
        assert (
            dialog.fields.assertion.toPlainText() == "Later words typed while saving must survive."
        )
    finally:
        release.set()
        closed(app, dialog)


def test_two_private_variants_can_be_loaded_without_rebasing_or_applying(source_pair, app):
    dialog = editor(app, source_pair)
    before = rows(source_pair["path"], "SELECT * FROM paper_claim_sets")
    try:
        dialog.fields.assertion.setPlainText("First independently saved interpretation.")
        dialog.save.click()
        wait(app, lambda: not dialog.busy and not dialog.dirty)
        first = dialog.persisted["draft_id"]
        expected = dialog.preview.data["expected"]
        dialog.separate.click()
        wait(app, lambda: not dialog.busy and not dialog.dirty)
        assert dialog.persisted["draft_id"] != first
        dialog.fields.assertion.setPlainText("Second independently saved interpretation.")
        dialog.save.click()
        wait(app, lambda: not dialog.busy and not dialog.dirty)
        assert dialog.variants.count() == 2
        dialog.variants.setCurrentIndex(dialog.variants.findData(first))
        dialog.load.click()
        wait(app, lambda: not dialog.busy)
        assert dialog.fields.assertion.toPlainText() == "First independently saved interpretation."
        assert dialog.preview.data["expected"] == expected
        assert rows(source_pair["path"], "SELECT * FROM paper_claim_sets") == before
    finally:
        closed(app, dialog)


def test_incomplete_field_cannot_close_or_erase_research_and_can_be_repaired(source_pair, app):
    dialog = editor(app, source_pair)
    before = rows(source_pair["path"], "SELECT * FROM paper_claim_sets")
    try:
        dialog.fields.assertion.clear()
        dialog.close()
        wait(app, lambda: not dialog.busy)
        assert dialog.isVisible() and not dialog.disposed and dialog.dirty
        assert dialog.fields.assertion.toPlainText() == ""
        assert rows(source_pair["path"], "SELECT * FROM paper_claim_sets") == before
        dialog.fields.assertion.setPlainText("Repaired draft after an incomplete edit.")
        closed(app, dialog)
        assert (
            json.loads(
                rows(source_pair["path"], "SELECT body FROM research_review_drafts")[0]["body"]
            )["claims"][0]["text"]
            == "Repaired draft after an incomplete edit."
        )
    finally:
        if not dialog.disposed:
            closed(app, dialog)


def test_field_keys_and_quote_changes_do_not_carry_old_coordinates(source_pair, app):
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest

    dialog = editor(app, source_pair)
    try:
        original = dialog.fields.assertion.toPlainText()
        dialog.fields.assertion.setFocus()
        QTest.keySequence(dialog.fields.assertion, QKeySequence.SelectAll)
        QTest.keyClicks(dialog.fields.assertion, "Keyboard editing works")
        QTest.keySequence(dialog.fields.assertion, QKeySequence.Undo)
        assert dialog.fields.assertion.toPlainText() == original
        QTest.keySequence(dialog.fields.assertion, QKeySequence.Redo)
        assert dialog.fields.assertion.toPlainText() == "Keyboard editing works"
        dialog.fields.quote.setPlainText("A newly edited quotation must be located again.")
        assert dialog.fields.draft()["claims"][0]["passages"][0]["anchor"] is None
        dialog.copy.click()
        from PySide6.QtWidgets import QApplication

        assert "Keyboard editing works" in QApplication.clipboard().text()
        assert "A newly edited quotation" in QApplication.clipboard().text()
    finally:
        closed(app, dialog)


def test_load_save_verify_and_original_admission_do_not_do_sql_or_pdf_work_on_gui(
    source_pair, app, monkeypatch
):
    import sqlite3

    import pymupdf

    gui = threading.get_ident()
    connect, open_pdf = sqlite3.connect, pymupdf.open

    def safe_connect(*args, **kwargs):
        assert threading.get_ident() != gui, "SQL ran on the GUI thread"
        return connect(*args, **kwargs)

    def safe_pdf(*args, **kwargs):
        assert threading.get_ident() != gui, "PDF parsing ran on the GUI thread"
        return open_pdf(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", safe_connect)
        patch.setattr(pymupdf, "open", safe_pdf)
        dialog = editor(app, source_pair)
        try:
            dialog.verify.click()
            wait(app, lambda: not dialog.busy, timeout=25)
            assert dialog.apply.isEnabled(), dialog.status.text()
            dialog.originals.button.click()
            wait(app, lambda: dialog.originals.viewer is not None, timeout=20)
            dialog.originals.viewer.close()
            wait(app, lambda: dialog.originals.viewer is None, timeout=20)
        finally:
            closed(app, dialog)


def test_restored_claim_editor_verifies_its_own_original_and_keeps_b(receiver, app):
    value = receiver
    dialog = ClaimDraftDialog(
        value["path"], "archived_draft", value["preview"].data["id"], language="zh-TW"
    )
    dialog.show()
    wait(app, lambda: not dialog.busy, timeout=20)
    try:
        dialog.targets.setCurrentIndex(1)
        dialog.choose.click()
        wait(app, lambda: dialog.preview is not None and not dialog.busy, timeout=20)
        dialog.fields.assertion.setPlainText(
            "Recovered structured revision through real Qt fields."
        )
        dialog.verify.click()
        wait(app, lambda: not dialog.busy, timeout=25)
        assert dialog.apply.isEnabled(), dialog.status.text()
        dialog.originals.button.click()
        wait(app, lambda: dialog.originals.viewer is not None, timeout=20)
        assert dialog.originals.viewer.snapshot.document_hash == value["source_hash"]
        dialog.originals.viewer.close()
        wait(app, lambda: dialog.originals.viewer is None, timeout=20)
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        dialog.apply.click()
        wait(app, lambda: not dialog.busy, timeout=20)
        body = json.loads(
            rows(value["path"], "SELECT body_json FROM paper_claim_sets")[0]["body_json"]
        )
        assert (
            body["report"]["claims"][0]["text"]
            == "Recovered structured revision through real Qt fields."
        )
        assert body["report"]["source"]["document_hash"] == value["source_hash"]
        assert (
            DocumentReader.from_workspace(value["path"])
            .resolve(value["preview"].data["expected"]["paper_id"])
            .sha256
            == value["current"].sha256
        )
    finally:
        closed(app, dialog)


def test_replacing_workspace_during_native_verification_keeps_text_without_delivery(
    source_pair, app, monkeypatch
):
    import sqlite3
    from contextlib import closing

    value = source_pair
    dialog = editor(app, value)
    entered, release = threading.Event(), threading.Event()
    verify = dialog.service.verify_claim_draft

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(20)
        return verify(*args, **kwargs)

    monkeypatch.setattr(dialog.service, "verify_claim_draft", held)
    try:
        dialog.fields.assertion.setPlainText("Text remains visible when the database is replaced.")
        dialog.verify.click()
        wait(app, entered.is_set)
        replacement = value["path"].with_suffix(".new.sqlite")
        with (
            closing(sqlite3.connect(value["path"])) as old,
            closing(sqlite3.connect(replacement)) as new,
        ):
            old.backup(new)
        replacement.replace(value["path"])
        before = rows(value["path"], "SELECT * FROM paper_claim_sets")
        release.set()
        wait(app, lambda: not dialog.busy, timeout=20)
        assert not dialog.apply.isEnabled()
        assert (
            dialog.fields.assertion.toPlainText()
            == "Text remains visible when the database is replaced."
        )
        assert rows(value["path"], "SELECT * FROM paper_claim_sets") == before
    finally:
        release.set()
        closed(app, dialog)


def test_older_private_variants_are_reachable_through_bounded_pages(source_pair, app, monkeypatch):
    dialog = editor(app, source_pair)
    listing = dialog.service.list_drafts

    def small_page(origin, identity, **options):
        options["limit"] = 2
        return listing(origin, identity, **options)

    monkeypatch.setattr(dialog.service, "list_drafts", small_page)
    try:
        dialog.fields.assertion.setPlainText("The oldest of three private interpretations.")
        dialog.save.click()
        wait(app, lambda: not dialog.busy and not dialog.dirty)
        first = dialog.persisted["draft_id"]
        for number in range(2):
            dialog.separate.click()
            wait(app, lambda: not dialog.busy and not dialog.dirty)
            dialog.fields.assertion.setPlainText("Later private interpretation " + str(number))
            dialog.save.click()
            wait(app, lambda: not dialog.busy and not dialog.dirty)
        assert dialog.variants.findData(first) == -1
        dialog.variants.setCurrentIndex(dialog.variants.count() - 1)
        dialog.load.click()
        wait(app, lambda: not dialog.busy)
        assert dialog.variants.findData(first) >= 0
        dialog.variants.setCurrentIndex(dialog.variants.findData(first))
        dialog.load.click()
        wait(app, lambda: not dialog.busy)
        assert (
            dialog.fields.assertion.toPlainText() == "The oldest of three private interpretations."
        )
    finally:
        closed(app, dialog)


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_native_claim_layout_keeps_actions_reachable_at_two_widths(source_pair, app, language):
    from pathlib import Path

    from PySide6.QtCore import QPoint

    dialog = editor(app, source_pair, language)
    try:
        dialog.verify.click()
        wait(app, lambda: not dialog.busy, timeout=25)
        assert dialog.apply.isEnabled(), dialog.status.text()
        for width, label in ((980, "wide"), (620, "narrow")):
            dialog.resize(width, 780)
            app.processEvents()
            assert dialog.width() == width
            for control in (
                dialog.save,
                dialog.verify,
                dialog.apply,
                dialog.copy,
                dialog.cancel,
                dialog.close_button,
                dialog.targets,
                dialog.choose,
                dialog.more,
            ):
                position = control.mapTo(dialog, QPoint(0, 0))
                assert position.x() >= 0 and position.x() + control.width() <= dialog.width()
                assert position.y() >= 0 and position.y() + control.height() <= dialog.height()
            output = (
                Path(__file__).resolve().parents[1]
                / "build"
                / f"claim-editor-{language}-{label}.png"
            )
            assert dialog.grab().save(str(output))
    finally:
        closed(app, dialog)


def test_unsaved_proposal_is_not_listed_as_a_stored_variant(source_pair, app):
    dialog = editor(app, source_pair)
    try:
        assert dialog.persisted.get("revision") is None
        assert dialog.variants.count() == 0
        assert not dialog.load.isEnabled()
        dialog.verify.click()
        wait(app, lambda: not dialog.busy, timeout=25)
        assert dialog.variants.count() == 1
        assert dialog.variants.currentData() == dialog.persisted["draft_id"]
        assert dialog.persisted["revision"] == 1
    finally:
        closed(app, dialog)


def test_claim_review_entry_shows_readable_words_before_opening_editor(source_pair, app):
    value = source_pair
    host = opened(app, value["path"], language="zh-TW")
    try:
        identity = value["original"].data["id"]
        index = next(
            i
            for i in range(host.list.count())
            if tuple(host.list.item(i).data(Qt.ItemDataRole.UserRole)) == ("generation", identity)
        )
        host.list.setCurrentRow(index)
        wait(app, lambda: host.preview is not None and host.preview.data["id"] == identity)
        assert "Retained original-A proposal" in host.draft.toPlainText()
        assert "body_json" not in host.draft.toPlainText()
        assert "generation" not in host.draft.toPlainText()
        assert "原文引句" in host.draft.toPlainText()
        quotation = json.loads(value["body"])["claims"][0]["passages"][0]["quote"]
        assert quotation in host.draft.toPlainText()
        assert host.draft.isReadOnly()
        assert host.words["claim_reason"] in host.status.text()
        assert not host.apply.isEnabled() and host.claim_button.isEnabled()
    finally:
        host.close()
        wait(app, lambda: host.disposed)


def test_autosave_retries_if_its_timer_expires_during_history_refresh(
    source_pair, app, monkeypatch
):
    dialog = editor(app, source_pair)
    entered, release = threading.Event(), threading.Event()
    listing = dialog.service.list_drafts

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(20)
        return listing(*args, **kwargs)

    monkeypatch.setattr(dialog.service, "list_drafts", held)
    try:
        dialog.fields.assertion.setPlainText("First privately saved words.")
        dialog.save.click()
        wait(app, entered.is_set)
        assert dialog.fields.isEnabled()
        dialog.fields.assertion.setPlainText("Later words survive a busy history refresh.")
        dialog.autosave.stop()
        dialog.autosave.timeout.emit()
        release.set()
        wait(app, lambda: not dialog.busy and not dialog.dirty, timeout=5)
        saved = rows(source_pair["path"], "SELECT body,revision FROM research_review_drafts")
        assert len(saved) == 1 and saved[0]["revision"] == 2
        assert (
            json.loads(saved[0]["body"])["claims"][0]["text"]
            == "Later words survive a busy history refresh."
        )
    finally:
        release.set()
        closed(app, dialog)


def test_add_remove_and_external_reference_fields_save_complete_private_content(source_pair, app):
    from PySide6.QtTest import QTest
    from test_highlight_generation import QUOTES

    dialog = editor(app, source_pair)
    try:
        original = dialog.fields.draft()["claims"][0]
        before = rows(source_pair["path"], "SELECT * FROM paper_claim_sets")
        dialog.fields.add_claim.click()
        dialog.fields.assertion.setPlainText("A second explicitly edited research assertion.")
        dialog.fields.reason.setPlainText("Compare the matched-budget control.")
        dialog.fields.add_passage.click()
        dialog.fields.quote.setPlainText(QUOTES[1])
        dialog.fields.page.setValue(1)
        dialog.fields.external.setChecked(True)
        dialog.fields.citation_title.setFocus()
        QTest.keyClicks(dialog.fields.citation_title, "External comparison study")
        dialog.fields.doi.setFocus()
        QTest.keyClicks(dialog.fields.doi, "10.1234/fixture")
        dialog.save.click()
        wait(app, lambda: not dialog.busy and not dialog.dirty)
        saved = json.loads(
            rows(source_pair["path"], "SELECT body FROM research_review_drafts")[0]["body"]
        )
        assert len(saved["claims"]) == 2 and saved["claims"][0] == original
        second = saved["claims"][1]
        assert second["text"] == "A second explicitly edited research assertion."
        assert second["judgment"]["reason"] == "Compare the matched-budget control."
        assert second["passages"] == [
            dict(
                quote=QUOTES[1],
                page=1,
                anchor=None,
                citation=dict(
                    paper_id=None, title="External comparison study", doi="10.1234/fixture"
                ),
            )
        ]
        assert rows(source_pair["path"], "SELECT * FROM paper_claim_sets") == before
        dialog.fields.remove_passage.click()
        dialog.fields.remove_claim.click()
        assert not dialog.fields.remove_claim.isEnabled()
        dialog.fields.remove_claim.click()
        dialog.save.click()
        wait(app, lambda: not dialog.busy and not dialog.dirty)
        saved = json.loads(
            rows(source_pair["path"], "SELECT body FROM research_review_drafts")[0]["body"]
        )
        assert saved["claims"] == [original]
        assert rows(source_pair["path"], "SELECT * FROM paper_claim_sets") == before
    finally:
        closed(app, dialog)


def test_field_collection_controls_bound_repeated_clicks_and_empty_selection(source_pair, app):
    from paper_daily.desktop.claim_draft_dialog import LABELS
    from paper_daily.desktop.claim_fields import ClaimFields

    fields = ClaimFields({key: pair[0] for key, pair in LABELS.items()})
    try:
        fields.add_claim.click()
        fields.add_passage.click()
        fields.remove_claim.click()
        fields.remove_passage.click()
        assert fields.value is None
        fields.set_draft(json.loads(source_pair["body"]))
        for _ in range(60):
            fields.add_claim.click()
        assert len(fields.draft()["claims"]) == 16 and not fields.add_claim.isEnabled()
        for _ in range(60):
            fields.remove_claim.click()
        assert len(fields.draft()["claims"]) == 1 and not fields.remove_claim.isEnabled()
        for _ in range(60):
            fields.add_passage.click()
        assert len(fields.draft()["claims"][0]["passages"]) == 48
        assert not fields.add_passage.isEnabled()
        for _ in range(60):
            fields.remove_passage.click()
        assert fields.draft()["claims"][0]["passages"] == []
        assert not fields.remove_passage.isEnabled()
    finally:
        fields.close()
