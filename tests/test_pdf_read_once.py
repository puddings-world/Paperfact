"""A PDF that has not changed is not read again for its hash or its text: each read
holds the interpreter, which stalls the window even from a worker thread."""

import os

import pytest

from paper_daily import materials, pdf_highlights

pymupdf = pytest.importorskip("pymupdf")


def _pdf(path, text):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def test_the_hash_follows_the_file(tmp_path):
    path = tmp_path / "a.pdf"
    _pdf(path, "first")
    first = pdf_highlights.document_hash(path)
    assert pdf_highlights.document_hash(path) == first
    _pdf(path, "second, longer")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
    assert pdf_highlights.document_hash(path) != first


def test_page_text_is_read_once_until_the_pdf_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(materials, "PDF_DIR", tmp_path)
    path = tmp_path / "ref_a.pdf"
    _pdf(path, "Old words")
    opened = []
    real_open = pymupdf.open
    monkeypatch.setattr(pymupdf, "open", lambda *a, **k: opened.append(1) or real_open(*a, **k))
    assert "Old words" in materials._pages("ref:a")[0][1]
    assert "Old words" in materials._pages("ref:a")[0][1]
    assert len(opened) == 1
    monkeypatch.setattr(pymupdf, "open", real_open)
    _pdf(path, "New words here")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
    assert "New words here" in materials._pages("ref:a")[0][1]
