"""A packaged first-use smoke run must close without accepting for the user."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog

from paper_daily import feedback, llm, onboarding
from paper_daily.desktop.main import _finish_smoke
from paper_daily.desktop.onboarding_dialog import UsageDialog


def test_smoke_deadline_closes_first_use_without_granting_consent(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, 'SETTINGS_PATH', tmp_path / 'llm.json')
    app = QApplication.instance() or QApplication([])
    dialog = UsageDialog()
    QTimer.singleShot(10, lambda: _finish_smoke(app))
    assert dialog.exec() == QDialog.DialogCode.Rejected
    assert not onboarding.accepted()
    assert feedback.consent() is None
