import json
from contextlib import closing

import pytest
from test_reader_chat import reader as reader_fixture
from test_research_chat import legacy as legacy_fixture
from test_research_chat import messages, start
from test_sync_capture import bound as bound_fixture
from test_sync_capture import seed

from paper_daily import llm
from paper_daily import research_chat as chat
from paper_daily import research_generation as generation
from paper_daily.desktop.qa_job import ChatJob
from paper_daily.research_chat_review import ChatReview

legacy = legacy_fixture
reader = reader_fixture
bound = bound_fixture


def make_job(monkeypatch, request=None):
    monkeypatch.setattr(llm, "ACCESS_CHECK", None)
    return ChatJob(request or start(), {}, llm.Settings("none"))


def test_unexpected_publish_failure_survives_new_job_without_second_model(legacy, monkeypatch):
    calls = []
    monkeypatch.setattr(
        llm, "complete", lambda *a, **k: (calls.append(1) or "Durable output", "ok")
    )
    original = chat.publish_answer
    monkeypatch.setattr(
        chat,
        "publish_answer",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("private provider error")),
    )
    job = make_job(monkeypatch)
    result, _ = job("")
    assert json.loads(result)["status"] == "candidate"
    request_id = job.request.request_id
    del job
    record = chat.list_recovery_requests(legacy)[0]
    assert "private provider error" not in json.dumps(record)
    restored = chat.load_request(legacy, request_id)
    assert chat.answer_record(restored) == "Durable output"
    monkeypatch.setattr(chat, "publish_answer", original)
    second = make_job(monkeypatch, restored)
    monkeypatch.setattr(
        llm, "ACCESS_CHECK", lambda *a, **k: pytest.fail("Completed output checked account")
    )
    assert json.loads(second("")[0])["status"] == "accepted"
    assert calls == [1] and len(messages()) == 2
    assert ChatReview(legacy).records() == []
    assert chat.answer_record(chat.load_request(legacy, request_id)) == "Durable output"


def test_exception_after_commit_recovers_exact_success_without_sidecar_or_duplicate(
    legacy, monkeypatch
):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: ("Committed output", "ok"))
    original = chat.publish_answer

    def lost_response(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Reply lost after commit")

    monkeypatch.setattr(chat, "publish_answer", lost_response)
    job = make_job(monkeypatch)
    assert json.loads(job("")[0])["status"] == "accepted"
    assert len(messages()) == 2 and chat.list_recovery_requests(legacy) == []
    assert json.loads(job("")[0])["status"] == "accepted"
    assert len(messages()) == 2


def test_completed_sidecar_can_be_reviewed_after_original_question_deleted(legacy, monkeypatch):
    request, _ = chat.prepare_chat(start())
    chat.retain_failed_answer(request, "Retained output")
    with closing(generation._connect(legacy)) as conn:
        conn.execute("DELETE FROM chat")
        conn.commit()
    restored = chat.load_request(legacy, request.request_id, resolve_document=False)
    assert chat.answer_record(restored) == "Retained output"
    review = ChatReview(legacy)
    preview = review.preview(restored._receipt)
    assert preview.data["confirmation"] and not preview.data["target"]["reuse"]


def test_same_path_completed_sidecar_with_changed_context_never_resumes_model(legacy):
    request, _ = chat.prepare_chat(start())
    chat.retain_failed_answer(request, "Original output")
    path = next((legacy.parent / ".paperfact-chat").glob("*/*.json"))
    row = json.loads(path.read_text(encoding="utf-8"))
    data = json.loads(row["context_json"])
    data["parent"]["row"]["title"] = "Forged context"
    row["context_json"] = chat._json(data)
    import hashlib

    row["candidate_id"] = hashlib.sha256(
        (row["context_json"] + row["answer_json"]).encode()
    ).hexdigest()
    path.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match="original question"):
        chat.load_request(legacy, request.request_id)
    assert len(messages()) == 1


def test_completed_output_found_by_deferred_resume_skips_preflight_and_model(legacy, monkeypatch):
    request, _ = chat.prepare_chat(start())
    job = ChatJob(request, {}, llm.Settings("none"), resume=True)
    assert job.answer is None
    chat.retain_failed_answer(request, "Output from earlier worker")
    monkeypatch.setattr(
        llm, "ACCESS_CHECK", lambda *a, **k: pytest.fail("preflight after completion")
    )
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("second model"))
    assert json.loads(job("")[0])["status"] == "accepted"
    assert len(messages()) == 2


def test_replaced_database_never_activates_old_completed_request(legacy):
    import sqlite3

    from paper_daily import store

    request, _ = chat.prepare_chat(start())
    saved = legacy.with_suffix(".old")
    legacy.rename(saved)
    store.init_db()
    before = legacy.read_bytes()
    assert chat.retain_failed_answer(request, "Old workspace output").status == "candidate"
    assert legacy.read_bytes() == before
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        chat.load_request(legacy, request.request_id)
    review = ChatReview(legacy)
    records = review.records()
    assert len(records) == 1
    assert review.preview(records[0]).data["target"] is None
    assert legacy.read_bytes() != b""


def test_completed_sidecar_keeps_old_pdf_source_when_new_pdf_arrives(tmp_path, monkeypatch):
    from test_chat_documents import request
    from test_document_reader import LOCAL, prepared
    from test_sync_document_research import document, pdf_bytes
    from test_sync_reading_state_research import save

    path, journal, _, reader, _, _ = prepared(tmp_path)
    original, _ = chat.prepare_chat(request(path, reader.resolve(LOCAL)))
    chat.retain_failed_answer(original, "Old PDF answer")
    save(journal, document(pdf_bytes("Later document"), op_id="later-document"))
    restored = chat.load_request(path, original.request_id)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("stale output reran AI"))
    job = ChatJob(restored, {}, llm.Settings("none"))
    assert json.loads(job("")[0])["status"] == "candidate"
    assert restored.data["document"]["sha256"] == original.data["document"]["sha256"]


def test_retention_failure_never_claims_success_and_keeps_live_cached_answer(legacy, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: ("Completed output", "ok"))
    monkeypatch.setattr(
        chat, "publish_answer", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("write failed"))
    )
    monkeypatch.setattr(
        chat, "_retain", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    )
    job = make_job(monkeypatch)
    with pytest.raises(OSError, match="disk full"):
        job("")
    assert job.result is None and job.answer == "Completed output"
    assert chat.list_recovery_requests(legacy) == [] and len(messages()) == 1


def test_existing_accepted_different_answer_is_never_acknowledged_as_ours(legacy):
    request, _ = chat.prepare_chat(start())
    assert chat.publish_answer(request, "Canonical answer").status == "accepted"
    with pytest.raises(ValueError, match="another result"):
        chat.retain_failed_answer(request, "Different output")
    assert messages()[-1]["body"] == "Canonical answer"
    assert chat.list_recovery_requests(legacy) == []


def test_accepted_sidecar_is_not_actionable_after_detached_restore(legacy, tmp_path):
    from paper_daily import sync_recovery

    request, _ = chat.prepare_chat(start())
    chat.retain_failed_answer(request, "Answer")
    assert chat.publish_answer(request, "Answer").status == "accepted"
    assert ChatReview(legacy).records() == []
    archive = tmp_path / "accepted.zip"
    sync_recovery.create(legacy, archive)
    sync_recovery.restore_detached(archive, tmp_path / "restored")
    assert ChatReview(tmp_path / "restored" / "papers.db").records() == []


def test_actual_reader_restart_opens_completed_review_without_model_or_account_prompt(
    reader, monkeypatch
):
    from types import SimpleNamespace

    from PySide6.QtCore import QCoreApplication, QEvent
    from test_reader_chat import Deferred

    from paper_daily import store
    from paper_daily.desktop import main

    app, first, view = reader
    calls = []
    monkeypatch.setattr(
        llm, "complete", lambda *a, **k: (calls.append(1) or "Recovered in UI", "ok")
    )
    original = chat.publish_answer
    monkeypatch.setattr(
        chat,
        "publish_answer",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("unexpected writer error")),
    )
    deferred = Deferred()
    monkeypatch.setattr(view, "runner", deferred)
    view._ask("Question")
    deferred.run()
    request_id = view._qa_job.request.request_id
    assert len(messages()) == 1 and first.close()
    monkeypatch.setattr(chat, "publish_answer", original)
    monkeypatch.setattr(
        main.QMessageBox,
        "question",
        lambda *a, **k: pytest.fail("Completed answer prompted AI route"),
    )
    second = main.MainWindow()
    current = second.reader_page
    current.paper = SimpleNamespace(id="local-paper")
    current._qa_view_database = store.DB_PATH.resolve()
    try:
        current._resume_qa(request_id)
        dialog = current._qa_review_dialog
        assert dialog.isVisible() and "Recovered in UI" in dialog.body.toPlainText()
        assert dialog.apply.isEnabled() and not dialog.resume.isEnabled()
        dialog.apply.click()
        assert messages()[-1]["body"] == "Recovered in UI" and calls == [1]
        dialog.close()
    finally:
        second._ready_poll.stop()
        second.workspace_changes.timer.stop()
        second.close()
        second.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("complete_rebind", [False, True])
def test_changed_binding_preserves_original_answer_without_writing_rebound_db(
    bound, complete_rebind
):
    import sqlite3

    seed()
    request, _ = chat.prepare_chat(start())
    path = bound.journal.path
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE research_capture_binding SET device='new-device'")
        if complete_rebind:
            conn.execute("UPDATE paperfact_sync_identity SET device='new-device'")
        count = conn.execute("SELECT COUNT(*) FROM paperfact_sync_operations").fetchone()[0]
    result = chat.retain_failed_answer(request, "Captured before binding changed")
    assert result.status == "candidate"
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM chat").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM paperfact_sync_operations").fetchone()[0] == count
    with pytest.raises(ValueError):
        chat.load_request(path, request.request_id)
    sidecar = next(path.parent.glob(".paperfact-chat/*/*.json"))
    record = chat.validate_request_record(json.loads(sidecar.read_text(encoding="utf-8")))
    assert json.loads(record["context_json"])["binding"]["device_id"] == "a"
    assert json.loads(record["answer_json"])["body"] == "Captured before binding changed"
