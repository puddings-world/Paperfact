"""Actual paper-only queue-pin producer with authenticated local HTTP; no external calls."""

import importlib.util
import json
import sys
import tempfile
import threading
from pathlib import Path

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
from paper_daily import store  # noqa: E402
from paper_daily.list_pins import set_pinned  # noqa: E402
from paper_daily.sync_http import make_server  # noqa: E402
from paper_daily.sync_schema_v2 import membership_id  # noqa: E402
from paper_daily.sync_service import ReferenceService  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "queue_pin_fixture_setup", root / "mobile/chat-service-fixture.py"
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
STAMP = "2026-10-30T12:34:56.123456+08:00"


def main():
    with tempfile.TemporaryDirectory(prefix="paperfact-queue-pin-http-") as folder:
        path = Path(folder)
        desktop = setup.client(path / "desktop/papers.db", "desktop")
        service = ReferenceService(path / "service.sqlite")
        token = service.enroll("qa-workspace", "desktop")
        with store.connect() as conn:
            store.upsert_papers(
                conn,
                [
                    dict(
                        id="local-paper",
                        title="Orphan pinned paper",
                        source="fixture",
                        venue="Fixture",
                        year=2026,
                    )
                ],
            )
        with store.connect() as conn:
            first = set_pinned(conn, "queue", "local-paper", True, pinned_at=STAMP)
            assert (
                first["changed"]
                and not set_pinned(conn, "queue", "local-paper", True, pinned_at=STAMP)["changed"]
            )
        desktop.sync_once(service, token)
        phone = service.enroll("qa-workspace", "phone")
        server = make_server(service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def emit():
            with store.connect() as conn:
                assert conn.execute("SELECT COUNT(*) FROM queue").fetchone()[0] == 0
                assert (
                    conn.execute("SELECT COUNT(*) FROM lists WHERE id!='queue'").fetchone()[0] == 0
                )
                assert (
                    conn.execute(
                        "SELECT COUNT(*) FROM list_papers WHERE list_id!='queue'"
                    ).fetchone()[0]
                    == 0
                )
                pin = conn.execute("SELECT pinned_at FROM pins WHERE scope='queue'").fetchone()
            print(
                json.dumps(
                    dict(
                        url=f"http://127.0.0.1:{server.server_port}",
                        token=phone,
                        workspace="qa-workspace",
                        stamp=STAMP,
                        pinned=pin is not None,
                        events=len(service.pull(phone)),
                    )
                ),
                flush=True,
            )

        emit()
        try:
            for raw in sys.stdin:
                command = raw.strip()
                if command in {"quit", ""}:
                    break
                assert command in {
                    "off",
                    "on",
                    "rollback",
                    "make-queue-list",
                    "remove-queue-member",
                    "remove-queue-list",
                }
                if command == "make-queue-list":
                    with store.connect() as conn:
                        portable = conn.execute(
                            "SELECT sync_id FROM research_paper_identity "
                            "WHERE local_id='local-paper'"
                        ).fetchone()[0]
                    desktop.save(
                        desktop.new_graph_operation(
                            "list", "queue", {"name": "Actual user list", "note": ""}
                        )
                    )
                    desktop.save(
                        desktop.new_graph_operation(
                            "membership",
                            membership_id("queue", portable),
                            {
                                "list_id": "queue",
                                "paper_id": portable,
                                "citation": None,
                                "added_at": STAMP,
                            },
                        )
                    )
                    desktop.sync_once(service, token)
                    emit()
                    continue
                with store.connect() as conn:
                    if command == "remove-queue-member":
                        conn.execute("DELETE FROM list_papers WHERE list_id='queue'")
                    elif command == "remove-queue-list":
                        conn.execute("DELETE FROM lists WHERE id='queue'")
                    else:
                        set_pinned(conn, "queue", "local-paper", command == "on", pinned_at=STAMP)
                    if command == "rollback":
                        conn.rollback()
                desktop.sync_once(service, token)
                emit()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    main()
