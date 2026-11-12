"""Regression boundaries exposed by the source mapping integration checks."""

import pytest
from PySide6.QtCore import QTimer
from test_archived_draft_resumption import copied as copied
from test_archived_draft_resumption import decision as decision
from test_archived_draft_resumption import draft_variants as draft_variants
from test_archived_draft_resumption import rows
from test_archived_draft_resumption import source as source
from test_local_source_owners import import_owned
from test_local_source_owners import receiver as receiver
from test_note_draft_resumption import recovered_note as recovered_note
from test_note_draft_resumption_ui import choose_target, note_view
from test_package_import import package as package
from test_package_import import rich_package as rich_package
from test_resumed_draft_original_ui import source_view
from test_review_dialog import app as app
from test_review_dialog import wait

from paper_daily import local_source_owners, sync_recovery
from paper_daily.desktop import original_version


def test_unrepresentable_current_backup_reports_recovery_error_and_keeps_prior_backup(
    rich_package, receiver, tmp_path
):
    import_owned(rich_package, receiver)
    owned = local_source_owners.list_owned(receiver[0])
    incomplete = tmp_path / "must-not-publish-incomplete.zip"
    with pytest.raises(sync_recovery.RecoveryError, match="complete migration"):
        sync_recovery.create(receiver[0], incomplete)
    assert not incomplete.exists()
    output = tmp_path / "keep-prior-backup.zip"
    output.write_bytes(b"Prior independent backup remains untouched")
    with pytest.raises(sync_recovery.RecoveryError, match="new backup filename"):
        sync_recovery.create(receiver[0], output)
    assert output.read_bytes() == b"Prior independent backup remains untouched"
    assert local_source_owners.list_owned(receiver[0]) == owned


def test_open_original_saves_the_pending_manual_draft_before_source_capture(
    recovered_note, app, monkeypatch
):
    value = recovered_note
    view = note_view(app, value)
    actual, admitted = original_version.prepare_resumed_draft, []
    try:
        QTimer.singleShot(0, choose_target)
        view.resume_button.click()
        wait(app, lambda: view.preview is not None and view.apply.isEnabled(), timeout=20)
        view.draft.setPlainText("Pending manual text before viewing its original")

        def prepare(*args, **kwargs):
            bodies = rows(value["path"], "SELECT body FROM research_review_drafts")
            admitted.append(bodies)
            if ("Pending manual text before viewing its original",) not in bodies:
                raise ValueError("Pending human draft was not durably saved before opening")
            return actual(*args, **kwargs)

        monkeypatch.setattr(original_version, "prepare_resumed_draft", prepare)
        for _ in range(20):
            view.originals.button.click()
        viewer = source_view(app, view)
        assert len(admitted) == 1 and viewer.snapshot.document_hash == value["source_a"]
        assert view.draft.toPlainText() == "Pending manual text before viewing its original"
        assert not view.dirty and not view.draft_errors
    finally:
        view.close()
        wait(app, lambda: view.disposed, timeout=20)
