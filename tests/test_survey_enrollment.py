"""First enrollment retains local surveys/history with fresh native source grants."""

import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from test_survey_package_compound import archive
from test_survey_package_import import changed_package
from test_survey_package_local import local as local
from test_survey_packages import exported as exported
from test_survey_publication import prepared as prepared
from test_sync_capture import bound as bound
from test_sync_files import drain

from paper_daily import bundle, source_snapshots, survey_enrollment, survey_local, survey_reader
from paper_daily import research_generation as generation
from paper_daily.sync_artifacts import desired_file, paths, register_paths
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_client import SyncClient
from paper_daily.sync_deck_publication import runtime
from paper_daily.sync_file_transfers import FileTransfers
from paper_daily.sync_files import list_file_id
from paper_daily.sync_journal import Journal
from paper_daily.sync_research import prepare as prepare_adapter
from paper_daily.sync_research import (
    research_order_writer,
    research_projection_writer,
    research_writer,
)
from paper_daily.sync_service import ReferenceService
from paper_daily.workspace_enrollment import EnrollmentService
from paper_daily.workspace_service import Cancelled, Ticket


@pytest.fixture
def imported(exported, local, tmp_path):
    result = bundle.import_(archive(exported, tmp_path), pdfs=False)
    with closing(generation._connect(local[0])) as conn, conn:
        conn.execute("INSERT INTO kv VALUES('auth.secret','private-fixture')")
        conn.execute("INSERT INTO kv VALUES('ui.theme','dark')")
    with closing(generation._connect(local[0])) as conn:
        row = survey_local.current_in(conn, result["list"])
    return local[0], result["list"], survey_local.validate_record(row), row


def prepare(database, tmp_path, **kwargs):
    return EnrollmentService(database).prepare(
        tmp_path / "candidate",
        backup_output=tmp_path / "backup.zip",
        request_id=str(uuid4()),
        **kwargs,
    )


def test_first_enrollment_creates_readable_report_with_fresh_pins_and_independent_peer(
    imported,
    tmp_path,
):
    database, list_id, previous, row = imported
    before = database.read_bytes()
    service = EnrollmentService(database)
    plan = service.plan()
    assert plan["supported"], plan["blockers"]
    assert plan["saved_survey_reports"] == 1 and plan["original_source_count"] == 1
    result = prepare(database, tmp_path)
    candidate = Path(result["database"])
    read = survey_reader.read(candidate, list_id)
    assert read.data["kind"] == "native" and read.data["report"] == previous["report"]
    assert database.read_bytes() == before
    client = runtime(database=candidate)
    with client.journal.transaction() as conn:
        report = desired_file(conn, list_file_id(list_id))
        original = desired_file(conn, report["payload"]["source_bindings"][0]["file_id"])
        store, version_root = paths(conn)
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_local_surveys'"
        ).fetchone()
        history = [
            json.loads(r[0])
            for r in conn.execute(
                "SELECT body_json FROM research_history_archive "
                "WHERE protocol='research_local_surveys'"
            )
        ]
        assert history == [row]
    pin = report["payload"]["source_bindings"][0]
    assert pin["paper_id"] != previous["bindings"][0]["paper_id"]
    assert pin["paper_incarnation"] != previous["bindings"][0]["parent_lifecycle"]
    assert report["parents"][0]["incarnation"] != previous["list_lifecycle"]
    assert all(
        "database_identity" not in json.dumps(op) and "private-fixture" not in json.dumps(op)
        for op in client.journal.pending()
    )
    assert survey_reader.inspect(read, 0, 0, 0)["quote"] == "A selected method"
    with zipfile.ZipFile(result["backup"]) as zipped:
        assert (
            zipped.read("objects/" + original["payload"]["slot"])
            == source_snapshots.source_path(
                database, previous["bindings"][0]["original"]
            ).read_bytes()
        )
    server = ReferenceService(tmp_path / "authority.sqlite", blob_root=tmp_path / "remote")
    token = server.enroll(result["workspace_id"], result["device_id"])
    files = FileTransfers(
        client,
        store,
        server,
        origin="https://fixture.invalid",
        token=token,
        version_root=version_root,
    )
    drain(lambda: files.upload(original), "uploaded")
    client.sync_once(server, token, prepare_push=files.ready_to_push)
    drain(lambda: files.upload(report), "uploaded")
    client.sync_once(server, token, prepare_push=files.ready_to_push)
    peer_db = tmp_path / "peer.sqlite"
    from paper_daily import store as research_store

    with closing(sqlite3.connect(peer_db)) as conn:
        conn.executescript(research_store.SCHEMA)
        research_store._migrate(conn)
    prepare_adapter(peer_db, workspace_id=result["workspace_id"], device_id="peer")
    peer = SyncClient(
        Journal(peer_db, workspace_id=result["workspace_id"], device_id="peer"),
        research_writer,
        order_writer=research_order_writer,
        projection_writer=research_projection_writer,
    )
    peer_token = server.enroll(result["workspace_id"], "peer")
    peer_store = BlobStore(tmp_path / "peer-blobs")
    peer_root = tmp_path / "peer-versions"
    with peer.journal.transaction() as conn:
        register_paths(conn, result["workspace_id"], peer_store, peer_root)
    peer.sync_once(server, peer_token)
    transfer = FileTransfers(
        peer,
        peer_store,
        server,
        origin="https://fixture.invalid",
        token=peer_token,
        version_root=peer_root,
    )
    drain(lambda: transfer.download(original["entity_id"]), "bound")
    drain(lambda: transfer.download(report["entity_id"]), "bound")
    peer_read = survey_reader.read(peer_db, list_id)
    assert peer_read.data["report"] == previous["report"]
    assert survey_reader.inspect(peer_read, 0, 0, 0)["document_hash"] == pin["document_hash"]
    assert database.read_bytes() == before


def test_multiple_local_versions_archive_distinctly_and_only_current_report_is_enrolled(
    imported,
    exported,
    tmp_path,
):
    database, list_id, previous, _row = imported
    changed = changed_package(exported, tmp_path / "changed.zip")
    with zipfile.ZipFile(changed) as zipped:
        files = {i.filename: zipped.read(i.filename) for i in zipped.infolist()}
    manifest = json.loads(files["manifest.json"])
    manifest.update(
        members=[
            dict(
                paper_id="local-paper",
                position=0,
                added_at="2026-11-16T00:00:00+00:00",
                citation=None,
            )
        ],
        pdfs={},
    )
    files["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(changed, "w") as zipped:
        for name, raw in files.items():
            zipped.writestr(name, raw)
    assert bundle.import_(changed, replace=True, pdfs=False)["survey_state"] == "imported"
    plan = EnrollmentService(database).plan()
    assert plan["supported"] and plan["saved_survey_reports"] == 1
    assert plan["archived_history_by_protocol"]["research_local_surveys"] == 2
    result = prepare(database, tmp_path)
    with closing(generation._connect(result["database"])) as conn:
        retained = [
            json.loads(r[0])
            for r in conn.execute(
                "SELECT body_json FROM research_history_archive "
                "WHERE protocol='research_local_surveys'"
            )
        ]
    assert len(retained) == 2 and len({r["version_id"] for r in retained}) == 2
    assert previous["report"]["id"] in {
        survey_local.validate_record(r)["report"]["id"] for r in retained
    }
    current = survey_reader.read(result["database"], list_id).data["report"]
    assert current["id"] != previous["report"]["id"]
    assert current["sections"][0]["statements"][0]["text"] == "A new retained interpretation."


@pytest.mark.parametrize("outcome", ["failure", "cancel"])
def test_failure_or_cancel_after_private_report_publication_exposes_no_partial_candidate(
    imported,
    tmp_path,
    monkeypatch,
    outcome,
):
    database, _list, _body, _row = imported
    before = database.read_bytes()
    ticket = Ticket()
    actual = survey_enrollment.publish

    def late(*args, **kwargs):
        result = actual(*args, **kwargs)
        assert result["survey_reports"] == 1
        if outcome == "failure":
            raise OSError("fixture after native report publication")
        ticket.cancel()
        ticket.check()

    with monkeypatch.context() as patch:
        patch.setattr(survey_enrollment, "publish", late)
        with pytest.raises(OSError if outcome == "failure" else Cancelled):
            prepare(database, tmp_path, ticket=ticket)
    assert database.read_bytes() == before
    assert not (tmp_path / "candidate").exists() and not (tmp_path / "backup.zip").exists()
    assert prepare(database, tmp_path)["saved_survey_reports"] == 1


def test_changed_or_unavailable_original_never_becomes_new_authority(imported, tmp_path):
    database, _list, body, _row = imported
    path = source_snapshots.source_path(database, body["bindings"][0]["original"])
    before = database.read_bytes()
    original = path.read_bytes()
    path.write_bytes(b"x" * len(original))
    with pytest.raises(ValueError):
        prepare(database, tmp_path)
    assert database.read_bytes() == before
    assert not (tmp_path / "candidate").exists() and not (tmp_path / "backup.zip").exists()
    path.write_bytes(original)
    assert EnrollmentService(database).plan()["saved_survey_reports"] == 1


def test_enrollment_refuses_foreign_workspace_and_unsealed_export(imported, exported):
    from paper_daily import survey_package_native

    database, _list_id, _body, _row = imported
    with closing(generation._connect(database)) as conn:
        captured = survey_enrollment.inventory(database, conn, Ticket())
    client = exported[0][0]
    before = client.journal.pending()
    with pytest.raises(ValueError, match="exact fresh request"):
        survey_enrollment.publish(
            client,
            exported[0][3].store,
            client.journal.path.parent / "unused",
            captured,
            request_id=str(uuid4()),
            ticket=Ticket(),
        )
    assert client.journal.pending() == before
    from paper_daily import survey_packages

    value = survey_packages.collect(database, _list_id)
    source = value.sources[0]
    raw = dict((p.as_posix(), data) for p, data in value.files)[source["path"]]
    with pytest.raises(ValueError, match="shared digest"):
        survey_package_native.from_export(value, shared_bytes={source["sha256"]: bytearray(raw)})
    with pytest.raises(ValueError, match="sealed native export"):
        survey_package_native.from_export({"report": _body["report"]})


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_enrollment_preview_lists_saved_reports_for_explicit_review(imported, language):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from paper_daily.desktop.enrollment_dialog import EnrollmentDialog

    app = QApplication.instance() or QApplication([])
    database, _list, _body, _row = imported
    plan = EnrollmentService(database).plan()
    view = EnrollmentDialog(database, language=language)
    try:
        view._show_coverage(plan, {})
        assert view.t["surveys"] + ": 1" in view.coverage.toPlainText()
        assert view.t["originals"] + ": 1" in view.coverage.toPlainText()
    finally:
        view.close()
        view.deleteLater()
        app.processEvents()


def test_missing_current_originals_stay_explicit_even_when_older_bytes_are_archived(
    imported,
    tmp_path,
):
    from paper_daily import survey_content, survey_packages
    from paper_daily.sync_files import canonical_json, descriptor, read_json

    database, list_id, previous, _row = imported
    original_package = tmp_path / "original-whole.zip"
    bundle.export(list_id, original_package)
    with zipfile.ZipFile(original_package) as zipped:
        files = {i.filename: zipped.read(i.filename) for i in zipped.infolist()}
    manifest, tables = json.loads(files["manifest.json"]), json.loads(files["tables.json"])
    record = tables["survey_reports"][0]
    portable = read_json(files.pop("files/" + record["path"]))
    old = portable["report"]
    for source in old["sources"]:
        source["state"], source["page_count"] = "unavailable", None
    for section in old["sections"]:
        for statement in section["statements"]:
            del statement["id"]
            for passage in statement["passages"]:
                passage["location"] = None
    portable["report"] = survey_content.assemble(
        inputs=old["inputs"],
        generation=old["generation"],
        sources=old["sources"],
        sections=old["sections"],
    )
    portable["bindings"] = []
    for item in manifest.pop("survey_sources"):
        files.pop("files/" + item["path"])
    raw = canonical_json(portable)
    record.update(
        report_id=portable["report"]["id"],
        path=survey_packages.relative(list_id, portable["report"]["id"]).as_posix(),
        **descriptor(raw, "application/json"),
    )
    files["files/" + record["path"]] = raw
    manifest["file_hashes"] = {
        name.removeprefix("files/"): hashlib.sha256(data).hexdigest()
        for name, data in files.items()
        if name.startswith("files/")
    }
    files["manifest.json"], files["tables.json"] = canonical_json(manifest), canonical_json(tables)
    package = tmp_path / "unavailable-whole.zip"
    with zipfile.ZipFile(package, "w") as zipped:
        for name, data in files.items():
            zipped.writestr(name, data)
    assert bundle.import_(package, replace=True, pdfs=False)["survey_state"] == "imported"
    plan = EnrollmentService(database).plan()
    assert plan["supported"] and plan["saved_survey_reports"] == 1
    assert plan["original_source_count"] == 0 and plan["archived_source_receipts"] == 1
    result = prepare(database, tmp_path)
    client = runtime(database=result["database"])
    with client.journal.transaction() as conn:
        native = desired_file(conn, list_file_id(list_id))
    assert native["payload"]["source_bindings"] == []
    assert not any(
        op["payload"].get("feature") == "original_source" for op in client.journal.pending()
    )
    saved = survey_reader.read(result["database"], list_id)
    assert saved.data["report"]["sources"][0]["state"] == "unavailable"
    assert saved.data["sources"] == []
    assert saved.data["report"]["id"] != previous["report"]["id"]
