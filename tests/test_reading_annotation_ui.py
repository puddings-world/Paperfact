"""Actual grouped annotation jobs are launched from the displayed pane's owner."""
import sqlite3
from contextlib import closing

import pytest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QWidget
from test_highlight_generation import marks
from test_highlight_generation import ready as ready_fixture
from test_highlight_generation import workspace as workspace_fixture
from test_reading_annotation_jobs import explained as explained_fixture

from paper_daily import llm, manual_highlight_ops, reading_annotation_jobs, store, sync_capture
from paper_daily import research_generation as generation
from paper_daily.desktop import reading_annotation_ui as ui

workspace = workspace_fixture
ready = ready_fixture
explained = explained_fixture


class Runner:
    busy = False

    def start(self, prompt, done, failed, *, call, task):
        self.busy = True
        self.done, self.failed, self.work = done, failed, call

    def finish(self):
        answer, reason = self.work('')
        self.busy = False
        (self.done if answer else self.failed)(answer or reason)


class Pane(QWidget):
    highlights_ready = Signal(str)

    def __init__(self):
        super().__init__()
        self.paper_id = 'paper'
        self.runner = Runner()
        self._highlights_busy = False
        self.messages = []
        self.material_reads = 0

    @property
    def busy(self):
        return self._highlights_busy or self.runner.busy

    def _update_controls(self):
        pass

    def _highlight_status(self, text):
        self.messages.append(text)

    def _load_materials(self):
        self.material_reads += 1


@pytest.fixture
def pane(ready, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(llm, 'available', lambda **kwargs: True)
    from paper_daily.config import PDF_DIR
    monkeypatch.setattr('paper_daily.config.PDF_DIR', ready[2].path.parent)
    view = Pane()
    ui.bind(view)
    assert view._annotation_owner is not None
    yield view
    view.close()
    view.deleteLater()
    app.processEvents()
    assert PDF_DIR is not None


def saved(database, table):
    with closing(generation._connect(database)) as conn:
        return [dict(row) for row in conn.execute(f'SELECT * FROM {table}')]


def test_pane_job_publishes_analysis_and_located_marks_together_on_original_route(
    pane, ready,
):
    assert ui.start(pane, force=True)
    ready[3].update(account='changed', model='changed-model')
    assert not ui.start(pane, force=True)
    pane.runner.finish()
    assert len(ready[5]) == 1 and len(marks(ready[0])) == 1
    assert len(saved(ready[0], 'paper_highlight_analysis')) == 1
    assert ready[4][0] == {'account': 'original', 'model': 'original-model'}
    assert pane.material_reads == 1 and not pane.busy


def test_loaded_parent_deletion_prevents_generation_even_before_job_capture(pane, ready):
    assert ui.start(pane, force=True)
    # Simulate an external deletion; normal enrolled paper deletion is gated.
    with sqlite3.connect(ready[0]) as conn:
        sync_capture.trusted_connection(conn)
        conn.execute("DELETE FROM papers WHERE id='paper'")
    pane.runner.finish()
    assert not ready[5] and not saved(ready[0], 'paper_highlight_analysis')
    assert pane.material_reads == 0 and not pane.busy


def test_paper_switch_during_model_retains_original_result_without_repainting_new_pane(
    pane, ready, monkeypatch,
):
    complete = llm.complete_result

    def switch(*args, **kwargs):
        output = complete(*args, **kwargs)
        pane.paper_id = 'other'
        ui.bind(pane)
        return output

    monkeypatch.setattr(llm, 'complete_result', switch)
    ready_signals = []
    pane.highlights_ready.connect(ready_signals.append)
    assert ui.start(pane, force=True)
    pane.runner.finish()
    assert len(marks(ready[0])) == 1 and len(ready[5]) == 1
    assert pane.material_reads == 0 and ready_signals == [] and not pane.busy


def test_workspace_switch_during_model_cannot_redirect_output_or_repaint(
    pane, ready, monkeypatch, tmp_path,
):
    complete = llm.complete_result
    other = tmp_path / 'other.sqlite'

    def switch(*args, **kwargs):
        output = complete(*args, **kwargs)
        monkeypatch.setattr(store, 'DB_PATH', other)
        return output

    monkeypatch.setattr(llm, 'complete_result', switch)
    assert ui.start(pane, force=True)
    pane.runner.finish()
    assert len(marks(ready[0])) == 1 and not other.exists()
    assert pane.material_reads == 0 and not pane.busy


def test_cancel_before_model_does_not_call_provider_or_mutate_old_content(pane, ready):
    assert ui.start(pane, force=True)
    ui.cancel(pane)
    pane.runner.finish()
    assert not ready[5] and marks(ready[0]) == []
    assert not saved(ready[0], 'paper_highlight_analysis')
    assert pane.material_reads == 0 and not pane.busy


def test_cancel_after_highlights_saves_group_but_skips_link_model(
    pane, explained, monkeypatch,
):
    ready, links = explained
    complete = llm.complete_result

    def stop_after_highlight(*args, **kwargs):
        output = complete(*args, **kwargs)
        ui.cancel(pane)
        return output

    monkeypatch.setattr(llm, 'complete_result', stop_after_highlight)
    assert ui.start(pane, force=True)
    pane.runner.finish()
    assert len(ready[5]) == 1 and links == []
    assert len(saved(ready[0], 'paper_highlight_analysis')) == 1 and len(marks(ready[0])) == 1
    assert saved(ready[0], 'paper_reading_links') == []
    assert pane.material_reads == 1 and not pane.busy


def test_two_phase_success_is_reused_without_accounts_or_models(pane, explained, monkeypatch):
    ready, links = explained
    assert ui.start(pane, force=True)
    pane.runner.finish()
    assert len(links) == 1 and len(marks(ready[0])) == 1
    before = len(ready[5])
    monkeypatch.setattr(llm, 'capture_connections',
                        lambda: pytest.fail('Saved work consulted account configuration'))
    monkeypatch.setattr(llm, 'complete_result',
                        lambda *a, **k: pytest.fail('Saved work called a model'))
    assert ui.start(pane, force=False)
    pane.runner.finish()
    assert len(ready[5]) == before and pane.material_reads == 2


def test_expected_loaded_pdf_is_checked_before_model(ready):
    owner = manual_highlight_ops.capture_owner(ready[0], 'paper')
    with pytest.raises(ValueError, match='displayed PDF'):
        reading_annotation_jobs.prepare(
            ready[0], 'paper', legacy_root=ready[2].path.parent, force=True,
            owner=owner, expected_document_hash='a' * 64,
        )
    assert not ready[5] and not saved(ready[0], 'paper_highlight_analysis')


def test_missing_owner_never_uses_legacy_fallback(pane, ready):
    pane._annotation_owner = None
    assert not ui.start(pane)
    assert not ready[5] and not pane.busy


def test_actual_presentation_worker_keeps_draft_and_partial_group_on_stop(
    ready, monkeypatch, tmp_path,
):
    import threading
    import time

    from PySide6.QtCore import QCoreApplication, QEvent, QThread

    from paper_daily import presentations
    from paper_daily.desktop.presentation_pane import PresentationPane

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(presentations, 'DECK_DIR', tmp_path / 'decks')
    monkeypatch.setattr('paper_daily.config.PDF_DIR', ready[2].path.parent)
    monkeypatch.setattr(llm, 'available', lambda **kwargs: True)
    entered, release = threading.Event(), threading.Event()
    complete = llm.complete_result
    worker_threads = []

    def blocked(*args, **kwargs):
        worker_threads.append(QThread.currentThread() != app.thread())
        entered.set()
        assert release.wait(10), 'Fixture model was not released'
        return complete(*args, **kwargs)

    monkeypatch.setattr(llm, 'complete_result', blocked)
    widget = PresentationPane()
    widget.load('paper', 'Paper', defer=True)
    widget.slide_title.setText('Unsent slide draft')
    try:
        widget._analyze_highlights(force=True)
        assert entered.wait(10), 'Actual model worker did not start'
        assert widget.busy and not widget.materials_panel.analyze.isEnabled()
        widget._analyze_highlights(force=True)
        widget._cancel_highlights()
        release.set()
        deadline = time.monotonic() + 15
        while widget.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        app.processEvents()
        assert not widget.busy and worker_threads == [True]
        assert len(ready[5]) == 1 and len(marks(ready[0])) == 1
        assert len(saved(ready[0], 'paper_highlight_analysis')) == 1
        assert widget.slide_title.text() == 'Unsent slide draft'
        assert widget.materials_panel.analyze.isEnabled()
    finally:
        release.set()
        if widget.runner._thread:
            widget.runner._thread.quit()
            widget.runner._thread.wait(15000)
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_empty_target_and_failure_retry_keep_previous_group(pane, ready, monkeypatch):
    from paper_daily.ai_types import Completion

    pane.paper_id = ''
    assert not ui.start(pane) and not pane.busy
    pane.paper_id = 'paper'
    ui.bind(pane)
    assert ui.start(pane, force=True)
    pane.runner.finish()
    previous_analysis = saved(ready[0], 'paper_highlight_analysis')
    previous_marks = marks(ready[0])
    complete = llm.complete_result
    monkeypatch.setattr(llm, 'complete_result', lambda *a, **k: Completion(None, 'Unavailable'))
    assert ui.start(pane, force=True)
    pane.runner.finish()
    assert not pane.busy and pane.material_reads == 1
    assert saved(ready[0], 'paper_highlight_analysis') == previous_analysis
    assert marks(ready[0]) == previous_marks
    monkeypatch.setattr(llm, 'complete_result', complete)
    assert ui.start(pane, force=True)
    pane.runner.finish()
    assert len(marks(ready[0])) == 1 and pane.material_reads == 2 and not pane.busy


def test_a_stopped_preparation_says_why_and_records_where(tmp_path, monkeypatch):
    from paper_daily import diagnostics
    from paper_daily.desktop import reading_annotation_ui

    recorded = []
    monkeypatch.setattr(diagnostics, "record_exception",
                        lambda kind, tb, **k: recorded.append((kind, k.get("phase"))))

    def raised(error):
        try:
            raise error
        except ValueError as caught:
            return reading_annotation_ui.preparation_failure(caught)

    known = raised(ValueError("The displayed PDF changed before highlight analysis"))
    assert "重新開啟" in known and "ValueError" not in known
    other = raised(ValueError("Highlight target has no saved paper"))
    assert "Highlight target has no saved paper" in other and "ValueError" in other
    assert "原因不明" in raised(ValueError())
    assert recorded == [(ValueError, "annotation")] * 3
