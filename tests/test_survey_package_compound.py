"""Whole-package survey import uses one root/source/report/receipt transaction."""

import json
import zipfile
from contextlib import closing
from dataclasses import replace

import pytest
from test_survey_package_import import changed_package
from test_survey_package_import import receiver as receiver
from test_survey_packages import exported as exported
from test_survey_packages import package
from test_survey_publication import dump
from test_survey_publication import prepared as prepared
from test_sync_capture import bound as bound

from paper_daily import bundle, store, survey_packages
from paper_daily import research_generation as generation
from paper_daily import survey_package_native as native
from paper_daily.package_import import PackageImporter, import_package
from paper_daily.sync_artifacts import applied_file
from paper_daily.sync_files import list_file_id
from paper_daily.workspace_service import Cancelled, Ticket


def archive(exported, tmp_path):
    target = tmp_path / "whole-survey.zip"

    def complete(manifest, tables, files):
        manifest["members"] = [
            dict(
                paper_id=row["id"], position=i, added_at="2026-11-16T00:00:00+00:00", citation=None
            )
            for i, row in enumerate(tables["papers"])
        ]
        manifest["pdfs"] = {}
        manifest["notes_included"] = True

    package(exported[1], target, complete)
    return target


def importer(receiver, tmp_path):
    root = tmp_path / "compound-data"
    root.mkdir(exist_ok=True)
    return PackageImporter(receiver[0].journal.path, root)


def test_shared_import_creates_new_roots_sources_report_and_one_durable_receipt(
    exported,
    receiver,
    tmp_path,
):
    path = archive(exported, tmp_path)
    owner = importer(receiver, tmp_path)
    before = dump(owner.client)
    staged = owner.prepare(path, allow_new_namespace=True)
    assert dump(owner.client) == before
    report = owner.apply(staged)
    assert report["survey_reports"] == 1 and report["survey_state"] == "imported"
    mapping = report["identity_mapping"]["local-paper"]
    with owner.client.journal.transaction() as conn:
        assert conn.execute("SELECT 1 FROM lists WHERE id=?", (report["list"],)).fetchone()
        assert conn.execute("SELECT 1 FROM papers WHERE id=?", (mapping["local_id"],)).fetchone()
        assert conn.execute(
            "SELECT 1 FROM list_papers WHERE list_id=? AND paper_id=?",
            (report["list"], mapping["local_id"]),
        ).fetchone()
        actual = applied_file(conn, list_file_id(report["list"]))
        assert actual["payload"]["source_bindings"][0]["paper_id"] == mapping["portable_id"]
        assert conn.execute("SELECT count(*) FROM package_import_receipts").fetchone()[0] == 1
    collected = survey_packages.collect(owner.database, report["list"])
    assert json.loads(collected.observed)["operation"] == actual
    assert collected.sources[0]["paper_id"] == mapping["local_id"]
    before = dump(owner.client)
    repeated = import_package(owner.database, owner.root, path, allow_new_namespace=True)
    assert repeated["replayed"] and repeated["identity_mapping"] == report["identity_mapping"]
    assert dump(owner.client) == before


@pytest.mark.parametrize("mode", ["failure", "cancel"])
def test_late_report_failure_or_cancel_rolls_back_new_roots_sources_outbox_and_receipt(
    exported,
    receiver,
    tmp_path,
    monkeypatch,
    mode,
):
    owner = importer(receiver, tmp_path)
    path = archive(exported, tmp_path)
    ticket = Ticket()
    value = owner.prepare(path, allow_new_namespace=True, ticket=ticket)
    before = dump(owner.client)
    original = owner.client.journal.apply_in
    reached = []

    def late(conn, operation, writer):
        result = original(conn, operation, writer)
        if operation["payload"].get("feature") == "survey":
            reached.append(operation)
            assert conn.execute("SELECT count(*) FROM lists").fetchone()[0] == 2
            assert operation["payload"]["source_bindings"]
            if mode == "failure":
                raise OSError("fixture: failure after actual report apply")
            ticket.cancel()
        return result

    with monkeypatch.context() as patch:
        patch.setattr(owner.client.journal, "apply_in", late)
        with pytest.raises(OSError if mode == "failure" else Cancelled):
            owner.apply(value, ticket=ticket)
    assert reached and dump(owner.client) == before
    retry = owner.apply(owner.prepare(path, allow_new_namespace=True))
    assert retry["survey_state"] == "imported"


def test_prepared_archive_and_validated_frame_cannot_be_substituted(
    exported,
    receiver,
    tmp_path,
):
    owner = importer(receiver, tmp_path)
    path = archive(exported, tmp_path)
    value = owner.prepare(path, allow_new_namespace=True)
    before = dump(owner.client)
    with pytest.raises(ValueError, match="validated archive frame"):
        native.checked(replace(value.survey, _json="{}"))
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="archive changed"):
        owner.apply(value)
    assert dump(owner.client) == before


def test_unsupported_local_only_receiver_refuses_before_research_or_file_writes(
    exported,
    tmp_path,
    monkeypatch,
):
    path = archive(exported, tmp_path)
    root = tmp_path / "local-only"
    root.mkdir()
    database = root / "research.sqlite"
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(bundle, "DATA_DIR", root)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    store.init_db()
    before = database.read_bytes()
    with pytest.raises(ValueError, match="enrolled receiver"):
        bundle.import_(path, pdfs=False)
    with closing(generation._connect(database)) as conn:
        assert conn.execute("SELECT count(*) FROM lists").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM papers").fetchone()[0] == 0
    assert database.read_bytes() == before and path.exists()
    assert not (root / "survey-reports").exists() and not (root / "survey-sources").exists()


def test_capability_and_list_owned_report_validation_precede_compound_writes(
    exported,
    receiver,
    tmp_path,
):
    path = archive(exported, tmp_path)
    with zipfile.ZipFile(path) as zipped:
        manifest, tables, owners = bundle._validated(zipped)
        assert owners[tables["survey_reports"][0]["path"]] is None
        assert owners[manifest["survey_sources"][0]["path"]] == "local-paper"
        files = {info.filename: zipped.read(info.filename) for info in zipped.infolist()}
    manifest["capabilities"] = []
    files["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as zipped:
        for name, raw in files.items():
            zipped.writestr(name, raw)
    owner = importer(receiver, tmp_path)
    before = dump(owner.client)
    with pytest.raises(ValueError, match="capability"):
        owner.prepare(path, allow_new_namespace=True)
    assert dump(owner.client) == before


def test_compound_existing_list_preserves_by_default_and_replaces_only_when_requested(
    exported,
    receiver,
    tmp_path,
):
    owner = importer(receiver, tmp_path)
    first = owner.apply(owner.prepare(archive(exported, tmp_path), allow_new_namespace=True))
    list_id = first["list"]
    mapping = {old: item["local_id"] for old, item in first["identity_mapping"].items()}
    path = changed_package(exported, tmp_path / "updated-whole.zip")
    with zipfile.ZipFile(path) as zipped:
        files = {info.filename: zipped.read(info.filename) for info in zipped.infolist()}
    manifest = json.loads(files["manifest.json"])
    manifest["members"] = [
        dict(paper_id=old, position=i, added_at="2026-11-16T00:00:00+00:00", citation=None)
        for i, old in enumerate(mapping)
    ]
    manifest["pdfs"] = {}
    files["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as zipped:
        for name, raw in files.items():
            zipped.writestr(name, raw)
    options = dict(target_list_id=list_id, paper_mapping=mapping, confirmed_mapping=True)
    with owner.client.journal.transaction() as conn:
        previous = applied_file(conn, list_file_id(list_id))
    value = owner.prepare(path, **options)
    assert value.preview()["survey_state"] == "preserved"
    result = owner.apply(value)
    assert result["survey_state"] == "preserved" and result["survey_reports"] == 0
    with owner.client.journal.transaction() as conn:
        assert applied_file(conn, list_file_id(list_id)) == previous
    value = owner.prepare(path, replace=True, **options)
    assert value.preview()["survey_state"] == "imported"
    result = owner.apply(value)
    assert result["survey_reports"] == 1
    with owner.client.journal.transaction() as conn:
        current = applied_file(conn, list_file_id(list_id))
        assert current["payload"] != previous["payload"]
        assert conn.execute(
            "SELECT 1 FROM research_file_versions WHERE operation_id=?", (previous["operation_id"],)
        ).fetchone()
    count = len(owner.client.journal.pending())
    assert owner.apply(owner.prepare(path, replace=True, **options))["replayed"]
    assert len(owner.client.journal.pending()) == count
