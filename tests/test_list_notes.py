"""Why a paper is on a list can be rewritten, and its #tags filter the list."""

import pytest
from PySide6.QtWidgets import QInputDialog
from test_queue_keys import page as _page

from paper_daily import lists, store
from paper_daily.desktop.queue_view import PAPER_ROLE, note_parts

page = _page


@pytest.fixture
def listed(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    with store.connect() as conn:
        store.upsert_papers(
            conn, [{"id": "p1", "title": "Paper 1", "venue": "MICCAI", "year": 2026, "source": "t"}]
        )
        conn.execute("INSERT INTO lists(id, name, created_at) VALUES ('list', 'Cataract', 'now')")
        conn.execute(
            "INSERT INTO list_papers(list_id, paper_id, position, citation, added_at) "
            "VALUES ('list', 'p1', 0, 'Paper 1', 'now')"
        )


def _citation():
    with store.connect() as conn:
        return conn.execute("SELECT citation FROM list_papers WHERE paper_id='p1'").fetchone()[0]


def test_a_note_is_rewritten_cleared_and_bounded(listed):
    assert lists.set_note("list", "p1", "  dataset for #gap  ") == "dataset for #gap"
    assert _citation() == "dataset for #gap"
    assert lists.set_note("list", "p1", "   ") is None and _citation() is None
    with pytest.raises(ValueError):
        lists.set_note("list", "p1", "x" * (lists.NOTE_LIMIT + 1))
    with pytest.raises(ValueError):
        lists.set_note("list", "missing", "why")
    assert _citation() is None


def test_tags_are_split_from_the_words_and_a_bare_title_says_nothing(page):
    _page_widget, win = page
    paper = win.papers[0]
    paper.reason = "MICCAI sweep #venue #dataset-gap  centres?"
    assert note_parts(paper) == (["venue", "dataset-gap"], "MICCAI sweep centres?")
    paper.reason = "Paper 0"
    assert note_parts(paper) == ([], "")


def test_searching_a_tag_shows_only_the_papers_given_it(page):
    widget, win = page
    win.papers[1].reason = "#dataset-gap three centres"
    win.papers[3].reason = "#venue"
    widget.search.setText("#dataset-gap")
    widget.refresh()
    shown = [widget.model.index(r, 0).data(PAPER_ROLE).id for r in range(widget.model.rowCount())]
    assert shown == ["p1"]


def test_editing_from_the_row_menu_saves_and_redraws(page, listed, monkeypatch):
    widget, win = page
    win.active_list = "list"
    paper = win.papers[1]
    paper.id = "p1"
    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", lambda *a, **k: ("#venue keep for survey", True)
    )
    widget._edit_note(paper)
    assert paper.reason == "#venue keep for survey" == _citation()
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *a, **k: ("ignored", False))
    widget._edit_note(paper)
    assert _citation() == "#venue keep for survey"
