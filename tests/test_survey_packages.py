"""Portable surveys preserve exact science/bytes and never transfer a native writer."""

import hashlib
import json
import zipfile
from copy import deepcopy

import pytest
from test_survey_publication import dump
from test_survey_publication import prepared as prepared
from test_sync_capture import bound as bound

from paper_daily import survey_content, survey_publication
from paper_daily import survey_packages as packages
from paper_daily.sync_files import canonical_json, descriptor, read_json


def package(value, destination, mutate=lambda _m, _t, _f: None):
    files = {path.as_posix(): data for path, data in value.files}
    tables = dict(papers=value.papers, cited_papers=[], survey_reports=[value.record])
    manifest = dict(
        format=2,
        list=dict(id="list", name="Research", created_at="fixture"),
        capabilities=[packages.CAPABILITY],
        pdfs_included=True,
        survey_sources=value.sources,
    )
    mutate(manifest, tables, files)
    manifest["file_hashes"] = {
        path: hashlib.sha256(data).hexdigest() for path, data in files.items()
    }
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("tables.json", json.dumps(tables))
        for path, data in files.items():
            archive.writestr("files/" + path, data)
    return manifest, tables


@pytest.fixture
def exported(prepared):
    client, _, _, _, _, proposal = prepared
    survey_publication.publish(survey_publication.prepare(proposal))
    before = dump(client)
    value = packages.collect(client.journal.path, "list")
    assert dump(client) == before
    return prepared, value


def test_real_native_report_and_original_roundtrip_is_content_only_and_read_only(
    exported, tmp_path
):
    native, value = exported
    client, _, _, _, root, proposal = native
    before = dump(client)
    target = tmp_path / "survey.zip"
    manifest, tables = package(value, target)
    with zipfile.ZipFile(target) as archive:
        body = packages.validate_package(archive, manifest, tables)
        assert body["report"] == proposal.report
        assert body["bindings"][0]["paper_id"] == "local-paper"
        source = manifest["survey_sources"][0]
        assert archive.read("files/" + source["path"]) == (root / "local-paper.pdf").read_bytes()
    encoded = canonical_json(body).decode()
    assert not any(
        key in encoded
        for key in (
            '"workspace_id"',
            '"device_id"',
            '"operation_id"',
            '"paper_incarnation"',
            '"db_path"',
        )
    )
    packages.check_export(value)
    assert dump(client) == before
    with pytest.raises(ValueError, match="sealed native"):
        packages.check_export(value.record)


def test_missing_wrong_owner_path_and_extra_archive_members_are_refused(exported, tmp_path):
    _, value = exported

    def omit(_m, _t, files):
        del files[value.sources[0]["path"]]

    def owner(manifest, _t, _files):
        manifest["survey_sources"][0]["paper_id"] = "another-owner"

    def path(manifest, _t, _files):
        manifest["survey_sources"][0]["path"] = "../private.pdf"

    def extra(_m, _t, files):
        files["survey-sources/unclaimed.pdf"] = b"unowned"

    def case_alias(_m, _t, files):
        files["SURVEY-SOURCES/unclaimed.pdf"] = b"unowned"

    for index, mutate in enumerate((omit, owner, path, extra, case_alias)):
        target = tmp_path / f"bad-{index}.zip"
        manifest, tables = package(value, target, mutate)
        with zipfile.ZipFile(target) as archive, pytest.raises(ValueError):
            packages.validate_package(archive, manifest, tables)


def test_rehashed_located_quote_must_still_match_actual_original(exported, tmp_path):
    _, value = exported

    def forge(_m, tables, files):
        record = tables["survey_reports"][0]
        body = read_json(files.pop(record["path"]))
        report = body["report"]
        sections = deepcopy(report["sections"])
        for section in sections:
            for item in section["statements"]:
                del item["id"]
        sections[0]["statements"][0]["passages"][0]["quote"] = "Never present in the original"
        body["report"] = survey_content.assemble(
            inputs=report["inputs"],
            generation=report["generation"],
            sources=report["sources"],
            sections=sections,
        )
        data = canonical_json(body)
        record.update(
            report_id=body["report"]["id"],
            path=packages.relative("list", body["report"]["id"]).as_posix(),
            **descriptor(data, "application/json"),
        )
        files[record["path"]] = data

    target = tmp_path / "rehashed.zip"
    manifest, tables = package(value, target, forge)
    with zipfile.ZipFile(target) as archive, pytest.raises(ValueError, match="located quote"):
        packages.validate_package(archive, manifest, tables)


def test_final_export_guard_rejects_changed_list_context_and_retains_old_bytes(exported):
    native, value = exported
    client = native[0]
    changed = client.new_graph_operation("list", "list", dict(name="Changed list", note=""))
    client.save(changed)
    with pytest.raises(ValueError, match="changed during export"):
        packages.check_export(value)
    assert dict(value.files)[packages.relative("list", native[5].report["id"])].startswith(b"{")


def test_cancel_budget_and_absent_owned_original_do_not_fall_back_to_legacy_alias(
    exported,
    monkeypatch,
):
    native, value = exported
    client = native[0]
    before = dump(client)
    with pytest.raises(ValueError, match="cancelled"):
        packages.collect(client.journal.path, "list", cancelled=lambda: True)
    with pytest.raises(ValueError, match="Include exact"):
        packages.collect(client.journal.path, "list", with_pdfs=False)
    original_limit = packages.MAX_PDF_BYTES
    monkeypatch.setattr(packages, "MAX_PDF_BYTES", 1)
    with pytest.raises(ValueError, match="aggregate"):
        packages.collect(client.journal.path, "list")
    monkeypatch.setattr(packages, "MAX_PDF_BYTES", original_limit)
    proof, operation = value._proofs[1]
    sha = json.loads(operation)["payload"]["slot"]
    original = proof.files[sha][0]
    renamed = original.with_name(original.name + ".held")
    original.rename(renamed)
    try:
        with pytest.raises((FileNotFoundError, ValueError)):
            packages.collect(client.journal.path, "list")
    finally:
        renamed.rename(original)
    assert dump(client) == before


def test_actual_metadata_private_fields_and_cancel_are_checked_without_import_grants(
    exported,
    tmp_path,
):
    native, value = exported
    target = tmp_path / "observed.zip"
    manifest, tables = package(value, target)
    before = dump(native[0])
    with zipfile.ZipFile(target) as archive:
        changed = deepcopy(manifest)
        changed["list"]["name"] = "Different admitted metadata"
        with pytest.raises(ValueError, match="admitted snapshot"):
            packages.validate_package(archive, changed, tables)
        with pytest.raises(ValueError, match="cancelled"):
            packages.validate_package(archive, manifest, tables, cancelled=lambda: True)

    def private(_m, tables, files):
        record = tables["survey_reports"][0]
        body = read_json(files[record["path"]])
        body["device_id"] = "sender"
        files[record["path"]] = canonical_json(body)
        record.update(**descriptor(files[record["path"]], "application/json"))

    manifest, tables = package(value, target, private)
    with zipfile.ZipFile(target) as archive, pytest.raises(ValueError):
        packages.validate_package(archive, manifest, tables)
    assert dump(native[0]) == before


def test_detached_restore_preserves_report_originals_and_local_bindings_without_sync_authority(
    exported,
    tmp_path,
):
    import sqlite3
    from contextlib import closing

    from paper_daily import source_snapshots, sync_recovery
    from paper_daily.sync_deck_publication import runtime

    native, value = exported
    client, _, _, _, root, proposal = native
    backup = tmp_path / "survey-backup.zip"
    sync_recovery.create(client.journal.path, backup, blob_store=native[3].store, legacy_root=root)
    destination = tmp_path / "detached-survey"
    sync_recovery.restore_detached(backup, destination)
    original_operation = json.loads(value.observed)["operation"]
    report_sha = original_operation["payload"]["body"]["sha256"]
    recovered = read_json((destination / "objects" / report_sha).read_bytes())
    assert recovered["report"] == proposal.report
    assert recovered["list_id"] == "list"
    source = value.sources[0]
    assert (destination / "objects" / source["sha256"]).read_bytes() == (
        root / "local-paper.pdf"
    ).read_bytes()
    assert runtime(database=destination / "papers.db") is None
    assert source_snapshots.list_owned(destination / "papers.db") == []
    with closing(sqlite3.connect(destination / "papers.db")) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name IN "
            "('research_file_applied','paperfact_sync_identity')"
        ).fetchone()
        retained = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_file_applied'"
            )
        ]
    recovered_operations = [json.loads(row["operation"]) for row in retained]
    assert original_operation in recovered_operations
    with closing(sqlite3.connect(destination / "papers.db")) as conn:
        mappings = [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_paper_identity'"
            )
        ]
    binding = original_operation["payload"]["source_bindings"][0]
    assert (
        dict((row["sync_id"], row["local_id"]) for row in mappings)[binding["paper_id"]]
        == "local-paper"
    )
    again = tmp_path / "detached-again.zip"
    # Preserve the maintained reviewed-recovery gate; do not invent a new writer
    # or discard the original archive merely to make detached re-export succeed.
    with pytest.raises(sync_recovery.RecoveryError, match="Keep the original archive"):
        sync_recovery.create(destination / "papers.db", again)
    assert not again.exists()
    with zipfile.ZipFile(backup) as archive:
        assert read_json(archive.read("objects/" + report_sha))["report"] == proposal.report
        assert (
            archive.read("objects/" + source["sha256"]) == (root / "local-paper.pdf").read_bytes()
        )
