"""Real legacy writer + loopback authenticated service; no AI/account/network."""

import hashlib
import importlib.util
import json
import sys
import tempfile
import threading
from pathlib import Path

core_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(core_root / "src"))

from paper_daily import legacy_briefs, store  # noqa: E402
from paper_daily import queue as queue_module  # noqa: E402
from paper_daily.sync_blobs import BlobStore  # noqa: E402
from paper_daily.sync_file_transfers import FileTransfers  # noqa: E402
from paper_daily.sync_http import make_server  # noqa: E402
from paper_daily.sync_service import ReferenceService  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "legacy_fixture_setup", core_root / "mobile" / "chat-service-fixture.py"
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
STAMP = "2026-10-30T12:34:56.123456+08:00"
DATA = "# Brief\r\n\r\n<script>never execute</script> \u4e2d\u6587\U0001f600\r\n".encode()


def main():
    with tempfile.TemporaryDirectory(prefix="paperfact-mobile-workflow-") as folder:
        root = Path(folder)
        authority = ReferenceService(root / "service.sqlite", blob_root=root / "authority-blobs")
        desktop = setup.client(root / "desktop" / "papers.db", "desktop")
        token_desktop = authority.enroll("qa-workspace", "desktop")
        transfers = FileTransfers(
            desktop,
            BlobStore(root / "desktop" / "blobs"),
            authority,
            origin="https://fixture.invalid",
            token=token_desktop,
            version_root=root / "desktop" / "research-versions",
        )
        with store.connect() as conn:
            for paper in ["local-paper", "parent", "next-parent"]:
                store.upsert_papers(
                    conn,
                    [dict(id=paper, title=paper, source="fixture", venue="Fixture", year=2026)],
                )
            conn.execute(
                "INSERT INTO queue VALUES(?,-2.75,'deferred','manual',?,?,?,NULL,?)",
                ("local-paper", "parent", "Exact reason", STAMP, STAMP),
            )
            conn.execute("INSERT INTO refs VALUES(?,?,1)", ("next-parent", "local-paper"))
            path = legacy_briefs.record_pack(
                conn, "local-paper", STAMP, "manual", DATA, legacy_day="2026-10-30"
            )
        assert path.read_bytes() == DATA
        event = next(
            op
            for op in desktop.journal.pending()
            if op.get("payload", {}).get("feature") == "reading_event"
        )
        file = next(
            op
            for op in desktop.journal.pending()
            if op.get("payload", {}).get("feature") == "legacy_brief"
        )
        queue = next(
            op
            for op in desktop.journal.pending()
            if op.get("payload", {}).get("feature") == "queue_entry"
        )
        for _ in range(20):
            if transfers.upload(file)["state"] == "uploaded":
                break
        else:
            raise AssertionError("Fixture brief upload incomplete")
        desktop.sync_once(authority, token_desktop, prepare_push=transfers.ready_to_push)
        token = authority.enroll("qa-workspace", "phone")
        server = make_server(authority)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def emit(**extra):
            print(
                json.dumps(
                    dict(
                        url=f"http://127.0.0.1:{server.server_port}",
                        token=token,
                        workspace="qa-workspace",
                        event=event,
                        file=file,
                        queue=queue,
                        markdown=DATA.decode(),
                        sha256=hashlib.sha256(DATA).hexdigest(),
                        events=len(authority.pull(token)),
                        **extra,
                    )
                ),
                flush=True,
            )

        emit()
        try:
            for line in sys.stdin:
                command = line.strip()
                if command in {"quit", ""}:
                    break
                if command == "companion":
                    with store.connect() as conn:
                        conn.execute(
                            "UPDATE queue SET state='pending' WHERE paper_id='local-paper'"
                        )
                with store.connect() as conn:
                    if command == "clear":
                        conn.execute("UPDATE reading_log SET brief_path=NULL")
                    elif command == "delete":
                        conn.execute("DELETE FROM reading_log")
                    elif command == "note":
                        conn.execute("UPDATE reading_log SET note='Edited note'")
                    elif command == "companion":
                        assert queue_module.add_companions(conn, "next-parent") == ["local-paper"]
                        assert tuple(
                            conn.execute(
                                "SELECT rank,role,parent_id FROM queue WHERE paper_id='local-paper'"
                            ).fetchone()
                        ) == (0.1, "companion", "next-parent")
                    elif command == "rank":
                        conn.execute("UPDATE queue SET rank=1e21")
                    else:
                        raise AssertionError("Unknown fixture command")
                if command in {"rank", "companion"}:
                    pending = [
                        op
                        for op in desktop.journal.pending()
                        if op.get("payload", {}).get("feature") == "queue_entry"
                    ]
                    if pending:
                        previous_queue = queue
                        queue = pending[-1]
                        if command == "companion":
                            assert (
                                queue["incarnation"]
                                == queue["operation_id"]
                                != previous_queue["incarnation"]
                            )
                desktop.sync_once(authority, token_desktop)
                emit(command=command)
        finally:
            transfers.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
