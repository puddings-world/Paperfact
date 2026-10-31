"""Search all notes and highlights; [[Title]] links papers and shows backlinks."""

import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from paper_daily import notes_search, store
from paper_daily.desktop import main

ANCHOR = json.dumps({"p0": 4, "o0": 10, "p1": 4, "o1": 20})


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    with store.connect() as conn:
        for pid, title in (
            ("p1", "Sparse Attention"),
            ("p2", "Dense  Retrieval Revisited"),
            ("p3", "Twin"),
            ("p4", "twin"),
        ):
            conn.execute(
                "INSERT INTO papers(id,venue,year,title,title_key,source) "
                "VALUES (?,'ICLR',2024,?,?,'list')",
                (pid, title, pid),
            )
        conn.executemany(
            "INSERT INTO notes(paper_id,body,created_at,kind,page,anchor) VALUES (?,?,?,?,?,?)",
            [
                (
                    "p1",
                    "> local windows\n\n稀疏注意力 compares with [[dense retrieval revisited]]",
                    "2026-10-02",
                    "note",
                    5,
                    ANCHOR,
                ),
                (
                    "p1",
                    "Why 100% recall? see [[Twin]] and [[Unknown Paper]]",
                    "2026-10-01",
                    "ask",
                    None,
                    None,
                ),
                (
                    "p2",
                    "Back to [[Dense Retrieval Revisited]] itself",
                    "2026-10-03",
                    "note",
                    None,
                    None,
                ),
            ],
        )
        conn.execute(
            "INSERT INTO pdf_highlights(paper_id,document_hash,anchor,quote,created_at) "
            "VALUES ('p2','h',?,'retrieval with sparse windows','2026-10-04')",
            (ANCHOR,),
        )
        conn.commit()
    return tmp_path


def _search(query):
    with store.connect() as conn:
        return notes_search.search(conn, query)


def test_every_word_must_appear_across_notes_and_highlights(db):
    hits = _search("sparse windows")
    assert [(h["kind"], h["paper_id"]) for h in hits] == [("highlight", "p2")]
    assert hits[0]["page"] == 5 and hits[0]["anchor"] == ANCHOR
    [note] = _search("稀疏注意力")
    assert note["kind"] == "note" and note["title"] == "Sparse Attention"
    assert note["page"] == 5 and note["anchor"] == ANCHOR and "稀疏注意力" in note["snippet"]
    # % and _ are searched for literally, not as wildcards.
    assert [h["ask"] for h in _search("100%")] == [True]
    assert _search("1_0") == [] and _search("   ") == []


def test_links_resolve_on_the_whole_title_and_only_when_unambiguous(db):
    with store.connect() as conn:
        text = notes_search.linked(conn, "see [[dense retrieval revisited]], [[Twin]], [[Nope]]")
    assert text == "see [dense retrieval revisited](paper:p2), [[Twin]], [[Nope]]"


def test_a_paper_lists_the_notes_elsewhere_that_link_to_it(db):
    with store.connect() as conn:
        found = notes_search.backlinks(conn, "p2")
        assert notes_search.backlinks(conn, "p1") == []
    # Its own notes linking to itself are not backlinks.
    assert [(b["paper_id"], b["title"]) for b in found] == [("p1", "Sparse Attention")]
    assert "dense retrieval revisited" in found[0]["snippet"]


@pytest.fixture
def win(db):
    from paper_daily.desktop.main import MainWindow

    QApplication.instance() or QApplication([])
    window = MainWindow()
    yield window
    window.close()
    window.deleteLater()


def test_a_search_result_opens_its_paper_on_the_passage(win, monkeypatch):
    opened, revealed = [], []
    monkeypatch.setattr(win, "open_anywhere", lambda pid: opened.append(pid) or True)
    monkeypatch.setattr(win.reader_page, "reveal", lambda a, p: revealed.append((a, p)))
    dialog = win._search_notes()
    dialog.box.setText("稀疏")
    dialog.run()
    assert dialog.results.count() == 1 and "Sparse Attention" in dialog.results.item(0).text()
    dialog.box.returnPressed.emit()
    assert opened == ["p1"] and revealed == [(ANCHOR, 5)]

    dialog = win._search_notes()
    dialog.box.setText("nothing like this")
    dialog.run()
    assert dialog.results.count() == 0 and "沒有" in dialog.status.text()


def test_the_notes_tab_shows_backlinks_and_follows_title_links(win, monkeypatch):
    reader = win.reader_page
    reader.paper = SimpleNamespace(id="p2")
    links = main._backlinks_html(win.data.backlinks("p2"), win.pal)
    assert "連到這篇的筆記（1）" in links and 'href="paper:p1"' in links
    assert main._linked("[[Twin]]") == "[[Twin]]"
    assert "(paper:p2)" in main._linked("[[Dense Retrieval Revisited]]")

    opened = []
    monkeypatch.setattr(win, "open_anywhere", lambda pid: opened.append(pid) or False)
    reader._note_action(QUrl("paper:p1"))
    assert opened == ["p1"] and "無法開啟" in reader.note_status.text()
