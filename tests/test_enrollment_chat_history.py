"""Real fake-provider QA publication survives isolated enrollment and peer transfer."""

import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_enrollment_history_peer import peer
from test_sync_source_files import pdf as pdf_bytes
from test_workspace_enrollment import pdf
from test_workspace_enrollment import source as source_fixture

from paper_daily import enrollment_chat_history as history
from paper_daily import enrollment_history, llm
from paper_daily import research_chat as chat
from paper_daily import research_generation as generation
from paper_daily.desktop.qa_job import ChatJob
from paper_daily.sync_source_files import resolved
from paper_daily.workspace_enrollment import EnrollmentService
from paper_daily.workspace_service import Cancelled, SnapshotChanged, Ticket

source = source_fixture


def ask(source, monkeypatch, *, complete=True):
    original = pdf(source)
    with closing(generation._connect(source)) as conn:
        request = chat.begin_chat(
            conn,
            paper_id="paper",
            question="Explain the original evidence",
            request_id=str(uuid4()),
            legacy_root=original.parent,
        )
    calls = []
    monkeypatch.setattr(llm, "ACCESS_CHECK", None)
    monkeypatch.setattr(
        llm, "complete", lambda *a, **k: (calls.append(1) or "The original answer", "ok")
    )
    job = ChatJob(request, {}, llm.Settings("none"))
    if complete:
        assert json.loads(job("")[0])["status"] == "accepted"
        assert json.loads(job("")[0])["status"] == "accepted"
        assert calls == [1]
    else:
        job.request, _ = chat.prepare_chat(request)
    return original, job


def prepare(source, tmp_path, primary, **kwargs):
    return EnrollmentService(source).prepare(
        tmp_path / "candidate",
        backup_output=tmp_path / "backup.zip",
        request_id=str(uuid4()),
        pdfs={"paper": primary},
        **kwargs,
    )


def test_actual_chatjob_plan_prepare_backup_peer_preserves_links_and_old_source(
    source, tmp_path, monkeypatch
):
    primary, job = ask(source, monkeypatch)
    old_bytes = primary.read_bytes()
    old_hash = hashlib.sha256(old_bytes).hexdigest()
    old = primary.with_name("original.pdf")
    primary.rename(old)
    primary.write_bytes(pdf_bytes("Primary B is now current"))
    before = source.read_bytes()
    with closing(generation._connect(source)) as conn:
        expected = chat.history(conn, "paper")
        receipt = dict(conn.execute("SELECT * FROM research_chat_requests").fetchone())
    plan = EnrollmentService(source).plan(pdfs={"paper": primary})
    assert plan["supported"] and plan["live_chat_links"] == 2
    assert plan["original_source_count"] == 1 and plan["unresolved_chat_replies"] == 0
    result = prepare(source, tmp_path, primary)
    assert source.read_bytes() == before and old.read_bytes() == old_bytes
    assert result["uploaded"] is result["adopted"] is False
    database = Path(result["database"])
    with closing(generation._connect(database)) as conn:
        assert chat.history(conn, "paper") == expected
        rows = enrollment_history.archived(conn)
        assert receipt in [enrollment_history.validate(row)[0] for row in rows]
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_chat_requests'"
        ).fetchone()
        assert len(history.live_inventory(conn, Ticket())["links"]) == 2
    with zipfile.ZipFile(result["backup"]) as archive:
        archived = archive.read("tables/research_history_archive.jsonl")
        assert receipt["request_id"].encode() in archived
        assert archive.read("objects/" + old_hash) == old_bytes
    a, b, service, ta, tb, portable, local, artifacts = peer(result, tmp_path)
    with b.journal.transaction() as conn:
        turns = chat.history(conn, local)
        assert [{key: row[key] for key in history.LINK} for row in turns] == [
            {key: row[key] for key in history.LINK} for row in expected
        ]
        assert [row["body"] for row in turns] == [row["body"] for row in expected]
        located = resolved(conn, portable, old_hash)
        assert located is not None and located.read_bytes() == old_bytes
    assert source.read_bytes() == before


@pytest.mark.parametrize("mode", ["prepared", "candidate", "sidecar"])
def test_partial_and_completed_candidate_remain_private_without_assistant_turn(
    source, tmp_path, monkeypatch, mode
):
    primary, job = ask(source, monkeypatch, complete=False)
    if mode == "candidate":
        with closing(generation._connect(source)) as conn, conn:
            conn.execute(
                "UPDATE papers SET title='Changed title',title_key='changedtitle' WHERE id='paper'"
            )
        assert chat.publish_answer(job.request, "Private completed candidate").status == "candidate"
    elif mode == "sidecar":
        chat.retain_failed_answer(job.request, "Private completed candidate")
    before = source.read_bytes()
    result = prepare(source, tmp_path, primary)
    with closing(generation._connect(result["database"])) as conn:
        assert [(row["role"], row["body"]) for row in chat.history(conn, "paper")] == [
            ("user", "Explain the original evidence")
        ]
        records = [
            enrollment_history.validate(row)[0]
            for row in enrollment_history.archived(conn)
            if row["protocol"].startswith("research_chat_")
            and row["protocol"] != "research_chat_links"
        ]
        assert len(records) == (2 if mode == "sidecar" else 1)
        if mode != "prepared":
            assert any(
                "Private completed candidate" in (row["answer_json"] or "") for row in records
            )
    assert source.read_bytes() == before


@pytest.mark.parametrize("change", ["missing", "changed"])
def test_missing_or_changed_declared_original_blocks_even_when_primary_B_exists(
    source, tmp_path, monkeypatch, change
):
    primary, _ = ask(source, monkeypatch)
    old = primary.with_name("original.pdf")
    primary.rename(old)
    primary.write_bytes(pdf_bytes("Primary B"))
    if change == "missing":
        old.unlink()
    else:
        old.write_bytes(pdf_bytes("Wrong old bytes"))
    before = source.read_bytes()
    with pytest.raises(ValueError, match="source|original|PDF"):
        prepare(source, tmp_path, primary)
    assert source.read_bytes() == before
    assert not (tmp_path / "candidate").exists() and not (tmp_path / "backup.zip").exists()


@pytest.mark.parametrize("change", ["unknown", "bool_id", "bad_history", "desired", "duplicate"])
def test_closed_nested_receipts_reject_malformed_inputs(source, monkeypatch, change):
    _, _job = ask(source, monkeypatch)
    with closing(generation._connect(source)) as conn:
        record = dict(conn.execute("SELECT * FROM research_chat_requests").fetchone())
    data = json.loads(record["context_json"])
    if change == "unknown":
        data["parent"]["row"]["unexpected"] = 1
    elif change == "bool_id":
        data["parent"]["row"]["_rowid"] = True
    elif change == "bad_history":
        row = json.loads(record["question_json"])
        row["message_id"] = None
        row["body"] = {"not": "text"}
        data["history"] = [row]
    elif change == "desired":
        data["desired"] = {"path": "/untrusted.pdf"}
    record["context_json"] = json.dumps(data)
    if change == "duplicate":
        record["context_json"] = record["context_json"].replace(
            '"version": 1', '"version": 1, "version": 1'
        )
    with pytest.raises(ValueError):
        enrollment_history.wrap("research_chat_requests", record)


def test_explicit_dangling_reply_preserved_and_legacy_turn_never_paired(
    source, tmp_path, monkeypatch
):
    primary, _ = ask(source, monkeypatch)
    missing = str(uuid4())
    with closing(generation._connect(source)) as conn, conn:
        conn.execute(
            "UPDATE research_chat_links SET reply_to=? WHERE reply_to IS NOT NULL", (missing,)
        )
        conn.execute(
            "INSERT INTO chat(paper_id,role,body,created_at) VALUES('paper','user','Legacy',?)",
            ("2026-10-30T00:00:00+00:00",),
        )
    result = prepare(source, tmp_path, primary)
    assert result["unresolved_chat_replies"] == result["legacy_unpaired_chat_turns"] == 1
    with closing(generation._connect(result["database"])) as conn:
        turns = chat.history(conn, "paper")
        assert turns[1]["reply_to"] == missing
        assert all(turns[2][key] is None for key in history.LINK)


@pytest.mark.parametrize("change", ["exchange", "role", "paper"])
def test_present_reply_requires_exact_user_exchange_and_paper(source, monkeypatch, change):
    primary, _ = ask(source, monkeypatch)
    with closing(generation._connect(source)) as conn, conn:
        if change == "exchange":
            conn.execute(
                "UPDATE research_chat_links SET exchange_id=? WHERE local_id=1", (str(uuid4()),)
            )
        elif change == "role":
            conn.execute("UPDATE chat SET role='assistant' WHERE id=1")
        else:
            conn.execute("INSERT INTO papers(id,title,title_key,venue,year,source) "
                         "VALUES('other','Other','other','Fixture',2026,'fixture')")
            conn.execute("UPDATE chat SET paper_id='other' WHERE id=1")
    with pytest.raises(ValueError):
        EnrollmentService(source).plan(pdfs={"paper": primary})


@pytest.mark.parametrize("change", ["duplicate", "unknown", "oversized", "partial_file"])
def test_owned_sidecars_reject_invalid_bounded_records(source, monkeypatch, change):
    primary, job = ask(source, monkeypatch, complete=False)
    chat.retain_failed_answer(job.request, "Private completed candidate")
    location = chat._retained_path(job.request)
    if change == "duplicate":
        text = location.read_text(encoding="utf-8")
        location.write_text('{"status":"candidate",' + text[1:], encoding="utf-8")
    elif change == "unknown":
        record = json.loads(location.read_text(encoding="utf-8"))
        record["unexpected"] = 1
        location.write_text(json.dumps(record), encoding="utf-8")
    elif change == "oversized":
        location.write_bytes(b" " * (chat.MAX_BYTES + 1))
    else:
        location.with_suffix(".part").write_text("unfinished", encoding="utf-8")
    with pytest.raises(ValueError):
        EnrollmentService(source).plan(pdfs={"paper": primary})


def test_live_anchor_without_request_publishes_its_exact_source(source, tmp_path):
    primary = pdf(source)
    sha = hashlib.sha256(primary.read_bytes()).hexdigest()
    anchor = {"p0": 0, "o0": 0, "p1": 0, "o1": 2, "document_hash": sha}
    with closing(generation._connect(source)) as conn, conn:
        conn.execute(
            "INSERT INTO chat(paper_id,role,body,created_at,anchor) VALUES(?,?,?,?,?)",
            (
                "paper",
                "user",
                "Legacy anchored question",
                "2026-10-30T00:00:00+00:00",
                json.dumps(anchor),
            ),
        )
    result = prepare(source, tmp_path, primary)
    assert result["original_source_count"] == 1 and result["live_chat_links"] == 0
    with closing(sqlite3.connect(result["database"])) as conn:
        payloads = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT envelope FROM paperfact_sync_operations WHERE server_revision IS NULL"
            )
        ]
        assert any(
            row["entity_type"] == "research_file" and row["payload"]["slot"] == sha
            for row in payloads
        )


def test_link_install_caller_rollback_leaves_no_semantic_identity(source, monkeypatch):
    _, _ = ask(source, monkeypatch)
    with closing(generation._connect(source)) as conn:
        links = history.live_inventory(conn, Ticket())["links"]
        conn.execute("DELETE FROM research_chat_links")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        history.install_live_in(conn, links)
        history.install_live_in(conn, links)
        assert conn.execute("SELECT COUNT(*) FROM research_chat_links").fetchone()[0] == 2
        conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM research_chat_links").fetchone()[0] == 0


@pytest.mark.parametrize("mode", ["cancel", "source_change", "rollback"])
def test_failure_late_cancel_or_source_change_publishes_nothing_then_retry(
    source, tmp_path, monkeypatch, mode
):
    primary, _ = ask(source, monkeypatch)
    ticket = Ticket()
    original = enrollment_history.retain_in
    if mode == "rollback":

        def fail(conn, records):
            original(conn, records)
            raise RuntimeError("Injected after archive insertion")

        monkeypatch.setattr(enrollment_history, "retain_in", fail)

    def progress(message):
        if message.startswith("Verified candidate"):
            if mode == "cancel":
                ticket.cancel()
            elif mode == "source_change":
                with closing(sqlite3.connect(source)) as conn, conn:
                    conn.execute("UPDATE papers SET abstract='Late change'")

    with pytest.raises((Cancelled, SnapshotChanged, RuntimeError)):
        prepare(source, tmp_path, primary, ticket=ticket, progress=progress)
    assert not (tmp_path / "candidate").exists() and not (tmp_path / "backup.zip").exists()
    monkeypatch.setattr(enrollment_history, "retain_in", original)
    result = prepare(source, tmp_path, primary)
    with closing(generation._connect(result["database"])) as conn:
        assert len(chat.history(conn, "paper")) == 2
        assert len(history.live_inventory(conn, Ticket())["links"]) == 2
