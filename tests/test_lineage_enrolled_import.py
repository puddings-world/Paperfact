"""Actual source-complete list package import into an existing native workspace."""

import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import pytest
from test_lineage_bundle_journey import shared as shared
from test_lineage_jobs import work
from test_package_import import enroll_capture
from test_research_lineage import corpus as corpus
from test_sync_files import codec as codec
from test_sync_files import pair as pair

from paper_daily import lineage_sets, package_import
from paper_daily.package_import import PackageImporter, import_package
from paper_daily.workspace_service import Cancelled, Ticket, WorkspaceChanged


@pytest.fixture
def native_shared(shared, tmp_path):
    archive, database, originals, rows = shared
    target = tmp_path / "native-dated-package.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(target, "w") as output:
        for name in source.namelist():
            data = source.read(name)
            if name == "manifest.json":
                manifest = json.loads(data)
                manifest["list"]["created_at"] = "2026-11-14T00:00:00+00:00"
                for member in manifest["members"]:
                    member["added_at"] = "2026-11-14T00:00:00+00:00"
                data = json.dumps(manifest).encode()
            output.writestr(name, data)
    return target, database, originals, rows


def test_source_complete_package_imports_into_native_workspace_without_ai(
    native_shared, pair, tmp_path
):
    archive, _unbound, originals, expected = native_shared
    assert (
        Path(package_import.__file__)
        .resolve()
        .is_relative_to(Path(__file__).resolve().parents[1] / "src")
    )
    client = pair[1]
    enroll_capture(client)
    importer = PackageImporter(client.journal.path, client.journal.path.parent)
    before = client.journal.pending()
    prepared = work(importer.prepare, archive, allow_new_namespace=True)
    assert client.journal.pending() == before
    receipt = work(importer.apply, prepared)
    assert receipt["lineage_reports"] == 1
    mapping = receipt["identity_mapping"]
    focal = mapping["focal"]["local_id"]
    saved = lineage_sets.saved(client.journal.path, focal)
    assert len(saved) == 1 and saved[0]["source_hash"] == expected[0]["source_hash"]
    assert (
        json.loads(saved[0]["body_json"])["report"]
        == json.loads(expected[0]["body_json"])["report"]
    )
    pending = client.journal.pending()
    science = [op for op in pending if op["payload"].get("feature") == "lineage"]
    assert len(science) == 1 and len(science[0]["source_dependencies"]) == len(originals) == 3
    from paper_daily.sync_source_files import resolved

    with closing(client.journal._connect()) as conn:
        for binding, source in zip(
            json.loads(saved[0]["body_json"])["bindings"],
            json.loads(saved[0]["body_json"])["report"]["sources"],
            strict=True,
        ):
            old = next(
                old
                for old, identity in mapping.items()
                if identity["local_id"] == binding["paper_id"]
            )
            portable = mapping[old]["portable_id"]
            assert resolved(conn, portable, source["document_hash"]).read_bytes() == originals[old]
    again = work(importer.apply, prepared)
    assert again["state"] == "previously_applied"
    assert client.journal.pending() == pending
    with closing(client.journal._connect()) as conn:
        marker = conn.execute(
            "SELECT operation_json,active FROM research_lineage_sync_sources"
        ).fetchall()
        assert len(marker) == 1 and marker[0][1] == 1
        assert json.loads(marker[0][0])["operation_id"] == science[0]["operation_id"]


def dump(client):
    with closing(client.journal._connect()) as conn:
        return tuple(conn.iterdump())


def receiver(pair):
    client = pair[1]
    enroll_capture(client)
    return client, PackageImporter(client.journal.path, client.journal.path.parent)


def test_cancelled_native_import_keeps_all_research_and_outbox(native_shared, pair):
    client, importer = receiver(pair)
    ticket = Ticket()
    prepared = work(importer.prepare, native_shared[0], allow_new_namespace=True, ticket=ticket)
    before = dump(client)
    ticket.cancel()
    with pytest.raises(Cancelled):
        work(importer.apply, prepared, ticket=ticket)
    assert dump(client) == before


def test_late_scientific_failure_rolls_back_sources_schema_and_receipt_then_reprepare_retries(
    native_shared,
    pair,
    monkeypatch,
):
    client, importer = receiver(pair)
    prepared = work(importer.prepare, native_shared[0], allow_new_namespace=True)
    before = dump(client)
    original = importer.client.writer
    written = []

    def fail(conn, operation):
        original(conn, operation)
        if operation["payload"].get("feature") == "lineage":
            written.append(True)
            assert conn.execute("SELECT count(*) FROM paper_lineage_sets").fetchone()[0] == 1
            raise RuntimeError("fixture late science write")

    monkeypatch.setattr(importer.client, "writer", fail)
    with pytest.raises(RuntimeError, match="fixture late science write"):
        work(importer.apply, prepared)
    assert written == [True]
    assert dump(client) == before
    monkeypatch.setattr(importer.client, "writer", original)
    retry = work(importer.prepare, native_shared[0], allow_new_namespace=True)
    receipt = work(importer.apply, retry)
    assert receipt["lineage_reports"] == 1
    assert (
        len([op for op in client.journal.pending() if op["payload"].get("feature") == "lineage"])
        == 1
    )


def test_workspace_switch_during_prepared_import_does_not_write_either_database(
    native_shared, pair
):
    client, importer = receiver(pair)
    current = [client.journal.path]
    importer.current_path = lambda: current[0]
    prepared = work(importer.prepare, native_shared[0], allow_new_namespace=True)
    before, other = dump(client), dump(pair[2])
    current[0] = pair[2].journal.path
    with pytest.raises(WorkspaceChanged):
        work(importer.apply, prepared)
    assert dump(client) == before and dump(pair[2]) == other


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_missing_or_damaged_exact_original_rejects_before_research_writes(
    native_shared, pair, tmp_path, damage
):
    client, importer = receiver(pair)
    archive = tmp_path / (damage + ".zip")
    with zipfile.ZipFile(native_shared[0]) as source, zipfile.ZipFile(archive, "w") as output:
        target = next(
            name for name in source.namelist() if name.startswith("files/lineage-sources/")
        )
        for name in source.namelist():
            if name == target and damage == "missing":
                continue
            output.writestr(name, b"damaged" if name == target else source.read(name))
    before = dump(client)
    with pytest.raises(ValueError):
        work(importer.prepare, archive, allow_new_namespace=True)
    assert dump(client) == before


def test_cancel_after_scientific_write_rolls_back_before_final_publication(
    native_shared, pair, monkeypatch
):
    client, importer = receiver(pair)
    ticket = Ticket()
    prepared = work(importer.prepare, native_shared[0], allow_new_namespace=True, ticket=ticket)
    before = dump(client)
    original = importer.client.writer
    written = []

    def cancel(conn, operation):
        original(conn, operation)
        if operation["payload"].get("feature") == "lineage":
            written.append(True)
            ticket.cancel()

    monkeypatch.setattr(importer.client, "writer", cancel)
    with pytest.raises(Cancelled):
        work(importer.apply, prepared, ticket=ticket)
    assert written == [True] and dump(client) == before


def test_actual_public_bundle_entry_imports_native_science_without_unbound_grants(
    native_shared, pair, monkeypatch
):
    from test_lineage_bundle_journey import select

    from paper_daily import bundle

    client, _importer = receiver(pair)
    select(monkeypatch, client.journal.path)
    result = work(bundle.import_, native_shared[0], pdfs=False)
    assert result["lineage_reports"] == 1
    assert (
        len(
            lineage_sets.saved(client.journal.path, result["identity_mapping"]["focal"]["local_id"])
        )
        == 1
    )
    with closing(client.journal._connect()) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_lineage_imports'"
        ).fetchone()


def test_late_scientific_row_arrival_is_not_overwritten_by_prepared_absence(native_shared, pair):
    from test_sync_files import LOCAL

    client, importer = receiver(pair)
    prepared = work(
        importer.prepare,
        native_shared[0],
        allow_new_namespace=True,
        paper_mapping={"focal": LOCAL},
        confirmed_mapping=True,
    )
    mapping = prepared.preview()["identity_mapping"]
    row = dict(native_shared[3][0])
    body = json.loads(row["body_json"])
    row["paper_id"] = LOCAL
    for binding in body["bindings"]:
        binding["paper_id"] = mapping[binding["paper_id"]]["local_id"]
    row["body_json"] = lineage_sets.canonical(body)
    with client.journal.transaction() as conn:
        conn.execute(lineage_sets.SCHEMA)
        conn.execute(
            "INSERT INTO paper_lineage_sets VALUES(?,?,?,?,?,?)",
            [row[k] for k in lineage_sets.COLUMNS.split()],
        )
    before = dump(client)
    with pytest.raises(ValueError, match="Lineage import targets changed"):
        work(importer.apply, prepared)
    assert dump(client) == before


def test_original_source_complete_import_syncs_to_peer_before_bytes_then_opens_all_three(
    native_shared,
    pair,
):
    from test_sync_files import drain

    from paper_daily import lineage_bound_originals
    from paper_daily import research_generation as generation
    from paper_daily.manual_highlight_ops import observe_owner
    from paper_daily.sync_client import SyncClient
    from paper_daily.sync_research import research_projection_writer

    client, importer = receiver(pair)
    prepared = work(importer.prepare, native_shared[0], allow_new_namespace=True)
    work(importer.apply, prepared)
    service, _client, peer, files, peer_files, token, peer_token = pair
    for operation in client.journal.pending():
        if operation["entity_type"] == "research_file":
            drain(lambda op=operation: files.upload(op), "uploaded")
    for _ in range(4):
        result = importer.client.sync_once(service, token, prepare_push=files.ready_to_push)
        if not result["pending"]:
            break
    assert result["pending"] == 0 and result["conflicts"] == 0
    enroll_capture(peer)
    receiving = SyncClient.attach_existing(
        peer.journal, peer.writer, projection_writer=research_projection_writer
    )
    receiving.sync_once(service, peer_token)
    with closing(peer.journal._connect()) as conn:
        saved = conn.execute("SELECT paper_id FROM paper_lineage_sets").fetchone()
        assert conn.execute("SELECT count(*) FROM research_file_applied").fetchone()[0] == 0
    row = lineage_sets.saved(peer.journal.path, saved[0])[0]
    owner = observe_owner(
        peer.journal.path, saved[0], expected_native=generation._identity(peer.journal.path)
    )
    source = json.loads(row["body_json"])["report"]["sources"][0]
    assert work(lineage_bound_originals.prepare, owner, row, source["id"]) is None
    original_rows = json.loads(native_shared[3][0]["body_json"])
    exact = {
        source["document_hash"]: native_shared[2][binding["paper_id"]]
        for binding, source in zip(
            original_rows["bindings"], original_rows["report"]["sources"], strict=True
        )
    }
    science = next(
        op for op in client.history() if op["operation"]["payload"].get("feature") == "lineage"
    )["operation"]
    for pin in science["source_dependencies"]:
        drain(lambda identity=pin["file_id"]: peer_files.download(identity), "bound")
    for source in json.loads(row["body_json"])["report"]["sources"]:
        proof = work(lineage_bound_originals.prepare, owner, row, source["id"])
        assert (
            lineage_bound_originals.for_delivery(proof, owner, row, source["id"])
            == exact[source["document_hash"]]
        )


def test_repeated_concurrent_package_activation_creates_one_native_scientific_action(
    native_shared, pair, monkeypatch
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    client, _importer = receiver(pair)
    admitted, release = threading.Event(), threading.Event()
    original = PackageImporter.prepare

    def held(self, *args, **kwargs):
        prepared = original(self, *args, **kwargs)
        admitted.set()
        assert release.wait(10)
        return prepared

    monkeypatch.setattr(PackageImporter, "prepare", held)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            import_package,
            client.journal.path,
            client.journal.path.parent,
            native_shared[0],
            allow_new_namespace=True,
        )
        try:
            assert admitted.wait(20)
            with pytest.raises(ValueError, match="already in progress"):
                import_package(
                    client.journal.path,
                    client.journal.path.parent,
                    native_shared[0],
                    allow_new_namespace=True,
                )
        finally:
            release.set()
        assert pending.result(timeout=10)["lineage_reports"] == 1
    assert (
        len([op for op in client.journal.pending() if op["payload"].get("feature") == "lineage"])
        == 1
    )


def updated_package(native_shared, target, *, change_science=False):
    with zipfile.ZipFile(native_shared[0]) as source, zipfile.ZipFile(target, "w") as output:
        for name in source.namelist():
            data = source.read(name)
            if name == "manifest.json":
                body = json.loads(data)
                body["list"]["name"] = "Reviewed incoming list"
                data = json.dumps(body).encode()
            if name == "tables.json" and change_science:
                body = json.loads(data)
                body["paper_lineage_sets"][0]["written_at"] = "2026-11-14T03:00:00+00:00"
                data = json.dumps(body).encode()
            output.writestr(name, data)
    return target


def mapping_options(receipt):
    return dict(
        target_list_id=receipt["list"],
        paper_mapping={
            old: value["local_id"] for old, value in receipt["identity_mapping"].items()
        },
        confirmed_mapping=True,
    )


@pytest.mark.parametrize("replace", [False, True])
def test_changed_native_report_requires_review_even_with_generic_replace(
    native_shared,
    pair,
    tmp_path,
    replace,
):
    client, importer = receiver(pair)
    first = work(importer.prepare, native_shared[0], allow_new_namespace=True)
    receipt = work(importer.apply, first)
    incoming = updated_package(native_shared, tmp_path / "changed-report.zip", change_science=True)
    before = dump(client)
    with pytest.raises(ValueError, match="Lineage replacement requires reviewed adoption"):
        work(importer.prepare, incoming, replace=replace, **mapping_options(receipt))
    assert dump(client) == before


def test_reused_science_target_is_rechecked_after_preview(native_shared, pair, tmp_path):
    client, importer = receiver(pair)
    first = work(importer.prepare, native_shared[0], allow_new_namespace=True)
    receipt = work(importer.apply, first)
    incoming = updated_package(native_shared, tmp_path / "same-science.zip")
    prepared = work(importer.prepare, incoming, **mapping_options(receipt))
    assert prepared.preview()["lineage_reports"] == 0 and prepared.preview()["lineage_reused"] == 1
    with client.journal.transaction() as conn:
        conn.execute("UPDATE paper_lineage_sets SET written_at='2026-11-14T04:00:00+00:00'")
    before = dump(client)
    with pytest.raises(ValueError, match="Lineage import targets changed"):
        work(importer.apply, prepared)
    assert dump(client) == before


def test_native_import_reexports_and_backups_preserve_all_science_and_exact_originals(
    native_shared,
    pair,
    tmp_path,
    monkeypatch,
):
    from test_lineage_bundle_journey import select

    from paper_daily import bundle, store, sync_recovery

    client, importer = receiver(pair)
    prepared = work(importer.prepare, native_shared[0], allow_new_namespace=True)
    receipt = work(importer.apply, prepared)
    local = receipt["identity_mapping"]["focal"]["local_id"]
    saved = lineage_sets.saved(client.journal.path, local)
    before = dump(client)
    select(monkeypatch, client.journal.path)
    exported = tmp_path / "native-reexport.zip"
    work(bundle.export, receipt["list"], exported)
    with zipfile.ZipFile(exported) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert len(manifest["lineage_sources"]) == 3
        expected = {
            source["document_hash"]
            for source in json.loads(saved[0]["body_json"])["report"]["sources"]
        }
        assert {source["sha256"] for source in manifest["lineage_sources"]} == expected
    backup = tmp_path / "native-import-backup.zip"
    manifest = sync_recovery.create(client.journal.path, backup, blob_store=pair[3].store)
    assert sync_recovery.inspect(backup) == manifest
    assert expected <= {blob["sha256"] for blob in manifest["blobs"]}
    restored = tmp_path / "detached-import"
    sync_recovery.restore_detached(backup, restored)
    assert lineage_sets.saved(restored / "papers.db", local) == saved
    with closing(sqlite3.connect(restored / "papers.db")) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='paperfact_sync_identity'"
        ).fetchone()
    assert dump(client) == before
    third = tmp_path / "third-researcher" / "papers.db"
    third.parent.mkdir()
    select(monkeypatch, third)
    store.init_db()
    result = work(bundle.import_, exported, pdfs=False)
    assert result["lineage_reports"] == 1
    assert lineage_sets.saved(third, local) == saved

    import hashlib

    from paper_daily import lineage_import_originals
    from paper_daily import research_generation as generation
    from paper_daily.manual_highlight_ops import observe_owner

    owner = observe_owner(third, local, expected_native=generation._identity(third))
    exact = {hashlib.sha256(data).hexdigest(): data for data in native_shared[2].values()}
    for source in json.loads(saved[0]["body_json"])["report"]["sources"]:
        proof = work(lineage_import_originals.prepare, owner, saved[0], source["id"])
        assert (
            lineage_import_originals.for_delivery(proof, owner, saved[0], source["id"])
            == exact[source["document_hash"]]
        )


def test_confirmed_mapping_cannot_collapse_two_selected_sources_into_one_receiver(
    native_shared, pair
):
    from test_sync_files import LOCAL

    client, importer = receiver(pair)
    before = dump(client)
    with pytest.raises(ValueError):
        work(
            importer.prepare,
            native_shared[0],
            allow_new_namespace=True,
            paper_mapping={"focal": LOCAL, "prior": LOCAL},
            confirmed_mapping=True,
        )
    assert dump(client) == before
