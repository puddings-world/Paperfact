"""The list overview: one card per list saying what it holds and how far it is read."""

import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from paper_daily import lists, llm, store
from paper_daily.desktop import list_overview
from paper_daily.desktop.main import MainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_the_summary_counts_lists_papers_and_reading():
    entries = [{"count": 4000, "read": 20}, {"count": 43, "read": 1}]
    assert list_overview.summary(entries) == "2 份清單 · 共 4,043 篇 · 已讀 21 篇"
    assert list_overview.summary([]) == "還沒有清單"


def test_a_card_names_only_what_the_list_has():
    bare = {"count": 3, "read": 0, "explained": 0, "pinned": 0}
    assert list_overview.card_facts(bare) == "3 篇 · 已讀 0"
    full = {"count": 43, "read": 2, "explained": 35, "pinned": 4}
    assert list_overview.card_facts(full) == "43 篇 · 已讀 2 · 已講解 35 · 置頂 4"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    store.init_db()
    yield app


def _window(monkeypatch):
    window = MainWindow()
    monkeypatch.setattr(window, "top_up_dives", lambda: None)
    window.show_lists()
    return window


def test_cards_carry_each_lists_counts(workspace, monkeypatch):
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                {"id": "p1", "title": "One", "venue": "MICCAI", "year": 2025, "source": "t"},
                {"id": "p2", "title": "Two", "venue": "MICCAI", "year": 2024, "source": "t"},
            ],
        )
        conn.executescript(
            """
            INSERT INTO lists(id, name, note, created_at)
                VALUES ('cat', 'Cataract', 'surgery', 'now');
            INSERT INTO list_papers(list_id, paper_id, position, state, added_at)
                VALUES ('cat', 'p1', 0, 'read', 'now'), ('cat', 'p2', 1, 'pending', 'now');
            INSERT INTO dives(paper_id, body, written_at) VALUES ('p1', 'dive', 'now');
            INSERT INTO pins(scope, paper_id, pinned_at) VALUES ('cat', 'p2', 'now');
            """
        )
        conn.commit()
    entry = lists.all_lists()[0]
    assert (entry["count"], entry["read"], entry["explained"], entry["pinned"]) == (2, 1, 1, 1)
    assert entry["note"] == "surgery"
    window = _window(monkeypatch)
    page = window.lists_page
    item = page.view.item(page.view.currentRow())
    assert item.data(list_overview.STATS_ROLE)["name"] == "Cataract"
    assert page.summary.text() == "1 份清單 · 共 2 篇 · 已讀 1 篇"
    assert not page.empty_card.isVisibleTo(page) and page.view.isVisibleTo(page)
    assert "Cataract" in page.selected_label.text()
    window.close()
    window.deleteLater()


def test_an_empty_workspace_shows_the_first_steps_instead_of_a_blank_list(
    workspace, monkeypatch
):
    window = _window(monkeypatch)
    page = window.lists_page
    assert page.empty_card.isVisibleTo(page) and "空的" in page.empty.text()
    assert not page.view.isVisibleTo(page) and not page.actions.isVisibleTo(page)
    assert page.create_button.isVisibleTo(page) and page.import_button.isVisibleTo(page)
    window.close()
    window.deleteLater()


def test_the_page_paints_every_card_without_error(workspace, monkeypatch):
    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id, name, created_at) VALUES ('a', 'Alpha', 'now')")
        conn.commit()
    window = _window(monkeypatch)
    window.resize(1280, 800)
    window.lists_page.grab()
    assert window.lists_page.view.item(0).data(Qt.ItemDataRole.UserRole) == "a"
    window.close()
    window.deleteLater()


def test_up_next_puts_pinned_papers_first_and_skips_read_ones(workspace):
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                {"id": f"p{i}", "title": f"Paper {i}", "venue": "MICCAI", "year": 2025,
                 "source": "t"}
                for i in range(4)
            ],
        )
        conn.executescript(
            """
            INSERT INTO lists(id, name, created_at) VALUES ('l', 'L', 'now');
            INSERT INTO list_papers(list_id, paper_id, position, state, added_at)
                VALUES ('l', 'p0', 0, 'read', 'now'), ('l', 'p1', 1, 'pending', 'now'),
                       ('l', 'p2', 2, 'pending', 'now'), ('l', 'p3', 3, 'pending', 'now');
            INSERT INTO pins(scope, paper_id, pinned_at) VALUES ('l', 'p3', 'now');
            """
        )
        conn.commit()
    got = lists.up_next("l", 2)
    assert [(p["id"], p["pinned"]) for p in got] == [("p3", True), ("p1", False)]
    pal = {"muted": "#555", "accent": "#00f"}
    shown = list_overview.up_next_html(got, pal)
    assert "置頂" in shown and shown.index("Paper 3") < shown.index("Paper 1")
    assert "讀完" in list_overview.up_next_html([], pal)
