"""Synthetic authority behind the existing isolated Chromium fixture proxy."""

import json
import os
import secrets
import sqlite3
import sys
import tempfile
import threading
from contextlib import closing
from pathlib import Path

core = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(core / "src"))
from paper_daily import store, sync_admin  # noqa: E402
from paper_daily.sync_browser import BrowserSessions  # noqa: E402
from paper_daily.sync_client import SyncClient  # noqa: E402
from paper_daily.sync_http import make_server  # noqa: E402
from paper_daily.sync_journal import Journal  # noqa: E402
from paper_daily.sync_pairing import Invitation  # noqa: E402
from paper_daily.sync_research import prepare, research_writer  # noqa: E402
from paper_daily.sync_schema_v2 import membership_id  # noqa: E402


def main():
    with tempfile.TemporaryDirectory(prefix="browser-pairing-", dir=core / "build") as directory:
        root = Path(directory)
        database = root / "papers.db"
        with closing(sqlite3.connect(database)) as conn:
            conn.executescript(store.SCHEMA)
        workspace, device = "browser-workspace", "desktop"
        paper = "00000000-0000-4000-8000-000000000001"
        prepare(database, workspace_id=workspace, device_id=device)
        writer = SyncClient(
            Journal(database, workspace_id=workspace, device_id=device), research_writer
        )
        sync_admin.initialize(root / "authority")
        service = sync_admin.authority(root / "authority")
        token = service.enroll(workspace, device)
        payload = dict(title="Synthetic paired research", authors=[], year=2026)
        payload.update(
            {
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
            }
        )
        writer.save(writer.new_graph_operation("paper", paper, payload))
        writer.save(
            writer.new_graph_operation(
                "list", "browser-list", dict(name="Paired research", note="")
            )
        )
        writer.save(
            writer.new_graph_operation(
                "membership",
                membership_id("browser-list", paper),
                dict(
                    list_id="browser-list",
                    paper_id=paper,
                    citation=None,
                    added_at="2026-11-14T00:00:00+00:00",
                ),
            )
        )
        writer.sync_once(service, token)
        origin = sys.argv[2]
        sessions = BrowserSessions(service, origin, secrets.token_bytes(32))
        code = secrets.token_urlsafe(32)
        grant = service.create_pairing(
            token, code, checkpoint=service.history_page(token)["checkpoint"],
        )
        packet = Invitation(origin, code=code, **grant).encoded()
        server = make_server(service, browser=sessions, allow_unverified_mutations=False)
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        thread.start()
        print(
            json.dumps(
                dict(
                    url=f"http://127.0.0.1:{server.server_port}",
                    workspace=workspace,
                    paper=paper,
                    invitation=packet,
                    test_revocation=os.environ.get("PAPERFACT_TEST_PAIRING_REVOCATION") == "1",
                )
            ),
            flush=True,
        )
        try:
            for command in sys.stdin:
                if command.strip() == "quit":
                    break
                if command.strip() == "revoke":
                    catalog = service.device_catalog(token)["devices"]
                    peers = [row["device_id"] for row in catalog if row["device_id"] != device]
                    if len(peers) != 1:
                        raise ValueError("Expected exactly one paired fixture browser")
                    result = service.revoke_peer(
                        token, peers[0], checkpoint=service.history_page(token)["checkpoint"]
                    )
                    print(json.dumps(result), flush=True)
                    continue
                if command.strip() != "inspect":
                    raise ValueError("Unknown fixture command")
                catalog = service.device_catalog(token)["devices"]
                events = service.pull(token)
                notes = [
                    event["operation"]["payload"]["body"]
                    for event in events
                    if event["operation"]["entity_type"] == "note"
                ]
                print(
                    json.dumps(dict(devices=len(catalog), events=len(events), notes=notes)),
                    flush=True,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
            if thread.is_alive():
                raise RuntimeError("Fixture server did not stop")


if __name__ == "__main__":
    main()
