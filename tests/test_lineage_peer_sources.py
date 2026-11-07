"""Real three-peer original publication, caller rollback and immutable byte proof."""

import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from test_lineage_observation import work
from test_research_evidence import pdf
from test_sync_files import codec as _codec
from test_sync_files import drain, paper_payload
from test_sync_files import pair as _pair

from paper_daily import (
    lineage_observation,
    lineage_peer_sources,
    lineage_sets,
    research_lineage,
    store,
)
from paper_daily.fetch import _safe_name
from paper_daily.research_lifecycle import ensure_lifecycle
from paper_daily.sync_artifacts import desired_file
from paper_daily.sync_blobs import BlobManifest
from paper_daily.sync_capture import install
from paper_daily.sync_files import file_id
from paper_daily.sync_source_files import resolved

codec = _codec
pair = _pair


@pytest.fixture
def selected(pair, tmp_path):
    _service, client, _peer, files, _peer_files, _token, _peer_token = pair
    with closing(sqlite3.connect(client.journal.path)) as initial, initial:
        initial.execute(lineage_sets.SCHEMA)
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id=client.journal.workspace_id, device_id=client.journal.device_id)
    for title in ("Prior selected paper", "Later selected paper"):
        payload = {**paper_payload(), "title": title}
        client.save(client.new_graph_operation("paper", str(uuid4()), payload))
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_lifecycle(conn)
        local = [row[0] for row in conn.execute("SELECT id FROM papers ORDER BY title")]
    root = tmp_path / "selected-originals"
    root.mkdir()
    for index, identity in enumerate(local):
        pdf(root / (_safe_name(identity) + ".pdf"), [[f"Actual selected original {index}."]])
    corpus = research_lineage.capture(client.journal.path, local[0], local[1:], legacy_root=root)
    observed = work(lineage_observation.observe, corpus, str(uuid4()), str(uuid4()))
    prepared = work(
        lineage_peer_sources.prepare,
        observed,
        store=files.store,
        version_root=files.root,
        client=client,
    )
    return pair, corpus, observed, prepared


def publish(client, prepared):
    with client.journal.transaction() as conn:
        return lineage_peer_sources.publish_in(conn, client, prepared)


def file_counts(client):
    with closing(client.journal._connect()) as conn:
        return tuple(
            conn.execute("SELECT count(*) FROM " + name).fetchone()[0]
            for name in ("research_file_desired", "research_file_versions")
        )


def test_three_exact_peer_sources_stage_privately_then_publish_once_and_transfer(selected):
    pair, corpus, observed, prepared = selected
    server, client, peer, files, peer_files, token, peer_token = pair
    before = client.journal.pending()
    assert file_counts(client) == (0, 0)
    assert len(prepared.descriptors) == 3
    for row, source in zip(prepared.descriptors, observed.data["sources"], strict=True):
        assert row["sha256"] == source["document_hash"] and row["size"] == source["size"]
        path = files.store.verified_path(BlobManifest(row["sha256"], row["size"]))
        assert (
            path.read_bytes()
            == corpus._documents[
                [s["source_id"] for s in observed.data["sources"]].index(row["source_id"])
            ].path.read_bytes()
        )
    operations = work(publish, client, prepared)
    assert file_counts(client) == (3, 3)
    assert len(client.journal.pending()) == len(before) + 3
    assert work(publish, client, prepared) == operations
    assert file_counts(client) == (3, 3)
    for source in observed.data["sources"]:
        operation = operations[source["source_id"]]
        assert operation["parents"] == [source["parent"]]
        assert operation["payload"]["paper_id"] == source["parent"]["id"]
        assert operation["payload"]["source_document_hash"] == source["document_hash"]
        drain(lambda op=operation: files.upload(op), "uploaded")
    client.sync_once(server, token, prepare_push=files.ready_to_push)
    peer.sync_once(server, peer_token)
    for source in observed.data["sources"]:
        identity = file_id(source["parent"]["id"], "original_source", source["document_hash"])
        drain(lambda key=identity: peer_files.download(key), "bound")
        with peer.journal.transaction() as conn:
            path = resolved(conn, source["parent"]["id"], source["document_hash"])
            assert (
                path.read_bytes()
                == files.store.verified_path(
                    BlobManifest(source["document_hash"], source["size"])
                ).read_bytes()
            )
            assert not conn.execute("SELECT 1 FROM research_document_desired").fetchall()
    with closing(client.journal._connect()) as conn:
        assert conn.execute("SELECT count(*) FROM paper_lineage_sets").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM paper_claim_sets").fetchone()[0] == 0


def test_peer2_failure_rolls_back_entire_batch_even_if_caller_catches_then_retry_once(
    selected, monkeypatch
):
    pair, _corpus, _observed, prepared = selected
    client = pair[1]
    before = client.journal.pending()
    actual = lineage_peer_sources.publish_source_in
    calls = []

    def broken(*args):
        result = actual(*args)
        calls.append(result)
        if len(calls) == 2:
            raise RuntimeError("Injected after peer2 publication")
        return result

    def attempt():
        with client.journal.transaction() as conn:
            conn.execute("INSERT INTO kv VALUES('preserved-caller-work','fixture')")
            with pytest.raises(RuntimeError, match="peer2"):
                lineage_peer_sources.publish_in(conn, client, prepared)

    monkeypatch.setattr(lineage_peer_sources, "publish_source_in", broken)
    work(attempt)
    assert len(calls) == 2 and file_counts(client) == (0, 0)
    assert client.journal.pending() == before
    with closing(client.journal._connect()) as conn:
        assert (
            conn.execute("SELECT value FROM kv WHERE key='preserved-caller-work'").fetchone()[0]
            == "fixture"
        )
    monkeypatch.setattr(lineage_peer_sources, "publish_source_in", actual)
    operations = work(publish, client, prepared)
    assert len(operations) == 3 and file_counts(client) == (3, 3)
    assert work(publish, client, prepared) == operations
    assert len(client.journal.pending()) == len(before) + 3


def test_outer_caller_rollback_removes_all_source_outbox_ownership(selected):
    pair, _corpus, _observed, prepared = selected
    client = pair[1]
    before = client.journal.pending()

    def attempt():
        with (
            pytest.raises(RuntimeError, match="later compound action"),
            client.journal.transaction() as conn,
        ):
            lineage_peer_sources.publish_in(conn, client, prepared)
            raise RuntimeError("later compound action failed")

    work(attempt)
    assert file_counts(client) == (0, 0) and client.journal.pending() == before
    assert len(work(publish, client, prepared)) == 3


def test_changed_staged_original_or_parent_refuses_without_any_partial_source(selected):
    pair, _corpus, _observed, prepared = selected
    client, files = pair[1], pair[3]
    source = prepared.descriptors[1]
    path = files.store.verified_path(BlobManifest(source["sha256"], source["size"]))
    path.write_bytes(b"x" * path.stat().st_size)
    before = client.journal.pending()
    with pytest.raises(ValueError, match="changed"):
        work(publish, client, prepared)
    assert client.journal.pending() == before and file_counts(client) == (0, 0)


def test_cancelled_staging_and_wrong_connection_grant_no_source_authority(selected):
    pair, _corpus, observed, prepared = selected
    _server, client, peer, files, _peer_files, _token, _peer_token = pair
    before = client.journal.pending()
    with pytest.raises(research_lineage.LineageError, match="cancelled"):
        work(
            lineage_peer_sources.prepare,
            observed,
            store=files.store,
            version_root=files.root,
            client=client,
            cancelled=lambda: True,
        )
    with pytest.raises(research_lineage.LineageError, match="lineage_client_scope_changed"):
        work(publish, peer, prepared)
    assert client.journal.pending() == before and file_counts(client) == (0, 0)


def test_different_actual_source_head_is_not_waived_by_matching_source_bytes(selected):
    pair, _corpus, observed, prepared = selected
    client = pair[1]
    source = observed.data["sources"][0]
    from paper_daily.sync_source_files import prepare_source, publish_source_in

    other = work(
        prepare_source,
        client,
        source["parent"]["id"],
        observed._corpus._documents[0].path,
        document_hash=source["document_hash"],
        parent_incarnation=source["parent"]["incarnation"],
        store=pair[3].store,
        version_root=pair[3].root,
        request_id="different-accepted-original",
    )

    def install_other():
        with client.journal.transaction() as conn:
            return publish_source_in(conn, client, other)

    accepted = work(install_other)
    before = client.journal.pending()
    with pytest.raises(research_lineage.LineageError, match="lineage_observation_changed"):
        work(publish, client, prepared)
    assert client.journal.pending() == before and file_counts(client) == (1, 1)
    with closing(client.journal._connect()) as conn:
        assert desired_file(conn, accepted["entity_id"]) == accepted


def test_retire_restore_same_hash_does_not_reactivate_old_peer_intent(selected):
    pair, corpus, observed, first = selected
    client, files = pair[1], pair[3]
    existing = work(publish, client, first)
    fresh = work(lineage_observation.observe, corpus, observed.data["corpus_id"], str(uuid4()))
    held = work(
        lineage_peer_sources.prepare,
        fresh,
        store=files.store,
        version_root=files.root,
        client=client,
    )
    original = existing[observed.data["sources"][0]["source_id"]]

    def retire_restore():
        with client.journal.transaction() as conn:
            deleted = client.new_graph_operation_in(
                conn, "research_file", original["entity_id"], {}, action="delete"
            )
            client.journal.apply_in(conn, deleted, client.writer)
            restored = client.new_graph_operation_in(
                conn, "research_file", original["entity_id"], original["payload"], restore=True
            )
            client.journal.apply_in(conn, restored, client.writer)
            return restored

    restored = work(retire_restore)
    assert restored["payload"] == original["payload"]
    assert restored["incarnation"] != original["incarnation"]
    before, count = client.journal.pending(), file_counts(client)
    with pytest.raises(research_lineage.LineageError, match="lineage_source_operation_changed"):
        work(publish, client, held)
    assert client.journal.pending() == before and file_counts(client) == count
    assert work(research_lineage.current, corpus)


def test_selected_owned_A_publishes_while_verified_primary_B_stays_current(selected, tmp_path):
    import hashlib

    from test_sync_document_research import local_blob, pdf_bytes

    from paper_daily.document_reader import register_document_paths
    from paper_daily.sync_documents import (
        applied_document,
        bind_verified_document,
        desired_document,
        verify_document,
    )

    pair, legacy_corpus, legacy_observed, _unused = selected
    client, files = pair[1], pair[3]
    legacy_root = legacy_corpus._documents[0].path.parent

    def set_primary(source, raw):
        local_blob(files.store, raw)
        paper = source["parent"]["id"]
        client.save(
            client.new_graph_operation(
                "paper_document",
                paper,
                dict(
                    paper_id=paper,
                    sha256=hashlib.sha256(raw).hexdigest(),
                    size=len(raw),
                    media_type="application/pdf",
                ),
            )
        )
        with client.journal.transaction() as conn:
            target = desired_document(conn, paper)
        proof = verify_document(files.store, target)
        with client.journal.transaction() as conn:
            assert bind_verified_document(conn, target, proof)
        return target

    def managed_A():
        with client.journal.transaction() as conn:
            register_document_paths(
                conn,
                workspace_id=client.journal.workspace_id,
                blob_root=files.store.root,
                projection_root=tmp_path / "owned-projections",
                legacy_root=legacy_root,
            )
        for source, original in zip(
            legacy_observed.data["sources"], legacy_corpus._documents, strict=True
        ):
            set_primary(source, original.path.read_bytes())
        ids = [s["local_id"] for s in legacy_observed.data["sources"]]
        return research_lineage.capture(
            client.journal.path, ids[0], ids[1:], legacy_root=legacy_root
        )

    corpus = work(managed_A)
    assert all(d.managed for d in corpus._documents)
    observed = work(lineage_observation.observe, corpus, str(uuid4()), str(uuid4()))
    focal = observed.data["sources"][0]
    wanted_B = work(set_primary, focal, pdf_bytes("Actual new primary original B."))
    assert wanted_B["sha256"] != focal["document_hash"]
    assert work(research_lineage.current, corpus)
    prepared = work(
        lineage_peer_sources.prepare,
        observed,
        store=files.store,
        version_root=files.root,
        client=client,
    )
    operations = work(publish, client, prepared)
    assert operations[focal["source_id"]]["payload"]["slot"] == focal["document_hash"]
    with client.journal.transaction() as conn:
        assert desired_document(conn, focal["parent"]["id"]) == wanted_B
        assert applied_document(conn, focal["parent"]["id"]) == wanted_B
    assert file_counts(client) == (3, 3)
