"""Opening a marked paper cuts into words only the pages a mark is seen on."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from paper_daily.desktop import pdfpane  # noqa: E402

pytestmark = pytest.mark.skipif(not pdfpane.HAVE_QTPDF, reason="needs QtPdf")


@pytest.fixture
def pane(tmp_path):
    import pymupdf

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "paper.pdf"
    doc = pymupdf.open()
    for page in range(8):
        doc.new_page().insert_text((72, 72), f"Words on page {page} stand here")
    doc.save(path)
    from paper_daily.desktop.main import palette

    widget = pdfpane._QtPdfPane(palette=palette())
    widget.resize(700, 600)
    widget.show()
    assert widget.load(path)
    for _ in range(10):
        app.processEvents()
    yield app, widget
    widget.unload()
    widget.close()
    widget.deleteLater()
    app.processEvents()


def mark(ident, page, origin="ai"):
    return {"id": ident, "origin": origin,
            "anchor": {"p0": page, "o0": 0, "p1": page, "o1": 2}}


def test_marks_off_screen_are_not_cut_into_words_until_needed(pane):
    app, widget = pane
    selection = widget.selection
    selection.set_highlights([mark(1, 0), mark(2, 7)])
    assert selection._words == {}  # Nothing is cut up front.
    selection.grab()  # A paint: the first page is on screen, the last is not.
    app.processEvents()
    assert 0 in selection._words and 7 not in selection._words
    # Every mark is still there when something asks for all of them.
    assert [record["id"] for record, _words in selection._marks] == [1, 2]
    assert [w.text for w in selection._marks[1][1]] == ["Words", "on", "page"]


def test_a_selected_mark_is_found_on_its_own_page(pane):
    _app, widget = pane
    selection = widget.selection
    selection.set_highlights([mark(1, 0), mark(2, 7, "mine")])
    selection._selected = selection.words_on(7)[:1]
    assert selection.selected_highlights() == [2]
    assert 0 not in selection._words  # The other page was not needed for that.
