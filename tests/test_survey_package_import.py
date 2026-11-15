"""Actual portable survey -> explicit receiver native owners -> peer/re-export."""

import json
import sqlite3
from contextlib import closing

import pytest
from test_survey_packages import exported as exported
from test_survey_packages import package
from test_survey_publication import dump
from test_survey_publication import prepared as prepared
from test_sync_capture import bound as bound
from test_sync_files import drain

from paper_daily import research_generation as generation
from paper_daily import store, survey_packages
from paper_daily import survey_package_import as imports
from paper_daily.sync_artifacts import applied_file, desired_file, register_paths
from paper_daily.sync_blobs import BlobManifest, BlobStore
from paper_daily.sync_capture import install
from paper_daily.sync_client import SyncClient
from paper_daily.sync_deck_publication import runtime
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_files import list_file_id, validate_closure
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare, research_writer
from paper_daily.sync_service import ReferenceService


@pytest.fixture
def receiver(tmp_path):
    database = tmp_path / "receiver.sqlite"
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript(store.SCHEMA)
    prepare(database, workspace_id="receiver-workspace", device_id="laptop")
    client = SyncClient(
        Journal(database, workspace_id="receiver-workspace", device_id="laptop"), research_writer
    )
    with closing(generation._connect(database)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        install(conn, workspace_id="receiver-workspace", device_id="laptop")
    with closing(generation._connect(database)) as conn, conn:
        conn.execute(
            "INSERT INTO lists VALUES('receiver-list','Receiver collection','',?)", (store.now(),)
        )
        store.upsert_papers(
            conn,
            [
                dict(
                    id="receiver-paper",
                    title="Explicit receiver selection",
                    year=2026,
                    venue="Fixture",
                    source="fixture",
                )
            ],
        )
    client = runtime(database=database)
    blobs = BlobStore(tmp_path / "receiver-blobs")
    with client.journal.transaction() as conn:
        register_paths(conn, "receiver-workspace", blobs, tmp_path / "receiver-versions")
    return client, blobs


def incoming(exported, tmp_path):
    destination = tmp_path / "incoming.zip"
    package(exported[1], destination)
    return destination


def staged(receiver, archive, **kwargs):
    return imports.prepare(
        receiver[0].journal.path,
        archive,
        target_list_id="receiver-list",
        paper_mapping={"local-paper": "receiver-paper"},
        **kwargs,
    )


def test_import_uses_receiver_identities_exact_retry_and_roundtrip_reexport(
    exported,
    receiver,
    tmp_path,
):
    client, blobs = receiver
    archive = incoming(exported, tmp_path)
    before = dump(client)
    value = staged(receiver, archive)
    assert value.preview()["state"] == "prepared" and dump(client) == before
    assert value.preview()["decision"] == "add"
    first = imports.publish(value)
    assert first["state"] == "imported"
    operation = first["operation"]
    binding = operation["payload"]["source_bindings"][0]
    assert operation["workspace_id"] == "receiver-workspace" and operation["device_id"] == "laptop"
    assert operation["payload"]["list_id"] == "receiver-list"
    sender = json.loads(exported[1].observed)["operation"]
    assert binding["paper_id"] != sender["payload"]["source_bindings"][0]["paper_id"]
    assert operation["operation_id"] != sender["operation_id"]
    with client.journal.transaction() as conn:
        assert (
            conn.execute(
                "SELECT local_id FROM research_paper_identity WHERE sync_id=?",
                (binding["paper_id"],),
            ).fetchone()[0]
            == "receiver-paper"
        )
        assert applied_file(conn, operation["entity_id"]) == operation
        count = conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0]
    assert imports.publish(value)["state"] == "unchanged"
    with client.journal.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0] == count
    body = validate_closure(
        operation["payload"],
        lambda row: blobs._path(BlobManifest(row["sha256"], row["size"])).read_bytes(),
    )
    assert body["report"] == exported[0][5].report
    outgoing = survey_packages.collect(client.journal.path, "receiver-list")
    assert outgoing.sources[0]["paper_id"] == "receiver-paper"
    target = tmp_path / "reexport.zip"
    manifest, tables = package(outgoing, target)
    # The helper defaults to the sender fixture's ID; use the actual outgoing owner.
    import zipfile

    manifest["list"]["id"] = "receiver-list"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr("manifest.json", json.dumps(manifest))
        zipped.writestr("tables.json", json.dumps(tables))
        for path, data in outgoing.files:
            zipped.writestr("files/" + path.as_posix(), data)
    with zipfile.ZipFile(target) as zipped:
        assert (
            survey_packages.validate_package(zipped, manifest, tables)["report"] == body["report"]
        )


def test_imported_report_reaches_independent_receiver_peer_without_source_identity_copy(
    exported,
    receiver,
    tmp_path,
):

    client, blobs = receiver
    result = imports.publish(staged(receiver, incoming(exported, tmp_path)))
    operation = result["operation"]
    server = ReferenceService(tmp_path / "authority.sqlite", blob_root=tmp_path / "remote-blobs")
    token = server.enroll("receiver-workspace", "laptop")
    files = FileTransfers(
        client,
        blobs,
        server,
        origin="https://fixture.invalid",
        token=token,
        version_root=tmp_path / "receiver-versions",
    )
    with client.journal.transaction() as conn:
        original = desired_file(conn, operation["payload"]["source_bindings"][0]["file_id"])
    drain(lambda: files.upload(original), "uploaded")
    client.sync_once(server, token, prepare_push=files.ready_to_push)
    drain(lambda: files.upload(operation), "uploaded")
    client.sync_once(server, token, prepare_push=files.ready_to_push)
    # A fresh peer belongs to the receiver workspace, never the source workspace.
    database = tmp_path / "peer.sqlite"
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript(store.SCHEMA)
    prepare(database, workspace_id="receiver-workspace", device_id="phone")
    peer = SyncClient(
        Journal(database, workspace_id="receiver-workspace", device_id="phone"), research_writer
    )
    peer = runtime(database=database)
    peer_token = server.enroll("receiver-workspace", "phone")
    peer_files = FileTransfers(
        peer,
        BlobStore(tmp_path / "peer-blobs"),
        server,
        origin="https://fixture.invalid",
        token=peer_token,
    )
    peer.sync_once(server, peer_token)
    drain(lambda: peer_files.download(operation["entity_id"]), "bound")
    with peer.journal.transaction() as conn:
        assert applied_file(conn, operation["entity_id"]) == operation
    assert not [item for item in peer.journal.pending() if item["device_id"] == "a"]


def test_caught_late_failure_and_cancellation_leave_no_partial_grants_or_report(
    exported,
    receiver,
    tmp_path,
    monkeypatch,
):
    client, _ = receiver
    value = staged(receiver, incoming(exported, tmp_path))
    before = dump(client)
    real = imports.sync_source_files.publish_source_in

    def fail(*args, **kwargs):
        real(*args, **kwargs)
        raise OSError("fixture interruption after original grant")

    monkeypatch.setattr(imports.sync_source_files, "publish_source_in", fail)
    with closing(generation._connect(client.journal.path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(OSError, match="interruption"):
            imports.publish_in(conn, value)
        assert desired_file(conn, list_file_id("receiver-list")) is None
    assert dump(client) == before
    monkeypatch.setattr(imports.sync_source_files, "publish_source_in", real)
    with closing(generation._connect(client.journal.path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="cancelled"):
            imports.publish_in(conn, value, cancelled=lambda: True)
        imports.publish_in(conn, value)
        conn.rollback()
    assert dump(client) == before
    assert imports.publish(value)["state"] == "imported"


def test_stale_receiver_or_archive_replacement_cannot_apply_prepared_result(
    exported, receiver, tmp_path
):
    client, _ = receiver
    archive = incoming(exported, tmp_path)
    value = staged(receiver, archive)
    client.save(
        client.new_graph_operation("list", "receiver-list", dict(name="New receiver name", note=""))
    )
    before = dump(client)
    with pytest.raises(ValueError, match="targets changed"):
        imports.publish(value)
    assert dump(client) == before
    fresh = staged(receiver, archive)
    archive.write_bytes(b"replaced selected archive")
    with pytest.raises(ValueError, match="package changed"):
        imports.publish(fresh)
    assert dump(client) == before


def test_unconfirmed_missing_duplicate_mapping_and_raw_data_create_no_receiver_writes(
    exported,
    receiver,
    tmp_path,
):
    client, _ = receiver
    archive = incoming(exported, tmp_path)
    before = dump(client)
    with pytest.raises(ValueError, match="complete distinct"):
        imports.prepare(
            client.journal.path, archive, target_list_id="receiver-list", paper_mapping={}
        )
    with pytest.raises(ValueError, match="active receiver paper"):
        imports.prepare(
            client.journal.path,
            archive,
            target_list_id="receiver-list",
            paper_mapping={"local-paper": "not-present"},
        )
    with pytest.raises(ValueError, match="checked receiver"):
        imports.publish(exported[1].record)
    assert dump(client) == before


def changed_package(exported, target):
    from paper_daily import survey_content
    from paper_daily.sync_files import canonical_json, descriptor, read_json

    def edit(_manifest, tables, files):
        row = tables["survey_reports"][0]
        body = read_json(files.pop(row["path"]))
        report = body["report"]
        for section in report["sections"]:
            for statement in section["statements"]:
                del statement["id"]
        report["sections"][0]["statements"][0]["text"] = "A new retained interpretation."
        body["report"] = survey_content.assemble(
            inputs=report["inputs"],
            generation=report["generation"],
            sources=report["sources"],
            sections=report["sections"],
        )
        raw = canonical_json(body)
        row.update(
            report_id=body["report"]["id"],
            path=survey_packages.relative("list", body["report"]["id"]).as_posix(),
            **descriptor(raw, "application/json"),
        )
        files[row["path"]] = raw

    package(exported[1], target, edit)
    return target


def test_default_preserves_existing_report_and_explicit_replacement_retains_old_version(
    exported,
    receiver,
    tmp_path,
):
    client, _ = receiver
    first = imports.publish(staged(receiver, incoming(exported, tmp_path)))
    newer = changed_package(exported, tmp_path / "newer.zip")
    keep = staged(receiver, newer)
    before = dump(client)
    assert keep.preview()["decision"] == "preserve"
    assert imports.publish(keep)["state"] == "preserved"
    assert dump(client) == before
    replace = staged(receiver, newer, replace=True)
    assert replace.preview()["decision"] == "replace"
    updated = imports.publish(replace)
    assert updated["state"] == "imported"
    assert updated["report_id"] != first["report_id"]
    with client.journal.transaction() as conn:
        assert desired_file(conn, list_file_id("receiver-list")) == updated["operation"]
        assert conn.execute(
            "SELECT operation FROM research_file_versions WHERE operation_id=?",
            (first["operation"]["operation_id"],),
        ).fetchone()


def test_reused_request_for_changed_content_and_foreign_receiver_cannot_write(
    exported,
    receiver,
    tmp_path,
):
    client, _ = receiver
    first = staged(receiver, incoming(exported, tmp_path), request_id="same-action")
    imports.publish(first)
    conflict = staged(
        receiver,
        changed_package(exported, tmp_path / "different.zip"),
        request_id="same-action",
        replace=True,
    )
    before = dump(client)
    with pytest.raises(ValueError, match="request no longer matches"):
        imports.publish(conflict)
    source_client = exported[0][0]
    source_before = dump(source_client)
    with closing(generation._connect(source_client.journal.path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="binding changed"):
            imports.publish_in(conn, first)
    assert dump(client) == before and dump(source_client) == source_before


def test_report_with_all_originals_unavailable_needs_no_invented_source_or_mapping(
    exported,
    receiver,
    tmp_path,
):
    import zipfile

    from paper_daily import survey_content
    from paper_daily.sync_files import canonical_json, descriptor, read_json

    def unavailable(manifest, tables, files):
        row = tables["survey_reports"][0]
        body = read_json(files.pop(row["path"]))
        report = body["report"]
        for source in report["sources"]:
            source["state"] = "unavailable"
            source["page_count"] = None
        for section in report["sections"]:
            for item in section["statements"]:
                del item["id"]
                for passage in item["passages"]:
                    passage["location"] = None
        body["report"] = survey_content.assemble(
            inputs=report["inputs"],
            generation=report["generation"],
            sources=report["sources"],
            sections=report["sections"],
        )
        body["bindings"] = []
        for source in manifest.pop("survey_sources"):
            files.pop(source["path"])
        raw = canonical_json(body)
        row.update(
            report_id=body["report"]["id"],
            path=survey_packages.relative("list", body["report"]["id"]).as_posix(),
            **descriptor(raw, "application/json"),
        )
        files[row["path"]] = raw

    archive = tmp_path / "unavailable.zip"
    package(exported[1], archive, unavailable)
    with zipfile.ZipFile(archive) as zipped:
        manifest = json.loads(zipped.read("manifest.json"))
        tables = json.loads(zipped.read("tables.json"))
        assert (
            survey_packages.validate_package(zipped, manifest, tables)["report"]["sources"][0][
                "state"
            ]
            == "unavailable"
        )
    value = imports.prepare(
        receiver[0].journal.path, archive, target_list_id="receiver-list", paper_mapping={}
    )
    result = imports.publish(value)
    assert result["state"] == "imported" and result["operation"]["payload"]["source_bindings"] == []
    with receiver[0].journal.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM research_file_versions").fetchone()[0] == 1
