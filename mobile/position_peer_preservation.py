"""Synthetic fresh desktop package/backup proof after phone-first retained B."""

import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing


def verify_peer(
    root, authority, url, primary_b, current, *, proof_name="independent-peer", count=2, page=2
):
    from paper_daily import bundle, local_source_owners, source_snapshots, store, sync_recovery
    from paper_daily.sync_blobs import BlobManifest, BlobStore
    from paper_daily.sync_client import SyncClient, validate_event
    from paper_daily.sync_file_transfers import FileTransfers
    from paper_daily.sync_http import HttpTransport
    from paper_daily.sync_journal import Journal
    from paper_daily.sync_research import prepare, research_order_writer, research_writer
    from paper_daily.sync_schema_v2 import membership_id
    from paper_daily.sync_transfers import DocumentTransfers

    assert primary_b["sha256"] != current["sha256"], "Choose actual primary C first"
    folder = root / proof_name
    folder.mkdir()
    database = folder / "papers.db"
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript(store.SCHEMA)
    prepare(database, workspace_id="source-workspace", device_id=proof_name)
    peer = SyncClient(
        Journal(database, workspace_id="source-workspace", device_id=proof_name),
        research_writer,
        order_writer=research_order_writer,
    )
    token = authority.enroll("source-workspace", proof_name)
    transport = HttpTransport(url)
    for _ in range(30):
        peer.sync_once(transport, token)
        if peer.status()["cursor"] == len(authority.pull(token, limit=100)):
            break
    else:
        raise AssertionError("Bounded independent metadata pages did not finish")
    with peer.journal.transaction() as conn:
        portable, local = conn.execute(
            "SELECT sync_id,local_id FROM research_paper_identity"
        ).fetchone()
        originals = [
            json.loads(row[0])
            for row in conn.execute("SELECT operation FROM research_file_desired WHERE active=1")
        ]
    peer_blobs = BlobStore(folder / "blobs")
    files = FileTransfers(peer, peer_blobs, transport, origin=url, token=token)
    documents = DocumentTransfers(
        peer,
        peer_blobs,
        transport,
        origin=url,
        token=token,
        reader_root=folder / "reader",
        legacy_root=folder / "pdf",
    )
    try:
        for operation in originals:
            if operation["payload"]["feature"] != "original_source":
                continue
            for _ in range(30):
                if files.download(operation["entity_id"])["state"] == "bound":
                    break
            else:
                raise AssertionError("Bounded independent original download did not finish")
        for _ in range(30):
            if documents.download(portable)["state"] == "bound":
                break
        else:
            raise AssertionError("Bounded independent primary C download did not finish")
    finally:
        files.close()
        documents.close()
    assert local_source_owners.list_owned(database) == [], "Received bytes invented native receipts"
    peer.save(
        peer.new_graph_operation("list", "continuity", {"name": "Continuity fixture", "note": ""})
    )
    peer.save(
        peer.new_graph_operation(
            "membership",
            membership_id("continuity", portable),
            {
                "list_id": "continuity",
                "paper_id": portable,
                "citation": None,
                "added_at": "2026-10-31T02:00:00Z",
            },
        )
    )
    old_database, old_data, old_pdf, old_fetch = (
        store.DB_PATH,
        bundle.DATA_DIR,
        bundle.PDF_DIR,
        bundle.fetch,
    )
    try:
        store.DB_PATH, bundle.DATA_DIR, bundle.PDF_DIR = database, folder, folder / "pdf"

        def no_network(*_args, **_kwargs):
            raise AssertionError("Complete fixture package attempted external fetch")

        bundle.fetch = no_network
        package = folder / "research.zip"
        bundle.export("continuity", package)
        with zipfile.ZipFile(package) as zipped:
            manifest, tables, _files = bundle._validated(zipped)
            assert len(tables["reading_positions"]) == count
            original = next(
                row for row in manifest["position_sources"] if row["sha256"] == primary_b["sha256"]
            )
            assert (
                hashlib.sha256(zipped.read("files/" + original["path"])).hexdigest()
                == primary_b["sha256"]
            )
            assert manifest["pdfs"][local]["sha256"] == current["sha256"]
            current_members = [
                name
                for name, digest in manifest["file_hashes"].items()
                if name.startswith("pdf/") and name.count("/") == 1 and digest == current["sha256"]
            ]
            assert len(current_members) == 1
            assert (
                hashlib.sha256(zipped.read("files/" + current_members[0])).hexdigest()
                == current["sha256"]
            )
        backup = folder / "independent.zip"
        if count == 3:
            before = database.read_bytes()
            try:
                sync_recovery.create(
                    database, backup, blob_store=peer_blobs, legacy_root=folder / "pdf"
                )
            except FileNotFoundError:
                pass
            else:
                raise AssertionError(
                    "Missing historical primary falsely produced a complete backup"
                )
            assert not backup.exists() and not list(folder.glob(".paperfact-recovery-*.zip"))
            assert database.read_bytes() == before
            assert local_source_owners.list_owned(database) == []
            captured = bundle._document(local)
            assert captured.available and captured.sha256 == current["sha256"]
            assert hashlib.sha256(captured.path.read_bytes()).hexdigest() == current["sha256"]
            # Explicit fixture preparation: strict recovery includes received
            # historical document receipts too. Fetch only their exact descriptors;
            # these cache bytes grant no current original-source authority.
            with peer.journal.transaction() as conn:
                received = conn.execute(
                    "SELECT event FROM paperfact_sync_graph_receipts LIMIT 101"
                ).fetchall()
            assert len(received) <= 100
            downloaded = 0
            for (raw,) in received:
                received_event = json.loads(validate_event(json.loads(raw), "source-workspace"))
                operation = received_event["operation"]
                if (
                    received_event["outcome"] != "accepted"
                    or operation["entity_type"] != "paper_document"
                    or operation["action"] != "put"
                ):
                    continue
                assert (
                    operation["entity_id"] == portable
                    and operation["payload"]["paper_id"] == portable
                )
                descriptor = BlobManifest(
                    operation["payload"]["sha256"], operation["payload"]["size"]
                )
                assert descriptor.size <= 32 * 1024**2
                if peer_blobs.available(descriptor):
                    continue
                downloaded += descriptor.size
                assert downloaded <= 64 * 1024**2
                offset = peer_blobs.begin(descriptor)["offset"]
                while offset < descriptor.size:
                    chunk = transport.blob_read(token, descriptor.sha256, descriptor.size, offset)
                    assert chunk
                    offset = peer_blobs.append(descriptor, offset, chunk)
                exact = peer_blobs.finalize(descriptor)
                assert exact.stat().st_size == descriptor.size
                assert hashlib.sha256(exact.read_bytes()).hexdigest() == descriptor.sha256
            assert downloaded > 0 and database.read_bytes() == before
            assert local_source_owners.list_owned(database) == []
        sync_recovery.create(database, backup, blob_store=peer_blobs, legacy_root=folder / "pdf")
        sync_recovery.inspect(backup)
        restored = folder / "detached"
        sync_recovery.restore_detached(backup, restored)
        assert (
            hashlib.sha256((restored / "objects" / primary_b["sha256"]).read_bytes()).hexdigest()
            == primary_b["sha256"]
        )
        with closing(sqlite3.connect(restored / "papers.db")) as conn:
            assert (
                conn.execute(
                    "SELECT page FROM reading_positions WHERE document_hash=?",
                    (primary_b["sha256"],),
                ).fetchone()[0]
                == page
            )
            names = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert (
                not {"paperfact_sync_identity", "research_capture_binding", "document_reader_paths"}
                & names
            )
            assert (
                conn.execute("SELECT count(*) FROM research_reading_position_receipts").fetchone()[
                    0
                ]
                == 0
            )
        destination = folder / "package-receiver"
        destination.mkdir()
        store.DB_PATH, bundle.DATA_DIR, bundle.PDF_DIR = (
            destination / "papers.db",
            destination,
            destination / "pdf",
        )
        bundle.PDF_DIR.mkdir()
        store.init_db()
        result = bundle.import_(package)
        assert result["reading_positions"] == count
        owner = next(
            row
            for row in local_source_owners.list_owned(store.DB_PATH)
            if row["sha256"] == primary_b["sha256"]
        )
        assert (
            hashlib.sha256(
                source_snapshots.source_path(store.DB_PATH, owner).read_bytes()
            ).hexdigest()
            == primary_b["sha256"]
        )
        assert (
            hashlib.sha256((destination / current_members[0]).read_bytes()).hexdigest()
            == current["sha256"]
        )
        return {
            "peer": True,
            "package_positions": count,
            "backup_positions": count,
            "detached_no_active_identity": True,
            "fresh_package_source_owner": True,
            "retained_B": primary_b["sha256"],
            "current_C": current["sha256"],
            "missing_history_refused_then_explicitly_downloaded": count == 3,
        }
    finally:
        store.DB_PATH, bundle.DATA_DIR, bundle.PDF_DIR, bundle.fetch = (
            old_database,
            old_data,
            old_pdf,
            old_fetch,
        )
