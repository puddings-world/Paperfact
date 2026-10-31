"""Temporary typed journal + loopback reference service for independent activity views."""

import hashlib
import json
import sqlite3
import sys
import tempfile
import threading
from contextlib import closing
from pathlib import Path

core = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(core / "src"))

from paper_daily import store  # noqa: E402
from paper_daily.sync_client import SyncClient  # noqa: E402
from paper_daily.sync_http import make_server  # noqa: E402
from paper_daily.sync_journal import Journal  # noqa: E402
from paper_daily.sync_research import prepare, research_order_writer, research_writer  # noqa: E402
from paper_daily.sync_schema_v2 import membership_id  # noqa: E402
from paper_daily.sync_service import ReferenceService  # noqa: E402
from paper_daily.workspace_activity import ActivityReader  # noqa: E402

PAPER = "11111111-1111-4111-8111-111111111111"
NOTE = "22222222-2222-4222-8222-222222222222"
WORKSPACE, STAMP = "activity-workspace", "2026-10-30T12:00:00+08:00"
PARENT = dict(kind="paper", id=PAPER, incarnation="paper-created")


def operation(
    kind,
    identity,
    payload,
    request,
    *,
    parents=(),
    base=0,
    incarnation=None,
    device="peer",
    action="put",
    structure=0,
):
    return dict(
        version=2,
        operation_id=request,
        workspace_id=WORKSPACE,
        device_id=device,
        entity_type=kind,
        entity_id=identity,
        action=action,
        payload=payload,
        base_revision=base,
        depends_on=None,
        incarnation=incarnation or request,
        parents=list(parents),
        structure_revision=structure,
    )


def pdf(text):
    import pymupdf

    with pymupdf.open() as document:
        document.new_page().insert_text((40, 60), text)
        return document.tobytes()


def main():
    with tempfile.TemporaryDirectory(prefix="paperfact-activity-fixture-") as folder:
        root = Path(folder)
        path = root / "reader.sqlite"
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript(store.SCHEMA)
            conn.commit()
        prepare(path, workspace_id=WORKSPACE, device_id="phone")
        client = SyncClient(
            Journal(path, workspace_id=WORKSPACE, device_id="phone"),
            research_writer,
            order_writer=research_order_writer,
        )
        authority = ReferenceService(root / "authority.sqlite", blob_root=root / "blobs")
        peer, phone = authority.enroll(WORKSPACE, "peer"), authority.enroll(WORKSPACE, "phone")

        def upload(data):
            declared = dict(sha256=hashlib.sha256(data).hexdigest(), size=len(data))
            started = authority.blob_begin(peer, declared)
            if not started["complete"]:
                authority.blob_append(peer, started["upload_id"], 0, data)
                authority.blob_commit(peer, started["upload_id"])
            return declared

        source = upload(pdf("Original recorded source A"))
        paper = dict(
            title="Recorded research <script>literal</script> " + "😀" * 170,
            authors=[],
            year=2026,
            venue=None,
            abstract=None,
            doi=None,
            arxiv_id=None,
            s2_id=None,
            page_url=None,
            pdf_url=None,
            source="fixture",
        )
        authority.push(peer, operation("paper", PAPER, paper, "paper-created"))
        authority.push(
            peer, operation("list", "reading-list", dict(name="Reading", note=None), "list-created")
        )
        member = membership_id("reading-list", PAPER)
        list_parent = dict(kind="list", id="reading-list", incarnation="list-created")
        authority.push(
            peer,
            operation(
                "membership",
                member,
                dict(paper_id=PAPER, list_id="reading-list", citation=None, added_at=STAMP),
                "membership-created",
                parents=[list_parent, PARENT],
            ),
        )
        authority.push(
            peer,
            operation(
                "reading_state",
                member,
                dict(
                    paper_id=PAPER,
                    list_id="reading-list",
                    state="read",
                    delivered_at=STAMP,
                    read_at=STAMP,
                ),
                "reading-record",
                parents=[
                    dict(kind="membership", id=member, incarnation="membership-created"),
                    list_parent,
                    PARENT,
                ],
            ),
        )
        note = dict(
            paper_id=PAPER,
            body="Saved note",
            kind="note",
            created_at=STAMP,
            page=1,
            anchor=dict(p0=0, o0=0, p1=0, o1=2, document_hash=source["sha256"]),
        )
        authority.push(peer, operation("note", NOTE, note, "note-created", parents=[PARENT]))
        authority.push(
            peer,
            operation(
                "paper_document",
                PAPER,
                dict(paper_id=PAPER, **source, media_type="application/pdf"),
                "pdf-created",
                parents=[PARENT],
            ),
        )
        client.receive(authority.pull(phone))
        reader = ActivityReader(path)
        server = make_server(authority)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def emit(command="ready"):
            print(
                json.dumps(
                    dict(
                        command=command,
                        url=f"http://127.0.0.1:{server.server_port}",
                        token=phone,
                        workspace=WORKSPACE,
                        paper_id=PAPER,
                        note_id=NOTE,
                        source_hash=source["sha256"],
                        report=dict(reader.snapshot()),
                    )
                ),
                flush=True,
            )

        def head(kind, identity):
            with closing(sqlite3.connect(path)) as conn:
                revision, raw = conn.execute(
                    "SELECT revision,operation FROM paperfact_sync_heads "
                    "WHERE entity_type=? AND entity_id=?",
                    (kind, identity),
                ).fetchone()
                graph = json.loads(
                    conn.execute(
                        "SELECT metadata FROM paperfact_sync_graph "
                        "WHERE entity_type=? AND entity_id=?",
                        (kind, identity),
                    ).fetchone()[0]
                )
            return revision, json.loads(raw), graph

        emit()
        try:
            for line in sys.stdin:
                command = line.strip()
                if command in {"quit", ""}:
                    break
                if command == "own":
                    revision, old, _ = head("note", NOTE)
                    changed = dict(note, body="My recorded note")
                    result = authority.push(
                        phone,
                        operation(
                            "note",
                            NOTE,
                            changed,
                            "own-note",
                            parents=[PARENT],
                            base=revision,
                            incarnation=old["incarnation"],
                            device="phone",
                        ),
                    )
                    assert result["outcome"] == "accepted"
                elif command == "conflict":
                    result = authority.push(
                        phone,
                        operation(
                            "note",
                            NOTE,
                            dict(note, body="Conflict"),
                            "own-conflict",
                            parents=[PARENT],
                            incarnation="note-created",
                            device="phone",
                        ),
                    )
                    assert result["outcome"] == "conflict"
                elif command == "source":
                    replacement = upload(pdf("Replacement current source B"))
                    revision, old, _ = head("paper_document", PAPER)
                    result = authority.push(
                        peer,
                        operation(
                            "paper_document",
                            PAPER,
                            dict(paper_id=PAPER, **replacement, media_type="application/pdf"),
                            "pdf-replaced",
                            parents=[PARENT],
                            base=revision,
                            incarnation=old["incarnation"],
                        ),
                    )
                    assert result["outcome"] == "accepted"
                elif command == "delete":
                    revision, old, graph = head("note", NOTE)
                    result = authority.push(
                        peer,
                        operation(
                            "note",
                            NOTE,
                            {},
                            "note-deleted",
                            parents=[PARENT],
                            base=revision,
                            incarnation=old["incarnation"],
                            action="delete",
                            structure=graph["structure_revision"],
                        ),
                    )
                    assert result["outcome"] == "accepted"
                else:
                    raise ValueError("Unknown fixture control")
                client.receive(authority.pull(phone))
                emit(command)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
