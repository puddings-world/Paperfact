"""A PDF pane closes without tripping over its own documents."""

import sys

import pymupdf
import shiboken6
from PySide6.QtWidgets import QApplication

from paper_daily.desktop import pdfpane


def test_destroying_a_pane_with_a_loaded_pdf_raises_nothing(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "paper.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40, 50), "A loaded paper")
        pdf.save(path)
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: errors.append(exc[1]))
    pane = pdfpane.make_pdf_pane()
    changes = []
    pane.source_changed.connect(lambda: changes.append(1))
    assert pane.load(path)
    assert changes
    shiboken6.delete(pane)
    app.processEvents()
    assert errors == []
