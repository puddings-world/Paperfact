"""Optional scientific schema follows actual analysis/receive transaction ownership."""

import json
from contextlib import closing

import pytest
from test_lineage_jobs import routes, work
from test_lineage_live_journey import native, setup_publication, sync_all
from test_lineage_peer_sources import codec as codec
from test_lineage_peer_sources import pair as pair
from test_lineage_peer_sources import selected as selected
from test_lineage_projection import rows
from test_lineage_workflow_native import prepare
from test_sync_files import drain

from paper_daily import (
    lineage_dependencies,
    lineage_projection,
    lineage_sets,
    llm,
    research_lineage,
)
from paper_daily import research_generation as generation
from paper_daily.ai_types import Completion
from paper_daily.lineage_workflow import LineageWorkflow
from paper_daily.manual_highlight_ops import observe_owner
from paper_daily.research_lifecycle import ensure_lifecycle
from paper_daily.sync_capture import install
from paper_daily.sync_client import SyncClient
from paper_daily.sync_research import research_projection_writer


def snapshot(client):
    with closing(client.journal._connect()) as conn:
        return tuple(conn.iterdump())


def has_report(client):
    with closing(client.journal._connect()) as conn:
        return bool(
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name=?", (lineage_sets.TABLE,)
            ).fetchone()
        )


def test_fresh_native_attach_and_saved_read_do_not_create_report(pair):
    client = pair[1]
    assert not has_report(client)
    assert rows(client, lineage_projection.TABLE) == []
    assert rows(client, lineage_projection.HISTORY) == []
    before = snapshot(client)
    reader = native(client)
    assert lineage_sets.saved(reader.journal.path, "not-analyzed") == []
    assert snapshot(reader) == before
    assert not has_report(reader)


def test_first_actual_receive_creates_report_without_granting_pdf_bytes(selected, monkeypatch):
    client, _result, _receipt, _science, sources = setup_publication(selected, monkeypatch)
    assert not has_report(selected[0][2])
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Receive used AI"))
    peer = sync_all(selected, client, sources)
    assert (
        rows(peer, lineage_sets.TABLE)[0]["source_hash"]
        == (rows(client, lineage_sets.TABLE)[0]["source_hash"])
    )
    with closing(peer.journal._connect()) as conn:
        assert conn.execute("SELECT count(*) FROM research_file_applied").fetchone()[0] == 0
    before = snapshot(peer)
    peer.sync_once(selected[0][0], selected[0][6])
    assert snapshot(peer) == before


def test_late_receive_failure_rolls_back_schema_content_and_cursor_then_retries(
    selected, monkeypatch
):
    client, _result, _receipt, _science, sources = setup_publication(selected, monkeypatch)
    service, _origin, peer, files, _peer_files, token, peer_token = selected[0]
    for source in sources:
        drain(lambda op=source: files.upload(op), "uploaded")
    for _ in range(3):
        state = client.sync_once(service, token, prepare_push=files.ready_to_push)
        if state["pending"] == 0:
            break
    assert state["pending"] == 0
    events = service.pull(peer_token)
    with closing(generation._connect(peer.journal.path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
        install(conn, workspace_id=peer.journal.workspace_id, device_id=peer.journal.device_id)
        conn.commit()

    applied = []

    def late_failure(conn, operation, *, visible):
        research_projection_writer(conn, operation, visible=visible)
        if lineage_dependencies.requires_readiness(operation):
            applied.append(True)
            assert conn.execute("SELECT count(*) FROM paper_lineage_sets").fetchone()[0] == 1
            raise RuntimeError("fixture late receive")

    receiving = SyncClient.attach_existing(
        peer.journal, peer.writer, projection_writer=late_failure
    )
    assert not has_report(receiving)
    before = snapshot(receiving)
    with pytest.raises(RuntimeError, match="fixture late receive"):
        receiving.receive(events)
    assert applied == [True]
    assert snapshot(receiving) == before
    assert not has_report(receiving)
    repaired = native(peer)
    repaired.receive(events)
    assert len(rows(repaired, lineage_sets.TABLE)) == 1
    after = snapshot(repaired)
    repaired.receive(events)
    assert snapshot(repaired) == after


def test_explicit_analysis_on_cold_native_workspace_initializes_and_publishes(
    selected, monkeypatch
):
    client = selected[0][1]
    assert rows(client, lineage_sets.TABLE) == []
    with client.journal.transaction() as conn:
        conn.execute("DROP TABLE paper_lineage_sets")
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Prepare used AI"))
    workflow = prepare(selected)
    assert has_report(client)
    assert rows(client, lineage_sets.TABLE) == []
    corpus = workflow._job._corpus
    response = dict(
        format=research_lineage.PROPOSALS,
        focal=corpus.focal,
        statements=[
            dict(
                stage="current_change",
                subject=corpus.focal,
                text="A concrete selected result.",
                function="unresolved",
                judgment=dict(status="unresolved", reason="Review needed."),
                passages=[
                    dict(
                        source_id=corpus.focal,
                        role="change_evidence",
                        cites=None,
                        quote="Actual selected original 0.",
                        page=1,
                        anchor=None,
                    )
                ],
            )
        ],
    )
    calls = []

    def complete(*args, **kwargs):
        calls.append(True)
        return Completion(json.dumps(response))

    monkeypatch.setattr(llm, "complete_result", complete)
    outcome = work(workflow.run)
    assert outcome.state == "queued_sync" and outcome.operation_id
    assert len(rows(client, lineage_sets.TABLE)) == 1
    assert work(workflow.run) is outcome and calls == [True]


@pytest.mark.parametrize("change", ["cancel", "view"])
def test_cancel_or_view_change_after_schema_setup_rolls_back_before_ai(
    selected, monkeypatch, change
):
    client = selected[0][1]
    with client.journal.transaction() as conn:
        conn.execute("DROP TABLE paper_lineage_sets")
    owners = [x["local_id"] for x in research_lineage._checked(selected[1])["observed"]]
    owner = observe_owner(
        client.journal.path, owners[0], expected_native=generation._identity(client.journal.path)
    )
    before = snapshot(client)
    initialized = []
    original = lineage_projection.initialize_in

    def setup(conn, **options):
        original(conn, **options)
        initialized.append(True)

    monkeypatch.setattr(lineage_projection, "initialize_in", setup)
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Cancelled used AI"))
    with pytest.raises(research_lineage.LineageError, match="cancelled"):
        work(
            LineageWorkflow.prepare,
            owner,
            owners[1:],
            connections=routes(),
            legacy_root=selected[1]._documents[0].path.parent,
            cancelled=lambda: bool(initialized) and change == "cancel",
            current=lambda: not initialized or change != "view",
        )
    assert initialized == [True]
    assert snapshot(client) == before
    assert not has_report(client)
