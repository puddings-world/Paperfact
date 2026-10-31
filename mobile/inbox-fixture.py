"Actual Inbox desktop operations and private loopback authority; temporary data only."

import json
import sqlite3
import sys
import tempfile
import threading
from contextlib import closing
from pathlib import Path
from uuid import uuid4

core = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(core / "src"))

from paper_daily import inbox_content as content  # noqa: E402
from paper_daily import store, sync_recovery  # noqa: E402
from paper_daily.research_inbox import Inbox  # noqa: E402
from paper_daily.sync_client import SyncClient  # noqa: E402
from paper_daily.sync_http import make_server  # noqa: E402
from paper_daily.sync_journal import Journal  # noqa: E402
from paper_daily.sync_projection import read_manifest  # noqa: E402
from paper_daily.sync_research import prepare, research_order_writer, research_writer  # noqa: E402
from paper_daily.sync_service import ReferenceService  # noqa: E402

WORKSPACE = "inbox-fixture-workspace"
STAMP = "2026-10-30T12:00:00+00:00"


def main():
    with tempfile.TemporaryDirectory(prefix="paperfact-inbox-fixture-") as folder:
        root = Path(folder)
        database = root / "desktop.sqlite"
        with closing(sqlite3.connect(database)) as conn:
            conn.executescript(store.SCHEMA)
            store._migrate(conn)
            conn.commit()
        prepare(database, workspace_id=WORKSPACE, device_id="desktop")
        client = SyncClient(
            Journal(database, workspace_id=WORKSPACE, device_id="desktop"),
            research_writer,
            order_writer=research_order_writer,
        )
        inbox = Inbox(database)
        identity = str(uuid4())
        body = dict(
            kind="doi",
            text="  DOI:10.1234/Exact-Mixed  ",
            state="new",
            created_at=STAMP,
            updated_at=STAMP,
        )
        inbox.save(inbox.read(), request_id=str(uuid4()), item_id=identity, payload=body)
        authority = ReferenceService(root / "authority.sqlite", blob_root=root / "blobs")
        desktop, phone = (
            authority.enroll(WORKSPACE, "desktop"),
            authority.enroll(WORKSPACE, "phone"),
        )
        client.sync_once(authority, desktop)
        server = make_server(authority, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = "http://127.0.0.1:" + str(server.server_address[1])

        def output(extra=None):
            view = inbox.read(include_deleted=True)
            print(
                json.dumps(
                    dict(
                        workspace=WORKSPACE,
                        url=url,
                        token=phone,
                        initial_id=identity,
                        items=view.data["items"],
                        projection=read_manifest(
                            database, workspace_id=WORKSPACE, schema_version=2
                        ),
                        retained=inbox.retained(view).data["retained"],
                        **(extra or {}),
                    ),
                    ensure_ascii=True,
                ),
                flush=True,
            )

        output()
        try:
            for line in sys.stdin:
                command = json.loads(line)
                mode = command["command"]
                if mode == "quit":
                    break
                client.sync_once(authority, desktop)
                if mode in {"triage", "delete"}:
                    view = inbox.read(include_deleted=True)
                    item = next(
                        row for row in view.data["items"] if row["id"] == command["item_id"]
                    )
                    data = (
                        dict(item["payload"], state="kept", updated_at="2026-10-30T13:00:00Z")
                        if mode == "triage"
                        else None
                    )
                    inbox.save(
                        view,
                        request_id=str(uuid4()),
                        item_id=item["id"],
                        payload=data,
                        action="put" if mode == "triage" else "delete",
                        observed=inbox.observe(item),
                    )
                    client.sync_once(authority, desktop)
                extra = {}
                if mode == "backup":
                    sync_recovery.create(database, root / "backup.zip")
                    sync_recovery.restore_detached(root / "backup.zip", root / "restored")
                    restored = Inbox(root / "restored/papers.db")
                    with closing(sqlite3.connect(root / "restored/papers.db")) as conn:
                        tables = {
                            row[0]
                            for row in conn.execute(
                                "SELECT name FROM sqlite_master WHERE type='table'"
                            )
                        }
                        fresh = conn.execute(f"SELECT token FROM {content.OWNER}").fetchone()[0]
                        requests = conn.execute(
                            f"SELECT count(*) FROM {content.REQUESTS}"
                        ).fetchone()[0]
                    with closing(sqlite3.connect(database)) as conn:
                        old = conn.execute(f"SELECT token FROM {content.OWNER}").fetchone()[0]
                    extra = dict(
                        restored=restored.read(include_deleted=True).data["items"],
                        fresh_receiver=fresh != old,
                        sender_receipts_live=requests,
                        active_binding="paperfact_sync_identity" in tables,
                    )
                output(extra)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
