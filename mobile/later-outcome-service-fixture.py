"""Only synthetic explicit empty queries and exact retained A/current B via loopback."""

import hashlib
import json
import sys
import tempfile
import threading
from pathlib import Path

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
import pymupdf  # noqa:E402

from paper_daily import config, followups, llm, store  # noqa:E402
from paper_daily.sync_blobs import BlobStore  # noqa:E402
from paper_daily.sync_capture import install  # noqa:E402
from paper_daily.sync_client import SyncClient  # noqa:E402
from paper_daily.sync_file_transfers import FileTransfers  # noqa:E402
from paper_daily.sync_http import make_server  # noqa:E402
from paper_daily.sync_journal import Journal  # noqa:E402
from paper_daily.sync_projection import read_manifest  # noqa:E402
from paper_daily.sync_research import prepare, research_writer  # noqa:E402
from paper_daily.sync_service import ReferenceService  # noqa:E402


def pdf(text):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40, 50), text)
        return doc.tobytes()


def forbidden(*a, **kw):
    raise AssertionError("Empty queries/transfer/read attempted AI or network lookup")


def main():
    with tempfile.TemporaryDirectory(prefix="paperfact-empty-http-") as folder:
        base = Path(folder)
        path = base / "research.sqlite"
        originals = base / "pdf"
        originals.mkdir()
        authority = ReferenceService(base / "authority.sqlite", blob_root=base / "authority-blobs")
        sender = authority.enroll("empty-workspace", "desktop")
        phone = authority.enroll("empty-workspace", "phone")
        store.DB_PATH = path
        store.ensure_dirs = lambda: None
        config.PDF_DIR = originals
        store.init_db()
        prepare(path, workspace_id="empty-workspace", device_id="desktop")
        client = SyncClient(
            Journal(path, workspace_id="empty-workspace", device_id="desktop"), research_writer
        )
        transfers = FileTransfers(
            client,
            BlobStore(base / "blobs"),
            authority,
            origin="https://fixture.invalid",
            token=sender,
        )
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            install(conn, workspace_id="empty-workspace", device_id="desktop")
            store.upsert_papers(
                conn,
                [
                    dict(
                        id="available",
                        title="Available A",
                        venue="Fixture",
                        year=2026,
                        source="fixture",
                    ),
                    dict(
                        id="missing",
                        title="Unavailable original",
                        venue="Fixture",
                        year=2026,
                        source="fixture",
                    ),
                ],
            )
        original = pdf("Original A for an accepted empty query")
        (originals / "available.pdf").write_bytes(original)
        original_hash = hashlib.sha256(original).hexdigest()
        llm.complete = llm.complete_result = forbidden
        followups.work_id = lambda _: "W1"
        followups._citing_openalex = lambda _: []
        followups._citing_s2 = lambda _: []
        assert followups.fetch("available", database=path) == 0
        assert followups.fetch("missing", database=path) == 0
        operations = client.journal.pending()
        source = next(
            op
            for op in operations
            if op["entity_type"] == "research_file"
            and op["payload"]["feature"] == "original_source"
        )
        for _ in range(12):
            if transfers.upload(source)["state"] == "uploaded":
                break
        else:
            raise AssertionError("Source upload failed finite steps")
        client.sync_once(authority, sender, prepare_push=transfers.ready_to_push)
        with client.journal.transaction() as conn:
            portable = conn.execute(
                "SELECT sync_id FROM research_paper_identity WHERE local_id='available'"
            ).fetchone()[0]
        current = pdf("Different current original B remains separate from A")
        target = {"sha256": hashlib.sha256(current).hexdigest(), "size": len(current)}
        upload = authority.blob_begin(sender, target)
        authority.blob_append(sender, upload["upload_id"], 0, current)
        authority.blob_commit(sender, upload["upload_id"])
        client.save(
            client.new_graph_operation(
                "paper_document",
                portable,
                dict(paper_id=portable, **target, media_type="application/pdf"),
            )
        )
        client.sync_once(authority, sender, prepare_push=transfers.ready_to_push)
        manifest = read_manifest(path, workspace_id="empty-workspace", schema_version=2)
        server = make_server(authority)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(
            json.dumps(
                dict(
                    url=f"http://127.0.0.1:{server.server_port}",
                    token=phone,
                    workspace="empty-workspace",
                    paper=portable,
                    source_id=source["entity_id"],
                    source_hash=original_hash,
                    source_size=len(original),
                    current_hash=target["sha256"],
                    projection=manifest,
                )
            ),
            flush=True,
        )
        try:
            for line in sys.stdin:
                if line.strip() == "quit":
                    break
                raise AssertionError("Unknown fixture command")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            transfers.close()


if __name__ == "__main__":
    main()
