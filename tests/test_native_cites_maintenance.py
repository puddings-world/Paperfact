"""Maintenance view contracts through retained native cards and actual Qt controls."""

import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from paper_daily import citegraph, followups, store
from paper_daily.desktop import cites_pane, ui_state
from paper_daily.desktop.main import LIGHT

REFS = [
    dict(
        ref_key=str(i), title=f"Reference number {i} on matrix functions",
        verdict="值得" if i % 3 == 0 else "參考", basis="context", purpose="baseline",
        contexts=[f"as shown in [{i}]"], here=None,
    )
    for i in range(40, 0, -1)
]
LATER = [
    dict(
        title=f"Later work {i} building on it", work_id=f"w{i}",
        verdict="值得" if i % 4 == 0 else "參考", citations=i, year=2020 + i % 6,
        relation="extends it", abstract="x", here=None,
    )
    for i in range(25)
]
HERE = {"id": "ICLR:2024:ref3", "read": False}


class Windows(QObject):
    def __init__(self):
        super().__init__()
        self.opened = []

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show and obj.isWidgetType() and obj.isWindow():
            self.opened.append(obj)
        return False


def graph(_conn, _paper_id):
    nodes = [citegraph.Node(key="c", title="Centre paper", side="center")]
    nodes += [
        citegraph.Node(key=f"ref:{r['ref_key']}", title=r["title"], side="ref",
                       verdict=r["verdict"])
        for r in REFS
    ]
    nodes += [
        citegraph.Node(key=f"later:{r['work_id']}", title=r["title"], side="later",
                       verdict=r["verdict"])
        for r in LATER
    ]
    edges = [(n.key, "c") for n in nodes if n.side == "ref"]
    edges += [("c", n.key) for n in nodes if n.side == "later"]
    return citegraph.Graph(nodes=nodes, edges=edges, checked="2026-10-19")


@pytest.fixture
def scene(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    with store.connect() as conn:
        store.upsert_papers(conn, [dict(
            id="p", title="Centre paper", venue="ICLR", year=2026, source="fixture"
        )])
    loads = dict(lists=0, graph=0)

    def references(_conn, _paper):
        loads["lists"] += 1
        return [dict(row) for row in REFS]

    def build(conn, paper):
        loads["graph"] += 1
        return graph(conn, paper)

    def in_corpus(_conn, _doi, title, _corpus):
        return dict(HERE) if title == REFS[-3]["title"] else None

    def no_process(*_args):
        raise AssertionError("A view operation must not start an external process")

    monkeypatch.setattr(followups, "references", references)
    monkeypatch.setattr(followups, "for_paper", lambda *_args: [dict(row) for row in LATER])
    monkeypatch.setattr(followups, "overview_for", lambda *_args: None)
    monkeypatch.setattr(followups, "checked", lambda *_args: "2026-10-19")
    monkeypatch.setattr(followups, "in_corpus", in_corpus)
    monkeypatch.setattr(citegraph, "build", build)
    monkeypatch.setattr(cites_pane, "_spawn", no_process)
    app = QApplication.instance() or QApplication([])
    opened, promoted = [], []
    host = SimpleNamespace(
        open_paper=opened.append, promote=promoted.append, active_list="my-list",
        analysis_running=lambda _paper=None: False, in_queue=lambda paper: paper == HERE["id"],
    )
    windows = Windows()
    app.installEventFilter(windows)
    pane = cites_pane.CitesPane(host, LIGHT)
    pane.resize(900, 700)
    pane.show()
    pane.load("p")
    # Deliberately no event pump: source lookup must also work before idle preparation.
    yield SimpleNamespace(
        app=app, pane=pane, loads=loads, opened=opened, promoted=promoted, windows=windows
    )
    app.removeEventFilter(windows)
    pane.close()
    assert ui_state.flush()
    pane.deleteLater()
    app.processEvents()


def wait(scene, ready):
    end = time.monotonic() + 10
    while not ready() and time.monotonic() < end:
        scene.app.processEvents()
    assert ready(), "Native citation view did not settle"


def settle(scene):
    wait(scene, lambda: not scene.pane._pending and scene.pane._graph_face is not None)


def cards(pane, side):
    box = pane._boxes[side]
    return [box.itemAt(i).widget() for i in range(box.count())
            if box.itemAt(i).widget() is not None
            and box.itemAt(i).widget().objectName() == "card"]


def text(card):
    return "\n".join(label.text() for label in card.findChildren(QLabel))


def order(pane, side):
    rows, key = (REFS, "ref_key") if side == "refs" else (LATER, "work_id")
    return [next(row[key] for row in rows if row["title"] in text(card))
            for card in cards(pane, side)]


def button(owner, label):
    matches = [item for item in owner.findChildren(QPushButton) if item.text() == label]
    assert len(matches) == 1
    return matches[0]


def test_every_work_is_on_the_page_once_and_flipping_never_reloads(scene):
    pane = scene.pane
    settle(scene)
    assert len(cards(pane, "refs")) == 40 and len(cards(pane, "later")) == 25
    title = "Reference number 7 on matrix functions"
    assert sum(text(card).count(title) for card in cards(pane, "refs")) == 1
    original = dict(pane._cards)
    assert scene.loads == {"lists": 1, "graph": 1}
    for view, side in (("graph", None), ("list", "later"), ("graph", None),
                       ("list", "refs"), ("list", "later")):
        pane._view_buttons[view].click()
        if side is not None:
            pane._side_buttons[side].click()
    scene.app.processEvents()
    assert pane._cards == original and scene.loads == {"lists": 1, "graph": 1}
    assert pane._list_face.isVisible() and not pane._graph_face.isVisible()
    assert pane._side_widgets["later"].isVisible() and not pane._side_widgets["refs"].isVisible()


def test_the_tab_never_opens_a_window_of_its_own(scene):
    pane = scene.pane
    pane._side_buttons["later"].click()
    pane._view_buttons["graph"].click()
    pane._view_buttons["list"].click()
    settle(scene)
    assert [type(widget).__name__ for widget in scene.windows.opened if widget is not pane] == []


def test_reordering_reorders_only_that_side(scene):
    pane = scene.pane
    settle(scene)
    later = order(pane, "later")
    button(pane._orders["refs"], "照論文編號").click()
    settle(scene)
    assert order(pane, "refs")[:3] == ["1", "2", "3"]
    assert order(pane, "later") == later
    assert scene.loads["lists"] == 1


def test_a_slide_source_finds_its_card_on_the_other_side(scene):
    pane = scene.pane
    assert pane._boxes["later"].count() == 0
    message = pane.focus({"id": "later:3", "label": "後續研究：Later work 7 building on it"})
    assert message == "已跳到「脈絡」分頁的後續研究這一筆。"
    target = pane._cards[("title", "laterwork7buildingonit")][1]
    wait(scene, lambda: target.isVisible() and pane.viewport().rect().contains(
        target.mapTo(pane.viewport(), target.rect().center())
    ))
    assert "Later work 7 building on it" in text(target)
    assert pane._side == "later" and pane._side_buttons["later"].isChecked()
    settle(scene)
    wait(scene, lambda: pane._source_focus is None)
    assert pane.viewport().rect().contains(
        target.mapTo(pane.viewport(), target.rect().center())
    )


def test_a_card_opens_lifts_or_adds_its_work(scene, monkeypatch):
    pane = scene.pane
    settle(scene)
    spawned = []
    monkeypatch.setattr(cites_pane, "_spawn", lambda *args: spawned.append(args))
    known = pane._cards[("ref", "3")][1]
    go, lift = button(known, "開啟"), button(known, "插到最前面")
    go.click()
    assert scene.opened == [HERE["id"]]
    lift.click()
    assert scene.promoted == [HERE["id"]]
    assert lift.text() == "已插到最前面" and not lift.isEnabled()
    other = pane._cards[("ref", "7")][1]
    add = button(other, "加入清單")
    add.click()
    add.clicked.emit()
    assert spawned == [("list-add", "my-list", "Reference number 7 on matrix functions")]
    assert add.text() == "已送到「my-list」" and not add.isEnabled()
    pane._clear()
    go.clicked.emit()
    assert scene.opened == [HERE["id"]]
    assert scene.promoted == [HERE["id"]] and len(spawned) == 1


def test_the_sides_and_orders_switch_from_their_links(scene):
    pane = scene.pane
    pane._side_buttons["later"].click()
    settle(scene)
    assert pane._side == "later" and pane._side_buttons["later"].isChecked()
    assert pane._side_widgets["later"].isVisible() and not pane._side_widgets["refs"].isVisible()
    assert any("Later work 3 building on it" in text(card) for card in cards(pane, "later"))
    button(pane._orders["later"], "被引用最多").click()
    settle(scene)
    assert order(pane, "later")[0] == "w24"


@pytest.mark.parametrize("change", ["paper", "list", "view", "side", "order", "team", "close"])
def test_pending_source_reveal_cannot_navigate_a_changed_context(scene, monkeypatch, change):
    pane = scene.pane
    revealed, prepared = [], []
    reveal, prepare = pane.ensureWidgetVisible, pane._prepare_rest

    def native_reveal(target, *args):
        revealed.append(target)
        return reveal(target, *args)

    def actual_preparation(generation):
        prepared.append(generation)
        return prepare(generation)

    monkeypatch.setattr(pane, "ensureWidgetVisible", native_reveal)
    monkeypatch.setattr(pane, "_prepare_rest", actual_preparation)
    assert pane.focus({"id": "later:3", "label": "後續研究：Later work 7 building on it"})
    assert pane._source_focus is not None
    if change == "paper":
        with store.connect() as conn:
            store.upsert_papers(conn, [dict(
                id="q", title="Next paper", venue="ICLR", year=2026, source="fixture"
            )])
        pane.load("q")
    elif change == "list":
        pane.win.active_list = "next-list"
    elif change == "view":
        pane._view_buttons["graph"].click()
    elif change == "side":
        pane._side_buttons["refs"].click()
    elif change == "order":
        button(pane._orders["later"], "被引用最多").click()
    elif change == "team":
        # A local completed lookup: this control must not perform network work.
        pane._team_data = {"refs": {}, "later": {}, "own": False}
        pane._team_buttons["team"].click()
    else:
        pane.close()
    # Observe the real queued idle callback; no sleep, manual scroll, or callback replacement.
    wait(scene, lambda: prepared and not pane._pending)
    scene.app.processEvents()
    assert revealed == []
    assert pane._source_focus is None


@pytest.mark.parametrize("gesture", ["wheel", "keyboard", "scrollbar"])
def test_user_navigation_cancels_pending_source_reveal(scene, monkeypatch, gesture):
    pane = scene.pane
    revealed, prepared = [], []
    reveal, prepare = pane.ensureWidgetVisible, pane._prepare_rest

    def native_reveal(target, *args):
        revealed.append(target)
        return reveal(target, *args)

    def actual_preparation(generation):
        prepared.append(generation)
        return prepare(generation)

    monkeypatch.setattr(pane, "ensureWidgetVisible", native_reveal)
    monkeypatch.setattr(pane, "_prepare_rest", actual_preparation)
    pane.focus({"id": "later:3", "label": "後續研究：Later work 7 building on it"})
    assert pane._source_focus is not None
    if gesture == "wheel":
        point = QPointF(40, 40)
        event = QWheelEvent(
            point, pane.viewport().mapToGlobal(point.toPoint()), QPoint(), QPoint(0, -120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        QApplication.sendEvent(pane.viewport(), event)
        assert event.isAccepted()
    elif gesture == "keyboard":
        QTest.keyClick(pane, Qt.Key.Key_Home)
    else:
        bar = pane.verticalScrollBar()
        QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=bar.rect().center())
        QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=bar.rect().center())
    assert pane._source_focus is None
    wait(scene, lambda: prepared and not pane._pending)
    scene.app.processEvents()
    assert revealed == []
