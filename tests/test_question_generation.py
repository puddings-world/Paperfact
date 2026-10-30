"""Actual question output uses captured PDF, analyses and route before publication."""

import json
import sqlite3
from contextlib import closing, contextmanager

import pytest
from test_research_generation import pdf, rows
from test_research_generation import workspace as base_workspace

from paper_daily import llm, store
from paper_daily import research_generation as generation
from paper_daily.ai_types import Completion
from paper_daily.research_question_jobs import QuestionJob

workspace = base_workspace
ITEM = {
    "question": "Which assumptions underlie the original experiment?",
    "why": "The scope of the result depends on those assumptions.",
    "evidence": "Original experiment",
}


@pytest.fixture
def ready(workspace, monkeypatch):
    database, client, document = workspace
    for table in ("dives", "close_readings"):
        with closing(generation._connect(database)) as conn:
            context = generation.begin_generation(
                conn, table=table, owner_id="paper", input_reader="target"
            )
        result = generation.publish_generation(
            context,
            row={
                "paper_id": "paper",
                "body": table + " original analysis",
                "written_at": store.now(),
                "spec": "fixture",
            },
        )
        assert result.status == "accepted"
    routes, requests = [], []
    selected = {"account": "original-account", "model": "original-model"}
    monkeypatch.setattr(llm, "capture_connections", lambda: dict(selected))

    @contextmanager
    def scope(value):
        routes.append(value)
        yield

    def complete(prompt, **kwargs):
        requests.append((json.loads(prompt), kwargs))
        return Completion(json.dumps({"questions": [ITEM]}))

    monkeypatch.setattr(llm, "connection_scope", scope)
    monkeypatch.setattr(llm, "complete_result", complete)
    return database, client, document, selected, routes, requests


def capture(ready):
    database, _, document, *_ = ready
    return QuestionJob.capture(database, "paper", legacy_root=document.path.parent)


def test_generated_questions_persist_exact_source_and_retry_without_ai(ready):
    database, client, document, selected, routes, requests = ready
    job = capture(ready)
    selected.update(account="another-account", model="another-model")
    result = job.run()
    assert result.status == "accepted"
    assert job.run() == result and len(requests) == 1
    assert routes == [{"account": "original-account", "model": "original-model"}]
    assert requests[0][0]["explanation"] == "dives original analysis"
    row = rows(database, "SELECT * FROM paper_research_questions")[0]
    assert json.loads(row["body_json"])["items"] == [{**ITEM, "page": 1}]
    record = rows(
        database,
        "SELECT * FROM research_generation_requests WHERE "
        "request_id='" + job.context.request_id + "'",
    )[0]
    assert generation.validate_request_record(record) == record
    assert json.loads(record["context_json"])["document"]["sha256"] == document.sha256
    if client:
        operations = client.journal.pending()
        questions = [
            op for op in operations if op.get("payload", {}).get("feature") == "research_questions"
        ]
        assert len(questions) == 1
        assert questions[0]["payload"]["source_document_hash"] == document.sha256


@pytest.mark.parametrize("change", ["analysis", "pdf", "target"])
def test_changed_inputs_or_target_during_model_call_retain_generated_output(
    ready, monkeypatch, change
):
    database, _, document, _, _, requests = ready
    job = capture(ready)
    complete = llm.complete_result

    def delayed(prompt, **kwargs):
        result = complete(prompt, **kwargs)
        if change == "pdf":
            document.path.unlink()
            pdf(document.path, "Replacement experiment")
        else:
            with closing(generation._connect(database)) as conn:
                table = "dives" if change == "analysis" else "paper_research_questions"
                manual = generation.begin_generation(
                    conn, table=table, owner_id="paper", input_reader="target"
                )
            row = (
                {
                    "paper_id": "paper",
                    "body": "New analysis",
                    "spec": None,
                    "written_at": store.now(),
                }
                if change == "analysis"
                else {
                    "paper_id": "paper",
                    "source_hash": "b" * 64,
                    "document_hash": None,
                    "written_at": store.now(),
                    "body_json": json.dumps(
                        {"items": [{**ITEM, "page": 1, "question": "Peer question?"}]}
                    ),
                }
            )
            assert generation.publish_generation(manual, row=row).status == "accepted"
        return result

    monkeypatch.setattr(llm, "complete_result", delayed)
    assert job.run().status == "candidate"
    assert job.run().status == "candidate" and len(requests) == 1
    current = rows(database, "SELECT * FROM paper_research_questions")
    assert len(current) == (1 if change == "target" else 0)
    if current:
        assert json.loads(current[0]["body_json"])["items"][0]["question"] == "Peer question?"


def test_storage_failure_retains_completed_questions_for_restart_without_ai(ready):
    database, _, _, _, _, requests = ready
    job = capture(ready)
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            "CREATE TRIGGER fail_questions BEFORE INSERT ON paper_research_questions "
            "BEGIN SELECT RAISE(ABORT,'fixture failure'); END"
        )
    assert job.run().status == "candidate"
    records = generation.list_recovery_requests(database)
    assert len(records) == 1
    assert json.loads(records[0]["row_json"])["body_json"] == job.result["body_json"]
    restored = generation.GenerationContext(records[0]["context_json"])
    assert generation.retry_publication(restored).status == "candidate"
    assert len(requests) == 1 and rows(database, "SELECT * FROM paper_research_questions") == []


def test_duplicate_question_generation_does_not_call_model_again(ready, monkeypatch):
    first = capture(ready)
    second = capture(ready)
    complete = llm.complete_result

    def nested(prompt, **kwargs):
        with pytest.raises(ValueError, match="already running"):
            second.run()
        return complete(prompt, **kwargs)

    monkeypatch.setattr(llm, "complete_result", nested)
    assert first.run().status == "accepted"
    assert len(ready[-1]) == 1


def test_failed_model_preserves_previously_accepted_questions(ready, monkeypatch):
    database = ready[0]
    assert capture(ready).run().status == "accepted"
    before = rows(database, "SELECT * FROM paper_research_questions")
    monkeypatch.setattr(llm, "complete_result", lambda *a, **kw: Completion(None, "Unavailable"))
    with pytest.raises(ValueError, match="Unavailable"):
        capture(ready).run()
    assert rows(database, "SELECT * FROM paper_research_questions") == before


def test_initial_changed_analysis_rejects_before_ai(ready):
    database = ready[0]
    job = capture(ready)
    with closing(generation._connect(database)) as conn:
        manual = generation.begin_generation(
            conn, table="dives", owner_id="paper", input_reader="target"
        )
    generation.publish_generation(
        manual,
        row={"paper_id": "paper", "body": "Changed", "spec": None, "written_at": store.now()},
    )
    with pytest.raises(ValueError, match="inputs changed"):
        job.run()
    assert ready[-1] == []


def test_switching_global_workspace_does_not_redirect_question_output(ready, monkeypatch, tmp_path):
    database = ready[0]
    job = capture(ready)
    complete = llm.complete_result
    other = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(other)) as conn:
        conn.executescript(store.SCHEMA)

    def delayed(prompt, **kwargs):
        monkeypatch.setattr(store, "DB_PATH", other)
        return complete(prompt, **kwargs)

    monkeypatch.setattr(llm, "complete_result", delayed)
    assert job.run().status == "accepted"
    assert len(rows(database, "SELECT * FROM paper_research_questions")) == 1
    assert rows(other, "SELECT * FROM paper_research_questions") == []


def test_recreated_paper_cannot_receive_old_question_output(ready, monkeypatch):
    database = ready[0]
    job = capture(ready)
    complete = llm.complete_result

    def delayed(prompt, **kwargs):
        with closing(generation._connect(database)) as conn, conn:
            old = dict(conn.execute("SELECT * FROM papers WHERE id='paper'").fetchone())
            conn.execute("DELETE FROM papers WHERE id='paper'")
            columns = list(old)
            conn.execute(
                "INSERT INTO papers("
                + ",".join(columns)
                + ") VALUES("
                + ",".join("?" for _ in columns)
                + ")",
                tuple(old.values()),
            )
        return complete(prompt, **kwargs)

    monkeypatch.setattr(llm, "complete_result", delayed)
    assert job.run().status == "candidate"
    assert rows(database, "SELECT * FROM paper_research_questions") == []
    assert len(ready[-1]) == 1


def test_replaced_database_retains_questions_outside_replacement(ready, monkeypatch):
    database = ready[0]
    job = capture(ready)
    complete = llm.complete_result

    def delayed(prompt, **kwargs):
        database.rename(database.with_suffix(".old"))
        with closing(sqlite3.connect(database)) as conn:
            conn.executescript(store.SCHEMA)
        if ready[1] is not None:
            from paper_daily.sync_capture import install
            from paper_daily.sync_client import SyncClient
            from paper_daily.sync_journal import Journal
            from paper_daily.sync_research import prepare, research_writer

            prepare(database, workspace_id="workspace", device_id="device")
            SyncClient(
                Journal(database, workspace_id="workspace", device_id="device"), research_writer
            )
            with closing(generation._connect(database)) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                install(conn, workspace_id="workspace", device_id="device")
        return complete(prompt, **kwargs)

    monkeypatch.setattr(llm, "complete_result", delayed)
    assert job.run().status == "candidate"
    assert rows(database, "SELECT * FROM paper_research_questions") == []
    records = generation.list_recovery_requests(database)
    assert len(records) == 1
    assert json.loads(records[0]["row_json"])["body_json"] == job.result["body_json"]
    assert len(ready[-1]) == 1


def test_rebound_workspace_cannot_discover_old_bound_question_sidecar(ready, monkeypatch):
    database = ready[0]
    job = capture(ready)
    complete = llm.complete_result

    def delayed(prompt, **kwargs):
        database.rename(database.with_suffix(".prior"))
        with closing(sqlite3.connect(database)) as conn:
            conn.executescript(store.SCHEMA)
        return complete(prompt, **kwargs)

    monkeypatch.setattr(llm, "complete_result", delayed)
    assert job.run().status == "candidate"
    retained = json.loads(generation._recovery_path(job.context).read_text(encoding="utf-8"))
    assert generation.validate_request_record(retained) == retained
    assert json.loads(retained["row_json"])["body_json"] == job.result["body_json"]
    if ready[1] is not None:
        assert generation.list_recovery_requests(database) == []
    assert rows(database, "SELECT * FROM paper_research_questions") == []


def test_list_package_preserves_question_pdf_identity_and_original_bytes(
    ready, monkeypatch, tmp_path
):
    import hashlib
    import zipfile

    from paper_daily import bundle

    database, _, document, *_ = ready
    assert capture(ready).run().status == "accepted"
    with closing(generation._connect(database)) as conn, conn:
        conn.execute("INSERT INTO lists VALUES('reading','Research','',?)", (store.now(),))
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
            "VALUES('reading','paper',0,?)",
            (store.now(),),
        )
    monkeypatch.setattr(bundle, "DATA_DIR", database.parent)
    monkeypatch.setattr(bundle, "PDF_DIR", document.path.parent)
    package = tmp_path / "questions.zip"
    bundle.export("reading", package, with_pdfs=True)
    with zipfile.ZipFile(package) as archive:
        tables = json.loads(archive.read("tables.json"))
        assert tables["paper_research_questions"][0]["document_hash"] == document.sha256
        originals = [archive.read(name) for name in archive.namelist() if name.endswith(".pdf")]
        assert any(hashlib.sha256(body).hexdigest() == document.sha256 for body in originals)
    destination = tmp_path / "recipient"
    destination.mkdir()
    monkeypatch.setattr(store, "DB_PATH", destination / "papers.db")
    monkeypatch.setattr(bundle, "DATA_DIR", destination)
    monkeypatch.setattr(bundle, "PDF_DIR", destination / "pdf")
    store.init_db()
    bundle.import_(package, pdfs=True)
    assert (
        rows(store.DB_PATH, "SELECT * FROM paper_research_questions")[0]["document_hash"]
        == document.sha256
    )
    assert any(
        hashlib.sha256(file.read_bytes()).hexdigest() == document.sha256
        for file in (destination / "pdf").glob("*.pdf")
    )


def test_successful_regeneration_replaces_existing_questions_without_marker_collision(ready):
    first = capture(ready)
    assert first.run().status == "accepted"
    second = capture(ready)
    assert second.run().status == "accepted"
    assert first.context.request_id != second.context.request_id
    assert len(ready[-1]) == 2
    assert len(rows(ready[0], "SELECT * FROM paper_research_questions")) == 1
    assert (
        len(
            rows(
                ready[0],
                "SELECT * FROM paper_annotation_known "
                "WHERE feature='research_questions' AND paper_id='paper'",
            )
        )
        == 1
    )
