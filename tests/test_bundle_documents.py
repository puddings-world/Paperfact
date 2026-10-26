"""Shared bundles use exact managed PDF bytes without importing sync enrollment."""

import json
import sqlite3
import zipfile
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from test_document_reader import LOCAL, prepared, register
from test_sync_document_research import document, pdf_bytes
from test_sync_reading_state_research import LIST, save

from paper_daily import bundle, store


@pytest.fixture
def managed(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    path, journal, blobs, reader, alias, data = prepared(source)
    register(path, journal, blobs, reader)
    monkeypatch.setattr(store, "DB_PATH", path)
    monkeypatch.setattr(store, "ensure_dirs", lambda: None)
    monkeypatch.setattr(bundle, "DATA_DIR", source)
    monkeypatch.setattr(bundle, "PDF_DIR", reader.legacy_root)
    monkeypatch.setattr(bundle, "fetch", lambda *a, **k: pytest.fail("Unexpected publisher fetch"))
    alias.write_bytes(b"%PDF-Old alias must never be exported")
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO dives VALUES(?,?,?,?)", (LOCAL, "Deep explanation", "now", "v1"))
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at) VALUES(?,?,?)", (LOCAL, "My note", "now")
        )
    deck = source / "presentations" / bundle._digest(LOCAL)[:24]
    (deck / "assets").mkdir(parents=True)
    (deck / "guide.json").write_text('{"editable":"layout"}', encoding="utf-8")
    (deck / "assets" / "diagram.png").write_bytes(b"fixture image")
    legacy_figures = source / "figures" / bundle._safe_name(LOCAL)
    legacy_figures.mkdir(parents=True)
    (legacy_figures / "index.json").write_text("[]", encoding="utf-8")
    (source / "text").mkdir()
    (source / "text" / (bundle._safe_name(LOCAL) + ".txt")).write_text("Stale text")
    return SimpleNamespace(
        root=source, path=path, journal=journal, reader=reader, alias=alias, data=data
    )


def test_export_packs_verified_document_and_curated_deck_without_legacy_aliases(managed, tmp_path):
    made = bundle.export(LIST, tmp_path / "research.zip")
    assert made["pdf_packed"] == 1 and made["pdf_missing"] == []
    with zipfile.ZipFile(made["out"]) as archive:
        assert archive.read(f"files/pdf/{bundle._safe_name(LOCAL)}.pdf") == managed.data
        names = archive.namelist()
        assert any(name.endswith("/guide.json") for name in names)
        assert any(name.endswith("/assets/diagram.png") for name in names)
        assert not any(name.startswith(("files/figures/", "files/text/")) for name in names)
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["pdfs"][LOCAL]["sha256"] == bundle._sha256(managed.data)
        assert b"paperfact_sync_" not in archive.read("tables.json")
    assert managed.alias.read_bytes() == b"%PDF-Old alias must never be exported"


def test_managed_export_import_into_clean_colleague_workspace(managed, tmp_path, monkeypatch):
    made = bundle.export(LIST, tmp_path / "research.zip")
    receiver = tmp_path / "receiver"
    receiver.mkdir()
    monkeypatch.setattr(store, "DB_PATH", receiver / "papers.db")
    monkeypatch.setattr(bundle, "DATA_DIR", receiver)
    monkeypatch.setattr(bundle, "PDF_DIR", receiver / "pdf")
    report = bundle.import_(made["out"])
    assert report["pdf_ok"] == [LOCAL]
    assert (receiver / "pdf" / (bundle._safe_name(LOCAL) + ".pdf")).read_bytes() == managed.data
    with store.connect() as conn:
        assert conn.execute("SELECT body FROM dives").fetchone()[0] == "Deep explanation"
        assert conn.execute("SELECT body FROM notes").fetchone()[0] == "My note"
        assert conn.execute("SELECT state FROM list_papers").fetchone()[0] == "pending"
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE name='paperfact_sync_identity'"
        ).fetchone() is None
    assert bundle.import_(made["out"])["notes"] == 0


@pytest.mark.parametrize("state", ["detached", "missing", "unbound"])
def test_unavailable_managed_document_never_exports_or_downloads_legacy_alias(
    managed, tmp_path, state
):
    if state == "detached":
        save(managed.journal, document(managed.data, op_id="detach", action="delete"))
    elif state == "unbound":
        save(managed.journal, document(pdf_bytes("New pending document"), op_id="new-version"))
    else:
        with sqlite3.connect(managed.path) as conn:
            conn.execute("DELETE FROM research_document_applied")
    made = bundle.export(LIST, tmp_path / "research.zip")
    assert made["pdf_packed"] == 0 and made["pdf_missing"] == [LOCAL]
    got = bundle.fetch_pdfs(
        {LOCAL: {"sha256": bundle._sha256(managed.data), "bytes": len(managed.data),
                 "url": "https://example.invalid/no-fetch"}}, {}
    )
    assert got == {"pdf_ok": [], "pdf_needed": [LOCAL]}
    assert managed.alias.read_bytes() == b"%PDF-Old alias must never be exported"


def test_link_only_managed_export_keeps_hash_without_searching_public_url(managed, tmp_path):
    made = bundle.export(LIST, tmp_path / "links.zip", with_pdfs=False)
    assert made["pdf_packed"] == 0 and made["pdf_verified"] == 0
    with zipfile.ZipFile(made["out"]) as archive:
        record = json.loads(archive.read("manifest.json"))["pdfs"][LOCAL]
        assert record == {"sha256": bundle._sha256(managed.data), "bytes": len(managed.data),
                          "url": None}


def test_changed_target_during_export_preserves_prior_archive(managed, tmp_path, monkeypatch):
    output = tmp_path / "existing.zip"
    output.write_bytes(b"Previous completed export")
    validate = bundle._validated

    def change(archive):
        result = validate(archive)
        save(managed.journal, document(pdf_bytes("Next"), op_id="changed-during-export"))
        return result

    monkeypatch.setattr(bundle, "_validated", change)
    with pytest.raises(ValueError, match="changed"):
        bundle.export(LIST, output)
    assert output.read_bytes() == b"Previous completed export"
    assert not list(tmp_path.glob(".paperfact-export-*"))


def test_import_same_managed_pdf_keeps_owned_binding_and_legacy_alias(managed, tmp_path):
    made = bundle.export(LIST, tmp_path / "same.zip")
    report = bundle.import_(made["out"], replace=True)
    assert report["pdf_conflicts"] == [] and report["pdf_ok"] == [LOCAL]
    assert managed.alias.read_bytes() == b"%PDF-Old alias must never be exported"
    assert managed.reader.resolve(LOCAL).path.read_bytes() == managed.data


def test_import_cannot_replace_managed_pdf_with_bundle_alias(managed, tmp_path):
    made = bundle.export(LIST, tmp_path / "old.zip")
    save(managed.journal, document(pdf_bytes("Pending newer PDF"), op_id="new"))
    with store.connect() as conn:
        conn.execute("UPDATE dives SET body='Keep current analysis'")
    report = bundle.import_(made["out"], replace=True)
    assert report["pdf_conflicts"] == [LOCAL]
    with store.connect() as conn:
        assert conn.execute("SELECT body FROM dives").fetchone()[0] == "Keep current analysis"
    assert managed.alias.read_bytes() == b"%PDF-Old alias must never be exported"


def test_bundle_without_document_provenance_cannot_replace_managed_analysis(managed, tmp_path):
    source = bundle.export(LIST, tmp_path / "source.zip")["out"]
    old = tmp_path / "legacy-no-pdf.zip"
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(old, "w") as result:
        manifest = json.loads(archive.read("manifest.json"))
        manifest["pdfs"] = {}
        manifest["pdfs_included"] = False
        manifest["file_hashes"] = {
            key: value for key, value in manifest["file_hashes"].items()
            if not key.startswith("pdf/")
        }
        result.writestr("manifest.json", json.dumps(manifest))
        for name in archive.namelist():
            if name != "manifest.json" and not name.startswith("files/pdf/"):
                result.writestr(name, archive.read(name))
    with store.connect() as conn:
        conn.execute("UPDATE dives SET body='Current verified research'")
    report = bundle.import_(old, replace=True)
    assert report["pdf_conflicts"] == [LOCAL]
    with store.connect() as conn:
        assert conn.execute("SELECT body FROM dives").fetchone()[0] == "Current verified research"


def test_version_change_during_import_rolls_back_research_and_staged_files(
    managed, tmp_path, monkeypatch
):
    archive = bundle.export(LIST, tmp_path / "share.zip")["out"]
    with store.connect() as conn:
        conn.execute("UPDATE dives SET body='Keep newer text'")
    original_stage = bundle.bundle_files.stage

    @contextmanager
    def race(*args):
        with original_stage(*args) as staged:
            save(managed.journal, document(pdf_bytes("Next document"), op_id="during-import"))
            yield staged

    monkeypatch.setattr(bundle.bundle_files, "stage", race)
    with pytest.raises(ValueError, match="changed during import"):
        bundle.import_(archive, replace=True)
    with store.connect() as conn:
        assert conn.execute("SELECT body FROM dives").fetchone()[0] == "Keep newer text"
        assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 1
    assert managed.alias.read_bytes() == b"%PDF-Old alias must never be exported"


def test_imported_explicit_old_hash_cannot_jump_into_current_legacy_pdf(
    managed, tmp_path, monkeypatch
):
    from paper_daily.desktop.document_flow import anchor_allowed
    from paper_daily.document_reader import from_workspace

    anchor = {"p0": 0, "o0": 0, "p1": 0, "o1": 3, "document_hash": "b" * 64}
    with store.connect() as conn:
        conn.execute("UPDATE notes SET page=1,anchor=?", (json.dumps(anchor),))
    archive = bundle.export(LIST, tmp_path / "anchored.zip")["out"]
    receiver = tmp_path / "receiver"
    receiver.mkdir()
    monkeypatch.setattr(store, "DB_PATH", receiver / "papers.db")
    monkeypatch.setattr(bundle, "DATA_DIR", receiver)
    monkeypatch.setattr(bundle, "PDF_DIR", receiver / "pdf")
    bundle.import_(archive)
    resolver = from_workspace(store.DB_PATH, legacy_root=bundle.PDF_DIR)
    loaded = resolver.resolve(LOCAL)
    reader = SimpleNamespace(
        paper=SimpleNamespace(id=LOCAL, _document_reader=resolver,
                              _document_status=resolver.inspect(LOCAL)),
        _pdf_fingerprint=loaded.sha256,
    )
    with store.connect() as conn:
        imported = json.loads(conn.execute("SELECT anchor FROM notes").fetchone()[0])
    assert not anchor_allowed(reader, imported)
    assert anchor_allowed(reader, {**imported, "document_hash": loaded.sha256})
    assert anchor_allowed(reader, {key: value for key, value in imported.items()
                                   if key != "document_hash"})


def collision_bundle(path, ids):
    data = pdf_bytes("Incoming PDF")
    filename = "pdf/" + bundle._safe_name(ids[0]) + ".pdf"
    manifest = {
        "format": 1, "list": {"id": "incoming", "name": "Incoming", "created_at": "now"},
        "members": [{"paper_id": pid, "position": i, "added_at": "now"}
                    for i, pid in enumerate(ids)],
        "pdfs": {ids[0]: {"sha256": bundle._sha256(data), "bytes": len(data), "url": None}},
        "pdfs_included": True, "file_hashes": {filename: bundle._sha256(data)},
    }
    papers = [{"id": pid, "title": "Incoming", "title_key": "incoming", "venue": "",
               "year": 2026, "source": "fixture"} for pid in ids]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("tables.json", json.dumps({"papers": papers}))
        archive.writestr("files/" + filename, data)
    return path


@pytest.mark.parametrize("incoming,existing", [("a:b", "a_b"), ("Paper-A", "paper-a")])
def test_incoming_alias_collision_cannot_replace_another_papers_file(
    managed, tmp_path, incoming, existing
):
    with store.connect() as conn:
        store.upsert_papers(conn, [{"id": existing, "title": "Keep", "venue": "",
                                    "year": 2026, "source": "fixture"}])
    existing_file = bundle.PDF_DIR / (bundle._safe_name(existing) + ".pdf")
    existing_file.write_bytes(b"Owned by the original paper")
    archive = collision_bundle(tmp_path / "collision.zip", [incoming])
    with pytest.raises(ValueError, match="alias"):
        bundle.inspect(archive)
    with pytest.raises(ValueError, match="alias"):
        bundle.import_(archive, replace=True)
    assert existing_file.read_bytes() == b"Owned by the original paper"
    with store.connect() as conn:
        assert conn.execute("SELECT id FROM papers WHERE id=?", (incoming,)).fetchone() is None


@pytest.mark.parametrize("ids", [["a:b", "a_b"], ["Paper-A", "paper-a"]])
def test_two_incoming_papers_cannot_claim_one_portable_filename(managed, tmp_path, ids):
    archive = collision_bundle(tmp_path / "ambiguous.zip", ids)
    with pytest.raises(ValueError):
        bundle.import_(archive, replace=True)
    with store.connect() as conn:
        assert conn.execute("SELECT id FROM lists WHERE id='incoming'").fetchone() is None
