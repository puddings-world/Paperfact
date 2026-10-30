"""Two real desktop QA producers and an isolated authenticated HTTP authority."""

import json
import sys
import tempfile
import threading
import zipfile
from contextlib import closing, nullcontext
from pathlib import Path
from uuid import uuid4

core_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(core_root / "src"))

from paper_daily import bundle, llm, research_chat, store  # noqa: E402
from paper_daily.research_generation import _connect as generation_connection  # noqa: E402
from paper_daily.sync_capture import install  # noqa: E402
from paper_daily.sync_client import SyncClient  # noqa: E402
from paper_daily.sync_http import make_server  # noqa: E402
from paper_daily.sync_journal import Journal  # noqa: E402
from paper_daily.sync_research import prepare, research_order_writer, research_writer  # noqa: E402
from paper_daily.sync_service import ReferenceService  # noqa: E402


def no_ai(*args, **kwargs):
    raise AssertionError("Reading or replaying QA must never invoke AI")


def client(path, device):
    path.parent.mkdir()
    store.DB_PATH = path
    store.ensure_dirs = lambda: None
    store.init_db()
    prepare(path, workspace_id="qa-workspace", device_id=device)
    result = SyncClient(
        Journal(path, workspace_id="qa-workspace", device_id=device),
        research_writer,
        order_writer=research_order_writer,
    )
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="qa-workspace", device_id=device)
    return result


def produce(client, body):
    store.DB_PATH = client.journal.path
    with store.connect() as conn:
        paper = conn.execute("SELECT id FROM papers").fetchone()[0]
        request = research_chat.begin_chat(
            conn,
            paper_id=paper,
            question="Same question",
            request_id=str(uuid4()),
            legacy_root=client.journal.path.parent / "pdf",
        )
    request, prompt = research_chat.prepare_chat(request)
    assert "Same question" in prompt
    assert research_chat.publish_answer(request, body).status == "accepted"
    assert research_chat.publish_answer(request, body).status == "accepted"
    return request



def produce_questions(desktop):
    import pymupdf

    from paper_daily import research_generation as generation
    from paper_daily.ai_types import Completion
    from paper_daily.research_question_jobs import QuestionJob

    database = desktop.journal.path
    source_root = database.parent / "pdf"
    source_root.mkdir(exist_ok=True)
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 50), "Original experiment with independent samples")
        document.save(source_root / "local-paper.pdf")
    for table in ("dives", "close_readings"):
        with closing(generation._connect(database)) as conn:
            context = generation.begin_generation(
                conn, table=table, owner_id="local-paper", input_reader="target"
            )
        assert generation.publish_generation(context, row={
            "paper_id": "local-paper", "body": "The study assumes independent samples.",
            "written_at": store.now(), "spec": "fixture",
        }).status == "accepted"
    llm.capture_connections = lambda: {}
    llm.connection_scope = lambda *args: nullcontext()
    calls = []

    def complete(*args, **kwargs):
        calls.append(1)
        return Completion(json.dumps({"questions": [{
            "question": "What happens when observations are correlated?",
            "why": "The conclusion relies on sample independence.",
            "evidence": "Original experiment with independent samples",
        }]}))

    llm.complete_result = complete
    job = QuestionJob.capture(database, "local-paper", legacy_root=source_root)
    assert job.run().status == "accepted"
    assert job.run().status == "accepted" and len(calls) == 1
    llm.complete_result = no_ai
    return {"data": {key: json.loads(value) if key == "body_json" else value
                     for key, value in job.result.items() if key != "paper_id"},
            "source_document_hash": job.context.data["document"]["sha256"]}


def main():
    llm.complete = no_ai
    llm.complete_result = no_ai
    with tempfile.TemporaryDirectory(prefix="paperfact-mobile-qa-") as folder:
        root = Path(folder)
        service = ReferenceService(root / "service.sqlite")
        desktop = client(root / "a" / "papers.db", "a")
        with store.connect() as conn:
            conn.execute(
                "INSERT INTO lists VALUES('list','Reading','',?)", ("2026-10-27T00:00:00Z",)
            )
            store.upsert_papers(
                conn,
                [
                    {
                        "id": "local-paper",
                        "title": "QA fixture",
                        "year": 2026,
                        "venue": "Fixture",
                        "source": "fixture",
                    }
                ],
            )
            conn.execute(
                "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES(?,?,0,?)",
                ("list", "local-paper", "2026-10-27T00:00:00Z"),
            )
        token_a = service.enroll("qa-workspace", "a")
        desktop.sync_once(service, token_a)
        peer = client(root / "b" / "papers.db", "b")
        token_b = service.enroll("qa-workspace", "b")
        peer.receive(service.pull(token_b))
        produce(desktop, "First answer")
        produce(peer, "Second answer")
        a_ops, b_ops = desktop.journal.pending(), peer.journal.pending()
        assert len(a_ops) == len(b_ops) == 2
        for token, op in [
            (token_a, a_ops[0]),
            (token_b, b_ops[0]),
            (token_b, b_ops[1]),
            (token_a, a_ops[1]),
        ]:
            assert service.push(token, op)["outcome"] == "accepted"
        desktop.sync_once(service, token_a)
        peer.sync_once(service, token_b)
        questions = produce_questions(desktop)
        desktop.sync_once(service, token_a)
        peer.sync_once(service, token_b)
        with closing(generation_connection(peer.journal.path)) as conn:
            row = conn.execute("SELECT body_json FROM paper_research_questions").fetchone()
            assert json.loads(row[0]) == questions["data"]["body_json"]
        store.DB_PATH = desktop.journal.path
        bundle.DATA_DIR = desktop.journal.path.parent
        bundle.PDF_DIR = bundle.DATA_DIR / "pdf"
        package = root / "research.zip"
        bundle.export("list", package, with_pdfs=False)
        with zipfile.ZipFile(package) as archive:
            shared = json.loads(archive.read("tables.json"))["chat"]
        assert len(shared) == 4
        token = service.enroll("qa-workspace", "phone")
        server = make_server(service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(
            json.dumps(
                {
                    "url": f"http://127.0.0.1:{server.server_port}",
                    "token": token,
                    "shared": shared,
                    "questions": questions,
                    "events": len(service.pull(token)),
                }
            ),
            flush=True,
        )
        try:
            sys.stdin.readline()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
