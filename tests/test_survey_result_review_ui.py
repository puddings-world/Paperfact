"""Actual confirmation/apply widgets use retained content without new AI work."""

from pathlib import Path
from threading import Event

import pytest
from PySide6.QtWidgets import QMessageBox
from test_survey import conn as conn
from test_survey_evidence_ui import app as app
from test_survey_evidence_ui import wait_until
from test_survey_jobs import ready as ready
from test_survey_publication import prepared as prepared
from test_survey_result_review import retained as retained
from test_survey_result_review import snapshot
from test_sync_capture import bound as bound

from paper_daily import llm, reading_goals, store, survey_reader, survey_result_review
from paper_daily.desktop.main import LIGHT
from paper_daily.desktop.survey_dialog import SurveyDialog


def open_retained(retained, monkeypatch):
    _database, list_id, _original, _calls, _make = retained
    actual, failures = survey_reader.read_retained, []

    def reading(*args, **options):
        try:
            return actual(*args, **options)
        except Exception as error:
            failures.append((type(error).__name__, str(error)))
            raise

    monkeypatch.setattr(survey_reader, "read_retained", reading)
    actual_prepare = survey_result_review.prepare

    def preparing(*args, **options):
        try:
            return actual_prepare(*args, **options)
        except Exception as error:
            failures.append(("prepare", type(error).__name__, str(error)))
            raise

    monkeypatch.setattr(survey_result_review, "prepare", preparing)
    dialog = SurveyDialog(list_id, "Research", LIGHT, language="en")
    dialog.show()
    pane = dialog.saved_report
    pane._test_failures = failures
    wait_until(lambda: pane.future is None)
    dialog.report_tabs.setCurrentIndex(1)
    pane.results.click()
    wait_until(lambda: pane.future is None)
    assert pane.saved is not None, (pane.status.text(), failures, pane.current())
    assert pane.saved.data["kind"] == "retained" and pane.apply_result.isEnabled()
    return dialog, pane


def finish(dialog, pane):
    dialog.close()
    wait_until(lambda: pane.disposed)
    dialog.deleteLater()


def test_refreshing_empty_retained_history_clears_the_previous_action(retained, app, monkeypatch):
    from paper_daily import survey_jobs

    database, list_id, _, calls, _ = retained
    dialog, pane = open_retained(retained, monkeypatch)
    try:
        before = snapshot(database)
        monkeypatch.setattr(survey_jobs, "list_retained", lambda *a, **kw: [])
        pane.results.click()
        wait_until(lambda: pane.future is None)
        assert pane.status.text() == pane.words["results_empty"]
        assert not pane.apply_result.isVisible() and not pane.result_selector.isVisible()
        assert pane.saved is None and not pane.view.toPlainText()
        pane.refresh.click()
        wait_until(lambda: pane.future is None)
        assert pane.saved.data["kind"] == survey_reader.read(database, list_id).data["kind"]
        assert snapshot(database) == before and len(calls) == 1
    finally:
        finish(dialog, pane)


def test_confirmation_cancel_then_apply_updates_current_report_without_ai(
    retained, app, monkeypatch
):
    database, list_id, original, calls, _make = retained
    dialog, pane = open_retained(retained, monkeypatch)
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Unexpected AI"))
    from functools import partial

    failures = []

    def observed(stage, function, *args, **options):
        try:
            return function(*args, **options)
        except Exception as error:
            failures.append((stage, type(error).__name__, str(error)))
            raise

    for stage in ("prepare", "apply"):
        monkeypatch.setattr(
            survey_result_review,
            stage,
            partial(observed, stage, getattr(survey_result_review, stage)),
        )
    try:
        owned = []

        def answer(box, choice):
            owned.append(Path(box.parentWidget()._review.lease.name))
            return choice

        before = snapshot(database)
        monkeypatch.setattr(
            QMessageBox, "exec", lambda box: answer(box, QMessageBox.StandardButton.Cancel)
        )
        pane.apply_result.click()
        wait_until(lambda: pane.future is None)
        assert pane._review is None and pane.apply_result.isEnabled()
        assert snapshot(database) == before
        monkeypatch.setattr(
            QMessageBox, "exec", lambda box: answer(box, QMessageBox.StandardButton.Yes)
        )
        pane.apply_result.click()
        pane.apply_result.click()
        try:
            wait_until(lambda: pane.future is None)
        except AssertionError:
            import faulthandler

            faulthandler.dump_traceback()
            print(
                "PENDING",
                pane.future[1].__name__ if pane.future else None,
                pane.status.text(),
                failures,
                flush=True,
            )
            raise
        assert pane.saved is not None and pane.saved.data["kind"] != "retained", (
            pane.status.text(),
            failures,
        )
        assert pane.saved.data["report"] == original.data["report"]
        assert pane.apply_result.isHidden() and pane._review is None
        assert reading_goals.text(reading_goals.load(database, list_id)) == "Current goal"
        assert len(calls) == 1 and len(owned) == 2
        assert all(not path.exists() for path in owned)
    finally:
        finish(dialog, pane)


@pytest.mark.parametrize("change", ["goal", "workspace"])
def test_confirmation_drops_stale_target_or_workspace_without_applying(
    retained, app, monkeypatch, tmp_path, change
):
    database, list_id, _original, calls, _make = retained
    dialog, pane = open_retained(retained, monkeypatch)

    confirmations, owned = [], []

    def confirm(box):
        owned.append(Path(box.parentWidget()._review.lease.name))
        confirmations.append(True)
        if change == "goal":
            confirmations.append(
                reading_goals.save(reading_goals.load(database, list_id), "Concurrent goal")
            )
        else:
            monkeypatch.setattr(store, "DB_PATH", tmp_path / "other.sqlite")
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "exec", confirm)
    try:
        pane.apply_result.click()
        wait_until(lambda: pane.future is None)
        assert pane._review is None and len(calls) == 1
        assert confirmations, (pane.status.text(), pane._test_failures)
        assert survey_reader.read(database, list_id).data["kind"] == "none"
        if change == "goal":
            assert pane.status.text() == pane.words["apply_failed"]
            assert reading_goals.text(reading_goals.load(database, list_id)) == "Concurrent goal", (
                confirmations,
                pane._test_failures,
            )
        assert owned and all(not path.exists() for path in owned)
    finally:
        finish(dialog, pane)


def test_close_during_apply_cancels_before_write_and_drains_owned_stage(retained, app, monkeypatch):
    database, list_id, _original, calls, _make = retained
    dialog, pane = open_retained(retained, monkeypatch)
    entered, release = Event(), Event()
    actual, owned = survey_result_review.apply, []

    def held(value, **options):
        owned.append(Path(value.lease.name))
        entered.set()
        assert release.wait(5)
        return actual(value, **options)

    monkeypatch.setattr(survey_result_review, "apply", held)
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.StandardButton.Yes)
    before = snapshot(database)
    try:
        pane.apply_result.click()
        wait_until(entered.is_set)
        pane.apply_result.click()
        pane.review_result()
        assert len(owned) == 1 and owned[0].exists()
        dialog.close()
        assert pane.closing and pane.cancelled.is_set()
        release.set()
        wait_until(lambda: pane.disposed)
        assert not owned[0].exists() and pane._review is None
        assert snapshot(database) == before and len(calls) == 1
        assert survey_reader.read(database, list_id).data["kind"] == "none"
    finally:
        release.set()
        finish(dialog, pane)
