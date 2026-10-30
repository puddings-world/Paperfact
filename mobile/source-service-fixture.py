"""Actual source publication and authenticated range transfer; entirely synthetic."""

import hashlib
import json
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path

core_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(core_root / "src"))

import pymupdf  # noqa: E402

from paper_daily import llm, store  # noqa: E402
from paper_daily.sync_blobs import BlobStore  # noqa: E402
from paper_daily.sync_client import SyncClient  # noqa: E402
from paper_daily.sync_file_transfers import FileTransfers  # noqa: E402
from paper_daily.sync_http import make_server  # noqa: E402
from paper_daily.sync_journal import Journal  # noqa: E402
from paper_daily.sync_research import prepare, research_writer  # noqa: E402
from paper_daily.sync_service import ReferenceService  # noqa: E402
from paper_daily.sync_source_files import publish, resolved  # noqa: E402

PAPER = "11111111-1111-4111-8111-111111111111"


def no_ai(*_args, **_kwargs):
    raise AssertionError("Source transfer and offline reads never invoke AI")


def pdf(text):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40, 50), text)
        return doc.tobytes()


def upload(authority, token, data):
    manifest = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    started = authority.blob_begin(token, manifest)
    offset = started["offset"]
    while offset < len(data):
        part = data[offset : offset + 256 * 1024]
        authority.blob_append(token, started["upload_id"], offset, part)
        offset += len(part)
    authority.blob_commit(token, started["upload_id"])
    return manifest


def main():
    llm.complete = llm.complete_result = no_ai
    with tempfile.TemporaryDirectory(prefix="paperfact-source-mobile-") as folder:
        root = Path(folder)
        authority = ReferenceService(root / "authority.sqlite", blob_root=root / "authority-blobs")
        desktop_token = authority.enroll("source-workspace", "desktop")
        phone_token = authority.enroll("source-workspace", "phone")
        database = root / "desktop.sqlite"
        with sqlite3.connect(database) as conn:
            conn.executescript(store.SCHEMA)
        prepare(database, workspace_id="source-workspace", device_id="desktop")
        desktop = SyncClient(
            Journal(database, workspace_id="source-workspace", device_id="desktop"), research_writer
        )
        paper = {
            "title": "Synthetic historical source A with current document B",
            "authors": [],
            "year": 2026,
            **{
                key: None
                for key in (
                    "venue",
                    "abstract",
                    "doi",
                    "arxiv_id",
                    "s2_id",
                    "page_url",
                    "pdf_url",
                    "source",
                )
            },
        }
        desktop.save(desktop.new_graph_operation("paper", PAPER, paper))
        desktop.sync_once(authority, desktop_token)
        transfers = FileTransfers(
            desktop,
            BlobStore(root / "desktop-blobs"),
            authority,
            origin="https://fixture.invalid",
            token=desktop_token,
        )
        # A valid trailing PDF comment makes a real source span more than one transport chunk.
        original = (
            pdf("Original A: an explicit research snapshot") + b"\n%" + b"F" * (256 * 1024 + 20)
        )
        original += b"\n%%EOF\n"
        path = root / "original-a.pdf"
        path.write_bytes(original)
        source_hash = hashlib.sha256(original).hexdigest()
        with desktop.journal.transaction() as conn:
            parent = desktop._optimistic_graph(conn)[0][("paper", PAPER)]["incarnation"]
        operation = publish(
            desktop,
            PAPER,
            path,
            document_hash=source_hash,
            parent_incarnation=parent,
            store=transfers.store,
            version_root=transfers.root,
            request_id="source-a",
        )
        assert (
            publish(
                desktop,
                PAPER,
                path,
                document_hash=source_hash,
                parent_incarnation=parent,
                store=transfers.store,
                version_root=transfers.root,
                request_id="source-a-repeated",
            )
            == operation
        )
        for _ in range(40):
            if transfers.upload(operation)["state"] == "uploaded":
                break
        else:
            raise AssertionError("Synthetic source upload did not finish")
        desktop.sync_once(authority, desktop_token, prepare_push=transfers.ready_to_push)
        current = upload(
            authority, desktop_token, pdf("Current primary B: distinct from original A")
        )
        desktop.save(
            desktop.new_graph_operation(
                "paper_document",
                PAPER,
                {"paper_id": PAPER, **current, "media_type": "application/pdf"},
            )
        )
        desktop.sync_once(authority, desktop_token, prepare_push=transfers.ready_to_push)
        with desktop.journal.transaction() as conn:
            assert resolved(conn, PAPER, source_hash).read_bytes() == original
        server = make_server(authority)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(
            json.dumps(
                {
                    "url": f"http://127.0.0.1:{server.server_port}",
                    "token": phone_token,
                    "id": operation["entity_id"],
                    "paper": PAPER,
                    "source_hash": source_hash,
                    "source_size": len(original),
                    "current_hash": current["sha256"],
                    "events": len(authority.pull(phone_token)),
                }
            ),
            flush=True,
        )
        try:
            if sys.stdin.readline().strip() == "retire":
                desktop.save(
                    desktop.new_graph_operation(
                        "research_file", operation["entity_id"], {}, action="delete"
                    )
                )
                desktop.sync_once(authority, desktop_token, prepare_push=transfers.ready_to_push)
                print(
                    json.dumps({"retired": True, "events": len(authority.pull(phone_token))}),
                    flush=True,
                )
                sys.stdin.readline()
        finally:
            transfers.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
