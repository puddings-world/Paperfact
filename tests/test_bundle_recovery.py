import sqlite3
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from test_bundle import _workspace
from test_bundle import sharer as _sharer

from paper_daily import bundle, bundle_files, research_service

sharer = _sharer


@pytest.mark.parametrize("existing", [False, True])
def test_file_failure_restores_database_and_files_then_retry_works(sharer, monkeypatch, existing):
    made, tmp = sharer
    root = tmp / "recipient"
    root.mkdir()
    db = _workspace(root, monkeypatch)
    if existing:
        research_service.import_bundle(made["out"])
        (root / "text/ref_a.txt").write_text("my exact original", encoding="utf-8")
        db.execute("UPDATE dives SET body='my existing analysis'")
        db.commit()
    before_db = list(db.iterdump())
    before_files = {
        p.relative_to(root): p.read_bytes()
        for p in root.rglob("*") if p.is_file() and not p.name.startswith("papers.db")
    }
    real_replace = bundle_files.os.replace
    calls = []

    def broken(source, target):
        if str(source).endswith(".new"):
            calls.append(str(target))
            if len(calls) == 2:
                raise OSError("fixture second file failure")
        return real_replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(bundle_files.os, "replace", broken)
        with pytest.raises(OSError, match="second file failure"):
            research_service.import_bundle(made["out"], replace=existing)
    assert list(db.iterdump()) == before_db
    after_files = {
        p.relative_to(root): p.read_bytes()
        for p in root.rglob("*") if p.is_file() and not p.name.startswith("papers.db")
    }
    assert after_files == before_files
    assert not list(root.glob(".bundle-import-*"))
    research_service.import_bundle(made["out"], replace=existing)
    assert (root / "text/ref_a.txt").read_text(encoding="utf-8") == "full text"
    assert db.execute("SELECT body FROM dives").fetchone()[0] == "sharer dive"


def test_database_failure_after_file_install_restores_files(sharer, monkeypatch):
    made, tmp = sharer
    root = tmp / "recipient"
    root.mkdir()
    db = _workspace(root, monkeypatch)
    original = bundle.connect

    @contextmanager
    def failing_commit():
        with original() as conn:
            yield conn
            raise sqlite3.OperationalError("fixture commit failure")

    monkeypatch.setattr(bundle, "connect", failing_commit)
    with pytest.raises(sqlite3.OperationalError, match="commit failure"):
        research_service.import_bundle(made["out"])
    assert db.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 0
    assert not (root / "text/ref_a.txt").exists()
    assert not list(root.glob(".bundle-import-*"))


def test_failed_export_preserves_previous_snapshot(sharer, monkeypatch):
    made, _tmp = sharer
    original = made["out"].read_bytes()

    def fail(*_args, **_kwargs):
        raise OSError("fixture disk full")

    monkeypatch.setattr(zipfile.ZipFile, "write", fail)
    with pytest.raises(OSError, match="disk full"):
        research_service.export_bundle("cat", made["out"])
    assert made["out"].read_bytes() == original
    assert not list(made["out"].parent.glob(".paperfact-export-*"))


def test_export_rejects_content_changed_while_packing(sharer, monkeypatch):
    made, _tmp = sharer
    before = made["out"].read_bytes()
    original = zipfile.ZipFile.write

    def change(self, filename, *args, **kwargs):
        if Path(filename).name == "ref_a.txt":
            Path(filename).write_text("changed during export", encoding="utf-8")
        return original(self, filename, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "write", change)
    with pytest.raises(ValueError, match="核對失敗"):
        research_service.export_bundle("cat", made["out"])
    assert made["out"].read_bytes() == before


def test_shared_service_lists_and_previews_without_ai(sharer, monkeypatch):
    made, _tmp = sharer
    from paper_daily import llm

    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("unexpected AI call"))
    assert research_service.list_collections() == [{"id": "cat", "name": "Cataract"}]
    result = research_service.inspect_bundle(made["out"])
    assert result["name"] == "Cataract" and result["papers"] == 2
