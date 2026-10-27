import json
from uuid import uuid4

import pytest
from test_chat_resume import candidate, pending
from test_reader_chat import reader as reader_fixture
from test_research_chat import legacy as legacy_fixture
from test_research_chat import messages

from paper_daily import llm, store, sync_recovery
from paper_daily import research_chat as chat
from paper_daily.desktop import main
from paper_daily.desktop.qa_review_dialog import ChatReviewDialog
from paper_daily.research_chat_review import (
    ChatPreview,
    ChatReview,
    load_record,
    validate_preview_snapshot,
)

reader = reader_fixture
legacy = legacy_fixture


def test_actual_candidate_dialog_applies_once_and_reopen_marks_reviewed(reader, monkeypatch):
    _, window, view = reader
    record = candidate()
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("review called AI"))
    dialog = ChatReviewDialog(
        store.DB_PATH, window, paper_id="local-paper", request_id=record["request_id"]
    )
    dialog.show()
    assert dialog.body.isReadOnly()
    assert "Retained answer" in dialog.body.toPlainText()
    assert dialog.apply.isEnabled() and not dialog.resume.isEnabled()
    dialog.apply.click()
    dialog.apply.click()
    assert len(messages()) == 2 and not dialog.apply.isEnabled()
    dialog.close()
    reopened = ChatReviewDialog(
        store.DB_PATH, window, paper_id="local-paper", request_id=record["request_id"]
    )
    assert not reopened.apply.isEnabled() and "已套用" in reopened.status.text()
    reopened.close()


def test_dialog_close_or_workspace_switch_rejects_late_apply(reader, tmp_path):
    _, window, _ = reader
    record = candidate()
    dialog = ChatReviewDialog(store.DB_PATH, window, request_id=record["request_id"])
    dialog.close()
    dialog._apply()
    assert len(messages()) == 1
    original = store.DB_PATH
    dialog = ChatReviewDialog(original, window, request_id=record["request_id"])
    store.DB_PATH = tmp_path / "different.db"
    try:
        dialog._apply()
    finally:
        store.DB_PATH = original
    assert len(messages()) == 1 and "失敗" in dialog.status.text()
    dialog.close()


def test_explicit_reattach_confirmation_cancel_preserves_candidate(reader, monkeypatch):
    _, window, _ = reader
    record = candidate()
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                {
                    "id": "target",
                    "title": "Chosen",
                    "year": 2026,
                    "venue": "Fixture",
                    "source": "fixture",
                }
            ],
        )
    dialog = ChatReviewDialog(store.DB_PATH, window, request_id=record["request_id"])
    dialog.target.setCurrentIndex(dialog.target.findData("target"))
    monkeypatch.setattr(
        main.QMessageBox, "question", lambda *a, **k: main.QMessageBox.StandardButton.No
    )
    dialog.apply.click()
    with store.connect() as conn:
        assert chat.history(conn, "target") == []
    assert dialog.apply.isEnabled()
    monkeypatch.setattr(
        main.QMessageBox, "question", lambda *a, **k: main.QMessageBox.StandardButton.Yes
    )
    dialog.apply.click()
    with store.connect() as conn:
        assert len(chat.history(conn, "target")) == 2
    dialog.close()


def test_pending_dialog_only_emits_explicit_resume(reader, monkeypatch):
    _, window, _ = reader
    request = pending()
    calls = []
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("dialog invoked AI"))
    dialog = ChatReviewDialog(store.DB_PATH, window, request_id=request.request_id)
    dialog.resume_requested.connect(calls.append)
    assert dialog.resume.isEnabled() and not dialog.apply.isEnabled() and calls == []
    dialog.resume.click()
    dialog.resume.click()
    assert calls == [request.request_id] and len(messages()) == 1


def test_review_backup_restore_archives_receipt_and_keeps_portable_link(legacy, tmp_path):
    record = candidate()
    review = ChatReview(legacy)
    preview = review.preview(record)
    review.apply(preview, request_id=str(uuid4()))
    archive = tmp_path / "review.zip"
    sync_recovery.create(legacy, archive)
    destination = tmp_path / "restore"
    sync_recovery.restore_detached(archive, destination)
    import sqlite3

    with sqlite3.connect(destination / "papers.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM chat").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM research_chat_links").fetchone()[0] == 2
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM recovery_records "
                "WHERE table_name='research_chat_review_receipts'"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='research_chat_review_receipts'"
            ).fetchone()[0]
            == 0
        )


def test_imported_foreign_record_requires_explicit_target_without_touching_source(legacy, tmp_path):
    record = candidate()
    path = tmp_path / "retained.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    imported = load_record(path)
    original = store.DB_PATH
    destination = tmp_path / "receiver"
    destination.mkdir()
    store.DB_PATH = destination / "papers.db"
    try:
        store.init_db()
        with store.connect() as conn:
            store.upsert_papers(
                conn,
                [
                    {
                        "id": "selected",
                        "title": "Receiver",
                        "year": 2026,
                        "venue": "Fixture",
                        "source": "fixture",
                    }
                ],
            )
        review = ChatReview(store.DB_PATH)
        preview = review.preview(imported)
        assert preview.data["target"] is None
        preview = review.target_preview(preview, "selected")
        review.apply(preview, request_id=str(uuid4()), confirm_target=True)
        with store.connect() as conn:
            assert len(chat.history(conn, "selected")) == 2
    finally:
        store.DB_PATH = original
    assert len(messages()) == 1 and json.loads(path.read_text(encoding="utf-8")) == record


def test_tampered_and_foreign_session_previews_are_rejected(legacy):
    record = candidate()
    review = ChatReview(legacy)
    preview = review.preview(record)
    other = ChatReview(legacy)
    with pytest.raises(ValueError):
        other.apply(preview, request_id=str(uuid4()))
    changed = preview.data
    changed["target"]["paper_id"] = "wrong"
    with pytest.raises(ValueError):
        review.apply(ChatPreview(json.dumps(changed), preview.seal), request_id=str(uuid4()))
    bad = preview.data
    bad["unknown"] = "injected"
    with pytest.raises(ValueError):
        validate_preview_snapshot(bad)
    assert len(messages()) == 1
