"""Real saved-report widgets: sources, stale delivery, retry and close barriers."""

import os
import time
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
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
        assert pane.saved and pane.saved.data["report"] == report
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
