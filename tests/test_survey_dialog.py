"""The list survey dialog: a running rewrite and a saved topic roadmap are respected."""

import sys
import time

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox, QVBoxLayout, QWidget
from test_workspace_transfer_ui import workspace as _workspace

from paper_daily import runtime, store, survey
from paper_daily.desktop import survey_dialog
from paper_daily.desktop.activity import ActivityHub, begin
from paper_daily.desktop.main import LIGHT
from paper_daily.desktop.survey_dialog import SurveyDialog

workspace = _workspace


@pytest.fixture
def owner(workspace):
    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('x','Research','now')")
        conn.execute(
            "INSERT INTO list_surveys(list_id,body,papers,spec,written_at,edited) "
            "VALUES ('x','# 研究路線',1,?,'2026-10-01T00:00',0)",
            (survey.ROADMAP_SPEC,),
        )
        conn.commit()
    window = QWidget()
    window.pal = LIGHT
    QVBoxLayout(window)
    window.activity_hub = ActivityHub(window)
    yield window
    for job in list(window.activity_hub.jobs.values()):
        window.activity_hub.finish(job.token, cancelled=True)
    window.close()
    window.deleteLater()


def test_a_reopened_dialog_shows_the_rewrite_still_running(owner):
    handle = begin(owner, "撰寫清單綜覽", key="survey:x")
    dialog = SurveyDialog("x", "Research", LIGHT, owner)
    assert not dialog.run_btn.isEnabled() and dialog.run_btn.text() == "撰寫中…"
    assert dialog.edit_btn.isHidden()
    assert "正在撰寫" in dialog.status.text()
    handle.finish(True)
    assert dialog.run_btn.isEnabled() and not dialog.edit_btn.isHidden()
    dialog.close()


def test_rewriting_a_topic_roadmap_asks_first(owner, monkeypatch):
    launched = []
    monkeypatch.setattr(
        runtime, "cli_command",
        lambda *args: launched.append(args) or [sys.executable, "-c", "pass"],
    )
    dialog = SurveyDialog("x", "Research", LIGHT, owner)
    monkeypatch.setattr(
        survey_dialog.QMessageBox, "question",
        lambda *a: QMessageBox.StandardButton.No,
    )
    dialog._run_ready()
    assert launched == [] and dialog.job is None

    monkeypatch.setattr(
        survey_dialog.QMessageBox, "question",
        lambda *a: QMessageBox.StandardButton.Yes,
    )
    dialog._run_ready()
    assert launched == [("survey", "x", "--force")]
    for _ in range(500):
        if dialog.job is None:
            break
        QTest.qWait(10)
        time.sleep(0)
    assert dialog.job is None
    dialog.close()
