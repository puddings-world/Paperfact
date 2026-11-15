"""Trusted native proposals atomically publish originals/report without model or cloud calls."""

import sqlite3
from contextlib import closing

import pymupdf
import pytest
from test_sync_capture import bound as bound
from test_sync_capture import seed
from test_sync_files import drain, side

from paper_daily import research_generation as generation
from paper_daily import survey_publication as publication
from paper_daily import survey_sources
from paper_daily.sync_artifacts import applied_file, desired_file, materialize
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_capture import expecting, observe_note
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_files import list_file_id, validate_closure
from paper_daily.sync_service import ReferenceService


@pytest.fixture
def prepared(bound, tmp_path):
    seed()
    root = tmp_path / "pdf"
    root.mkdir()
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72, 72), "A selected method improves measurement.")
        raw = pdf.tobytes()
    (root / "local-paper.pdf").write_bytes(raw)
    server = ReferenceService(tmp_path / "authority.sqlite", blob_root=tmp_path / "remote-blobs")
    token = server.enroll("workspace", "a")
    files = FileTransfers(
        bound, BlobStore(tmp_path / "blobs"), server, origin="https://fixture.invalid", token=token
    )
    bound.sync_once(server, token)
    with closing(generation._connect(bound.journal.path)) as conn:
        context = generation.begin_generation(conn, table="list_surveys", owner_id="list")
    corpus = survey_sources.capture(context, legacy_root=root)
    proposal = survey_sources.verify(
        corpus,
        [
            dict(
                heading="Captured evidence",
                statements=[
                    dict(
                        text="An interpretation for researcher review.",
                        interpretation="reported",
                        passages=[
                            dict(
                                source_id=corpus.sources[0]["id"],
                                quote="A selected method",
                                page=1,
                                anchor=None,
                            )
                        ],
                    )
                ],
            )
        ],
        provenance=dict(
            task="survey", backend="codex", requested_model="fixture", returned_model=None
        ),
    )
    return bound, server, token, files, root, proposal


def dump(client):
    with closing(sqlite3.connect(client.journal.path)) as conn:
        return list(conn.iterdump())


def test_sealed_publisher_stages_read_only_then_commits_once_and_peer_gets_exact_report(
    prepared,
    tmp_path,
):
    client, server, token, files, _, proposal = prepared
    before = dump(client)
    staged = publication.prepare(proposal)
    assert dump(client) == before
    with closing(generation._connect(client.journal.path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        operation = publication.publish_in(conn, staged)
    after = dump(client)
    with closing(generation._connect(client.journal.path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        assert publication.publish_in(conn, staged) == operation
    assert dump(client) == after
    assert len(operation["payload"]["source_bindings"]) == 1
    binding = operation["payload"]["source_bindings"][0]
    assert binding["paper_id"] != "local-paper"
    assert not files.ready_to_push(operation)
    with client.journal.transaction() as conn:
        original = desired_file(conn, binding["file_id"])
    drain(lambda: files.upload(original), "uploaded")
    client.sync_once(server, token, prepare_push=files.ready_to_push)
    drain(lambda: files.upload(operation), "uploaded")
    client.sync_once(server, token, prepare_push=files.ready_to_push)
    peer = side(tmp_path, "b")
    peer_token = server.enroll("workspace", "b")
    peer_files = FileTransfers(
        peer,
        BlobStore(tmp_path / "peer-blobs"),
        server,
        origin="https://fixture.invalid",
        token=peer_token,
    )
    peer.sync_once(server, peer_token)
    drain(lambda: peer_files.download(operation["entity_id"]), "bound")
    version = materialize(peer_files.store, peer_files.root, operation)
    body = validate_closure(
        operation["payload"], lambda row: staged.proof.files[row["sha256"]][0].read_bytes()
    )
    assert body["report"] == proposal.report
    assert (version / "survey.json").is_file()
    with peer.journal.transaction() as conn:
        assert applied_file(conn, operation["entity_id"]) == operation
        assert applied_file(conn, binding["file_id"]) is None
    # Received acknowledgements do not make the unchanged local intent stale.
    assert publication.publish(staged) == operation


def test_late_failure_caught_by_caller_rolls_back_all_sources_and_report_but_not_caller_edit(
    prepared,
    monkeypatch,
):
    client, _, _, _, _, proposal = prepared
    staged = publication.prepare(proposal)
    real = publication.sync_source_files.publish_source_in

    def failure(*args, **kwargs):
        real(*args, **kwargs)
        raise OSError("fixture interruption after original write")

    monkeypatch.setattr(publication.sync_source_files, "publish_source_in", failure)
    with (
        closing(generation._connect(client.journal.path)) as conn,
        expecting(conn, [observe_note(conn, 1)]),
        conn,
    ):
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE notes SET body='Preserve caller work'")
        with pytest.raises(OSError, match="interruption"):
            publication.publish_in(conn, staged)
        assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0] == 0
        assert conn.execute("SELECT body FROM notes").fetchone()[0] == "Preserve caller work"
    assert not [op for op in client.journal.pending() if op["entity_type"] == "research_file"]
    monkeypatch.setattr(publication.sync_source_files, "publish_source_in", real)
    with closing(generation._connect(client.journal.path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        assert publication.publish_in(conn, staged)["payload"]["feature"] == "survey"


def test_cancellation_and_outer_rollback_leave_no_report_or_original_grants(prepared):
    client, _, _, _, _, proposal = prepared
    staged = publication.prepare(proposal)
    before = dump(client)
    with closing(generation._connect(client.journal.path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="cancelled"):
            publication.publish_in(conn, staged, cancelled=lambda: True)
        publication.publish_in(conn, staged)
        conn.rollback()
    assert dump(client) == before
    assert staged.proof.matches(staged.proof_operation)  # Only inactive staged bytes remain.


def test_stale_report_observation_cannot_overwrite_another_publication(prepared):
    client, _, _, _, root, proposal = prepared
    old = publication.prepare(proposal)
    with closing(generation._connect(client.journal.path)) as conn:
        second_context = generation.begin_generation(conn, table="list_surveys", owner_id="list")
    second_corpus = survey_sources.capture(second_context, legacy_root=root)
    second_proposal = survey_sources.verify(
        second_corpus,
        [
            dict(
                heading="Competing job",
                statements=[
                    dict(
                        text="Preserve this independent result.",
                        interpretation="inference",
                        passages=[],
                    )
                ],
            )
        ],
        provenance=proposal.report["generation"],
    )
    second = publication.prepare(second_proposal)
    with closing(generation._connect(client.journal.path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        operation = publication.publish_in(conn, old)
    with closing(generation._connect(client.journal.path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="lifetimes changed"):
            publication.publish_in(conn, second)
        assert desired_file(conn, operation["entity_id"]) == operation
    # Native observations cannot be recreated by changing a private request ID.
    from dataclasses import replace

    context = proposal._capture._context
    data = context.data
    data["request_id"] = "different-job"
    # A forged capture cannot re-create the native observation's process seal.
    forged = replace(proposal._capture, _context=replace(context, _json=generation._json(data)))
    with pytest.raises(ValueError, match="capture changed"):
        survey_sources.checked_proposal(replace(proposal, _capture=forged))
    with closing(generation._connect(client.journal.path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        retirement = client.new_graph_operation_in(
            conn, "research_file", operation["entity_id"], {}, action="delete"
        )
        client.journal.apply_in(conn, retirement, client.writer)
    with closing(generation._connect(client.journal.path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="exact active publication"):
            publication.publish_in(conn, old)
        assert desired_file(conn, list_file_id("list")) is None


def test_foreign_database_raw_proposal_and_replaced_original_cannot_publish(prepared, tmp_path):
    client, _, _, _, root, proposal = prepared
    staged = publication.prepare(proposal)
    before = dump(client)
    with pytest.raises(ValueError, match="sealed"):
        publication.prepare(proposal.report)
    peer = side(tmp_path, "other")
    with closing(generation._connect(peer.journal.path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="database"):
            publication.publish_in(conn, staged)
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72, 72), "A replacement original must not authorize old work.")
        (root / "local-paper.pdf").write_bytes(pdf.tobytes())
    with closing(generation._connect(client.journal.path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="availability"):
            publication.publish_in(conn, staged)
    assert dump(client) == before
    assert staged.proof.matches(staged.proof_operation)


def test_materialization_interruption_retains_pending_intent_and_exact_retry_activates(
    prepared,
    monkeypatch,
):
    from paper_daily import sync_artifacts

    client, _, _, _, _, proposal = prepared
    staged = publication.prepare(proposal)
    real = sync_artifacts.materialize

    def fail(*args, **kwargs):
        raise OSError("fixture materialization interruption")

    monkeypatch.setattr(sync_artifacts, "materialize", fail)
    with pytest.raises(OSError, match="materialization interruption"):
        publication.publish(staged)
    with client.journal.transaction() as conn:
        pending = desired_file(conn, list_file_id("list"))
        assert pending is not None
        assert applied_file(conn, pending["entity_id"]) is None
        count = conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0]
    monkeypatch.setattr(sync_artifacts, "materialize", real)
    from paper_daily.sync_deck_publication import runtime

    # Reattach from disk, without passing the old PreparedSurvey to recovery.
    reopened = runtime(database=client.journal.path)
    assert reopened is not client
    assert publication.complete_pending(reopened, "list") == pending
    with reopened.journal.transaction() as conn:
        assert applied_file(conn, pending["entity_id"]) == pending
        assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0] == count
    # Exact replay by the still-live caller also reuses the same publication.
    assert publication.publish(staged) == pending
    with pytest.raises(ValueError, match="No owned pending"):
        publication.complete_pending(reopened, "unowned-list")


def test_offline_completion_refuses_same_binding_database_replacement(
    prepared, tmp_path, monkeypatch
):
    from paper_daily import sync_artifacts
    from paper_daily.sync_deck_publication import runtime

    client, _, _, _, _, proposal = prepared
    staged = publication.prepare(proposal)
    with closing(generation._connect(client.journal.path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        operation = publication.publish_in(conn, staged)
    reopened = runtime(database=client.journal.path)
    real = sync_artifacts.materialize
    replacement = tmp_path / "replacement.sqlite"

    def replace_after_materialize(*args, **kwargs):
        directory = real(*args, **kwargs)
        with (
            closing(sqlite3.connect(client.journal.path)) as source,
            closing(sqlite3.connect(replacement)) as target,
        ):
            source.backup(target)
        replacement.replace(client.journal.path)
        return directory

    monkeypatch.setattr(sync_artifacts, "materialize", replace_after_materialize)
    with pytest.raises(ValueError, match="database.*changed"):
        publication.complete_pending(reopened, "list")
    with reopened.journal.transaction() as conn:
        assert applied_file(conn, operation["entity_id"]) is None
