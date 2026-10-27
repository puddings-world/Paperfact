"""Kept notes open and close in place in the 筆記 tab."""

from types import SimpleNamespace

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from paper_daily.desktop import rich_html, rich_view
from paper_daily.desktop.main import ReaderPage, palette


def _page():
    QApplication.instance() or QApplication([])
    pal = palette()
    rows = [
        {
            "id": 3,
            "kind": "ask",
            "body": "> Farabi跟Noor是指什麼\n\n兩間位於德黑蘭的**眼科醫院**。",
            "created_at": "2026-10-14T13:33:00",
            "page": None,
            "anchor": None,
        }
    ]
    page = SimpleNamespace(
        win=SimpleNamespace(pal=pal, data=SimpleNamespace(notes=lambda _pid: rows)),
        paper=SimpleNamespace(id="p1"),
        _open_notes=set(),
        note_log=rich_view.RichView(pal),
    )
    page._card = lambda row: ReaderPage._card(page, row)
    page._load_notes = lambda: ReaderPage._load_notes(page)
    return page


def test_clicking_a_note_opens_it_and_clicking_again_closes_it():
    page = _page()
    page._load_notes()
    assert "眼科醫院" not in page.note_log._body
    # The click used to raise before redrawing, so the note never opened.
    ReaderPage._note_action(page, QUrl("toggle:3"))
    assert "眼科醫院" in page.note_log._body and "收合" in page.note_log._body
    ReaderPage._note_action(page, QUrl("toggle:3"))
    assert "眼科醫院" not in page.note_log._body


def test_note_cards_span_the_column_in_the_typeset_view():
    # The page's generic table rule makes tables shrink to their content; a card
    # sized to its headline left ragged right edges down the list.
    page = rich_html.page('<table class="note-card"><tr><td>x</td></tr></table>', palette())
    assert "table.note-card { display:table; width:100%;" in page
    assert 'class="note-card"' in ReaderPage._card(_page(), _page().win.data.notes("p1")[0])
