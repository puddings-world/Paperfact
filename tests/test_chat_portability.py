import json
import sqlite3
import zipfile
from contextlib import closing
from uuid import uuid4

from test_research_chat import legacy as legacy_fixture
from test_research_chat import start
from test_sync_capture import bound as bound_fixture
from test_sync_capture import make, seed

from paper_daily import bundle, research_generation, store, sync_recovery
from paper_daily import research_chat as chat
from paper_daily.desktop.main import _exchanges
from paper_daily.sync_capture import install
from paper_daily.sync_service import ReferenceService

legacy = legacy_fixture
bound = bound_fixture


def linked_rows():
    exchanges = [str(uuid4()), str(uuid4())]
    ids = [str(uuid4()) for _ in range(4)]
    rows = []
    for index, (role, body, group, parent) in enumerate(
        [
            ("user", "Same question", 0, None),
            ("user", "Same question", 1, None),
            ("assistant", "First answer", 0, ids[0]),
            ("assistant", "Second answer", 1, ids[1]),
        ]
    ):
        rows.append(
            dict(
                paper_id="local-paper",
                role=role,
                body=body,
                created_at="2026-10-27T00:00:00+00:00",
                page=None,
                anchor=None,
                message_id=ids[index],
                exchange_id=exchanges[group],
                reply_to=parent,
                source_hash=None,
            )
        )
    return rows


def pairs(path, paper="local-paper"):
    with closing(research_generation._connect(path)) as conn:
        return [
            (q["body"] if q else None, a["body"] if a else None)
            for q, a in _exchanges(chat.history(conn, paper))
        ]


def test_interleaved_bundle_import_and_reexport_preserves_ids_without_duplicates(
    legacy, tmp_path, monkeypatch
):
    with store.connect() as conn:
        for row in linked_rows():
            chat.import_shared_turn(conn, row)
    source = legacy.parent
    monkeypatch.setattr(bundle, "DATA_DIR", source)
    monkeypatch.setattr(bundle, "PDF_DIR", source / "pdf")
    archive = tmp_path / "share.zip"
    bundle.export("list", archive, with_pdfs=False)
    recipient = tmp_path / "recipient"
    recipient.mkdir()
    monkeypatch.setattr(store, "DB_PATH", recipient / "papers.db")
    monkeypatch.setattr(bundle, "DATA_DIR", recipient)
    monkeypatch.setattr(bundle, "PDF_DIR", recipient / "pdf")
    store.init_db()
    bundle.import_(archive, pdfs=False)
    assert pairs(store.DB_PATH) == [
        ("Same question", "First answer"),
        ("Same question", "Second answer"),
    ]
    bundle.import_(archive, pdfs=False)
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM chat").fetchone()[0] == 4
    exported = tmp_path / "again.zip"
    bundle.export("list", exported, with_pdfs=False)
    with zipfile.ZipFile(archive) as first, zipfile.ZipFile(exported) as second:
        assert (
            json.loads(first.read("tables.json"))["chat"]
            == json.loads(second.read("tables.json"))["chat"]
        )


def test_detached_backup_restores_links_but_does_not_activate_old_qa_receipts(legacy, tmp_path):
    request, _ = chat.prepare_chat(start())
    assert chat.publish_answer(request, "Answer").status == "accepted"
    archive = tmp_path / "backup.zip"
    sync_recovery.create(legacy, archive)
    sync_recovery.restore_detached(archive, tmp_path / "detached")
    detached = tmp_path / "detached" / "papers.db"
    assert pairs(detached) == [("Question", "Answer")]
    with sqlite3.connect(detached) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE name='research_chat_requests'"
            ).fetchone()[0]
            == 0
        )
        record = json.loads(
            conn.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_chat_requests'"
            ).fetchone()[0]
        )
        assert chat.validate_request_record(record)["status"] == "accepted"


def test_two_device_concurrent_questions_pair_after_actual_sync_without_model_calls(
    bound, tmp_path, monkeypatch
):
    seed()
    service = ReferenceService(tmp_path / "service.db")
    token_a = service.enroll("workspace", "a")
    bound.sync_once(service, token_a)
    peer = make(tmp_path / "peer.db", "b")
    token_b = service.enroll("workspace", "b")
    peer.receive(service.pull(token_b))
    first, _ = chat.prepare_chat(start("First question"))
    assert chat.publish_answer(first, "First answer").status == "accepted"
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "peer.db")
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="workspace", device_id="b")
    with store.connect() as conn:
        local = conn.execute("SELECT id FROM papers").fetchone()[0]
        request = chat.begin_chat(
            conn, paper_id=local, question="Second question", request_id=str(uuid4())
        )
    second, _ = chat.prepare_chat(request)
    assert chat.publish_answer(second, "Second answer").status == "accepted"
    bound.sync_once(service, token_a)
    peer.sync_once(service, token_b)
    bound.sync_once(service, token_a)
    assert set(pairs(bound.journal.path)) == {
        ("First question", "First answer"),
        ("Second question", "Second answer"),
    }


def test_hash_only_qa_source_cannot_be_claimed_as_complete_backup(legacy, tmp_path):
    import pytest

    row = linked_rows()[0]
    row["source_hash"] = "a" * 64
    with store.connect() as conn:
        chat.import_shared_turn(conn, row)
    with pytest.raises(sync_recovery.RecoveryError, match="source PDF"):
        sync_recovery.create(legacy, tmp_path / "incomplete.zip")
    assert not (tmp_path / "incomplete.zip").exists()
