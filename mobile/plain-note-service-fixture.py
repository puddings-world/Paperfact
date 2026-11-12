"""Actual desktop note writer behind an isolated authenticated reference HTTP service."""

import json
import sys
import tempfile
import threading
from contextlib import closing
from pathlib import Path

core = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(core / "src"))

from paper_daily import store, sync_capture  # noqa: E402
from paper_daily.desktop.main import Data  # noqa: E402
from paper_daily.research_generation import _connect  # noqa: E402
from paper_daily.sync_client import SyncClient  # noqa: E402
from paper_daily.sync_http import make_server  # noqa: E402
from paper_daily.sync_journal import Journal  # noqa: E402
from paper_daily.sync_research import prepare, research_writer  # noqa: E402
from paper_daily.sync_service import ReferenceService  # noqa: E402

PAPER = "00000000-0000-4000-8000-000000000001"
WORKSPACE = "plain-note-workspace"


def main():
    with tempfile.TemporaryDirectory(prefix="plain-note-http-", dir=core / "build") as folder:
        root = Path(folder)
        store.DB_PATH = root / "papers.db"
        store.ensure_dirs = lambda: None
        store.init_db()
        prepare(store.DB_PATH, workspace_id=WORKSPACE, device_id="desktop")
        desktop = SyncClient(
            Journal(store.DB_PATH, workspace_id=WORKSPACE, device_id="desktop"), research_writer
        )
        authority = ReferenceService(root / "authority.sqlite")
        desktop_token = authority.enroll(WORKSPACE, "desktop")
        phone_token = authority.enroll(WORKSPACE, "phone")
        payload = dict(title="Synthetic plain note continuation", authors=[], year=2026)
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
        desktop.save(desktop.new_graph_operation("paper", PAPER, payload))
        desktop.save(
            desktop.new_graph_operation("list", "plain-list", dict(name="Offline notes", note=""))
        )
        from paper_daily.sync_schema_v2 import membership_id

        desktop.save(
            desktop.new_graph_operation(
                "membership",
                membership_id("plain-list", PAPER),
                dict(
                    list_id="plain-list",
                    paper_id=PAPER,
                    citation=None,
                    added_at="2026-11-02T00:00:00+00:00",
                ),
            )
        )
        with closing(_connect(store.DB_PATH)) as conn:
            local = conn.execute(
                "SELECT local_id FROM research_paper_identity WHERE sync_id=?", (PAPER,)
            ).fetchone()[0]
            conn.execute("BEGIN IMMEDIATE")
            sync_capture.install(conn, workspace_id=WORKSPACE, device_id="desktop")
            conn.commit()
        data = Data()
        note = data.add_note(local, "Desktop plain note")
        stale = data.note_for_edit(local, note)
        with closing(_connect(store.DB_PATH)) as conn:
            identity = conn.execute(
                "SELECT sync_id FROM research_note_identity WHERE local_id=?", (note,)
            ).fetchone()[0]
        desktop.sync_once(authority, desktop_token)
        server = make_server(authority)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(
            json.dumps(
                dict(
                    url=f"http://127.0.0.1:{server.server_port}",
                    workspace=WORKSPACE,
                    device="phone",
                    token=phone_token,
                    paper=PAPER,
                    note=identity,
                )
            ),
            flush=True,
        )
        try:
            for raw in sys.stdin:
                request = json.loads(raw)
                command = request["command"]
                if command == "quit":
                    break
                desktop.sync_once(authority, desktop_token)
                conflict = False
                if command in {"edit", "edit-stale"}:
                    try:
                        data.update_note(
                            note,
                            request["body"],
                            expected=stale
                            if command == "edit-stale"
                            else data.note_for_edit(local, note),
                        )
                    except sync_capture.StaleCaptureError:
                        conflict = True
                    desktop.sync_once(authority, desktop_token)
                elif command != "inspect":
                    raise ValueError("Unknown synthetic fixture command")
                with closing(_connect(store.DB_PATH)) as conn:
                    row = conn.execute(
                        "SELECT body,kind,created_at,page,anchor FROM notes WHERE id=?", (note,)
                    ).fetchone()
                    candidates = conn.execute(
                        "SELECT content FROM research_capture_candidates"
                    ).fetchall()
                print(
                    json.dumps(
                        dict(
                            note=dict(row) if row else None,
                            conflict=conflict,
                            candidates=[json.loads(row[0]) for row in candidates],
                            pending=len(desktop.journal.pending()),
                        )
                    ),
                    flush=True,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
