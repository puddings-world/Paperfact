"""Two real desktop QA producers and an isolated authenticated HTTP authority."""

import json
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from uuid import uuid4

core_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(core_root / "src"))

from paper_daily import bundle, llm, research_chat, store  # noqa: E402
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
