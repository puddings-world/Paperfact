import os
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from paper_daily import feedback, llm


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    return tmp_path


@pytest.fixture
def app(workspace):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    instance = QApplication.instance() or QApplication([])
    yield instance
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    instance.processEvents()


def test_unanswered_notice_creates_no_tracking_identity(workspace):
    assert feedback.should_ask()
    assert feedback.consent() is None
    assert not feedback.path().exists()


def test_decline_without_reminder_is_not_consent_and_policy_scoped(workspace, monkeypatch):
    feedback.set_consent(False, dont_ask=True)
    assert not feedback.should_ask()
    feedback.record("ui.action", "list_overview")
    assert feedback.local_snapshot()["events"] == []
    assert feedback.consent() is None
    monkeypatch.setattr(feedback, "POLICY", "different-purpose-v2")
    assert feedback.should_ask() and feedback.consent() is None


def test_later_snoozes_instead_of_nagging_every_launch(workspace):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    feedback.set_consent(False, dont_ask=False, at=start)
    assert not feedback.should_ask(at=start + timedelta(days=29))
    assert feedback.should_ask(at=start + timedelta(days=30))
    assert feedback.consent() is None


def test_changed_policy_stops_recording_until_fresh_acceptance(workspace, monkeypatch):
    feedback.set_consent(True)
    old = feedback.consent()
    feedback.record("ui.action", "list_overview")
    monkeypatch.setattr(feedback, "POLICY", "different-purpose-v2")
    feedback.record("ui.action", "list_overview")
    assert feedback.consent() is None and feedback.should_ask()
    assert feedback.local_snapshot()["events"] == []
    feedback.set_consent(True)
    current = feedback.consent()
    assert current["policy"] == feedback.POLICY
    assert current["participant_id"] != old["participant_id"]
    assert feedback.local_snapshot()["events"] == []
    feedback.record("ui.action", "ai_settings")
    assert len(feedback.local_snapshot()["events"]) == 1
    feedback.set_consent(True)
    assert feedback.consent() == current
    assert not feedback.should_ask()


def test_invitation_requires_explicit_tick_and_acceptance(app):
    from paper_daily.desktop.feedback_dialog import FeedbackConsentDialog

    dialog = FeedbackConsentDialog()
    assert not dialog.enabled.isChecked() and not dialog.agree.isEnabled()
    dialog.accept()
    assert feedback.consent() is None
    dialog.enabled.setChecked(True)
    dialog.agree.click()
    saved = feedback.consent()
    assert saved and not feedback.should_ask()
    dialog.agree.click()
    dialog.reject()
    assert feedback.consent() == saved
    dialog.deleteLater()


def test_close_or_skip_with_tick_does_not_accept(app):
    from paper_daily.desktop.feedback_dialog import FeedbackConsentDialog

    dialog = FeedbackConsentDialog()
    dialog.enabled.setChecked(True)
    dialog.dont_ask.setChecked(True)
    dialog.show()
    dialog.close()
    assert feedback.consent() is None and not feedback.should_ask()
    dialog.deleteLater()


def test_save_failure_stays_disabled_and_does_not_block_reader(app, monkeypatch):
    from paper_daily.desktop.feedback_dialog import FeedbackConsentDialog

    dialog = FeedbackConsentDialog()
    dialog.enabled.setChecked(True)
    monkeypatch.setattr(feedback, "set_consent", lambda *a, **k: (_ for _ in ()).throw(
        sqlite3.OperationalError("fixture disk full")
    ))
    dialog.accept()
    assert feedback.consent() is None and "未儲存" in dialog.status.text()
    dialog.reject()
    assert dialog.result() == dialog.DialogCode.Rejected
    dialog.deleteLater()


def test_lifecycle_invitation_is_single_and_decline_persists(app):
    from PySide6.QtWidgets import QWidget

    from paper_daily.desktop.feedback_dialog import FeedbackInvitation

    window = QWidget()
    window.show()
    invitation = FeedbackInvitation(window)
    invitation.show_if_needed()
    first = invitation.dialog
    invitation.show_if_needed()
    assert first is not None and invitation.dialog is first
    first.dont_ask.setChecked(True)
    first.skip.click()
    assert invitation.dialog is None
    second = FeedbackInvitation(window)
    second.show_if_needed()
    assert second.dialog is None
    window.close()
    window.deleteLater()


def test_withdrawal_while_file_chooser_open_prevents_export(app, workspace, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from paper_daily.desktop.feedback_dialog import FeedbackDialog

    feedback.set_consent(True)
    feedback.record("ui.action", "ai_settings")
    widget = FeedbackDialog()
    destination = workspace / "must-not-exist.json"

    def withdraw(*_args):
        feedback.set_consent(False)
        return str(destination), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", withdraw)
    widget.export_preview()
    assert not destination.exists()
    assert "未匯出" in widget.status.text()
    widget.deleteLater()
