"""The 引用 tab's 條列 / 引用圖 switch and its 參考文獻 / 後續研究 sides: made once per
paper and flipped, not rebuilt. Each flip used to reload the database and remake
every card, two to four seconds on a paper with 60 references and 120 later
works; as widgets, even made once, the cards held the window for a second."""

import os
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from paper_daily import citegraph, followups, store  # noqa: E402
from paper_daily.desktop import cites_pane, ui_state  # noqa: E402
from paper_daily.desktop.main import LIGHT  # noqa: E402

REFS = [
    {"ref_key": str(i), "title": f"Reference number {i} on matrix functions",
     "verdict": "值得" if i % 3 == 0 else "參考", "basis": "context",
     "purpose": "baseline", "contexts": [f"as shown in [{i}]"], "here": None}
    for i in range(40, 0, -1)
]
LATER = [
    {"title": f"Later work {i} building on it", "work_id": f"w{i}",
     "verdict": "值得" if i % 4 == 0 else "參考", "citations": i, "year": 2020 + i % 6,
     "relation": "extends it", "abstract": "x", "here": None}
    for i in range(25)
]
# Reference 3 is already in the library and waiting in the queue.
HERE = {"id": "ICLR:2024:ref3", "read": False}


def _graph(_conn, paper_id):
    nodes = [citegraph.Node(key="c", title="Centre paper", side="center")]
    nodes += [citegraph.Node(key=f"ref:{r['ref_key']}", title=r["title"], side="ref",
                             verdict=r["verdict"]) for r in REFS]
    nodes += [citegraph.Node(key=f"later:{r['work_id']}", title=r["title"], side="later",
                             verdict=r["verdict"]) for r in LATER]
    edges = [(n.key, "c") for n in nodes if n.side == "ref"]
    edges += [("c", n.key) for n in nodes if n.side == "later"]
    return citegraph.Graph(nodes=nodes, edges=edges, checked="2026-10-19")


class _Windows(QObject):
    """Every widget that opened as a window of its own."""

    def __init__(self):
        super().__init__()
        self.opened = []

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show and obj.isWidgetType() and obj.isWindow():
            self.opened.append(obj)
        return False


@pytest.fixture
def pane(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    with store.connect() as conn:
        store.upsert_papers(conn, [dict(id="p", title="Centre paper", venue="ICLR",
                                        year=2026, source="test")])
    loads = {"lists": 0, "graph": 0}

    def references(conn, pid):
        loads["lists"] += 1
        return [dict(r) for r in REFS]

    def graph(conn, pid):
        loads["graph"] += 1
        return _graph(conn, pid)

    def in_corpus(conn, doi, title, corpus_id):
        return dict(HERE) if title == "Reference number 3 on matrix functions" else None

    monkeypatch.setattr(followups, "references", references)
    monkeypatch.setattr(followups, "for_paper", lambda conn, pid: [dict(r) for r in LATER])
    monkeypatch.setattr(followups, "overview_for", lambda conn, pid: None)
    monkeypatch.setattr(followups, "checked", lambda conn, pid: "2026-10-19")
    monkeypatch.setattr(followups, "in_corpus", in_corpus)
    monkeypatch.setattr(citegraph, "build", graph)
    app = QApplication.instance() or QApplication([])
    opened, promoted = [], []
    window = SimpleNamespace(open_paper=opened.append, analysis_running=lambda pid=None: False,
                             waiting=set, promote=promoted.append,
                             active_list="my-list")
    windows = _Windows()
    app.installEventFilter(windows)
    widget = cites_pane.CitesPane(window, LIGHT)
    widget.resize(900, 700)
    widget.show()
    widget.load("p")
    QApplication.processEvents()
    widget.loads, widget.opened, widget.promoted, widget.windows = loads, opened, promoted, windows
    yield widget
    app.removeEventFilter(windows)


def _page(widget):
    return widget._list_view.view.toPlainText()


def _titles(widget, side):
    return [title for (kind, title), (s, _anchor) in widget._cards.items()
            if kind == "title" and s == side]


def test_every_work_is_on_the_page_once_and_flipping_never_reloads(pane):
    assert len(_titles(pane, "refs")) == 40 and len(_titles(pane, "later")) == 25
    assert _page(pane).count("Reference number 7 on matrix functions") == 1
    cards = dict(pane._cards)
    for view, side in (("graph", "refs"), ("list", "later"), ("graph", "later"),
                       ("list", "refs"), ("list", "later")):
        pane._set_view(view)
        pane._set_side(side)
    QApplication.processEvents()
    assert pane._cards == cards
    # The lists were read once; the map was drawn once, when it was first shown.
    assert (pane.loads["lists"], pane.loads["graph"]) == (1, 1)
    assert pane._list_view.isVisible() and not pane._graph_face.isVisible()
    assert "Later work 7 building on it" in _page(pane)
    assert "Reference number 7" not in _page(pane)


def test_the_tab_never_opens_a_window_of_its_own(pane):
    # A switch made visible before it had a parent opened as a small window,
    # flashing on screen each time the tab was first shown.
    pane._set_side("later")
    pane._set_view("graph")
    pane._set_view("list")
    QApplication.processEvents()
    assert [type(w).__name__ for w in pane.windows.opened if w is not pane] == []


def test_the_switch_shows_where_it_is_and_is_remembered(pane):
    buttons = pane._view_buttons
    assert buttons["list"].isChecked() and not buttons["graph"].isChecked()
    buttons["graph"].click()
    assert buttons["graph"].isChecked() and not buttons["list"].isChecked()
    assert pane._graph_face.isVisible() and not pane._list_view.isVisible()
    assert pane._map is not None and pane._map.dots
    # View state is written by a background queue; closing the window flushes it.
    assert ui_state.flush()
    with store.connect() as conn:
        assert store.get_kv(conn, "ui.cites_view") == "graph"
    # A new pane, as after a restart, opens on the face last chosen.
    again = cites_pane.CitesPane(pane.win, LIGHT)
    assert again._view_buttons["graph"].isChecked()


def test_reordering_reorders_only_that_side(pane):
    later = [r["work_id"] for r in pane._rows["later"]]
    pane._set_order("number")
    text = _page(pane)
    assert text.index("[1] Reference number 1 ") < text.index("[2] Reference number 2 ")
    assert [r["ref_key"] for r in pane._rows["refs"]][:3] == ["1", "2", "3"]
    assert [r["work_id"] for r in pane._rows["later"]] == later
    assert pane.loads["lists"] == 1


def test_the_map_density_redraws_the_map_alone(pane):
    pane._set_view("graph")
    cards = dict(pane._cards)
    drawn = len(pane._map.dots)
    pane._set_density(True)
    assert len(pane._map.dots) > drawn
    assert pane._cards == cards and pane.loads["lists"] == 1


def test_a_slide_source_finds_its_card_on_the_other_side(pane):
    message = pane.focus({"id": "later:3", "label": "後續研究：Later work 7 building on it"})
    assert message == "已跳到「脈絡」分頁的後續研究這一筆。"
    assert pane._side == "later"
    assert "Later work 7 building on it" in _page(pane)
    assert 'id="seg-side-later" class="on"' in pane._list_view._body


def test_a_card_opens_lifts_or_adds_its_work(pane, monkeypatch):
    spawned = []
    monkeypatch.setattr(cites_pane, "_spawn", lambda *args: spawned.append(args))
    refs = pane._rows["refs"]
    here = next(i for i, r in enumerate(refs) if r["here"])
    assert "插到最前面" in _page(pane)
    pane._link(QUrl(f"cite:open:refs:{here}"))
    assert pane.opened == ["ICLR:2024:ref3"]
    pane._link(QUrl(f"cite:lift:refs:{here}"))
    assert pane.promoted == ["ICLR:2024:ref3"]
    assert "已插到最前面" in _page(pane)
    other = next(i for i, r in enumerate(refs) if not r["here"])
    pane._link(QUrl(f"cite:add:refs:{other}"))
    assert spawned == [("list-add", "my-list", refs[other]["title"])]
    assert "已送到「my-list」" in _page(pane)
    # A link to a card that is no longer there does nothing.
    pane._link(QUrl("cite:open:refs:999"))
    assert pane.opened == ["ICLR:2024:ref3"]


def test_the_sides_and_orders_switch_from_their_links(pane):
    pane._link(QUrl("cite:side:later"))
    assert pane._side == "later" and "Later work 3 building on it" in _page(pane)
    pane._link(QUrl("cite:order:cited"))
    assert [r["work_id"] for r in pane._rows["later"]][0] == "w24"


def test_a_label_measures_its_text_once_per_width():
    QApplication.instance() or QApplication([])
    label = cites_pane._Text("word " * 200)
    label.setWordWrap(True)
    tall = label.heightForWidth(200)
    assert label.heightForWidth(600) < tall
    assert label.heightForWidth(200) == tall
    label.setText("short")
    assert label.heightForWidth(200) < tall


def test_the_map_legend_shows_each_verdict_in_the_colour_the_map_draws_it():
    from paper_daily.desktop.cite_graph import VERDICT_STYLE

    legend = cites_pane.graph_legend(LIGHT)
    for verdict, (_fill, line) in VERDICT_STYLE.items():
        assert f"color:{LIGHT[line]};font-size:14px;'>●</span>&nbsp;{verdict}" in legend
    assert "B 引用了 A" in legend and "雙擊開啟" in legend
