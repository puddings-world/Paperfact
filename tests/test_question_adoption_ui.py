"""Actual local legacy adoption preserves source, drafts and worker ownership."""

import json
import os
import threading
import time
from contextlib import closing

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QThread
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget
from test_question_generation import ready as _ready
from test_question_legacy_adoption import old_questions as _old_questions
from test_research_generation import pdf, rows
from test_research_generation import workspace as _workspace

from paper_daily import question_legacy_adoption
from paper_daily import research_generation as generation
from paper_daily.desktop.question_adoption_job import AdoptionRunner
from paper_daily.desktop.research_questions import ResearchQuestions

workspace = _workspace
ready = _ready
old_questions = _old_questions


def wait(app, condition):
    deadline = time.monotonic() + 12
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    app.processEvents()
    assert condition(), "Local fixture worker did not finish"


@pytest.fixture
def view(old_questions):
    app = QApplication.instance() or QApplication([])
    database, document, path, content = old_questions
    selected = [database]
    window = QWidget()
    layout = QVBoxLayout(window)
    widget = ResearchQuestions(database=lambda: selected[0])
    composer = QLineEdit("A question I have not sent")
    layout.addWidget(widget)
    layout.addWidget(composer)
    widget.load("paper")
    window.show()
    app.processEvents()
    yield app, widget, composer, selected, document, path, content
    wait(app, lambda: not widget.adoption_busy)
    window.close()
    window.deleteLater()
    app.processEvents()


def verified(view):
    app, widget, *_ = view
    widget.verify_button.click()
    wait(app, lambda: not widget.adoption_busy)
    assert widget._prepared_adoption is not None, widget.status.text()


def test_actual_verify_preview_then_explicit_adopt_without_ai(view):
    app, widget, composer, selected, document, path, content = view
    original = path.read_bytes()
    assert widget.verify_button.isVisible()
    assert widget.adopt_button.isHidden()
    verified(view)
    assert rows(selected[0], "SELECT * FROM paper_research_questions") == []
    assert widget._item() == content["items"][0]
    assert document.sha256 in widget.adoption_status.text()
    assert widget.source.isVisible()
    requested = []
    widget.source_requested.connect(requested.append)
    widget.source.click()
    assert requested[0]["document_hash"] == document.sha256
    assert requested[0]["text"] == content["items"][0]["evidence"]
    widget.open_browser()
    widget.adopt_button.click()
    wait(app, lambda: not widget.adoption_busy)
    result = rows(selected[0], "SELECT * FROM paper_research_questions")[0]
    assert json.loads(result["body_json"])["items"] == content["items"]
    assert result["document_hash"] == document.sha256
    assert widget.verify_button.isHidden() and widget.adopt_button.isHidden()
    assert "已採用" in widget.adoption_status.text()
    assert path.read_bytes() == original
    assert composer.text() == "A question I have not sent"


def test_rapid_verify_and_adopt_are_single_jobs(view, monkeypatch):
    app, widget, _, selected, *_ = view
    original = question_legacy_adoption.prepare
    entered, release = threading.Event(), threading.Event()
    calls = []

    def prepare(*args, **kwargs):
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(question_legacy_adoption, "prepare", prepare)
    try:
        for _ in range(20):
            widget.verify_legacy()
        wait(app, entered.is_set)
        assert widget.adoption_busy and not widget.verify_button.isEnabled()
        assert not widget.refresh_button.isEnabled()
    finally:
        release.set()
    wait(app, lambda: not widget.adoption_busy)
    assert len(calls) == 1 and calls[0] != threading.get_ident()
    for _ in range(20):
        widget.adopt_legacy()
    wait(app, lambda: not widget.adoption_busy)
    assert len(rows(selected[0], "SELECT * FROM paper_research_questions")) == 1
    records = rows(selected[0], "SELECT * FROM research_generation_requests")
    assert len([r for r in records if json.loads(r['context_json'])['table']
                == 'paper_research_questions']) == 1


@pytest.mark.parametrize("change", ["workspace", "paper", "reload", "unannounced_workspace"])
def test_late_verification_never_enables_adoption_in_another_view(view, monkeypatch, change):
    app, widget, composer, selected, *_ = view
    original = question_legacy_adoption.prepare
    entered, release = threading.Event(), threading.Event()

    def prepare(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(8)
        return result

    monkeypatch.setattr(question_legacy_adoption, "prepare", prepare)
    try:
        widget.verify_legacy()
        wait(app, entered.is_set)
        if "workspace" in change:
            selected[0] = selected[0].with_name("another.sqlite")
        if change != "unannounced_workspace":
            widget.load("other" if change == "paper" else "paper")
        text = widget.detail.text()
    finally:
        release.set()
    wait(app, lambda: not widget.adoption_busy)
    widget.adopt_legacy()
    assert widget._prepared_adoption is None
    assert widget.detail.text() == text
    assert composer.text() == "A question I have not sent"
    if "workspace" in change:
        assert not selected[0].exists()


def test_failure_and_retry_preserve_original_preview_and_draft(view, monkeypatch):
    app, widget, composer, *_ = view
    old = widget.detail.text()
    original = question_legacy_adoption.prepare

    def fail(*args, **kwargs):
        raise OSError("Fixture PDF temporarily unavailable")

    monkeypatch.setattr(question_legacy_adoption, "prepare", fail)
    widget.verify_legacy()
    wait(app, lambda: not widget.adoption_busy)
    assert widget.detail.text() == old
    assert "Fixture PDF" in widget.adoption_status.text()
    assert widget.adopt_button.isHidden()
    assert widget.verify_button.isEnabled()
    monkeypatch.setattr(question_legacy_adoption, "prepare", original)
    verified(view)
    prepared = widget._prepared_adoption
    adopt = type(prepared).adopt
    monkeypatch.setattr(type(prepared), "adopt", fail)
    widget.adopt_legacy()
    wait(app, lambda: not widget.adoption_busy)
    assert widget._prepared_adoption is prepared
    assert widget.detail.text() == old.replace("（來源版本未確認）", "")
    assert widget.adopt_button.isEnabled()
    monkeypatch.setattr(type(prepared), "adopt", adopt)
    widget.adopt_legacy()
    wait(app, lambda: not widget.adoption_busy)
    assert "已採用" in widget.adoption_status.text()
    assert composer.text() == "A question I have not sent"


@pytest.mark.parametrize("change", ["pdf", "analysis", "parent"])
def test_source_or_parent_changes_after_preview_retain_instead_of_overwriting(view, change):
    app, widget, _, selected, document, *_ = view
    verified(view)
    if change == "pdf":
        document.path.unlink()
        pdf(document.path, "Replacement experiment")
    elif change == "analysis":
        with closing(generation._connect(selected[0])) as conn:
            context = generation.begin_generation(
                conn, table="dives", owner_id="paper", input_reader="target"
            )
            row = dict(conn.execute("SELECT * FROM dives WHERE paper_id='paper'").fetchone())
        row["body"] = "Newer analysis"
        assert generation.publish_generation(context, row=row).status == "accepted"
    else:
        from paper_daily.sync_capture import suppress_capture

        with closing(generation._connect(selected[0])) as conn, conn, suppress_capture(conn):
            row = conn.execute("SELECT * FROM papers WHERE id='paper'").fetchone()
            conn.execute("DELETE FROM papers WHERE id='paper'")
            fields = list(row.keys())
            conn.execute(f"INSERT INTO papers({','.join(fields)}) VALUES"
                         f"({','.join('?' for _ in fields)})", tuple(row))
    widget.adopt_legacy()
    wait(app, lambda: not widget.adoption_busy)
    assert rows(selected[0], "SELECT * FROM paper_research_questions") == []
    assert "未覆蓋" in widget.adoption_status.text()
    assert widget.picker.count() == 1
    records = rows(
        selected[0], "SELECT * FROM research_generation_requests WHERE status='candidate'"
    )
    assert len(records) == 1
    assert json.loads(records[0]["row_json"])["document_hash"] == document.sha256


def test_closing_preview_during_verification_does_not_reopen_or_steal_focus(view, monkeypatch):
    app, widget, composer, *_ = view
    original = question_legacy_adoption.prepare
    entered, release = threading.Event(), threading.Event()

    def prepare(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(8)
        return result

    monkeypatch.setattr(question_legacy_adoption, "prepare", prepare)
    widget.return_to_draft.connect(composer.setFocus)
    try:
        widget.verify_legacy()
        wait(app, entered.is_set)
        widget.browser.reject()
        app.processEvents()
        focus = app.focusWidget()
    finally:
        release.set()
    wait(app, lambda: not widget.adoption_busy)
    assert not widget.browser.isVisible()
    assert app.focusWidget() is focus
    assert rows(view[3][0], "SELECT * FROM paper_research_questions") == []


def test_destroyed_worker_owner_does_not_abandon_local_publication(old_questions):
    app = QApplication.instance() or QApplication([])
    database, document, path, _ = old_questions
    prepared = question_legacy_adoption.prepare(
        database, "paper", cache_root=path.parent, legacy_root=document.path.parent
    )
    owner = QWidget()
    runner = AdoptionRunner(owner)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    delivered = []

    def call():
        entered.set()
        assert release.wait(8)
        try:
            return prepared.adopt()
        finally:
            finished.set()

    try:
        assert runner.start(call, delivered.append, delivered.append)
        wait(app, entered.is_set)
        owner.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finally:
        release.set()
    wait(app, finished.is_set)
    assert len(rows(database, "SELECT * FROM paper_research_questions")) == 1
    assert delivered == []


def test_runner_delivers_on_gui_thread_and_recovers_start_failure(monkeypatch):
    app = QApplication.instance() or QApplication([])
    runner = AdoptionRunner()
    results = []
    assert runner.start(lambda: 7, lambda n: results.append((n, QThread.currentThread())),
                        pytest.fail)
    wait(app, lambda: not runner.busy)
    assert results == [(7, app.thread())]
    def failed_start(_self):
        raise RuntimeError("Fixture thread creation failure")

    monkeypatch.setattr(threading.Thread, "start", failed_start)
    assert not runner.start(lambda: None, pytest.fail, results.append)
    assert not runner.busy
    assert results[-1] == "Fixture thread creation failure"
    runner.deleteLater()

@pytest.mark.parametrize("when", ["before_worker", "after_preview"])
def test_replaced_database_is_never_adopted(view, monkeypatch, when):
    import shutil

    app, widget, _, selected, *_ = view
    database = selected[0]
    original = database.read_bytes()
    if when == "after_preview":
        verified(view)
    else:
        start = widget.adoption_runner.start

        def delayed(call, done, failed):
            replacement = database.with_suffix(".replacement")
            replacement.write_bytes(original)
            os.replace(replacement, database)
            return start(call, done, failed)

        monkeypatch.setattr(widget.adoption_runner, "start", delayed)
    if when == "after_preview":
        replacement = database.with_suffix(".replacement")
        shutil.copyfile(database, replacement)
        os.replace(replacement, database)
        widget.adopt_legacy()
    else:
        widget.verify_legacy()
    wait(app, lambda: not widget.adoption_busy)
    assert widget._prepared_adoption is None
    assert "工作區已變動" in widget.adoption_status.text()
    assert rows(database, "SELECT * FROM paper_research_questions") == []


def test_pending_adoption_keeps_original_workspace_and_does_not_repaint_next(view, monkeypatch):
    app, widget, composer, selected, *_ = view
    verified(view)
    database = selected[0]
    prepared = widget._prepared_adoption
    original = type(prepared).adopt
    entered, release = threading.Event(), threading.Event()

    def adopt(operation):
        entered.set()
        assert release.wait(8)
        return original(operation)

    monkeypatch.setattr(type(prepared), "adopt", adopt)
    try:
        widget.adopt_legacy()
        wait(app, entered.is_set)
        selected[0] = database.with_name("unopened.sqlite")
        widget.load("paper")
        text, status = widget.detail.text(), widget.status.text()
    finally:
        release.set()
    wait(app, lambda: not widget.adoption_busy)
    assert len(rows(database, "SELECT * FROM paper_research_questions")) == 1
    assert not selected[0].exists()
    assert widget.detail.text() == text and widget.status.text() == status
    assert composer.text() == "A question I have not sent"


@pytest.mark.parametrize("width", [940, 600])
def test_verified_preview_actions_fit_bounded_window(view, width):
    from pathlib import Path

    from paper_daily.desktop import fonts

    app, widget, *_ = view
    fonts.load()
    widget.browser.setFont(fonts.font(pixels=fonts.UI_PIXELS))
    verified(view)
    widget.browser.resize(width, 500)
    app.processEvents()
    assert widget.browser.width() <= width
    assert widget.browser.height() <= 500
    for button in (widget.adopt_button, widget.verify_in_browser, widget.cancel, widget.insert):
        assert button.isVisible()
        assert widget.browser.rect().contains(button.geometry())
    assert "Original experiment" in widget.detail.text()
    assert widget.details_scroll.viewport().height() > 60
    destination = os.environ.get("PAPERFACT_TEST_SCREENSHOTS")
    if destination:
        target = Path(destination)
        target.mkdir(parents=True, exist_ok=True)
        assert widget.browser.grab().save(str(target / f"question-adoption-{width}.png"))


@pytest.mark.parametrize("reload_view", [False, True])
def test_ai_completion_does_not_leave_verify_or_refresh_disabled(view, monkeypatch, reload_view):
    from types import SimpleNamespace

    app, widget, *_ = view
    pending = []
    runner = SimpleNamespace(busy=False)

    def start(_prompt, done, failed, **_kwargs):
        runner.busy = True
        pending.append(failed)

    runner.start = start
    widget.runner = runner
    from paper_daily import llm

    monkeypatch.setattr(llm, "capture_connections", lambda: {})
    widget.generate(force=True)
    if reload_view:
        widget.load("paper")
    old_status = widget.status.text()
    pending[0]("Fixture model unavailable")
    # Actual AskRunner clears its delivery flag after invoking the callback.
    runner.busy = False
    wait(app, lambda: widget.verify_button.isEnabled() and widget.refresh_button.isEnabled())
    if reload_view:
        assert widget.status.text() == old_status
    else:
        assert "Fixture model unavailable" in widget.status.text()


def test_actual_main_close_and_restart_wait_for_local_adoption(view, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtGui import QCloseEvent

    from paper_daily.desktop.main import MainWindow

    app, widget, _, _, *_ = view
    original = question_legacy_adoption.prepare
    entered, release = threading.Event(), threading.Event()

    def prepare(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(question_legacy_adoption, "prepare", prepare)
    owner = SimpleNamespace(
        reader_page=SimpleNamespace(questions=widget, presentation_pane=object()),
        findChildren=lambda _kind: [],
    )
    try:
        widget.verify_legacy()
        wait(app, entered.is_set)
        event = QCloseEvent()
        MainWindow.closeEvent(owner, event)
        assert not event.isAccepted()
        assert MainWindow._prepare_restart(owner) is False
        assert widget.adoption_busy and not widget.runner.busy
    finally:
        release.set()
    wait(app, lambda: not widget.adoption_busy)
    assert widget.adopt_button.isEnabled()


def test_retry_after_lost_success_delivery_replays_same_adoption(view, monkeypatch):
    app, widget, _, selected, *_ = view
    verified(view)
    operation = widget._prepared_adoption
    original = type(operation).adopt
    calls = []

    def lost_response(prepared):
        result = original(prepared)
        calls.append(result)
        if len(calls) == 1:
            raise OSError("Fixture success response lost")
        return result

    monkeypatch.setattr(type(operation), "adopt", lost_response)
    widget.adopt_legacy()
    wait(app, lambda: not widget.adoption_busy)
    assert len(rows(selected[0], "SELECT * FROM paper_research_questions")) == 1
    assert widget._prepared_adoption is operation
    assert "可重試" in widget.adoption_status.text()
    widget.adopt_legacy()
    wait(app, lambda: not widget.adoption_busy)
    assert calls[0] == calls[1]
    assert "已採用" in widget.adoption_status.text()
    records = rows(selected[0], "SELECT * FROM research_generation_requests")
    assert len([record for record in records
                if json.loads(record["context_json"])["table"] == "paper_research_questions"]) == 1
