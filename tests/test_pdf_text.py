"""A PDF's page text is read once per version of the file, then shared."""

import pymupdf

from paper_daily import pdf_text


def write(path, words):
    doc = pymupdf.open()
    for word in words:
        doc.new_page().insert_text((72, 72), word)
    doc.save(path)


def test_the_same_file_is_read_once_and_a_changed_file_again(tmp_path, monkeypatch):
    path = tmp_path / "paper.pdf"
    write(path, ["Alpha", "Beta"])
    opened = []
    real = pymupdf.open
    monkeypatch.setattr(pymupdf, "open", lambda *a, **k: opened.append(a) or real(*a, **k))
    first = pdf_text.pages(path)
    assert [t.strip() for t in first] == ["Alpha", "Beta"]
    assert pdf_text.pages(path) == first and len(opened) == 1
    monkeypatch.setattr(pymupdf, "open", real)
    write(path, ["Gamma"])  # A replaced PDF is a new version, read afresh.
    assert [t.strip() for t in pdf_text.pages(path)] == ["Gamma"]
