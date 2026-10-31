"""Actual initial enrollment -> empty annotation tombstones -> authenticated HTTP."""

import json
import sys
import tempfile
import threading
from contextlib import nullcontext
from pathlib import Path
from uuid import uuid4

core_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(core_root / "src"))

from paper_daily import annotation_content, llm, store  # noqa: E402
from paper_daily.ai_types import Completion, Settings  # noqa: E402
from paper_daily.claim_jobs import ClaimJob  # noqa: E402
from paper_daily.sync_blobs import BlobStore  # noqa: E402
from paper_daily.sync_client import SyncClient  # noqa: E402
from paper_daily.sync_http import make_server  # noqa: E402
from paper_daily.sync_journal import Journal  # noqa: E402
from paper_daily.sync_research import research_writer  # noqa: E402
from paper_daily.sync_service import ReferenceService  # noqa: E402
from paper_daily.sync_transfers import DocumentTransfers  # noqa: E402
from paper_daily.workspace_enrollment import EnrollmentService  # noqa: E402


def no_ai(*_args, **_kwargs):
    raise AssertionError("Enrollment, tombstone reads and sync must not call AI")


def main():
    import pymupdf

    with tempfile.TemporaryDirectory(prefix="paperfact-mobile-initial-deletion-") as folder:
        root = Path(folder)
        source = root / "source"
        source.mkdir()
        store.DB_PATH = source / "papers.db"
        store.init_db()
        with store.connect() as conn:
            store.upsert_papers(
                conn,
                [
                    {
                        "id": "paper",
                        "title": "Initial deletion fixture",
                        "venue": "Fixture",
                        "year": 2026,
                        "source": "fixture",
                    }
                ],
            )
            for table in ("dives", "close_readings"):
                conn.execute(
                    f"INSERT INTO {table}(paper_id,body,spec,written_at) VALUES(?,?,?,?)",
                    ("paper", "Original interpretation", "fixture", "2026-10-30T00:00:00+00:00"),
                )
        pdf_root = source / "pdf"
        pdf_root.mkdir()
        quote = "The study compared independent observations with a matched control."
        original = pdf_root / "paper.pdf"
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((40, 50), quote)
            pdf.save(original)
        calls = []
        llm.capture_connections = lambda: {}
        llm.connection_scope = lambda *_a, **_k: nullcontext()
        llm.settings = lambda **_k: Settings("fixture", model="fixture")

        def complete(*_args, **kwargs):
            assert kwargs["task"] == "claims"
            calls.append(1)
            return Completion(
                json.dumps(
                    {
                        "claims": [
                            {
                                "text": "A controlled comparison was reported.",
                                "judgment": {
                                    "status": "unresolved",
                                    "reason": "Independent appraisal required.",
                                },
                                "passages": [{"quote": quote, "page": 1, "anchor": None}],
                            }
                        ]
                    }
                ),
                model="fixture",
            )

        llm.complete_result = complete
        assert (
            ClaimJob.capture(store.DB_PATH, "paper", legacy_root=pdf_root).run().status
            == "accepted"
        )
        with store.connect() as conn:
            conn.execute("DELETE FROM paper_claim_sets WHERE paper_id='paper'")
            conn.executemany(
                "INSERT OR IGNORE INTO paper_annotation_known VALUES(?,?)",
                [(feature, "paper") for feature in annotation_content.FEATURES],
            )
        llm.complete = llm.complete_result = no_ai
        result = EnrollmentService(store.DB_PATH).prepare(
            root / "candidate",
            backup_output=root / "backup.zip",
            request_id=str(uuid4()),
            pdfs={"paper": original},
        )
        assert result["known_annotation_deletions"] == 4 and result["archived_history_records"] >= 2
        workspace, device = result["workspace_id"], result["device_id"]
        desktop = SyncClient(
            Journal(result["database"], workspace_id=workspace, device_id=device), research_writer
        )
        authority = ReferenceService(root / "service.sqlite", blob_root=root / "authority-blobs")
        token_desktop = authority.enroll(workspace, device)
        transfer = DocumentTransfers(
            desktop,
            BlobStore(Path(result["database"]).parent / "blobs"),
            authority,
            origin="https://fixture.invalid",
            token=token_desktop,
        )

        def ready(op):
            if op["entity_type"] == "paper_document":
                for _ in range(40):
                    if transfer.upload(op)["state"] == "uploaded":
                        break
                else:
                    raise AssertionError("Primary upload did not finish")
            return True

        desktop.sync_once(authority, token_desktop, limit=1000, prepare_push=ready)
        token = authority.enroll(workspace, "phone")
        events = authority.pull(token)
        tombstones = [
            event["operation"]
            for event in events
            if event["operation"]["entity_type"] == "research_content"
            and event["operation"]["action"] == "delete"
        ]
        assert len(tombstones) == 4 and all(not op["payload"] for op in tombstones)
        server = make_server(authority)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(
            json.dumps(
                {
                    "url": f"http://127.0.0.1:{server.server_port}",
                    "token": token,
                    "workspace": workspace,
                    "device": "phone",
                    "events": len(events),
                    "tombstones": [op["entity_id"] for op in tombstones],
                }
            ),
            flush=True,
        )
        try:
            sys.stdin.readline()
            assert len(calls) == 1
        finally:
            transfer.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
