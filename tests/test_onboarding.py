import sqlite3

import pytest

from paper_daily import feedback, llm, onboarding


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    return tmp_path


@pytest.fixture
def app(workspace):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_usage_acknowledgement_does_not_require_analytics(workspace):
    assert not onboarding.accepted() and not feedback.path().exists()
    onboarding.accept(analytics=False)
    assert onboarding.accepted() and feedback.consent() is None
    assert not feedback.should_ask()
    feedback.record("ui.action", "list_overview")
    assert feedback.local_snapshot()["events"] == []


def test_withdrawal_and_policy_changes_are_independent(workspace, monkeypatch):
    onboarding.accept(analytics=True)
    assert onboarding.accepted() and feedback.consent()
    feedback.set_consent(False)
    assert onboarding.accepted() and feedback.consent() is None
    monkeypatch.setattr(feedback, "POLICY", "new-feedback-purpose")
    assert onboarding.accepted() and feedback.should_ask()
    monkeypatch.setattr(onboarding, "POLICY", "new-usage-policy")
    assert not onboarding.accepted()


def test_both_choices_are_atomic_on_storage_failure(workspace, monkeypatch):
    def fail(db, *args):
        db.execute("INSERT INTO notice VALUES ('fixture', 'fixture', 1)")
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(feedback, "_save_choice", fail)
    with pytest.raises(sqlite3.OperationalError):
        onboarding.accept(analytics=True)
    assert not onboarding.accepted() and feedback.consent() is None
    with sqlite3.connect(feedback.path()) as db:
        assert db.execute("SELECT count(*) FROM notice").fetchone()[0] == 0


def test_analytics_checkbox_alone_cannot_enter_app(app):
    from paper_daily.desktop.onboarding_dialog import UsageDialog

    dialog = UsageDialog()
    assert not dialog.required.isChecked() and not dialog.analytics.isChecked()
    dialog.analytics.setChecked(True)
    dialog.accept()
    assert not dialog.start.isEnabled()
    assert not onboarding.accepted() and feedback.consent() is None
    dialog.reject()
    assert not feedback.path().exists()
    dialog.deleteLater()


@pytest.mark.parametrize("analytics", [False, True])
def test_first_use_accepts_only_explicit_choices_and_does_not_repeat(app, analytics):
    from paper_daily.desktop.onboarding_dialog import UsageDialog, ensure_accepted

    dialog = UsageDialog()
    dialog.required.setChecked(True)
    dialog.analytics.setChecked(analytics)
    dialog.start.click()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert ensure_accepted() and bool(feedback.consent()) is analytics
    saved = feedback.consent()
    dialog.analytics.setChecked(not analytics)
    dialog.accept()
    assert feedback.consent() == saved
    dialog.deleteLater()


def test_save_failure_leaves_gate_open_and_allows_retry(app, monkeypatch):
    from paper_daily.desktop.onboarding_dialog import UsageDialog

    dialog = UsageDialog()
    dialog.required.setChecked(True)
    original = onboarding.accept

    def fail(**kwargs):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(onboarding, "accept", fail)
    dialog.start.click()
    assert "未儲存" in dialog.status.text() and not onboarding.accepted()
    monkeypatch.setattr(onboarding, "accept", original)
    dialog.start.click()
    assert onboarding.accepted()
    dialog.deleteLater()


def test_closing_gate_does_not_accept_and_startup_can_exit(app):
    from paper_daily.desktop.onboarding_dialog import ensure_accepted

    visible = []

    def show(dialog):
        visible.append(dialog.isVisible())
        dialog.reject()

    assert not ensure_accepted(show=show)
    assert visible == [True]
    assert not onboarding.accepted() and feedback.consent() is None
