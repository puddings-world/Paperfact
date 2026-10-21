"""A list and its analyses travel as one file, and never overwrite the receiver's work."""

from __future__ import annotations

import sqlite3
import zipfile

import pytest

from paper_daily import bundle, store


def _workspace(root, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", root / "papers.db")
    monkeypatch.setattr(bundle, "DATA_DIR", root)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    store.init_db()
    return sqlite3.connect(root / "papers.db")


@pytest.fixture
def sharer(tmp_path, monkeypatch):
    root = tmp_path / "sharer"
    root.mkdir()
    c = _workspace(root, monkeypatch)
    store.upsert_papers(
        c,
        [
            {"id": "ref:a", "title": "A", "venue": "MICCAI", "year": 2025, "source": "t"},
            {"id": "ref:b", "title": "B", "venue": "MICCAI", "year": 2024, "source": "t"},
            {"id": "iclr:x", "title": "X", "venue": "ICLR", "year": 2021, "source": "t"},
        ],
    )
    c.executescript(
        """
        INSERT INTO lists(id, name, created_at) VALUES ('cat', 'Cataract', 'now');
        INSERT INTO list_papers(list_id, paper_id, position, state, added_at, read_at)
            VALUES ('cat', 'ref:a', 0, 'read', 'now', 'yesterday'),
                   ('cat', 'ref:b', 1, 'pending', 'now', NULL);
        INSERT INTO dives(paper_id, body, written_at) VALUES ('ref:a', 'sharer dive', 'now');
        INSERT INTO close_readings(paper_id, body, written_at) VALUES ('ref:a', 'close', 'now');
        INSERT INTO list_surveys(list_id, body, papers, written_at)
            VALUES ('cat', 'survey', 2, 'now');
        INSERT INTO kv(key, value) VALUES ('citegraph.ref:a', '{}');
        INSERT INTO refs(paper_id, ref_paper_id, influential) VALUES ('ref:a', 'iclr:x', 1);
        INSERT INTO notes(paper_id, body, created_at) VALUES ('ref:a', 'a note', 'now');
        INSERT INTO chat(paper_id, role, body, created_at)
            VALUES ('ref:a', 'user', 'Q?', 'now'), ('ref:a', 'assistant', 'A.', 'now');
        """
    )
    c.commit()
    figures = root / "figures" / "ref_a"
    figures.mkdir(parents=True)
    (figures / "index.json").write_text("[]", encoding="utf-8")
    (root / "text").mkdir()
    (root / "text" / "ref_a.txt").write_text("full text", encoding="utf-8")
    deck = root / "presentations" / bundle._digest("ref:a")[:24]
    (deck / "history").mkdir(parents=True)
    (deck / "guide.json").write_text("{}", encoding="utf-8")
    (deck / "history" / "guide-old.json").write_text("{}", encoding="utf-8")
    out = bundle.export("cat", tmp_path / "cat.zip")
    return out, tmp_path


def test_a_bundle_carries_the_analyses_and_files_but_not_history(sharer):
    made, tmp = sharer
    assert made["papers"] == 2 and made["dives"] == 1 and made["chat"] == 2
    names = zipfile.ZipFile(made["out"]).namelist()
    assert "files/figures/ref_a/index.json" in names
    assert any(n.endswith("/guide.json") for n in names)
    assert not any("history" in n for n in names)


def test_import_into_an_empty_workspace_keeps_reading_state_behind(sharer, monkeypatch):
    made, tmp = sharer
    root = tmp / "colleague"
    root.mkdir()
    c = _workspace(root, monkeypatch)
    got = bundle.import_(made["out"])
    assert got["papers"] == 2 and got["dives"] == 1 and got["files"] == 3
    # The reference outside the list arrives with its paper, so the reference tab
    # and the citation map show what the sharer's do -- but it joins no list.
    assert got["refs"] == 1 and got["cited_papers"] == 1
    assert c.execute("SELECT count(*) FROM list_papers").fetchone()[0] == 2
    assert (root / "text" / "ref_a.txt").read_text(encoding="utf-8") == "full text"
    states = c.execute("SELECT DISTINCT state, read_at FROM list_papers").fetchall()
    assert states == [("pending", None)]
    assert c.execute("SELECT body FROM list_surveys").fetchone()[0] == "survey"
    assert (root / "figures" / "ref_a" / "index.json").exists()
    again = bundle.import_(made["out"])
    assert again["papers"] == 0 and again["chat"] == 0 and again["files"] == 0


def test_the_receivers_own_work_wins_unless_asked(sharer, monkeypatch):
    made, tmp = sharer
    root = tmp / "colleague"
    root.mkdir()
    c = _workspace(root, monkeypatch)
    store.upsert_papers(
        c, [{"id": "ref:a", "title": "A", "venue": "MICCAI", "year": 2025, "source": "t"}]
    )
    c.execute("INSERT INTO dives(paper_id, body, written_at) VALUES ('ref:a', 'mine', 'now')")
    c.execute(
        "INSERT INTO chat(paper_id, role, body, created_at) VALUES ('ref:a', 'user', 'my Q', 'n')"
    )
    c.commit()
    got = bundle.import_(made["out"])
    assert c.execute("SELECT body FROM dives WHERE paper_id='ref:a'").fetchone()[0] == "mine"
    # Their own conversation is not interleaved with the sharer's.
    assert got["chat"] == 0
    bundle.import_(made["out"], replace=True)
    assert c.execute("SELECT body FROM dives WHERE paper_id='ref:a'").fetchone()[0] == "sharer dive"


def test_a_path_outside_the_data_directory_is_refused(tmp_path, monkeypatch):
    root = tmp_path / "w"
    root.mkdir()
    _workspace(root, monkeypatch)
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr(
            "manifest.json",
            '{"format": 1, "list": {"id": "x", "name": "x", "created_at": "n"}, "members": []}',
        )
        z.writestr("tables.json", '{"papers": []}')
        z.writestr("files/../../outside.txt", "no")
    with pytest.raises(ValueError, match="escapes"):
        bundle.import_(evil)


def test_the_receiver_keeps_only_the_sharers_exact_pdf(sharer, monkeypatch):
    """Page numbers and figures in the analyses refer to one file; another version
    of the same paper is refused, and analyze is kept from fetching one."""
    made, tmp = sharer
    root = tmp / "colleague"
    root.mkdir()
    c = _workspace(root, monkeypatch)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    right, wrong = b"%PDF-the shared version", b"%PDF-an arXiv version"
    pdfs = {
        "ref:a": {"sha256": bundle._sha256(right), "bytes": len(right), "url": "https://ok"},
        "ref:b": {"sha256": bundle._sha256(right), "bytes": len(right), "url": "https://other"},
        "ref:c": {"sha256": bundle._sha256(right), "bytes": len(right), "url": None},
    }
    served = {"https://ok": right, "https://other": wrong}
    monkeypatch.setattr(bundle, "fetch", lambda url, **k: served[url])
    got = bundle.fetch_pdfs(pdfs, {})
    assert got == {"pdf_ok": ["ref:a"], "pdf_needed": ["ref:b", "ref:c"]}
    assert (root / "pdf" / "ref_a.pdf").read_bytes() == right
    assert not (root / "pdf" / "ref_b.pdf").exists()
    blocked = c.execute("SELECT key FROM kv WHERE key LIKE 'analyze.failed.pdf.%'").fetchall()
    assert sorted(k for (k,) in blocked) == ["analyze.failed.pdf.ref:b", "analyze.failed.pdf.ref:c"]


def test_the_sharer_records_which_url_serves_the_same_file(tmp_path, monkeypatch):
    root = tmp_path / "s"
    root.mkdir()
    c = _workspace(root, monkeypatch)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    (root / "pdf").mkdir()
    mine = b"%PDF-mine"
    (root / "pdf" / "ref_a.pdf").write_bytes(mine)
    store.upsert_papers(
        c,
        [
            {
                "id": "ref:a",
                "title": "A",
                "venue": "V",
                "year": 2025,
                "source": "t",
                "arxiv_id": "2501.00001",
                "pdf_url": "https://publisher/a.pdf",
            }
        ],
    )
    c.commit()
    seen = []

    def fake(url, **k):
        seen.append(url)
        return b"%PDF-arxiv" if "arxiv" in url else mine

    monkeypatch.setattr(bundle, "fetch", fake)
    reader = sqlite3.connect(root / "papers.db")
    reader.row_factory = sqlite3.Row
    paper = reader.execute("SELECT * FROM papers WHERE id='ref:a'").fetchone()
    rec = bundle.pdf_record(paper)
    assert rec["url"] == "https://publisher/a.pdf" and rec["sha256"] == bundle._sha256(mine)
    seen.clear()
    assert bundle.pdf_record(paper) == rec and seen == []  # cached until the file changes


def test_an_arxiv_paper_revised_since_is_found_at_its_version(tmp_path, monkeypatch):
    root = tmp_path / "s"
    root.mkdir()
    c = _workspace(root, monkeypatch)
    monkeypatch.setattr(bundle, "PDF_DIR", root / "pdf")
    (root / "pdf").mkdir()
    v1 = b"%PDF-v1"
    (root / "pdf" / "ref_a.pdf").write_bytes(v1)
    store.upsert_papers(
        c,
        [
            {
                "id": "ref:a",
                "title": "A",
                "venue": "V",
                "year": 2026,
                "source": "t",
                "arxiv_id": "2609.24619",
            }
        ],
    )
    c.commit()
    served = {
        "https://arxiv.org/pdf/2609.24619": b"%PDF-v2",
        "https://arxiv.org/pdf/2609.24619v1": v1,
    }

    def fake(url, **k):
        if url not in served:
            raise bundle.FetchError("404")
        return served[url]

    monkeypatch.setattr(bundle, "fetch", fake)
    reader = sqlite3.connect(root / "papers.db")
    reader.row_factory = sqlite3.Row
    paper = reader.execute("SELECT * FROM papers WHERE id='ref:a'").fetchone()
    assert bundle.pdf_record(paper)["url"] == "https://arxiv.org/pdf/2609.24619v1"


def test_the_lists_pinned_papers_and_order_travel_with_it(sharer, monkeypatch):
    made, tmp = sharer
    with sqlite3.connect(tmp / "sharer" / "papers.db") as c:
        c.execute("INSERT INTO pins(scope, paper_id, pinned_at) VALUES ('cat', 'ref:b', 'then')")
    pinned = bundle.export("cat", tmp / "pinned.zip")["out"]
    root = tmp / "colleague"
    root.mkdir()
    c = _workspace(root, monkeypatch)
    got = bundle.import_(pinned)
    assert got["pins"] == 1
    assert c.execute("SELECT scope, paper_id FROM pins").fetchall() == [("cat", "ref:b")]
    order = c.execute("SELECT paper_id FROM list_papers WHERE list_id='cat' ORDER BY position")
    assert [r[0] for r in order] == ["ref:a", "ref:b"]
    assert bundle.import_(pinned)["pins"] == 0
