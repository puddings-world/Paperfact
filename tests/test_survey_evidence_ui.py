"""Real saved-report widgets: sources, stale delivery, retry and close barriers."""

import os
import time
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_survey import conn as conn
from test_survey_jobs import ready as ready
from test_survey_package_compound import archive
from test_survey_package_local import local as local
from test_survey_packages import exported as exported
from test_survey_publication import prepared as prepared
from test_survey_reader import saved as saved
from test_sync_capture import bound as bound

from paper_daily import bundle, store, survey_reader
from paper_daily.desktop.main import LIGHT
from paper_daily.desktop.survey_dialog import SurveyDialog
from paper_daily.desktop.survey_evidence import TEXT, render

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from paper_daily.desktop import fonts
    from paper_daily.desktop.main import style

    value = QApplication.instance() or QApplication([])
    style(value)
    fonts.load()
    yield value
    value.processEvents()


def wait_until(predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate()


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_saved_report_tab_and_exact_original_page_work_without_legacy_editing(
    saved,
    app,
    monkeypatch,
    language,
):
    database, list_id, report = saved
    monkeypatch.setattr(store, "DB_PATH", database)
    dialog = SurveyDialog(list_id, "Research", LIGHT, language=language)
    dialog.show()
    pane = dialog.saved_report
    try:
        wait_until(lambda: pane.future is None)
        assert pane.saved and pane.saved.data["report"] == report, (
            pane.status.text(), pane.current()
        )
        assert dialog.report_tabs.currentIndex() == 1
        assert dialog.run_btn.isHidden() and dialog.edit_btn.isHidden()
        assert report["sections"][0]["statements"][0]["text"] in pane.view.toPlainText()
        pane._link(QUrl("https://example.invalid/should-not-open"))
        assert pane.future is None
        pane._link(QUrl("paperfact-source:0/0/0"))
        wait_until(lambda: pane.future is None)
        assert not pane.source_panel.isHidden() and pane.image.original is not None
        assert pane.page.value() == 1 and pane.quote.text() == "A selected method"
        assert pane.words["checked"].format(page=1, pages=1) == pane.status.text()
        dialog.resize(1100, 800)
        QTest.qWait(30)
        if pane.saved.data["kind"] == "local":
            output = Path("build") / ("saved-survey-" + language + ".png")
            output.parent.mkdir(exist_ok=True)
            assert dialog.grab().save(str(output))
        dialog.report_tabs.setCurrentIndex(0)
        assert not dialog.run_btn.isHidden()
        dialog.report_tabs.setCurrentIndex(1)
        assert dialog.run_btn.isHidden()
    finally:
        dialog.close()
        wait_until(lambda: pane.disposed)
        dialog.deleteLater()


@pytest.mark.parametrize("change", ["workspace", "list"])
def test_held_read_deduplicates_and_drops_delivery_after_workspace_switch(
    exported,
    local,
    tmp_path,
    app,
    monkeypatch,
    change,
):
    result = bundle.import_(archive(exported, tmp_path), pdfs=False)
    entered, release = Event(), Event()
    actual = survey_reader.read
    calls = []

    def held(database, list_id, **options):
        calls.append((database, list_id))
        entered.set()
        assert release.wait(5)
        return actual(database, list_id, **options)

    monkeypatch.setattr(survey_reader, "read", held)
    dialog = SurveyDialog(result["list"], "Research", LIGHT, language="en")
    pane = dialog.saved_report
    try:
        wait_until(entered.is_set)
        pane.reload()
        pane.refresh.click()
        assert len(calls) == 1 and not pane.refresh.isEnabled()
        if change == "workspace":
            monkeypatch.setattr(store, "DB_PATH", tmp_path / "another.sqlite")
        else:
            dialog.list_id = "another-list"
        release.set()
        wait_until(lambda: pane.future is None)
        assert pane.saved is None and not pane.view.toPlainText()
        assert pane.status.text() == pane.words["stale"]
        assert pane.source_panel.isHidden() and not pane.refresh.isEnabled()
    finally:
        release.set()
        dialog.close()
        wait_until(lambda: pane.disposed)
        dialog.deleteLater()


def test_source_failure_retry_duplicate_activation_and_close_cancel_are_safe(
    exported,
    local,
    tmp_path,
    app,
    monkeypatch,
):
    result = bundle.import_(archive(exported, tmp_path), pdfs=False)
    dialog = SurveyDialog(result["list"], "Research", LIGHT, language="en")
    dialog.show()
    pane = dialog.saved_report
    actual = survey_reader.inspect
    calls = []
    entered = Event()

    def held(report, *selection, **options):
        calls.append(selection)
        if len(calls) == 1:
            raise ValueError("fixture missing original")
        entered.set()
        while not options["cancelled"]():
            time.sleep(0.005)
        return actual(report, *selection, **options)

    monkeypatch.setattr(survey_reader, "inspect", held)
    try:
        wait_until(lambda: pane.future is None)
        pane._link(QUrl("paperfact-source:0/0/0"))
        wait_until(lambda: pane.future is None)
        assert pane.status.text() == pane.words["failed"] and pane.refresh.isEnabled()
        assert pane.source_panel.isHidden()
        pane._link(QUrl("paperfact-source:0/0/0"))
        wait_until(entered.is_set)
        pane._link(QUrl("paperfact-source:0/0/0"))
        assert len(calls) == 2
        pane.stop.click()
        wait_until(lambda: pane.future is None)
        assert pane.status.text() == pane.words["cancelled"] and pane.refresh.isEnabled()
        assert not pane.cancelled.is_set() and pane.source_panel.isHidden()
        entered.clear()
        pane._link(QUrl("paperfact-source:0/0/0"))
        wait_until(entered.is_set)
        assert len(calls) == 3
        dialog.close()
        assert pane.closing and pane.cancelled.is_set()
        wait_until(lambda: pane.disposed)
        assert not dialog.isVisible() and pane.source_panel.isHidden()
        assert pane.image.original is None
    finally:
        pane.cancelled.set()
        wait_until(lambda: pane.future is None)
        dialog.close()
        dialog.deleteLater()


def test_failed_read_can_refresh_and_legacy_result_can_reopen_closed_dialog(
    exported,
    local,
    tmp_path,
    app,
    monkeypatch,
):
    result = bundle.import_(archive(exported, tmp_path), pdfs=False)
    actual = survey_reader.read
    calls = []

    def flaky(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise ValueError("fixture read failure")
        return actual(*args, **kwargs)

    monkeypatch.setattr(survey_reader, "read", flaky)
    dialog = SurveyDialog(result["list"], "Research", LIGHT, language="en")
    pane = dialog.saved_report
    try:
        wait_until(lambda: pane.future is None)
        assert pane.status.text() == pane.words["failed"]
        pane.refresh.click()
        wait_until(lambda: pane.future is None)
        assert pane.saved and pane.status.text() == pane.words["ready"]
        dialog.close()
        assert pane.disposed
        dialog._show_result()
        wait_until(lambda: pane.future is None)
        assert not pane.disposed and dialog.isVisible() and dialog.report_tabs.currentIndex() == 0
    finally:
        dialog.close()
        wait_until(lambda: pane.disposed)
        dialog.deleteLater()


def test_research_text_is_literal_and_never_creates_external_links(exported):
    report = exported[0][5].report
    report["sections"][0]["statements"][0]["text"] = (
        '<script>bad()</script><img src="https://example.invalid/pixel">'
    )
    data = dict(report=report, sources=[])
    for words in TEXT.values():
        value = render(data, words)
        assert "<script>" not in value and "<img " not in value
        assert "&lt;script&gt;" in value and 'href="https:' not in value
        assert "paperfact-source:0/0/0" in value
        assert words["tab"] and "?" not in words["tab"]


def test_saved_report_arrival_does_not_switch_tabs_during_existing_overview_job(
    exported,
    local,
    tmp_path,
    app,
):
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from paper_daily.desktop.activity import ActivityHub, begin

    result = bundle.import_(archive(exported, tmp_path), pdfs=False)
    owner = QWidget()
    QVBoxLayout(owner)
    owner.activity_hub = ActivityHub(owner)
    handle = begin(owner, "Fixture overview job", key="survey:" + result["list"])
    dialog = SurveyDialog(result["list"], "Research", LIGHT, owner, language="en")
    pane = dialog.saved_report
    try:
        wait_until(lambda: pane.future is None)
        assert pane.saved and pane.saved.data["kind"] == "local"
        assert dialog.report_tabs.currentIndex() == 0
        assert not dialog.run_btn.isEnabled() and not dialog.run_btn.isHidden()
        handle.finish(True)
        assert dialog.run_btn.isEnabled() and dialog.report_tabs.currentIndex() == 0
    finally:
        handle.finish(cancelled=True)
        dialog.close()
        wait_until(lambda: pane.disposed)
        dialog.deleteLater()
        owner.close()
        owner.deleteLater()


def test_source_button_uses_captured_child_action_and_reopens_completed_report(
    saved, app, monkeypatch, tmp_path,
):
    import json

    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QMessageBox, QVBoxLayout, QWidget

    import paper_daily.desktop.survey_dialog as dialogs
    from paper_daily import llm, survey_jobs
    from paper_daily.ai_types import Completion, Settings
    from paper_daily.cli_job_protocol import decode_frame
    from paper_daily.desktop import activity

    database, list_id, old_report = saved
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "private-ai.json")
    llm.save_settings(profile="fixture", backend="openai", model="original-model",
                      api_key="synthetic-key", isolated=True)
    llm.use_profile("fixture", desktop=True)
    calls = []
    class Process(QProcess):
        def start(self, program, arguments):
            calls.append((program, list(arguments)))
    monkeypatch.setattr(dialogs, "QProcess", Process)
    monkeypatch.setattr(dialogs.runtime, "cli_command", lambda *args: ["fixture", *args])
    monkeypatch.setattr(activity, "process_environment", lambda process: None)
    owner = QWidget()
    owner.pal = LIGHT
    QVBoxLayout(owner)
    owner.activity_hub = activity.ActivityHub(owner)
    dialog = SurveyDialog(list_id, "Research", LIGHT, owner, language="en")
    dialog.show()
    pane = dialog.saved_report
    try:
        wait_until(lambda: pane.future is None)
        dialog.report_tabs.setCurrentIndex(1)
        assert dialog.source_btn.isVisible() and dialog.source_btn.isEnabled()
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
        dialog._run_sources_ready()
        assert not calls and pane.saved.data["report"] == old_report
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        dialog._run_sources_ready()
        for _ in range(5):
            dialog._run_sources_ready()
        assert len(calls) == 1 and not dialog.source_btn.isEnabled()
        argv = calls[0][1]
        assert argv[2:] == ["survey", list_id, "--sources", "--expected-report",
                           old_report["id"], "--force"]
        process = dialog.job
        handoff = process._ai_job_handoff
        frame = decode_frame(handoff._frame, expected_request_id=argv[1],
                             expected_command=argv[2:])
        assert frame.routes.settings("survey").model == "original-model"
        dialog.reject()
        wait_until(lambda: pane.disposed)
        assert dialog.job is process

        reply = {"sections": [{"heading": "A newly saved report", "statements": [{
            "text": "A new interpretation awaits scientific review.",
            "interpretation": "inference", "passages": [],
        }]}]}
        monkeypatch.setattr(llm, "settings", lambda **kwargs: Settings("codex", model="fixture"))
        monkeypatch.setattr(llm, "complete_result",
                            lambda *args, **kwargs: Completion(json.dumps(reply)))
        result = survey_jobs.execute(
            database, list_id, force=True, expected_report=old_report["id"]
        )
        assert result["state"] == "saved"
        # The worker/persistence action above is real; only child IPC completion is simulated.
        monkeypatch.setattr(handoff, "complete", lambda code: code)
        process.finished.emit(0, QProcess.ExitStatus.NormalExit)
        assert dialog.job is None
        dialog._show_result()
        wait_until(lambda: pane.future is None and pane.saved is not None
                   and pane.saved.data["report"]["id"] == result["report_id"])
        assert dialog.report_tabs.currentIndex() == 1 and dialog.source_btn.isEnabled()
        assert "A new interpretation" in pane.view.toPlainText()
    finally:
        if dialog.job is not None:
            dialog.job.finished.emit(1, QProcess.ExitStatus.NormalExit)
        dialog.close()
        wait_until(lambda: pane.disposed)
        owner.activity_hub._poll.stop()
        dialog.deleteLater()
        owner.close()
        owner.deleteLater()

def test_report_read_retries_fresh_snapshot_but_bounds_continuous_changes(saved, app, monkeypatch):
    from contextlib import closing

    from paper_daily import research_generation as generation

    database, list_id, report = saved
    monkeypatch.setattr(store, "DB_PATH", database)
    actual = survey_reader.read
    calls = []
    keep_changing = False

    def racing(*args, **kwargs):
        value = actual(*args, **kwargs)
        calls.append(1)
        if len(calls) == 1 or keep_changing:
            with closing(generation._connect(database)) as conn, conn:
                conn.execute("UPDATE lists SET name=name||' changed' WHERE id=?", (list_id,))
        return value

    monkeypatch.setattr(survey_reader, "read", racing)
    dialog = SurveyDialog(list_id, "Research", LIGHT, language="en")
    pane = dialog.saved_report
    try:
        wait_until(lambda: pane.future is None and pane.saved is not None)
        assert len(calls) == 2 and pane.saved.data["report"] == report
        assert report["sections"][0]["statements"][0]["text"] in pane.view.toPlainText()
        keep_changing = True
        calls.clear()
        pane.reload()
        wait_until(lambda: pane.future is None and len(calls) == 2)
        assert pane.saved is None and pane.status.text() == pane.words["stale"]
        QTest.qWait(100)
        assert len(calls) == 2
    finally:
        dialog.close()
        wait_until(lambda: pane.disposed)
        dialog.deleteLater()


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_completed_results_reopen_literal_content_without_ai_or_source_grants(ready, app, language):
    from paper_daily import reading_goals, survey_jobs

    reading_goals.save(reading_goals.load(ready[0], "cat"), "<b>Original purpose</b>")
    first = survey_jobs.SurveyJob.capture(ready[0], "cat", legacy_root=ready[1])
    proposal = first.generate()
    retained = survey_jobs.retain(first, proposal)
    reading_goals.save(reading_goals.load(ready[0], "cat"), "A later purpose")
    second = survey_jobs.SurveyJob.capture(ready[0], "cat", legacy_root=ready[1])
    survey_jobs.retain(second, second.generate())
    records = survey_jobs.list_retained(ready[0], "cat")
    assert len(records) == 2 and survey_jobs.list_retained(ready[0], "another-list") == []
    assert len(ready[2]) == 2
    for _reopen in range(2):
        dialog = SurveyDialog("cat", "Research", LIGHT, language=language)
        pane = dialog.saved_report
        try:
            wait_until(lambda pane=pane: pane.future is None)
            pane.results.click()
            wait_until(lambda pane=pane: pane.future is None)
            assert pane.result_selector.count() == 2
            index = next(i for i, item in enumerate(pane._retained)
                         if item["request_id"] == retained.request_id)
            pane.result_selector.setCurrentIndex(index)
            text = pane.view.toPlainText()
            assert "<b>Original purpose</b>" in text and "A later purpose" not in text
            assert "The reported improvement needs review." in text
            assert "A selected method improves measurement." in text
            assert "paperfact-source:" not in pane.view.toHtml()
            assert "synthetic-key" not in text and pane.saved is None
            assert pane.status.text() == pane.words["result_scope"]
            pane._link(QUrl("paperfact-source:0/0/0"))
            assert pane.future is None and pane.source_panel.isHidden()
            pane.refresh.click()
            wait_until(lambda pane=pane: pane.future is None)
            assert pane.result_selector.isHidden() and not pane.view.toPlainText()
            assert pane.status.text() == pane.words["empty"]
            assert len(ready[2]) == 2
        finally:
            dialog.close()
            wait_until(lambda pane=pane: pane.disposed)
            dialog.deleteLater()
    assert survey_reader.read(ready[0], "cat").data["kind"] == "none"
    assert reading_goals.text(reading_goals.load(ready[0], "cat")) == "A later purpose"


@pytest.mark.parametrize("outcome", ["empty", "failure", "cancel", "workspace", "close"])
def test_completed_results_background_deduplication_and_delivery_guards(
    ready, app, monkeypatch, tmp_path, outcome,
):
    from paper_daily import survey_jobs

    dialog = SurveyDialog("cat", "Research", LIGHT, language="en")
    dialog.show()
    pane = dialog.saved_report
    wait_until(lambda pane=pane: pane.future is None)
    actual = survey_jobs.list_retained
    entered, release = Event(), Event()
    calls = []

    def held(*args, **options):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        if outcome == "failure":
            raise ValueError("Synthetic archive failure")
        return actual(*args, **options)

    monkeypatch.setattr(survey_jobs, "list_retained", held)
    try:
        pane.results.click()
        wait_until(entered.is_set)
        pane.results.click()
        pane.load_results()
        assert len(calls) == 1 and not pane.results.isEnabled()
        if outcome == "workspace":
            monkeypatch.setattr(store, "DB_PATH", tmp_path / "another.sqlite")
        elif outcome == "cancel":
            pane.stop.click()
        elif outcome == "close":
            dialog.close()
            assert pane.closing and pane.cancelled.is_set()
        release.set()
        wait_until(lambda pane=pane: pane.future is None)
        if outcome == "close":
            assert pane.disposed and not dialog.isVisible()
        else:
            expected = dict(empty="results_empty", failure="failed", cancel="cancelled",
                            workspace="stale")[outcome]
            assert pane.status.text() == pane.words[expected]
            assert pane.result_selector.isHidden() and not pane.view.toPlainText()
            if outcome != "workspace":
                monkeypatch.setattr(survey_jobs, "list_retained", actual)
                pane.results.click()
                wait_until(lambda pane=pane: pane.future is None)
                assert pane.status.text() == pane.words["results_empty"]
                assert pane.results.isEnabled()
        assert not ready[2]
    finally:
        release.set()
        dialog.close()
        wait_until(lambda pane=pane: pane.disposed)
        dialog.deleteLater()
