"""Actual report-source audit buttons use one background job and preserve saved research."""

from threading import Event

import pytest
from test_survey import conn as conn
from test_survey_audit import snapshot
from test_survey_evidence_ui import app as app
from test_survey_evidence_ui import wait_until
from test_survey_jobs import ready as ready
from test_survey_package_local import local as local
from test_survey_packages import exported as exported
from test_survey_publication import prepared as prepared
from test_survey_reader import saved as saved
from test_sync_capture import bound as bound

from paper_daily import store, survey_audit
from paper_daily.desktop.main import LIGHT
from paper_daily.desktop.survey_dialog import SurveyDialog


def test_audit_click_checks_sources_and_preserves_visible_report(saved, app, monkeypatch):
    database, list_id, _report = saved
    monkeypatch.setattr(store, "DB_PATH", database)
    dialog = SurveyDialog(list_id, "Research", LIGHT, language="en")
    pane = dialog.saved_report
    dialog.show()
    try:
        wait_until(lambda: pane.future is None)
        before, visible = snapshot(database), pane.view.toPlainText()
        assert pane.audit_sources.isEnabled()
        pane.audit_sources.click()
        pane.audit_sources.click()
        assert not pane.audit_sources.isEnabled()
        wait_until(lambda: pane.future is None)
        assert "Originals verified:" in pane.status.text(), pane.status.text()
        assert "Scientific support was not checked" in pane.status.text()
        assert pane.audit_sources.isEnabled() and pane.view.toPlainText() == visible
        assert snapshot(database) == before
    finally:
        dialog.close()
        wait_until(lambda: pane.disposed)
        dialog.deleteLater()


@pytest.mark.parametrize("action", ["close", "workspace"])
def test_close_or_workspace_change_drops_late_audit(saved, app, monkeypatch, tmp_path, action):
    database, list_id, _report = saved
    monkeypatch.setattr(store, "DB_PATH", database)
    entered, release = Event(), Event()
    actual, calls = survey_audit.audit, []

    def delayed(*args, **kwargs):
        calls.append(True)
        entered.set()
        assert release.wait(3)
        return actual(*args, **kwargs)

    monkeypatch.setattr(survey_audit, "audit", delayed)
    dialog = SurveyDialog(list_id, "Research", LIGHT, language="en")
    pane = dialog.saved_report
    dialog.show()
    try:
        wait_until(lambda: pane.future is None)
        before = snapshot(database)
        pane.audit_sources.click()
        wait_until(entered.is_set)
        pane.check_sources()
        if action == "close":
            assert not dialog.close()
        else:
            monkeypatch.setattr(store, "DB_PATH", tmp_path / "other.db")
        release.set()
        if action == "close":
            wait_until(lambda: pane.disposed)
        else:
            wait_until(lambda: pane.future is None)
            assert pane.saved is None and "Originals verified:" not in pane.status.text()
        assert len(calls) == 1 and snapshot(database) == before
    finally:
        release.set()
        dialog.close()
        wait_until(lambda: pane.disposed)
        dialog.deleteLater()
