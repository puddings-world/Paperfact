"""Actual first enrollment of SQL NULL list metadata, with authenticated HTTP."""

import json
import sys
import tempfile
import threading
from pathlib import Path
from uuid import uuid4

core_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(core_root / "src"))

from paper_daily import llm, store  # noqa: E402
from paper_daily.sync_client import SyncClient  # noqa: E402
from paper_daily.sync_http import make_server  # noqa: E402
from paper_daily.sync_journal import Journal  # noqa: E402
from paper_daily.sync_research import research_writer  # noqa: E402
from paper_daily.sync_service import ReferenceService  # noqa: E402
from paper_daily.workspace_enrollment import EnrollmentService  # noqa: E402


def no_ai(*_args, **_kwargs):
    raise AssertionError("List enrollment/read must not invoke AI")


def main():
    with tempfile.TemporaryDirectory(prefix="paperfact-nullable-list-http-") as folder:
        root = Path(folder)
        source = root / "source"
        source.mkdir()
        store.DB_PATH = source / "papers.db"
        store.init_db()
        values = {"null-route": None, "empty-route": "", "space-route": " "}
        with store.connect() as conn:
            for identity, note in values.items():
                conn.execute("INSERT INTO lists(id,name,note,created_at) VALUES(?,?,?,?)",
                             (identity, identity, note, "2026-10-30T00:00:00+00:00"))
        llm.complete = llm.complete_result = no_ai
        result = EnrollmentService(store.DB_PATH).prepare(
            root / "candidate", backup_output=root / "backup.zip", request_id=str(uuid4()),
        )
        workspace, device = result["workspace_id"], result["device_id"]
        desktop = SyncClient(Journal(result["database"], workspace_id=workspace, device_id=device),
                             research_writer)
        authority = ReferenceService(root / "authority.sqlite")
        desktop_token = authority.enroll(workspace, device)
        desktop.sync_once(authority, desktop_token, limit=1000)
        token = authority.enroll(workspace, "phone")
        events = authority.pull(token)
        received = {row["operation"]["entity_id"]: row["operation"]["payload"]["note"]
                    for row in events if row["operation"]["entity_type"] == "list"}
        assert received == values
        server = make_server(authority)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}", "token": token,
                          "workspace": workspace, "device": "phone", "events": len(events),
                          "expected": values}), flush=True)
        try:
            sys.stdin.readline()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
