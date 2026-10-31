import json
from contextlib import closing
from uuid import uuid4

import pytest
from test_reader_chat import Deferred
from test_reader_chat import reader as reader_fixture
from test_research_chat import legacy as legacy_fixture
from test_research_chat import messages, start
from test_sync_capture import bound as bound_fixture
from test_sync_capture import seed

from paper_daily import llm, store
from paper_daily import research_chat as chat
from paper_daily import research_generation as generation
from paper_daily.desktop import main
from paper_daily.research_chat_review import ChatReview

base_reader = reader_fixture


@pytest.fixture
def reader(base_reader, monkeypatch):
    from PySide6.QtTest import QTest

    from paper_daily.manual_highlight_ops import capture_owner

    app, window, view = base_reader
    view._highlight_owner = capture_owner(view._qa_view_database, "local-paper")
    original = main.ReaderPage._load_chat

    def await_render(target):
        original(target)
        if target is view:
            for _ in range(1000):
                app.processEvents()
                if not view.preparation.busy:
                    break
                QTest.qWait(5)
            else:
                pytest.fail("Queued saved conversation did not drain")

    monkeypatch.setattr(main.ReaderPage, "_load_chat", await_render)
    yield app, window, view
    view.preparation.dispose()
    for _ in range(1000):
        app.processEvents()
        if not view.preparation.busy:
            break
        QTest.qWait(5)
legacy = legacy_fixture
bound = bound_fixture


def pending():
    request, _ = chat.prepare_chat(start())
    return request


def candidate():
    request = pending()
    with store.connect() as conn:
        conn.execute("UPDATE papers SET title='New title' WHERE id='local-paper'")
    assert chat.publish_answer(request, "Retained answer").status == "candidate"
    with closing(generation._connect(store.DB_PATH)) as conn:
        return dict(conn.execute("SELECT * FROM research_chat_requests").fetchone())


def test_restart_resume_explicit_current_route_preserves_ids_and_deduplicates(reader, monkeypatch):
    app, _, view = reader
    request = pending()
    before = messages()[0]
    deferred = Deferred()
    monkeypatch.setattr(view, "runner", deferred)
    llm.save_settings(
        profile="restart", backend="openai", model="chosen-after-restart", isolated=True
    )
    llm.use_profile("restart", desktop=True)
    calls = []
    monkeypatch.setattr(
        llm,
        "complete",
        lambda prompt, cfg, **kw: (calls.append(cfg.model) or "Resumed answer", "ok"),
    )
    confirmations = []

    def confirm(*args, **kw):
        confirmations.append(args[2])
        view._resume_qa(request.request_id)
        app.processEvents()
        return main.QMessageBox.StandardButton.Yes

    monkeypatch.setattr(main.QMessageBox, "question", confirm)
    view._resume_qa(request.request_id)
    assert len(confirmations) == 1
    assert "chosen-after-restart" in confirmations[0]
    view._resume_qa(request.request_id)
    deferred.run()
    assert calls == ["chosen-after-restart"]
    assert messages()[0] == before
    assert len(messages()) == 2
    assert messages()[1]["reply_to"] == before["message_id"]


def test_cancel_resume_and_navigation_during_confirm_make_no_job(reader, monkeypatch):
    _, _, view = reader
    request = pending()
    deferred = Deferred()
    monkeypatch.setattr(view, "runner", deferred)
    monkeypatch.setattr(
        main.QMessageBox, "question", lambda *a, **k: main.QMessageBox.StandardButton.No
    )
    view._resume_qa(request.request_id)
    assert not deferred.busy and len(messages()) == 1

    def navigate(*a, **k):
        view._qa_epoch += 1
        return main.QMessageBox.StandardButton.Yes

    monkeypatch.setattr(main.QMessageBox, "question", navigate)
    view._resume_qa(request.request_id)
    assert not deferred.busy and len(messages()) == 1
    assert view.ask_btn.isEnabled()


def test_deleted_question_is_not_resumed_or_regenerated(legacy, monkeypatch):
    request = pending()
    with store.connect() as conn:
        conn.execute("DELETE FROM chat")
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("unexpected model"))
    with pytest.raises(ValueError, match="question changed"):
        chat.load_request(legacy, request.request_id, resolve_document=False)


def test_render_pending_question_has_explicit_resume_without_starting_job(reader, monkeypatch):
    _, _, view = reader
    request = pending()
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("read invoked model"))
    main.ReaderPage._load_chat(view)
    rendered = view._exchange(messages()[0], None)
    assert "resumeqa:" + request.request_id in rendered
    assert not view.runner.busy


def test_candidate_apply_atomic_reuses_original_turn_and_retains_source(legacy, monkeypatch):
    record = candidate()
    review = ChatReview(legacy)
    preview = review.preview(record)
    key = str(uuid4())
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("review invoked model"))
    result = review.apply(preview, request_id=key)
    assert review.apply(preview, request_id=key) == result
    rows = messages()
    assert len(rows) == 2 and rows[-1]["body"] == "Retained answer"
    assert rows[-1]["reply_to"] == rows[0]["message_id"]
    with store.connect() as conn:
        assert (
            conn.execute("SELECT status FROM research_chat_requests").fetchone()[0] == "candidate"
        )
        assert conn.execute("SELECT COUNT(*) FROM research_chat_review_receipts").fetchone()[0] == 1
    with pytest.raises(ValueError, match="reused"):
        review.apply(preview, body="Different", request_id=key)


@pytest.mark.parametrize("change", ["paper", "history", "delete_recreate", "closed"])
def test_candidate_displayed_base_changes_fail_without_overwrite(legacy, change):
    record = candidate()
    review = ChatReview(legacy)
    preview = review.preview(record)
    if change == "closed":
        review.close()
    else:
        with store.connect() as conn:
            if change == "paper":
                conn.execute("UPDATE papers SET title='Later title'")
            elif change == "history":
                conn.execute(
                    "INSERT INTO chat(paper_id,role,body,created_at) "
                    "VALUES('local-paper','user','New question','2026-10-27T00:00:00Z')"
                )
            else:
                original = dict(
                    conn.execute("SELECT * FROM papers WHERE id='local-paper'").fetchone()
                )
                conn.execute("DELETE FROM papers WHERE id='local-paper'")
                fields = ",".join(original)
                marks = ",".join("?" for _ in original)
                conn.execute(
                    f"INSERT INTO papers({fields}) VALUES({marks})", tuple(original.values())
                )
    before = messages()
    with pytest.raises(ValueError):
        review.apply(preview, request_id=str(uuid4()))
    assert messages() == before


def test_explicit_target_required_for_recreated_parent_and_keeps_original_receipt(legacy):
    record = candidate()
    with store.connect() as conn:
        conn.execute("DELETE FROM papers WHERE id='local-paper'")
        store.upsert_papers(
            conn,
            [
                {
                    "id": "new-paper",
                    "title": "Chosen target",
                    "year": 2026,
                    "venue": "Fixture",
                    "source": "fixture",
                }
            ],
        )
    review = ChatReview(legacy)
    preview = review.preview(record)
    assert preview.data["target"] is None
    with pytest.raises(ValueError):
        review.apply(preview, request_id=str(uuid4()))
    preview = review.target_preview(preview, "new-paper")
    with pytest.raises(ValueError, match="Confirm"):
        review.apply(preview, request_id=str(uuid4()))
    result = review.apply(preview, request_id=str(uuid4()), confirm_target=True)
    with store.connect() as conn:
        rows = chat.history(conn, "new-paper")
    assert len(rows) == 2 and rows[1]["reply_to"] == rows[0]["message_id"]
    assert result["exchange_id"] != record["request_id"]


def test_enrolled_review_captures_answer_and_receipt_in_one_transaction(bound):
    seed()
    record = candidate()
    review = ChatReview(store.DB_PATH)
    preview = review.preview(record)
    before = len(bound.journal.pending())
    review.apply(preview, request_id=str(uuid4()))
    ops = bound.journal.pending()[before:]
    assert len(ops) == 1 and ops[0]["payload"]["data"]["body"] == "Retained answer"
    assert ops[0]["payload"]["data"]["reply_to"] == json.loads(record["context_json"])["user_key"]


def test_writer_failure_rolls_back_both_turns_and_review_receipt(legacy, monkeypatch):
    record = candidate()
    review = ChatReview(legacy)
    preview = review.preview(record)
    original = chat._append

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected")

    monkeypatch.setattr(chat, "_append", fail)
    with pytest.raises(RuntimeError):
        review.apply(preview, request_id=str(uuid4()))
    assert len(messages()) == 1
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_chat_review_receipts").fetchone()[0] == 0


def test_resume_keeps_an_unrelated_composer_draft(reader, monkeypatch):
    _, _, view = reader
    request = pending()
    deferred = Deferred()
    monkeypatch.setattr(view, "runner", deferred)
    monkeypatch.setattr(
        main.QMessageBox, "question", lambda *a, **k: main.QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(llm, "complete", lambda *a, **k: ("Resumed", "ok"))
    view.ask_box.setText("Unrelated unsent draft")
    view._page_context = (3, "new selection")
    view._resume_qa(request.request_id)
    deferred.run()
    assert view.ask_box.text() == "Unrelated unsent draft"
    assert view._page_context == (3, "new selection")
    assert messages()[-1]["body"] == "Resumed"


def test_live_resume_retry_retains_route_and_question_after_failure(reader, monkeypatch):
    _, _, view = reader
    request = pending()
    deferred = Deferred()
    monkeypatch.setattr(view, "runner", deferred)
    monkeypatch.setattr(
        main.QMessageBox, "question", lambda *a, **k: main.QMessageBox.StandardButton.Yes
    )
    llm.save_settings(profile="first", backend="openai", model="resume-first", isolated=True)
    llm.save_settings(profile="second", backend="openai", model="resume-second", isolated=True)
    llm.use_profile("first", desktop=True)
    calls = []

    def complete(prompt, cfg, **kwargs):
        calls.append(cfg.model)
        return (None, "Fixture failure") if len(calls) == 1 else ("Retried", "ok")

    monkeypatch.setattr(llm, "complete", complete)
    view._resume_qa(request.request_id)
    deferred.run()
    assert len(messages()) == 1 and view.ask_box.text() == "Question"
    llm.use_profile("second", desktop=True)
    view._resume_qa(request.request_id)
    deferred.run()
    assert calls == ["resume-first", "resume-first"] and len(messages()) == 2


def test_review_reattach_enrolled_two_turns_replay_with_correct_pairing(bound, tmp_path):
    from test_sync_capture import make

    from paper_daily.desktop.main import _exchanges
    from paper_daily.sync_service import ReferenceService

    seed()
    record = candidate()
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                {
                    "id": "selected",
                    "title": "Selected",
                    "year": 2026,
                    "venue": "Fixture",
                    "source": "fixture",
                }
            ],
        )
    review = ChatReview(store.DB_PATH)
    preview = review.preview(record, target_paper_id="selected")
    result = review.apply(preview, request_id=str(uuid4()), confirm_target=True)
    authority = ReferenceService(tmp_path / "authority.db")
    bound.sync_once(authority, authority.enroll("workspace", "a"))
    peer = make(tmp_path / "peer.db", "b")
    peer.receive(authority.pull(authority.enroll("workspace", "b")))
    with closing(generation._connect(peer.journal.path)) as conn:
        paper = conn.execute("SELECT id FROM papers WHERE title='Selected'").fetchone()[0]
        rows = chat.history(conn, paper)
    pairs = _exchanges(rows)
    assert len(pairs) == 1 and pairs[0][1]["body"] == "Retained answer"
    assert pairs[0][0]["message_id"] == result["user_key"]
    assert pairs[0][1]["reply_to"] == result["user_key"]


def test_managed_document_replacement_after_review_rejects_without_new_answer(tmp_path):
    from test_chat_documents import request
    from test_document_reader import LOCAL, prepared
    from test_sync_document_research import document, pdf_bytes
    from test_sync_reading_state_research import save

    path, journal, _, reader, _, _ = prepared(tmp_path)
    original, _ = chat.prepare_chat(request(path, reader.resolve(LOCAL)))
    save(journal, document(pdf_bytes("New PDF"), op_id="new-pdf"))
    assert chat.publish_answer(original, "Old PDF answer").status == "candidate"
    with closing(generation._connect(path)) as conn:
        record = dict(conn.execute("SELECT * FROM research_chat_requests").fetchone())
    review = ChatReview(path)
    preview = review.preview(record)
    save(journal, document(pdf_bytes("Even newer PDF"), op_id="later-pdf"))
    with pytest.raises(ValueError, match="document version"):
        review.apply(preview, request_id=str(uuid4()))
    with closing(generation._connect(path)) as conn:
        assert len(chat.history(conn, LOCAL)) == 1


def test_retained_sidecar_supersedes_pending_receipt_and_detached_review_is_explicit(
    legacy, tmp_path
):
    import json

    from paper_daily import sync_recovery

    request = pending()
    chat._retain(
        request,
        {**request._receipt, "answer_json": json.dumps({"body": "Recovered output"})},
        "Original write temporarily unavailable",
    )
    review = ChatReview(legacy)
    records = review.records("local-paper")
    assert len(records) == 1 and records[0]["status"] == "candidate"
    archive = tmp_path / "sidecar.zip"
    sync_recovery.create(legacy, archive)
    sync_recovery.restore_detached(archive, tmp_path / "detached")
    detached = ChatReview(tmp_path / "detached" / "papers.db")
    records = detached.records()
    assert len(records) == 1 and records[0]["status"] == "candidate"
    preview = detached.preview(records[0])
    assert preview.data["target"] is None
    preview = detached.target_preview(preview, "local-paper")
    detached.apply(preview, request_id=str(uuid4()), confirm_target=True)
    with closing(generation._connect(detached.path)) as conn:
        assert chat.history(conn, "local-paper")[-1]["body"] == "Recovered output"
    assert len(messages()) == 1


def test_resume_deleted_question_before_worker_runs_never_calls_model(reader, monkeypatch):
    _, _, view = reader
    request = pending()
    deferred = Deferred()
    monkeypatch.setattr(view, "runner", deferred)
    monkeypatch.setattr(
        main.QMessageBox, "question", lambda *a, **k: main.QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(
        llm, "complete", lambda *a, **k: pytest.fail("Deleted question reached model")
    )
    view._resume_qa(request.request_id)
    with store.connect() as conn:
        conn.execute("DELETE FROM chat")
    deferred.run()
    assert messages() == [] and view.ask_box.text() == "Question"


def test_actual_close_rejects_while_resume_worker_active(reader, monkeypatch):
    from PySide6.QtGui import QCloseEvent

    _, window, view = reader
    request = pending()
    deferred = Deferred()
    monkeypatch.setattr(view, "runner", deferred)
    monkeypatch.setattr(
        main.QMessageBox, "question", lambda *a, **k: main.QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(llm, "complete", lambda *a, **k: ("Finished before close", "ok"))
    view._resume_qa(request.request_id)
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted() and len(messages()) == 1
    deferred.run()
    assert messages()[-1]["body"] == "Finished before close"


def test_review_supports_six_bounded_large_legacy_inputs_without_losing_history(legacy):
    with store.connect() as conn:
        for index in range(6):
            conn.execute(
                "INSERT INTO chat(paper_id,role,body,created_at) VALUES(?,?,?,?)",
                ("local-paper", "user", str(index) + "x" * (180 * 1024), "2026-10-27T00:00:00Z"),
            )
    record = candidate()
    review = ChatReview(legacy)
    preview = review.preview(record)
    review.apply(preview, request_id=str(uuid4()))
    assert len(messages()) == 8 and messages()[-1]["body"] == "Retained answer"
