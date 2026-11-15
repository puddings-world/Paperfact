"""Local-only list packages retain exact reports/PDFs and never enroll a device."""

import json
import sqlite3
import zipfile
from contextlib import closing

import pytest
from test_survey_package_compound import archive
from test_survey_package_import import changed_package
from test_survey_packages import exported as exported
from test_survey_publication import prepared as prepared
from test_sync_capture import bound as bound

from paper_daily import (
    bundle,
    source_snapshots,
    store,
    survey_local,
    survey_packages,
    sync_recovery,
)
from paper_daily import research_generation as generation
from paper_daily.sync_files import read_json


@pytest.fixture
def local(tmp_path, monkeypatch):
    root = tmp_path / "local"
    root.mkdir()
    database = root / "papers.db"
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(bundle, "DATA_DIR", root)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    store.init_db()
    return database, root


def rows(database):
    with closing(generation._connect(database)) as conn:
        result = {}
        for name in (
            "lists",
            "papers",
            "list_papers",
            survey_local.TABLE,
            "research_local_source_owners",
        ):
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone()
            result[name] = (
                [tuple(row) for row in conn.execute("SELECT * FROM " + name)] if exists else []
            )
        return result


def test_local_import_export_and_second_receiver_preserve_exact_report_and_originals(
    exported,
    local,
    tmp_path,
    monkeypatch,
):
    database, root = local
    result = bundle.import_(archive(exported, tmp_path), pdfs=False)
    with closing(generation._connect(database)) as conn:
        current = survey_local.current_in(conn, result["list"])
        body = survey_local.validate_record(current)
    original = body["bindings"][0]["original"]
    assert (
        source_snapshots.source_path(database, original).read_bytes()
        == dict((p.as_posix(), raw) for p, raw in exported[1].files)[exported[1].sources[0]["path"]]
    )
    before = rows(database)
    assert bundle.import_(archive(exported, tmp_path), pdfs=False)["survey_state"] == "unchanged"
    assert rows(database) == before
    out = tmp_path / "local-out.zip"
    bundle.export(result["list"], out)
    with zipfile.ZipFile(out) as zipped:
        manifest, tables, _owners = bundle._validated(zipped)
        value = survey_packages.validate_package(zipped, manifest, tables)
        assert value["report"] == body["report"] == exported[0][5].report
        assert (
            zipped.read("files/" + manifest["survey_sources"][0]["path"])
            == source_snapshots.source_path(database, original).read_bytes()
        )
    other = tmp_path / "second-local"
    other.mkdir()
    monkeypatch.setattr(store, "DB_PATH", other / "papers.db")
    monkeypatch.setattr(bundle, "DATA_DIR", other)
    monkeypatch.setattr(bundle, "PDF_DIR", other / "pdf")
    store.init_db()
    report = bundle.import_(out, pdfs=False)
    with closing(generation._connect(other / "papers.db")) as conn:
        second = survey_local.validate_record(survey_local.current_in(conn, report["list"]))
    assert second["report"] == body["report"]
    assert second["database_identity"] != body["database_identity"]
    assert second["bindings"][0]["original"] != original
    assert source_snapshots.source_path(
        other / "papers.db", second["bindings"][0]["original"]
    ).is_file()
    assert rows(database) == before and root.exists()


def test_failure_after_local_publication_rolls_back_roots_sources_and_report(
    exported,
    local,
    tmp_path,
    monkeypatch,
):
    database, _root = local
    path = archive(exported, tmp_path)
    before = rows(database)
    actual = survey_local.publish_in

    def fail(conn, staged, **options):
        result = actual(conn, staged, **options)
        assert result["state"] == "imported"
        raise OSError("fixture failure after report/source publication")

    with monkeypatch.context() as patch:
        patch.setattr(survey_local, "publish_in", fail)
        with pytest.raises(OSError, match="after report"):
            bundle.import_(path, pdfs=False)
    assert rows(database) == before
    assert bundle.import_(path, pdfs=False)["survey_state"] == "imported"


def test_original_tamper_and_parent_recreation_never_reexport_as_verified(
    exported,
    local,
    tmp_path,
):
    database, _root = local
    result = bundle.import_(archive(exported, tmp_path), pdfs=False)
    captured = survey_packages.collect(database, result["list"])
    with closing(generation._connect(database)) as conn:
        body = survey_local.validate_record(survey_local.current_in(conn, result["list"]))
    path = source_snapshots.source_path(database, body["bindings"][0]["original"])
    original = path.read_bytes()
    path.write_bytes(b"x" * len(original))
    with pytest.raises(ValueError):
        survey_packages.check_export(captured)
    out = tmp_path / "bad.zip"
    with pytest.raises(ValueError):
        bundle.export(result["list"], out)
    assert not out.exists()
    path.write_bytes(original)
    with closing(generation._connect(database)) as conn, conn:
        listing = tuple(
            conn.execute("SELECT * FROM lists WHERE id=?", (result["list"],)).fetchone()
        )
        conn.execute("DELETE FROM lists WHERE id=?", (result["list"],))
        conn.execute("INSERT INTO lists VALUES(?,?,?,?)", listing)
    with pytest.raises(ValueError, match="reattachment"):
        survey_packages.collect(database, result["list"])


def test_local_default_preserve_and_explicit_replace_retain_prior_report_versions(
    exported,
    local,
    tmp_path,
):
    database, _root = local
    result = bundle.import_(archive(exported, tmp_path), pdfs=False)
    with closing(generation._connect(database)) as conn:
        previous = survey_local.current_in(conn, result["list"])
    updated = changed_package(exported, tmp_path / "updated.zip")
    with zipfile.ZipFile(updated) as zipped:
        values = {i.filename: zipped.read(i.filename) for i in zipped.infolist()}
    manifest = json.loads(values["manifest.json"])
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
    values["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(updated, "w") as zipped:
        for name, raw in values.items():
            zipped.writestr(name, raw)
    assert bundle.import_(updated, pdfs=False)["survey_state"] == "preserved"
    with closing(generation._connect(database)) as conn:
        assert survey_local.current_in(conn, result["list"]) == previous
    assert bundle.import_(updated, replace=True, pdfs=False)["survey_state"] == "imported"
    with closing(generation._connect(database)) as conn:
        current = survey_local.current_in(conn, result["list"])
        assert current["version_id"] != previous["version_id"]
        assert (
            conn.execute(
                "SELECT is_current FROM research_local_surveys WHERE version_id=?",
                (previous["version_id"],),
            ).fetchone()[0]
            == 0
        )
        assert conn.execute("SELECT count(*) FROM research_local_surveys").fetchone()[0] == 2


def test_backup_keeps_local_report_and_originals_inactive_after_detached_restore(
    exported,
    local,
    tmp_path,
):
    database, root = local
    result = bundle.import_(archive(exported, tmp_path), pdfs=False)
    with closing(generation._connect(database)) as conn:
        body = survey_local.validate_record(survey_local.current_in(conn, result["list"]))
    backup = tmp_path / "local-backup.zip"
    sync_recovery.create(database, backup, legacy_root=root / "pdf")
    destination = tmp_path / "restored"
    sync_recovery.restore_detached(backup, destination)
    with closing(sqlite3.connect(destination / "papers.db")) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_local_surveys'"
        ).fetchone()
        retained = [
            json.loads(r[0])
            for r in conn.execute(
                "SELECT data FROM recovery_records WHERE table_name='research_local_surveys'"
            )
        ]
    assert (
        len(retained) == 1 and survey_local.validate_record(retained[0])["report"] == body["report"]
    )
    sha = body["bindings"][0]["original"]["sha256"]
    assert (destination / "objects" / sha).read_bytes() == source_snapshots.source_path(
        database, body["bindings"][0]["original"]
    ).read_bytes()
    assert source_snapshots.list_owned(destination / "papers.db") == []
    with pytest.raises(ValueError, match="Keep the original archive"):
        survey_packages.collect(destination / "papers.db", result["list"])
    with zipfile.ZipFile(backup) as zipped:
        assert (
            read_json(zipped.read("tables/research_local_surveys.jsonl").splitlines()[0])["list_id"]
            == result["list"]
        )


def test_public_native_export_imports_on_an_independent_local_only_receiver(
    exported,
    local,
    tmp_path,
    monkeypatch,
):
    client, _server, _token, _files, original_root, proposal = exported[0]
    out = tmp_path / "native-public.zip"
    with monkeypatch.context() as patch:
        patch.setattr(store, "DB_PATH", client.journal.path)
        patch.setattr(bundle, "DATA_DIR", client.journal.path.parent)
        patch.setattr(bundle, "PDF_DIR", original_root)
        bundle.export("list", out)
    result = bundle.import_(out, pdfs=False)
    with closing(generation._connect(local[0])) as conn:
        body = survey_local.validate_record(survey_local.current_in(conn, result["list"]))
        assert body["report"] == proposal.report
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_sync_binding'"
        ).fetchone()
    assert source_snapshots.source_path(local[0], body["bindings"][0]["original"]).is_file()


def test_local_export_budget_includes_all_paper_context_fields_and_metadata_only_is_explicit(
    exported,
    local,
    tmp_path,
    monkeypatch,
):
    database, _root = local
    result = bundle.import_(archive(exported, tmp_path), pdfs=False)
    with pytest.raises(ValueError, match="Include exact original"):
        survey_packages.collect(database, result["list"], with_pdfs=False)
    with closing(generation._connect(database)) as conn, conn:
        conn.execute("UPDATE papers SET pdf_url=? WHERE id='local-paper'", ("x" * 600,))
    monkeypatch.setattr(survey_packages, "MAX_METADATA", 512)
    with pytest.raises(ValueError, match="context exceeds"):
        survey_packages.collect(database, result["list"])


def test_final_export_rechecks_all_context_fields_and_rejects_raw_preparation(
    exported,
    local,
    tmp_path,
):
    database, _root = local
    result = bundle.import_(archive(exported, tmp_path), pdfs=False)
    value = survey_packages.collect(database, result["list"])
    with closing(generation._connect(database)) as conn, conn:
        conn.execute("UPDATE papers SET abstract='A later edit' WHERE id='local-paper'")
    with pytest.raises(ValueError, match="changed during export"):
        survey_packages.check_export(value)
    with pytest.raises(ValueError, match="staged receiver proof"):
        survey_local.checked({"report": exported[0][5].report})
