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
    assert len(launched) == 1
    assert launched[0][0] == "_desktop-job-v1" and len(launched[0][1]) == 32
    assert launched[0][2:] == ("survey", "x", "--force")
    for _ in range(500):
        if dialog.job is None:
            break
        QTest.qWait(10)
        time.sleep(0)
    assert dialog.job is None
    dialog.close()


def test_saved_overview_explains_unverified_sources_without_ai_or_writes(owner, monkeypatch):
    import httpx

    from paper_daily import llm

    def forbidden(*args, **kwargs):
        pytest.fail("Opening source status must not use AI, network or original downloads")

    monkeypatch.setattr(llm, "complete", forbidden)
    monkeypatch.setattr(llm, "complete_result", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    for language in ("en", "zh-TW"):
        text = survey_dialog.SURVEY_EVIDENCE_TEXT[language]
        for spec, key in ((survey.ROADMAP_SPEC, "roadmap"), (survey.SURVEY_SPEC, "survey"),
                          ("legacy-private-spec", "unknown")):
            with store.connect() as conn:
                conn.execute("UPDATE list_surveys SET spec=?,edited=1 WHERE list_id='x'", (spec,))
                before = list(conn.iterdump())
            dialog = SurveyDialog("x", "Research", LIGHT, owner, language=language)
            try:
                notice = dialog.evidence_notice.text()
                assert text[key] in notice and text["unverified"] in notice
                assert text["edited"] in notice and "legacy-private-spec" not in notice
                assert not dialog.evidence_notice.isHidden()
                assert dialog.job is None
                with store.connect() as conn:
                    assert list(conn.iterdump()) == before
                with monkeypatch.context() as changed:
                    changed.setattr(dialog, "_workspace_matches", lambda: False)
                    dialog._load()
                    assert dialog.evidence_notice.isHidden() and not dialog.evidence_notice.text()
                    assert not dialog.run_btn.isEnabled() and not dialog.edit_btn.isEnabled()
                dialog._load()
                assert not dialog.evidence_notice.isHidden()
                # A later refresh of an empty list must not retain an old evidence label.
                with store.connect() as conn:
                    conn.execute("DELETE FROM list_surveys WHERE list_id='x'")
                dialog._load()
                assert dialog.evidence_notice.isHidden() and not dialog.evidence_notice.text()
            finally:
                dialog.close()
            with store.connect() as conn:
                conn.execute(
                    "INSERT INTO list_surveys VALUES('x','Saved overview',1,?,"
                    "'2026-10-01T00:00',0)", (survey.ROADMAP_SPEC,),
                )
