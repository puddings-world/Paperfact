"""Prepared identity is presentation only; real ChatJob owns the durable answer."""

import threading
import weakref
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_reader_ai_scope import _bodies, _until
from test_reader_ai_scope import asking as _asking
from test_reader_prepare import _settle_owned
from test_reader_prepare import window as _window
from test_research_chat import legacy as _legacy
from test_research_chat import messages, start

from paper_daily import llm, research_chat
from paper_daily.desktop.qa_job import ChatJob

window = _window
asking = _asking
legacy = _legacy


def test_prepared_uuid_refreshes_on_gui_once_and_preserves_live_drafts(asking, monkeypatch):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    _settle_owned(reader.preparation, app)
    observed, refreshed = [], []
    reader.qa_presentation.prepared.connect(observed.append)
    request = reader.preparation.request

    def refresh(*args, **kwargs):
        refreshed.append(threading.current_thread() is threading.main_thread())
        return request(*args, **kwargs)

    monkeypatch.setattr(reader.preparation, "request", refresh)
    obsolete = "00000000-0000-4000-8000-000000000001"
    reader.qa_presentation.prepared.emit(obsolete)
    reader._ask("Prepared original question")
    job = reader._qa_job
    reader.ask_box.setText("Unsent next question")
    reader.note_edit.setPlainText("Unsent note")
    _until(app, lambda: reader.qa_presentation.state()[0] is not None)
    _settle_owned(reader.preparation, app)
    assert observed == [obsolete, job.request.request_id]
    assert all(refreshed) and refreshed
    assert "思考中" in reader.chat_view._body
    assert _bodies(win, "a") == [("user", "Prepared original question")]
    assert len(calls) == 1
    reader._ask("Duplicate click")
    with ThreadPoolExecutor(max_workers=1) as worker:
        worker.submit(job.prepared, job.request).result(timeout=10)
    app.processEvents()
    assert observed == [obsolete, job.request.request_id, job.request.request_id]
    assert reader.qa_presentation.state()[0] == job.request.request_id
    calls[0][1]("Original durable answer")
    _settle_owned(reader.preparation, app)
    assert reader.qa_presentation.state()[0] is None
    assert "思考中" not in reader.chat_view._body
    assert _bodies(win, "a") == [
        ("user", "Prepared original question"), ("assistant", "Original durable answer")
    ]
    assert reader.ask_box.text() == "Unsent next question"
    assert reader.note_edit.toPlainText() == "Unsent note"
    assert len(calls) == 1


def test_queued_original_notice_cannot_install_after_paper_switch(asking):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    _settle_owned(reader.preparation, app)
    reader._ask("A before queued delivery")
    win.open_paper("b")
    reader.ask_box.setText("B draft")
    reader.note_edit.setPlainText("B note")
    _settle_owned(reader.preparation, app)
    assert reader.qa_presentation.state()[0] is None
    assert "A before queued delivery" not in reader.chat_view._body
    calls[0][1]("Durable A answer")
    _settle_owned(reader.preparation, app)
    assert _bodies(win, "a")[-1] == ("assistant", "Durable A answer")
    assert _bodies(win, "b") == []
    assert "Durable A answer" not in reader.chat_view._body
    assert reader.ask_box.text() == "B draft" and reader.note_edit.toPlainText() == "B note"


def test_observer_failure_never_retries_or_loses_durable_answer(asking, monkeypatch):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    failures = []

    def broken(*_args):
        failures.append(True)
        raise RuntimeError("Display is unavailable")

    monkeypatch.setattr(reader.qa_presentation, "begin", lambda *_: broken)
    reader._ask("Durable despite observer")
    calls[0][1]("One durable answer")
    assert failures == [True] and len(calls) == 1
    assert _bodies(win, "a") == [
        ("user", "Durable despite observer"), ("assistant", "One durable answer")
    ]
    _settle_owned(reader.preparation, app)


def test_native_source_epoch_rejects_already_queued_prepared_notice(asking):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    _settle_owned(reader.preparation, app)
    reader._ask("Original loaded version")
    before = reader.pdf.position_identity()
    assert reader.pdf.load(before[1])
    assert reader.pdf.position_identity()[0] != before[0]
    _settle_owned(reader.preparation, app)
    assert reader.qa_presentation.state()[0] is None
    calls[0][1]("Answer remains owned by A")
    assert _bodies(win, "a")[-1] == ("assistant", "Answer remains owned by A")


def test_prior_failure_does_not_replace_new_current_status_or_drafts(asking):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    reader._ask("Old question")
    win.open_paper("b")
    reader.ask_status.setText("Current B action")
    reader.ask_box.setText("B typed question")
    calls[0][2]("Old failure")
    assert reader.ask_status.text() == "Current B action"
    assert reader.ask_box.text() == "B typed question"
    assert _bodies(win, "b") == []
    _settle_owned(reader.preparation, app)


def test_accepted_close_disposes_weak_sink_after_held_job_delivery(asking):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    _settle_owned(reader.preparation, app)
    reader._ask("Held close question")
    controller = reader.qa_presentation
    _until(app, lambda: controller.state()[0] is not None)
    assert not win.close()
    assert not controller._closed
    calls[0][1]("Drained answer")
    _settle_owned(reader.preparation, app)
    assert win.close()
    assert controller._closed and controller._mail is None
    assert controller._run is None and controller._lease is None and controller._scope is None
    assert isinstance(controller._reader, weakref.ReferenceType)
    reader._qa_job.prepared(reader._qa_job.request)
    app.processEvents()
    assert controller.state()[0] is None and len(calls) == 1


def test_workspace_owner_close_rejects_queued_notice_but_keeps_durable_job(asking):
    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    _settle_owned(reader.preparation, app)
    reader._ask("Original workspace")
    win._workspace_owner.close()
    app.processEvents()
    assert reader.qa_presentation.state()[0] is None
    calls[0][1]("Original workspace answer")
    assert _bodies(win, "a")[-1] == ("assistant", "Original workspace answer")


def test_cached_answer_publication_does_not_announce_model_thinking(legacy, monkeypatch):
    request, _ = research_chat.prepare_chat(start())
    accepted = research_chat.publish_answer(request, "Already completed answer")
    restored = research_chat.load_request(legacy, request.request_id)
    notices = []
    monkeypatch.setattr(llm, "complete", lambda *_, **__: pytest.fail("No repeated model"))
    monkeypatch.setattr(llm, "ACCESS_CHECK", lambda *_: pytest.fail("No login for saved output"))
    job = ChatJob(restored, {}, None, resume=True, prepared=notices.append)
    response, reason = job("")
    assert response and reason == "ok" and job.result == accepted
    assert notices == []
    assert [(row["role"], row["body"]) for row in messages()] == [
        ("user", "Question"), ("assistant", "Already completed answer")
    ]


def test_cancel_resume_keeps_original_request_without_job_or_display_authority(asking, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    reader._ask("Retry needs explicit consent")
    calls[0][2]("Unfinished fixture call")
    identity = reader._qa_job.request.request_id
    reader.ask_box.setText("Unsent different question")
    prompts = []

    def no(*args):
        prompts.append(args)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", no)
    reader._resume_qa(identity)
    _settle_owned(reader.preparation, app)
    assert len(prompts) == 1 and len(calls) == 1
    assert reader._qa_job.request.request_id == identity
    assert reader.qa_presentation.state()[0] is None
    assert reader.ask_box.text() == "Unsent different question"
    assert _bodies(win, "a") == [("user", "Retry needs explicit consent")]


def test_changed_same_path_bytes_reject_notice_and_retain_completed_output(asking):
    import pymupdf

    win, app, calls = asking
    reader = win.reader_page
    win.open_paper("a")
    _settle_owned(reader.preparation, app)
    reader._ask("Question about loaded bytes A")
    job = reader._qa_job
    path = reader.pdf.position_identity()[1]
    count = reader.pdf.page_count()
    with pymupdf.open(path) as changed:
        changed[0].insert_text((40, 260), "Changed source with unchanged page count")
        changed.saveIncr()
    app.processEvents()
    assert reader.pdf.page_count() == count
    assert reader.qa_presentation.state()[0] is None
    calls[0][1]("Completed for original bytes")
    assert job.result.status == "candidate"
    assert _bodies(win, "a") == [("user", "Question about loaded bytes A")]
    assert reader.ask_btn.isEnabled()


