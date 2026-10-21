import json
import zipfile

import pytest
from test_bundle import _workspace
from test_bundle import sharer as _sharer

from paper_daily import bundle

sharer = _sharer


def _rewrite(source, target, change):
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(target, "w") as new:
        data = {name: old.read(name) for name in old.namelist()}
        change(data)
        for name, blob in data.items():
            new.writestr(name, blob)


def test_offline_export_import_contains_all_pdfs_and_saved_questions(sharer, monkeypatch):
    _made, tmp = sharer
    (bundle.DATA_DIR / "pdf").mkdir()
    pdf = b"%PDF original version"
    (bundle.PDF_DIR / "ref_a.pdf").write_bytes(pdf)
    questions = bundle.DATA_DIR / "research-questions" / (bundle._digest("ref:a") + ".json")
    questions.parent.mkdir()
    questions.write_text('{"items":[{"question":"why?"}]}')
    monkeypatch.setattr(
        bundle, "fetch", lambda *a, **k: pytest.fail("offline transfer used network")
    )
    made = bundle.export("cat", tmp / "offline.zip")
    assert made["pdf_packed"] == 1 and made["pdf_missing"] == ["ref:b"]
    root = tmp / "receiver"
    root.mkdir()
    conn = _workspace(root, monkeypatch)
    preview = bundle.inspect(made["out"])
    assert preview["pdfs"] == 1 and preview["papers"] == 2
    got = bundle.import_(made["out"])
    assert got["pdf_ok"] == ["ref:a"] and not got["pdf_needed"]
    assert (bundle.PDF_DIR / "ref_a.pdf").read_bytes() == pdf
    assert (root / "research-questions" / questions.name).exists()
    assert conn.execute("SELECT body FROM dives").fetchone()[0] == "sharer dive"
    assert not bundle.import_(made["out"])["joined_list"]


def test_different_pdf_keeps_local_version_and_does_not_attach_foreign_analysis(
    sharer, monkeypatch
):
    _made, tmp = sharer
    bundle.PDF_DIR.mkdir()
    (bundle.PDF_DIR / "ref_a.pdf").write_bytes(b"%PDF shared")
    made = bundle.export("cat", tmp / "withpdf.zip")
    root = tmp / "receiver"
    root.mkdir()
    conn = _workspace(root, monkeypatch)
    bundle.PDF_DIR.mkdir()
    path = bundle.PDF_DIR / "ref_a.pdf"
    path.write_bytes(b"%PDF my version")
    got = bundle.import_(made["out"])
    assert got["pdf_conflicts"] == ["ref:a"]
    assert path.read_bytes() == b"%PDF my version"
    assert conn.execute("SELECT count(*) FROM dives").fetchone()[0] == 0
    assert not (root / "text" / "ref_a.txt").exists()
    got = bundle.import_(made["out"], replace=True)
    assert not got["pdf_conflicts"] and path.read_bytes() == b"%PDF shared"
    assert conn.execute("SELECT body FROM dives").fetchone()[0] == "sharer dive"


@pytest.mark.parametrize("bad", ["files/llm.json", "files/../secret", "files/pdf/not-in-list.pdf"])
def test_unexpected_files_rejected_before_importing_rows(sharer, monkeypatch, bad):
    made, tmp = sharer
    path = tmp / "bad.zip"
    _rewrite(made["out"], path, lambda data: data.update({bad: b"bad"}))
    root = tmp / "receiver"
    root.mkdir()
    conn = _workspace(root, monkeypatch)
    with pytest.raises(ValueError):
        bundle.import_(path)
    assert conn.execute("SELECT count(*) FROM papers").fetchone()[0] == 0


def test_corrupt_content_is_rejected_before_any_rows_are_added(sharer, monkeypatch):
    made, tmp = sharer
    path = tmp / "corrupt.zip"
    _rewrite(made["out"], path, lambda data: data.update({"files/text/ref_a.txt": b"corrupted"}))
    root = tmp / "receiver"
    root.mkdir()
    conn = _workspace(root, monkeypatch)
    with pytest.raises(ValueError, match="核對失敗"):
        bundle.import_(path)
    assert conn.execute("SELECT count(*) FROM lists").fetchone()[0] == 0


def test_missing_packed_file_is_rejected_before_import(sharer, monkeypatch):
    made, tmp = sharer
    path = tmp / "incomplete.zip"
    _rewrite(made["out"], path, lambda data: data.pop("files/text/ref_a.txt"))
    root = tmp / "receiver"
    root.mkdir()
    conn = _workspace(root, monkeypatch)
    with pytest.raises(ValueError, match="缺少檔案"):
        bundle.import_(path)
    assert conn.execute("SELECT count(*) FROM lists").fetchone()[0] == 0


def test_private_notes_can_be_excluded_and_no_login_settings_are_exported(sharer):
    _made, tmp = sharer
    (bundle.DATA_DIR / "llm.json").write_text('{"api_key":"private"}')
    made = bundle.export("cat", tmp / "without-notes.zip", notes=False)
    with zipfile.ZipFile(made["out"]) as z:
        tables = json.loads(z.read("tables.json"))
        assert "notes" not in tables and "chat" not in tables
        assert not any("llm.json" in name for name in z.namelist())


def test_clean_workspace_roundtrip_preserves_research_rows_and_every_file(sharer, monkeypatch):
    _made, tmp = sharer
    bundle.PDF_DIR.mkdir()
    (bundle.PDF_DIR / "ref_a.pdf").write_bytes(b"%PDF original bytes and page order")
    for folder in ("research-questions", "material-positions", "reading-links"):
        path = bundle.DATA_DIR / folder / (bundle._digest("ref:a") + ".json")
        path.parent.mkdir(exist_ok=True)
        path.write_text('{"page":3,"text":"saved evidence"}', encoding="utf-8")
    original = bundle.export("cat", tmp / "original.zip")["out"]
    root = tmp / "clean-workspace"
    root.mkdir()
    conn = _workspace(root, monkeypatch)
    monkeypatch.setattr(bundle, "fetch", lambda *a, **k: pytest.fail("transfer needs network"))
    bundle.import_(original)
    copied = bundle.export("cat", tmp / "copied.zip")["out"]
    with zipfile.ZipFile(original) as before, zipfile.ZipFile(copied) as after:
        assert set(before.namelist()) == set(after.namelist())
        for name in before.namelist():
            if name.startswith("files/"):
                assert before.read(name) == after.read(name), name
        left, right = (json.loads(z.read("manifest.json")) for z in (before, after))
        for key in ("list", "members", "pdfs", "file_hashes", "counts"):
            assert left[key] == right[key], key
        left, right = (json.loads(z.read("tables.json")) for z in (before, after))
        assert left.keys() == right.keys()

        def ordered(rows):
            return sorted(json.dumps(r, sort_keys=True) for r in rows)

        for table in left:
            assert ordered(left[table]) == ordered(right[table]), table
    assert conn.execute("SELECT DISTINCT state FROM list_papers").fetchall() == [("pending",)]
