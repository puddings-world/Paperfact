"""The 引用 tab's 條列 / 引用圖 switch and its 參考文獻 / 後續研究 sides: built once per
paper and flipped, not rebuilt. Each flip used to reload the database and remake
every card, two to four seconds on a paper with 60 references and 120 later
works."""

import os
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from paper_daily import citegraph, followups, store  # noqa: E402
from paper_daily.desktop import cites_pane  # noqa: E402
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


def _graph(_conn, paper_id):
    nodes = [citegraph.Node(key="c", title="Centre paper", side="center")]
    nodes += [citegraph.Node(key=f"ref:{r['ref_key']}", title=r["title"], side="ref",
                             verdict=r["verdict"]) for r in REFS]
    nodes += [citegraph.Node(key=f"later:{r['work_id']}", title=r["title"], side="later",
                             verdict=r["verdict"]) for r in LATER]
    edges = [(n.key, "c") for n in nodes if n.side == "ref"]
    edges += [("c", n.key) for n in nodes if n.side == "later"]
    return citegraph.Graph(nodes=nodes, edges=edges, checked="2026-10-19")


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

    monkeypatch.setattr(followups, "references", references)
    monkeypatch.setattr(followups, "for_paper", lambda conn, pid: [dict(r) for r in LATER])
    monkeypatch.setattr(followups, "overview_for", lambda conn, pid: None)
    monkeypatch.setattr(followups, "checked", lambda conn, pid: "2026-10-19")
    monkeypatch.setattr(followups, "in_corpus", lambda *a: None)
    monkeypatch.setattr(citegraph, "build", graph)
    app = QApplication.instance() or QApplication([])
    window = SimpleNamespace(open_paper=lambda pid: None, analysis_running=lambda pid=None: False,
                             in_queue=lambda pid: False, active_list=None)
    widget = cites_pane.CitesPane(window, LIGHT)
    widget.resize(900, 700)
    widget.show()
    widget.load("p")
    widget.loads = loads
    widget.settle = lambda: _settle(app, widget)
    return widget


def _settle(app, widget, limit=10.0):
    """Let the dozen-at-a-time building and the idle build of the rest finish."""
    end = time.monotonic() + limit
    while time.monotonic() < end:
        app.processEvents()
        if not widget._pending and widget._graph_face is not None:
            return
    raise AssertionError("the tab never finished building")


def _titles(widget, side):
    return [title for (kind, title), (s, _card) in widget._cards.items()
            if kind == "title" and s == side]


def test_every_card_is_made_once_and_flipping_never_rebuilds(pane):
    pane.settle()
    assert len(_titles(pane, "refs")) == 40 and len(_titles(pane, "later")) == 25
    cards = dict(pane._cards)
    lists, graphs = pane.loads["lists"], pane.loads["graph"]
    for view, side in (("graph", "refs"), ("list", "later"), ("graph", "later"),
                       ("list", "refs"), ("list", "later")):
        pane._set_view(view)
        pane._set_side(side)
    QApplication.processEvents()
    assert pane._cards == cards
    assert (pane.loads["lists"], pane.loads["graph"]) == (lists, graphs)
    assert pane._list_face.isVisible() and not pane._graph_face.isVisible()
    assert pane._side_widgets["later"].isVisible()
    assert not pane._side_widgets["refs"].isVisible()


def test_the_switch_shows_where_it_is_and_is_remembered(pane):
    pane.settle()
    buttons = pane._view_buttons
    assert buttons["list"].isChecked() and not buttons["graph"].isChecked()
    buttons["graph"].click()
    assert buttons["graph"].isChecked() and not buttons["list"].isChecked()
    assert pane._graph_face.isVisible() and not pane._list_face.isVisible()
    assert pane._map is not None and pane._map.dots
    with store.connect() as conn:
        assert store.get_kv(conn, "ui.cites_view") == "graph"
    # A new pane, as after a restart, opens on the face last chosen.
    again = cites_pane.CitesPane(pane.win, LIGHT)
    assert again._view_buttons["graph"].isChecked()


def test_reordering_remakes_only_that_side(pane):
    pane.settle()
    later_cards = {k: v for k, v in pane._cards.items() if v[0] == "later"}
    pane._set_order("number")
    pane.settle()
    box = pane._boxes["refs"]
    first = next(box.itemAt(i).widget() for i in range(box.count())
                 if box.itemAt(i).widget().objectName() == "card")
    assert first is pane._cards[("ref", "1")][1]
    assert {k: v for k, v in pane._cards.items() if v[0] == "later"} == later_cards
    assert pane.loads["lists"] == 1


def test_the_map_density_redraws_the_map_alone(pane):
    pane.settle()
    pane._set_view("graph")
    cards = dict(pane._cards)
    drawn = len(pane._map.dots)
    pane._set_density(True)
    assert len(pane._map.dots) > drawn
    assert pane._cards == cards and pane.loads["lists"] == 1


def test_a_slide_source_is_found_before_its_side_has_finished_building(pane):
    # No settling: the later side has not been made yet.
    message = pane.focus({"id": "later:3", "label": "後續研究：Later work 7 building on it"})
    assert message == "已跳到「引用」分頁的後續研究這一筆。"
    assert pane._side == "later" and pane._side_widgets["later"].isVisible()
    assert pane._side_buttons["later"].isChecked()


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
