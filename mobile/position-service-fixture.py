"""Actual entered position plus original A/current B, authenticated loopback only."""

import hashlib
import json
import sqlite3
import sys
import tempfile
import threading
from contextlib import closing
from pathlib import Path

core_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(core_root / "src"))

from uuid import uuid4  # noqa: E402

import pymupdf  # noqa: E402

from paper_daily import llm, manual_highlight_ops, reading_position_ops, store  # noqa: E402
from paper_daily.research_inbox import Inbox  # noqa: E402
from paper_daily.sync_blobs import BlobStore  # noqa: E402
from paper_daily.sync_capture import install  # noqa: E402
from paper_daily.sync_client import SyncClient  # noqa: E402
from paper_daily.sync_file_transfers import FileTransfers  # noqa: E402
from paper_daily.sync_http import make_server  # noqa: E402
from paper_daily.sync_journal import Journal  # noqa: E402
from paper_daily.sync_projection import read_manifest  # noqa: E402
from paper_daily.sync_research import prepare, research_writer  # noqa: E402
from paper_daily.sync_service import ReferenceService  # noqa: E402
from paper_daily.sync_source_files import publish, resolved  # noqa: E402

PAPER = "11111111-1111-4111-8111-111111111111"


def no_ai(*_args, **_kwargs):
    raise AssertionError("Source transfer and offline reads never invoke AI")


def pdf(text):
    with pymupdf.open() as doc:
        for index in range(2):
            doc.new_page().insert_text((40, 50), text + str(index + 1))
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
        recovery_token = authority.enroll("source-workspace", "recovery-phone")
        unsent_token = authority.enroll("source-workspace", "unsent-phone")
        unsent_receiver_token = authority.enroll("source-workspace", "unsent-receiver")
        database = root / "desktop.sqlite"
        with closing(sqlite3.connect(database)) as conn:
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
        store.DB_PATH = database
        store.ensure_dirs = lambda: None
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            store._migrate(conn)
            install(conn, workspace_id="source-workspace", device_id="desktop")
            local = conn.execute(
                "SELECT local_id FROM research_paper_identity WHERE sync_id=?", (PAPER,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO pins(scope,paper_id,pinned_at) VALUES('queue',?,?)",
                (local, "2026-10-31T00:00:00Z"),
            )
        inbox = Inbox(database)
        inbox.save(
            inbox.read(),
            request_id=str(uuid4()),
            item_id=str(uuid4()),
            payload=dict(
                kind="idea",
                text="Synthetic continuity fixture",
                state="new",
                created_at="2026-10-31T00:00:00Z",
                updated_at="2026-10-31T00:00:00Z",
            ),
        )
        owner = manual_highlight_ops.capture_owner(database, local)
        native = manual_highlight_ops.load(owner, path, source_hash)
        first = reading_position_ops.prepare(
            reading_position_ops.capture(native), 2, method="entered"
        )
        reading_position_ops.save(first, with_proof=True)
        desktop.sync_once(authority, desktop_token, prepare_push=transfers.ready_to_push)
        assert any(
            event["outcome"] == "accepted"
            and event["operation"]["payload"].get("feature") == "reading_position"
            for event in authority.pull(phone_token, limit=100)
        )
        with desktop.journal.transaction() as conn:
            assert resolved(conn, PAPER, source_hash).read_bytes() == original
        projection = read_manifest(database, workspace_id="source-workspace", schema_version=2)
        assert projection["required_capabilities"] == ["inbox", "queue_pin", "reading_position"]
        primary_b = dict(current)
        previous = dict(current)
        primary_serial = 0
        server = make_server(authority)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(
            json.dumps(
                {
                    "url": f"http://127.0.0.1:{server.server_port}",
                    "workspace": "source-workspace",
                    "projection": projection,
                    "token": phone_token,
                    "recovery_token": recovery_token,
                    "unsent_token": unsent_token,
                    "unsent_receiver_token": unsent_receiver_token,
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
            for line in sys.stdin:
                command = line.strip()
                if command == "quit":
                    break
                desktop.sync_once(authority, desktop_token, prepare_push=transfers.ready_to_push)
                if command == "position":
                    fresh = reading_position_ops.capture(native)
                    reading_position_ops.save(
                        reading_position_ops.prepare(fresh, 1, method="entered"), with_proof=True
                    )
                elif command == "primary":
                    previous = dict(current)
                    primary_serial += 1
                    current = upload(
                        authority,
                        desktop_token,
                        pdf(f"New primary revision {primary_serial}; retained B stays independent"),
                    )
                    desktop.save(
                        desktop.new_graph_operation(
                            "paper_document",
                            PAPER,
                            {"paper_id": PAPER, **current, "media_type": "application/pdf"},
                        )
                    )
                elif command in {"retire", "retire-b", "delete", "delete-current"}:
                    if command in {"retire", "retire-b"}:
                        from paper_daily.sync_files import file_id

                        identity = (
                            file_id(PAPER, "original_source", primary_b["sha256"])
                            if command == "retire-b"
                            else operation["entity_id"]
                        )
                        kind = "research_file"
                    else:
                        from paper_daily.sync_content import content_id

                        identity = content_id(
                            dict(kind="paper", id=PAPER),
                            "reading_position",
                            current["sha256"] if command == "delete-current" else source_hash,
                        )
                        kind = "research_content"
                    desktop.save(desktop.new_graph_operation(kind, identity, {}, action="delete"))
                elif command == "revoke":
                    authority.revoke_peer(desktop_token, "phone")
                elif command in {"peer", "peer-recovery"}:
                    from position_peer_preservation import verify_peer

                    options = (
                        dict(proof_name="recovered-independent-peer", count=3, page=1)
                        if command == "peer-recovery"
                        else {}
                    )
                    result = verify_peer(
                        root,
                        authority,
                        f"http://127.0.0.1:{server.server_port}",
                        previous if command == "peer-recovery" else primary_b,
                        current,
                        **options,
                    )
                    print(json.dumps(result), flush=True)
                    continue
                desktop.sync_once(authority, desktop_token, prepare_push=transfers.ready_to_push)
                with desktop.journal.transaction() as conn:
                    row = conn.execute(
                        "SELECT page,method FROM reading_positions "
                        "WHERE paper_id=? AND document_hash=?",
                        (local, source_hash),
                    ).fetchone()
                    all_positions = [
                        list(value)
                        for value in conn.execute(
                            "SELECT document_hash,page,method FROM reading_positions "
                            "WHERE paper_id=? ORDER BY document_hash",
                            (local,),
                        )
                    ]
                print(
                    json.dumps(
                        dict(
                            command=command,
                            position=list(row) if row else None,
                            all_positions=all_positions,
                            current_hash=current["sha256"],
                            events=len(authority.pull(desktop_token)),
                        )
                    ),
                    flush=True,
                )
        finally:
            transfers.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
