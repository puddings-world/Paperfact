"""Real Qt close/reopen and storage-failure behavior for durable review drafts."""

import sqlite3
from contextlib import closing

from PySide6.QtWidgets import QApplication
from test_research_review import candidate, context, output, query
from test_research_review import workspace as workspace  # noqa: F401
from test_review_dialog import app as app  # noqa: F401
from test_review_dialog import opened, wait

from paper_daily import research_generation as generation
from paper_daily.research_review import ResearchReview


def test_type_and_immediately_close_reopens_same_draft_and_base(app, workspace):
    path, client = workspace
    candidate(path)
    dialog = opened(app, path)
    observed = dialog.preview.data["expected"]
    before = client.journal.pending()
    dialog.draft.setPlainText("Typed just before close")
    assert dialog.dirty
    assert dialog.close()
    assert dialog.disposed
    reopened = opened(app, path)
    try:
        assert reopened.draft.toPlainText() == "Typed just before close"
        assert reopened.preview.data["expected"] == observed
        assert reopened.apply.isEnabled()
        assert client.journal.pending() == before
    finally:
        reopened.reject()


def test_restart_with_new_research_preserves_draft_and_requires_visible_refresh(app, workspace):
    path, _ = workspace
    candidate(path)
    dialog = opened(app, path)
    observed = dialog.preview.data["expected"]
    dialog.draft.setPlainText("Old-base user draft")
    dialog.reject()
    generation.publish_generation(context(path), row=output("Newer canonical text"))
    reopened = opened(app, path)
    try:
        assert reopened.draft.toPlainText() == "Old-base user draft"
        assert reopened.preview.data["expected"] == observed
        assert reopened.current.toPlainText() == "Current saved analysis"
        assert not reopened.apply.isEnabled()
        assert "review" in reopened.status.text().lower()
        reopened.refresh.click()
        wait(app, lambda: reopened.preview is not None)
        assert reopened.current.toPlainText() == "Newer canonical text"
        assert reopened.draft.toPlainText() == "Old-base user draft"
        assert reopened.apply.isEnabled()
    finally:
        reopened.reject()


def test_failed_close_keeps_window_and_text_until_retry_succeeds(app, workspace, monkeypatch):
    path, _ = workspace
    candidate(path)
    dialog = opened(app, path)
    dialog.draft.setPlainText("Never discard this text")
    original = dialog.service.save_draft

    def fail(*args, **kwargs):
        raise OSError("Fixture disk unavailable")

    monkeypatch.setattr(dialog.service, "save_draft", fail)
    assert not dialog.close()
    assert dialog.isVisible() and not dialog.disposed
    assert dialog.draft.toPlainText() == "Never discard this text"
    assert "not saved" in dialog.status.text()
    dialog.copy.click()
    assert "Never discard this text" in QApplication.clipboard().text()
    monkeypatch.setattr(dialog.service, "save_draft", original)
    assert dialog.close()
    reopened = opened(app, path)
    try:
        assert reopened.draft.toPlainText() == "Never discard this text"
    finally:
        reopened.reject()


def test_autosave_is_private_and_apply_after_restart_does_not_duplicate(app, workspace):
    path, client = workspace
    candidate(path)
    dialog = opened(app, path)
    before = len(client.journal.pending())
    dialog.draft.setPlainText("Autosaved draft")
    wait(app, lambda: not dialog.dirty)
    assert "saved locally" in dialog.status.text().lower()
    assert len(client.journal.pending()) == before
    dialog.reject()
    reopened = opened(app, path)
    reopened.apply.click()
    wait(app, lambda: not reopened.busy)
    assert query(path, "SELECT body FROM close_readings") == [("Autosaved draft",)]
    reopened.reject()
    third = opened(app, path)
    try:
        assert third.draft.toPlainText() == "Autosaved draft"
        assert not third.apply.isEnabled()
        assert "saved decision" in third.status.text()
        assert len(client.journal.pending()) == before + 1
    finally:
        third.reject()


def test_corrupt_draft_stays_exportable_without_becoming_an_apply_base(app, workspace):
    path, _ = workspace
    candidate(path)
    first = opened(app, path)
    first.draft.setPlainText("Recover this damaged-record text")
    first.reject()
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("UPDATE research_review_drafts SET fingerprint=?", ("f" * 64,))
        conn.commit()
    from paper_daily.desktop.review_dialog import ReviewDialog

    reopened = ReviewDialog(path)
    reopened.show()
    try:
        wait(app, lambda: reopened.corrupt_text is not None)
        assert reopened.draft.toPlainText() == "Recover this damaged-record text"
        assert not reopened.apply.isEnabled()
        assert reopened.draft.isReadOnly()
        reopened.copy.click()
        assert QApplication.clipboard().text() == "Recover this damaged-record text"
        assert "damaged" in reopened.status.text() or "copied" in reopened.status.text()
    finally:
        reopened.reject()


def test_two_open_windows_preserve_conflicting_draft_as_separate_copy(app, workspace):
    path, _ = workspace
    candidate(path)
    first = opened(app, path)
    first.draft.setPlainText("Initial durable draft")
    assert first._save_pending(all_items=True)
    second = opened(app, path)
    try:
        first.draft.setPlainText("First window revision")
        assert first._save_pending(all_items=True)
        second.draft.setPlainText("Second window revision")
        assert not second.close()
        assert second.isVisible()
        assert second.draft_copy.isVisible()
        second.draft_copy.click()
        assert not second.dirty
        assert {row[0] for row in query(path, "SELECT body FROM research_review_drafts")} == {
            "First window revision",
            "Second window revision",
        }
    finally:
        first.reject()
        second.reject()


def test_database_replacement_during_edit_prevents_close_and_allows_text_export(
    app, workspace, tmp_path
):
    path, _ = workspace
    candidate(path)
    dialog = opened(app, path)
    dialog.draft.setPlainText("Text from the original workspace")
    old = tmp_path / "old.db"
    path.rename(old)
    path.write_bytes(old.read_bytes())
    assert not dialog.close()
    assert dialog.isVisible() and dialog.draft.toPlainText() == "Text from the original workspace"
    destination = tmp_path / "recovered.txt"
    dialog.service.export(dialog.preview, destination, body=dialog.draft.toPlainText())
    assert "Text from the original workspace" in destination.read_text("utf-8")
    # Restore the original owned fixture to allow the close retry, without overwriting either DB.
    replacement = tmp_path / "replacement.db"
    path.rename(replacement)
    old.rename(path)
    assert dialog.close()
    assert (
        ResearchReview(path).load_draft("generation", dialog.selection_key[1])["body"]
        == "Text from the original workspace"
    )


def test_saved_variants_picker_reopens_older_text_without_rebasing(app, workspace, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from paper_daily.desktop.review_dialog import SavedDraftDialog

    path, _ = workspace
    identity = candidate(path)
    service = ResearchReview(path)
    preview = service.preview("generation", identity)
    old = service.save_draft(preview, "Earlier variant", "earlier")
    service.save_draft(preview, "Latest variant", "later")
    dialog = opened(app, path)
    try:
        assert dialog.draft.toPlainText() == "Latest variant"

        def choose_old(chooser):
            assert chooser.list.count() == 2
            chooser.list.setCurrentRow(1)
            chooser.choose()
            assert chooser.identity == old["draft_id"]
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(SavedDraftDialog, "exec", choose_old)
        dialog.draft_history.click()
        wait(app, lambda: dialog.preview is not None)
        assert dialog.draft.toPlainText() == "Earlier variant"
        assert dialog.preview.data["expected"] == preview.data["expected"]
        assert not dialog.dirty
    finally:
        dialog.reject()


def test_locked_database_close_fails_without_discard_and_retries(app, workspace):
    path, _ = workspace
    candidate(path)
    dialog = opened(app, path)
    dialog.draft.setPlainText("Draft blocked temporarily by another writer")
    with closing(sqlite3.connect(path)) as lock:
        lock.execute("BEGIN IMMEDIATE")
        assert not dialog.close()
        assert dialog.isVisible() and not dialog.disposed
        assert "not saved" in dialog.status.text()
        assert dialog.draft.toPlainText() == "Draft blocked temporarily by another writer"
        lock.rollback()
    assert dialog.close()
    assert (
        ResearchReview(path).load_draft("generation", dialog.selection_key[1])["body"]
        == "Draft blocked temporarily by another writer"
    )


def test_saved_draft_picker_keeps_multiline_excerpt_bounded_and_labels_plain(app, workspace):
    from PySide6.QtCore import Qt

    from paper_daily.desktop.review_dialog import LABELS, SavedDraftDialog

    path, _ = workspace
    identity = candidate(path)
    service = ResearchReview(path)
    preview = service.preview("generation", identity)
    service.save_draft(preview, "Line\n" * 30, "multiline")
    picker = SavedDraftDialog(service, "generation", identity, LABELS["en"])
    assert picker.list.item(0).text().count("\n") == 1
    picker.reject()
    dialog = opened(app, path)
    try:
        assert dialog.source.textFormat() == Qt.TextFormat.PlainText
        assert dialog.status.textFormat() == Qt.TextFormat.PlainText
    finally:
        dialog.reject()
