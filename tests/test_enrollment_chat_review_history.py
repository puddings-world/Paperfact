"""Actual reviewed answers survive first enrollment, backup and peer transfer."""

import hashlib
import json
import zipfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_enrollment_chat_history import ask
from test_enrollment_history_peer import peer
from test_sync_source_files import pdf as pdf_bytes
from test_workspace_enrollment import source as source

from paper_daily import enrollment_history, llm, sync_recovery
from paper_daily import research_chat as chat
from paper_daily import research_generation as generation
from paper_daily.research_chat_review import ChatReview
from paper_daily.workspace_enrollment import EnrollmentService

PROTOCOL = "research_chat_review_receipts"


@pytest.fixture
def reviewed(source, monkeypatch, request):
    history_file, history_ids = None, []
    if getattr(request, "param", None) == "history":
        folder = source.parent / "pdf"
        folder.mkdir()
        earlier_file = folder / "paper.pdf"
        earlier_file.write_bytes(pdf_bytes("Earlier C appears only in private review history"))
        with closing(generation._connect(source)) as conn:
            earlier = chat.begin_chat(
                conn,
                paper_id="paper",
                question="Earlier source C?",
                request_id=str(uuid4()),
                legacy_root=folder,
            )
        earlier, _prompt = chat.prepare_chat(earlier)
        assert chat.publish_answer(earlier, "Earlier C observation").status == "accepted"
        with closing(generation._connect(source)) as conn:
            history_ids = [row["id"] for row in chat.history(conn, "paper")]
        history_file = folder / "history-only-c.pdf"
        earlier_file.rename(history_file)
    primary, job = ask(source, monkeypatch, complete=False)
    with closing(generation._connect(source)) as conn, conn:
        conn.execute(
            "UPDATE papers SET title='Reconsidered evidence',title_key='reconsideredevidence' "
            "WHERE id='paper'"
        )
    assert chat.publish_answer(job.request, "Retained original answer").status == "candidate"
    review = ChatReview(source)
    record = review.records()[0]
    preview = review.preview(record)
    request = str(uuid4())
    result = review.apply(preview, body="A human-reviewed interpretation", request_id=request)
    assert (
        review.apply(preview, body="A human-reviewed interpretation", request_id=request) == result
    )
    review.close()
    if history_ids:
        # A self-contained real review receipt remains after ordinary old-turn
        # and job-history cleanup. C must be found from the receipt alone.
        with closing(generation._connect(source)) as conn, conn:
            for identity in history_ids:
                conn.execute("DELETE FROM research_chat_links WHERE local_id=?", (identity,))
                conn.execute("DELETE FROM chat WHERE id=?", (identity,))
            conn.execute("DELETE FROM research_chat_requests")
    with closing(generation._connect(source)) as conn:
        receipt = dict(conn.execute("SELECT * FROM research_chat_review_receipts").fetchone())
        turns = chat.history(conn, "paper")
    assert len(turns) == 2 and turns[-1]["body"] == "A human-reviewed interpretation"

    def deny(*_args, **_kwargs):
        pytest.fail("Enrollment, transfer and recovery must not call AI")

    monkeypatch.setattr(llm, "complete", deny)
    monkeypatch.setattr(llm, "complete_result", deny)
    return dict(
        database=source,
        primary=primary,
        receipt=receipt,
        turns=turns,
        review_request=request,
        history_file=history_file,
    )


def prepare(value, tmp_path):
    return EnrollmentService(value["database"]).prepare(
        tmp_path / "candidate",
        backup_output=tmp_path / "backup.zip",
        request_id=str(uuid4()),
        pdfs={"paper": value["primary"]},
    )


def test_reviewed_answer_enrollment_backup_and_peer_preserve_sources_without_old_job_authority(
    reviewed,
    tmp_path,
):
    value = reviewed
    primary = value["primary"]
    original = primary.with_name("original-a.pdf")
    primary.rename(original)
    original_bytes = original.read_bytes()
    original_hash = hashlib.sha256(original_bytes).hexdigest()
    primary.write_bytes(pdf_bytes("Current primary B after the reviewed answer"))
    before = value["database"].read_bytes()
    plan = EnrollmentService(value["database"]).plan(pdfs={"paper": primary})
    assert plan["supported"], plan["blockers"]
    assert plan["archived_history_by_protocol"][PROTOCOL] == 1
    result = prepare(value, tmp_path)
    database = Path(result["database"])
    assert not result["uploaded"] and not result["adopted"]
    assert value["database"].read_bytes() == before and original.read_bytes() == original_bytes
    with closing(generation._connect(database)) as conn:
        records = enrollment_history.archived(conn)
        review_rows = [
            enrollment_history.validate(row)[0] for row in records if row["protocol"] == PROTOCOL
        ]
        assert review_rows == [value["receipt"]]
        assert chat.history(conn, "paper") == value["turns"]
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name IN "
            "('research_chat_requests','research_chat_review_receipts')"
        ).fetchone()
        envelopes = "\n".join(
            row[0] for row in conn.execute("SELECT envelope FROM paperfact_sync_operations")
        )
        assert PROTOCOL not in envelopes and value["review_request"] not in envelopes
    assert ChatReview(database).records() == []
    with zipfile.ZipFile(result["backup"]) as archive:
        assert value["review_request"].encode() in archive.read(
            "tables/research_history_archive.jsonl"
        )
        assert archive.read("objects/" + original_hash) == original_bytes
    restored = tmp_path / "detached"
    sync_recovery.restore_detached(result["backup"], restored)
    with closing(generation._connect(restored / "papers.db")) as conn:
        # Detached restore keeps protocol records in recovery_records, not in
        # active protocol tables. Verify the exact same archived receipt there.
        rows = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_history_archive'"
            )
        ]
        assert value["receipt"] in [
            enrollment_history.validate(row)[0] for row in rows if row["protocol"] == PROTOCOL
        ]
    a, b, service, ta, tb, portable, local, _artifacts = peer(result, tmp_path)
    with b.journal.transaction() as conn:
        turns = chat.history(conn, local)
        assert [
            {
                k: row[k]
                for k in ("role", "body", "message_id", "exchange_id", "reply_to", "source_hash")
            }
            for row in turns
        ] == [
            {
                k: row[k]
                for k in ("role", "body", "message_id", "exchange_id", "reply_to", "source_hash")
            }
            for row in value["turns"]
        ]
        from paper_daily.sync_source_files import resolved

        located = resolved(conn, portable, original_hash)
        assert located is not None and located.read_bytes() == original_bytes
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (PROTOCOL,)).fetchone()
    # A real ordinary peer note write must still enter the shared operation path.
    with closing(generation._connect(b.journal.path)) as conn, conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,kind,created_at) VALUES(?,?,'note',?)",
            (
                local,
                "Peer continuation after reviewed-answer enrollment",
                "2026-11-01T00:00:00+00:00",
            ),
        )
    b.sync_once(service, tb, limit=1000)
    a.sync_once(service, ta, limit=1000)
    with closing(generation._connect(database)) as conn:
        assert conn.execute(
            "SELECT 1 FROM notes WHERE body=?",
            ("Peer continuation after reviewed-answer enrollment",),
        ).fetchone()
    assert value["database"].read_bytes() == before


@pytest.mark.parametrize("reviewed", ["history"], indirect=True)
@pytest.mark.parametrize("change", ["present", "missing", "changed"])
def test_original_used_only_by_private_review_history_is_preserved_or_blocks_copy(
    reviewed,
    tmp_path,
    change,
):
    value = reviewed
    original = value["history_file"]
    original_bytes = original.read_bytes()
    original_hash = hashlib.sha256(original_bytes).hexdigest()
    before = value["database"].read_bytes()
    wrapped = enrollment_history.wrap(PROTOCOL, value["receipt"])
    assert original_hash in enrollment_history.validate(wrapped)[1]
    with closing(generation._connect(value["database"])) as conn:
        assert conn.execute("SELECT count(*) FROM research_chat_requests").fetchone()[0] == 0
        assert all(turn["source_hash"] != original_hash for turn in chat.history(conn, "paper"))
    if change == "missing":
        original.unlink()
    elif change == "changed":
        original.write_bytes(pdf_bytes("Unrelated replacement is not original C"))
    if change != "present":
        with pytest.raises(ValueError, match="source|original|PDF"):
            prepare(value, tmp_path)
        assert not (tmp_path / "candidate").exists() and not (tmp_path / "backup.zip").exists()
    else:
        result = prepare(value, tmp_path)
        with zipfile.ZipFile(result["backup"]) as archive:
            assert archive.read("objects/" + original_hash) == original_bytes
        with closing(generation._connect(result["database"])) as conn:
            records = enrollment_history.archived(conn)
            assert [
                enrollment_history.validate(row)[0]
                for row in records
                if row["protocol"] == PROTOCOL
            ] == [value["receipt"]]
            # C is preserved privately, not automatically published as live research.
            operations = [
                json.loads(row[0])
                for row in conn.execute("SELECT envelope FROM paperfact_sync_operations")
            ]
            assert all(
                original_hash not in json.dumps(op["payload"])
                for op in operations
                if op["entity_type"] == "research_file"
            )
    assert value["database"].read_bytes() == before
