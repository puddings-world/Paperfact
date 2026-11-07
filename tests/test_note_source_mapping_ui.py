"""A researcher can repair a recovered note's source in the actual Qt review UI."""

import json
import threading

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from test_archived_draft_resume_ui import answer
from test_archived_draft_resumption import client_for
from test_archived_draft_resumption import copied as copied
from test_archived_draft_resumption import decision as decision
from test_archived_draft_resumption import draft_variants as draft_variants
from test_archived_draft_resumption import source as source
from test_note_draft_resumption import recovered_note as recovered_note
from test_note_draft_resumption_edges import note_rows, selected, stored
from test_note_draft_resumption_ui import choose_target, note_view
from test_note_source_mapping import UNKNOWN, picked
from test_review_dialog import app as app
from test_review_dialog import wait

from paper_daily.desktop.note_source_dialog import (
    NoteSourceDialog,
    selectable_text,
    selected_words,
)


def test_qt_utf16_selection_maps_astral_text_and_raw_word_gaps_without_off_by_one():
    page = {
        "page": 2,
        "document_hash": "a" * 64,
        "words": [
            {"order": 1, "text": "研究😀"},
            {"order": 7, "text": "paper"},
        ],
    }
    text, spans = selectable_text(page["words"])
    assert text == "研究😀 paper" and spans == [(0, 4, 1), (5, 10, 7)]
    anchor, quote = selected_words(page, spans, 5, 10)
    assert anchor == dict(p0=2, o0=7, p1=2, o1=7, document_hash="a" * 64)
    assert quote == "paper"
    assert selected_words(page, spans, 4, 5) == (None, "")


@pytest.mark.parametrize("recovered_note", [UNKNOWN], indirect=True)
@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_note_ui_selects_original_passage_preserves_edit_cancel_and_confirms_exact_source(
    recovered_note, tmp_path, app, monkeypatch, language
):
    value = recovered_note
    source = picked(value, tmp_path)
    view = note_view(app, value, language)
    errors, confirmations = [], []
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), "PDF"))
    try:
        QTimer.singleShot(0, choose_target)
        view.resume_button.click()
        wait(
            app,
            lambda: (
                view.preview is not None and view.preview.data["origin"] == "archived_note_resume"
            ),
        )
        assert not view.apply.isEnabled() and view.map_note_button.isEnabled()
        view.draft.setPlainText("My edited interpretation survives mapping")

        def configure(cancel=False):
            dialog = QApplication.activeModalWidget()
            try:
                assert isinstance(dialog, NoteSourceDialog)
                assert dialog.words["unknown"] in dialog.recorded.text()
                if cancel:
                    dialog.cancel.click()
                    return
                dialog.pick.click()
                for _ in range(8):
                    dialog.pick.click()
                wait(app, lambda: dialog.page_data is not None and dialog.future is None)
                assert dialog.text.toPlainText() == "A verified source paper"
                assert not dialog.image.pixmap().isNull()
                assert dialog.image.pixmap().width() <= dialog.image.width()
                dialog.text.selectAll()
                assert (
                    dialog.use.isEnabled()
                    and dialog.quote.toPlainText() == "A verified source paper"
                )
                if language == "zh-TW":
                    assert dialog.grab().save(str(tmp_path / "note-source-choice.png"))
                dialog.use.click()
                for _ in range(8):
                    dialog.use.click()
            except BaseException as error:
                errors.append(error)
                dialog.reject()

        QTimer.singleShot(0, lambda: configure(cancel=True))
        view.map_note_button.click()
        assert not errors and view.preview.data["source_hash"] is None
        assert view.draft.toPlainText() == "My edited interpretation survives mapping"
        QTimer.singleShot(0, configure)
        view.map_note_button.click()
        assert not errors, errors
        wait(app, lambda: view.preview is not None and view.apply.isEnabled(), timeout=20)
        assert view.draft.toPlainText() == "My edited interpretation survives mapping"
        assert view.preview.data["source_hash"] == value["source_a"]
        assert (
            view.words["recorded_note"].format(source=view.words["unknown_source"])
            in view.source.text()
        )
        assert (
            stored(value) == before and client_for(value["path"]).journal.pending(1000) == pending
        )
        if language == "zh-TW":
            assert view.grab().save(str(tmp_path / "note-source-review.png"))
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Cancel))
        view.apply.click()
        assert stored(value) == before

        def confirm():
            box = QApplication.activeModalWidget()
            confirmations.append(box.text())
            answer(QMessageBox.StandardButton.Yes)

        QTimer.singleShot(0, confirm)
        view.apply.click()
        wait(app, lambda: not view.busy, timeout=20)
        assert value["source_a"] in confirmations[0]
        assert "A verified source paper" in confirmations[0]
        row = note_rows(value, "body,anchor")[0]
        assert row[0] == "My edited interpretation survives mapping"
        assert json.loads(row[1])["selection"]["quote"] == "A verified source paper"
    finally:
        view.close()
        wait(app, lambda: view.disposed, timeout=20)


def test_source_dialog_held_close_drains_one_worker_without_late_choice(
    recovered_note, tmp_path, app, monkeypatch
):
    value, review = recovered_note, recovered_note["review"]
    preview = selected(value)
    before, pending = stored(value), client_for(value["path"]).journal.pending(1000)
    source = picked(value, tmp_path)
    entered, release = threading.Event(), threading.Event()
    native = review.inspect_note_source
    calls = []

    def inspect(*args, **kwargs):
        calls.append(True)
        entered.set()
        assert release.wait(15)
        return native(*args, **kwargs)

    monkeypatch.setattr(review, "inspect_note_source", inspect)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), "PDF"))
    dialog = NoteSourceDialog(review, preview)
    dialog.show()
    try:
        dialog.pick.click()
        wait(app, entered.is_set)
        for _ in range(8):
            dialog.pick.click()
        dialog.close()
        assert dialog.closing and not dialog.disposed
        release.set()
        wait(app, lambda: dialog.disposed)
        assert calls == [True] and dialog.result_preview is None
        assert (
            stored(value) == before and client_for(value["path"]).journal.pending(1000) == pending
        )
    finally:
        release.set()
        dialog.close()
        wait(app, lambda: dialog.disposed)
        review.close()
