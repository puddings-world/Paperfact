"""Which papers of a list have their PDF comes from one listing of the PDF folder.
Asking each paper in turn was a stat() per paper: half a second for a list of five
thousand, every time the list was shown."""

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paper_daily import store  # noqa: E402
from paper_daily.desktop import main as m  # noqa: E402


@pytest.fixture
def listed(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(m, "PDF_DIR", tmp_path / "pdf")
    store.init_db()
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                dict(id=pid, title=pid, venue="MICCAI", year=2025, source="test")
                for pid in ("ref:with", "ref:without", "arXiv/2401.1")
            ],
        )
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('l','A list','now')")
        for position, pid in enumerate(("ref:with", "ref:without", "arXiv/2401.1")):
            conn.execute(
                "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES (?,?,?,'now')",
                ("l", pid, position),
            )
    (tmp_path / "pdf").mkdir()
    (tmp_path / "pdf" / "ref_with.pdf").write_bytes(b"%PDF")
    (tmp_path / "pdf" / "arXiv_2401.1.pdf").write_bytes(b"%PDF")
    return tmp_path


def test_a_lists_pdfs_are_known_without_asking_each_paper(listed, monkeypatch):
    def no_stat(self):
        raise AssertionError(f"stat() of {self.name}")

    monkeypatch.setattr(Path, "exists", no_stat)
    papers = {p.id: p for p in m.Data().queue(list_id="l")}
    assert papers["ref:with"].has_pdf
    assert not papers["ref:without"].has_pdf
    assert papers["arXiv/2401.1"].has_pdf


def test_a_pdf_that_arrives_is_seen_on_the_next_reload(listed):
    assert not {p.id: p for p in m.Data().queue(list_id="l")}["ref:without"].has_pdf
    (listed / "pdf" / "ref_without.pdf").write_bytes(b"%PDF")
    assert {p.id: p for p in m.Data().queue(list_id="l")}["ref:without"].has_pdf


def test_no_pdf_folder_yet_means_no_pdfs(listed):
    for pdf in (listed / "pdf").iterdir():
        pdf.unlink()
    (listed / "pdf").rmdir()
    assert not any(p.has_pdf for p in m.Data().queue(list_id="l"))
