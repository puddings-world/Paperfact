"""Synthetic trusted native survey publisher for independent mobile HTTP acceptance."""

import json
import sqlite3
import sys
import tempfile
import threading
from contextlib import closing
from pathlib import Path

core_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(core_root / "src"))

import pymupdf  # noqa: E402

from paper_daily import (  # noqa: E402
    llm,
    research_generation,
    store,
    survey_publication,
    survey_sources,
)
from paper_daily.sync_artifacts import desired_file  # noqa: E402
from paper_daily.sync_blobs import BlobStore  # noqa: E402
from paper_daily.sync_capture import install  # noqa: E402
from paper_daily.sync_client import SyncClient  # noqa: E402
from paper_daily.sync_deck_publication import runtime  # noqa: E402
from paper_daily.sync_file_transfers import FileTransfers  # noqa: E402
from paper_daily.sync_http import make_server  # noqa: E402
from paper_daily.sync_journal import Journal  # noqa: E402
from paper_daily.sync_research import prepare, research_writer  # noqa: E402
from paper_daily.sync_service import ReferenceService  # noqa: E402


def no_ai(*_args, **_kwargs):
    raise AssertionError("Survey fixture must not invoke a model")


def upload(files, operation):
    for _ in range(40):
        if files.upload(operation)["state"] == "uploaded":
            return
    raise AssertionError("Bounded survey upload did not complete")


def main():
    llm.complete = llm.complete_result = no_ai
    with tempfile.TemporaryDirectory(prefix="paperfact-survey-mobile-") as folder:
        root = Path(folder)
        database = root / "desktop.sqlite"
        store.DB_PATH = database
        store.ensure_dirs = lambda: None
        with closing(sqlite3.connect(database)) as conn, conn:
            conn.executescript(store.SCHEMA)
        prepare(database, workspace_id="survey-workspace", device_id="desktop")
        SyncClient(
            Journal(database, workspace_id="survey-workspace", device_id="desktop"), research_writer
        )
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            install(conn, workspace_id="survey-workspace", device_id="desktop")
        with store.connect() as conn:
            conn.execute("INSERT INTO lists VALUES('field','Synthetic field','',?)", (store.now(),))
            store.upsert_papers(
                conn,
                [
                    dict(
                        id="local-input",
                        title="Synthetic input",
                        year=2026,
                        venue="Fixture",
                        source="fixture",
                    )
                ],
            )
            conn.execute(
                "INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                "VALUES('field','local-input',0,?)",
                (store.now(),),
            )
        goal = "Compare assumptions: \u7814\u7a76 \U0001f9ea"
        with store.connect() as conn:
            conn.execute("INSERT INTO list_reading_goals VALUES('field',?,?)", (goal, store.now()))
        desktop = runtime(database=database)
        authority = ReferenceService(root / "authority.sqlite", blob_root=root / "remote-blobs")
        token = authority.enroll("survey-workspace", "desktop")
        phone_token = authority.enroll("survey-workspace", "phone")
        files = FileTransfers(
            desktop,
            BlobStore(root / "blobs"),
            authority,
            origin="https://fixture.invalid",
            token=token,
        )
        desktop.sync_once(authority, token)
        pdf_root = root / "pdf"
        pdf_root.mkdir()
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((72, 72), "A selected method improves measurement.")
            (pdf_root / "local-input.pdf").write_bytes(pdf.tobytes())
        with closing(research_generation._connect(database)) as conn:
            context = research_generation.begin_generation(
                conn, table="list_surveys", owner_id="field"
            )
        corpus = survey_sources.capture(context, legacy_root=pdf_root)
        source_id = corpus.sources[0]["id"]
        # Long retained interpretations and explicitly unlocated proposals test the blob
        # boundary. Only the short original quotation is located; semantics stay unchecked.
        statements = [
            dict(
                text="Discussion \u7814\u7a76 \U0001f9ea " + str(i) + " " + "x" * 9900,
                interpretation="inference",
                passages=[
                    dict(
                        source_id=source_id,
                        quote=f"Unmatched proposal {i}:{j} " + "x" * 3900,
                        page=None,
                        anchor=None,
                    )
                    for j in range(3)
                ],
            )
            for i in range(12)
        ]
        statements[0]["passages"].append(
            dict(source_id=source_id, quote="A selected method", page=1, anchor=None)
        )
        proposal = survey_sources.verify(
            corpus,
            [dict(heading="Retained research", statements=statements)],
            provenance=dict(
                task="survey", backend="codex", requested_model="fixture", returned_model=None
            ),
        )
        operation = survey_publication.publish(survey_publication.prepare(proposal))
        binding = operation["payload"]["source_bindings"][0]
        with desktop.journal.transaction() as conn:
            original = desired_file(conn, binding["file_id"])
        upload(files, original)
        desktop.sync_once(authority, token, prepare_push=files.ready_to_push)
        upload(files, operation)
        desktop.sync_once(authority, token, prepare_push=files.ready_to_push)
        server = make_server(authority)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(
            json.dumps(
                dict(
                    url=f"http://127.0.0.1:{server.server_port}",
                    token=phone_token,
                    id=operation["entity_id"],
                    body_hash=operation["payload"]["body"]["sha256"],
                    body_size=operation["payload"]["body"]["size"],
                    source_id=binding["file_id"],
                    report_id=proposal.report["id"],
                    goal=goal,
                    events=len(authority.pull(phone_token)),
                )
            ),
            flush=True,
        )
        try:
            if sys.stdin.readline().strip() == "retire":
                desktop.save(desktop.new_graph_operation("list", "field", {}, action="delete"))
                desktop.sync_once(authority, token)
                print(
                    json.dumps(dict(retired=True, events=len(authority.pull(phone_token)))),
                    flush=True,
                )
                sys.stdin.readline()
        finally:
            files.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
