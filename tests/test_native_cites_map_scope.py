"""Native feature map callbacks and queued reads keep their admitted workspace."""

import shutil
import sqlite3
import sys
from contextlib import closing
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication
from test_reader_chat import reader as reader_fixture
from test_research_chat import legacy as legacy_fixture

from paper_daily import llm, store
from paper_daily.desktop import cites_pane
from paper_daily.desktop.main import LIGHT
from paper_daily.desktop.window_workspace import WindowWorkspace

reader = reader_fixture
legacy = legacy_fixture


class Job:
    status = None

    def poll(self):
        return self.status


@pytest.fixture
def scene(tmp_path, monkeypatch, request):
    app = QApplication.instance() or QApplication([])
    database = tmp_path / "A.sqlite"
    monkeypatch.setattr(store, "DB_PATH", database)
    store.init_db()
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                dict(
                    id=key,
                    title="Focal " + key,
                    venue="Fixture",
                    year=2026,
                    source="fixture",
                )
                for key in ("A", "B")
            ],
        )
        conn.executemany(
            "INSERT INTO cites(paper_id,ref_key,title,doi,purpose,contexts_json,basis,written_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            [
                (
                    "A",
                    str(i),
                    "External source " + str(i),
                    "10.fixture/" + str(i),
                    "Own source context",
                    '["The focal study cites this work."]',
                    "context",
                    "2026-10-31T00:00:00Z",
                )
                for i in (1, 2)
            ],
        )
    opened, submitted = [], []
    host = SimpleNamespace(
        active_list="list-A",
        selected="A",
        waiting=set,
        in_queue=lambda _paper: False,
        analysis_running=lambda *_: False,
        _workspace_owner=WindowWorkspace.capture(),
    )

    def open_paper(identity):
        opened.append(identity)
        host.selected = identity

    host.open_paper = open_paper

    def spawn(*args):
        submitted.append(args)
        return Job()

    monkeypatch.setattr(cites_pane, "_spawn", spawn)
    pane = cites_pane.CitesPane(host, LIGHT)
    pane.resize(800, 650)
    if getattr(request, "param", None) == "graph-only":
        pane._view_buttons["graph"].click()
    pane.load("A")
    if getattr(request, "param", None) == "list-only":
        pane.show()
        graph, note, nodes = None, None, []
    else:
        if getattr(request, "param", None) != "graph-only":
            pane._build_graph_face()
        graph, note = pane._map, pane._graph_note
        nodes = [dot.node for dot in graph.dots.values() if dot.node.side == "ref"]
        assert len(nodes) == 2
    yield SimpleNamespace(
        app=app,
        database=database,
        host=host,
        pane=pane,
        graph=graph,
        note=note,
        nodes=nodes,
        submitted=submitted,
        opened=opened,
        root=tmp_path,
    )
    pane._watch.stop()
    app.processEvents()
    pane.close()
    pane.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def records(path):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(
            "SELECT paper_id,ref_key,purpose FROM cites ORDER BY paper_id,ref_key"
        ).fetchall()


def change(scene, monkeypatch, kind):
    if kind == "paper":
        scene.pane.paper_id = "B"
        scene.host.selected = "B"
    elif kind == "list":
        scene.host.active_list = "list-B"
    elif kind == "workspace":
        other = scene.root / "B.sqlite"
        with closing(sqlite3.connect(other)) as conn:
            conn.execute("CREATE TABLE private_sentinel(value TEXT)")
            conn.commit()
        monkeypatch.setattr(store, "DB_PATH", other)
    elif kind == "closed-map":
        scene.graph.close()
    elif kind == "closed-pane":
        scene.pane.close()
    elif kind == "owner":
        scene.host._workspace_owner.close()
    elif kind == "owner-replacement":
        scene.host._workspace_owner = WindowWorkspace.capture()
    elif kind == "owner-removed":
        del scene.host._workspace_owner
    elif kind == "replacement":
        replacement = scene.database.with_suffix(".replacement")
        shutil.copyfile(scene.database, replacement)
        replacement.replace(scene.database)


@pytest.mark.parametrize(
    "kind",
    [
        "none",
        "paper",
        "list",
        "workspace",
        "closed-map",
        "closed-pane",
        "owner",
        "owner-replacement",
        "owner-removed",
        "replacement",
    ],
)
def test_actual_map_add_and_open_keep_the_displayed_scope(scene, monkeypatch, kind):
    before, notice = records(scene.database), scene.note.text()
    change(scene, monkeypatch, kind)
    selected = scene.host.selected
    scene.graph.on_add(scene.nodes[0])
    scene.graph.on_open("B")
    if kind == "none":
        node = scene.nodes[0]
        assert scene.submitted == [("list-add", "list-A", node.title, "--doi", node.doi)]
        assert scene.opened == ["B"] and scene.host.selected == "B"
        assert scene.note.text() != notice and "list-A" in scene.note.text()
    else:
        assert scene.submitted == [] and scene.opened == []
        assert scene.host.selected == selected and scene.note.text() == notice
    assert records(scene.database) == before


def test_one_graph_item_add_is_deduplicated_but_distinct_items_still_work(scene):
    before = records(scene.database)
    first, second = scene.nodes
    for _ in range(20):
        scene.graph.on_add(first)
    scene.graph.on_add(second)
    assert scene.submitted == [
        ("list-add", "list-A", first.title, "--doi", first.doi),
        ("list-add", "list-A", second.title, "--doi", second.doi),
    ]
    assert records(scene.database) == before


def test_native_card_order_change_does_not_revoke_the_existing_map(scene):
    original = scene.pane._generation
    scene.pane._set_order("number")
    assert scene.pane._generation == original and scene.pane._map is scene.graph
    scene.graph.on_add(scene.nodes[0])
    scene.graph.on_open("B")
    assert scene.submitted and scene.opened == ["B"]


@pytest.mark.parametrize("method", ["load", "fill_graph", "links_done"])
def test_queued_projection_never_opens_the_next_workspace(scene, monkeypatch, method):
    pane = scene.pane
    if method == "links_done":
        pane._run_links()
        job = pane._links_job
        job.status = 0
        scene.submitted.clear()
    other = scene.root / "next.sqlite"
    with closing(sqlite3.connect(other)) as conn:
        conn.execute("CREATE TABLE sentinel(value TEXT)")
        conn.execute("INSERT INTO sentinel VALUES('unchanged')")
        conn.commit()
    original = other.read_bytes()
    reads, errors = [], []
    connect = cites_pane.connect

    def observed(*args, **kwargs):
        reads.append(str(kwargs.get("path", store.DB_PATH)))
        return connect(*args, **kwargs)

    monkeypatch.setattr(cites_pane, "connect", observed)
    monkeypatch.setattr(store, "DB_PATH", other)
    paper, graph, body = pane.paper_id, pane._map, pane._list_face

    def invoke():
        try:
            if method == "load":
                pane.load("B")
            elif method == "fill_graph":
                pane._fill_graph(pane._graph_face.layout())
            else:
                pane._links_done()
        except sqlite3.Error as error:
            errors.append(type(error).__name__)

    QTimer.singleShot(0, pane, invoke)
    scene.app.processEvents()
    assert reads == [] and errors == []
    assert pane.paper_id == paper and pane._map is graph and pane._list_face == body
    assert not pane._watch.isActive()
    assert other.read_bytes() == original
    replacement = scene.root / "next-replacement.sqlite"
    replacement.write_bytes(original)
    replacement.replace(other)
    assert other.read_bytes() == original


def test_stale_timer_keeps_admitted_running_process_owned(scene, monkeypatch):
    scene.pane._run_links()
    job = scene.pane._links_job
    change(scene, monkeypatch, "workspace")
    scene.pane._links_done()
    assert not scene.pane._watch.isActive()
    assert scene.pane._links_job is job
    assert scene.pane._running(scene.pane._links_job)
    job.status = 0
    assert not scene.pane._running(scene.pane._links_job)


def test_late_team_delivery_does_not_repaint_a_stale_workspace(scene, monkeypatch):
    pane = scene.pane
    pane._team = "team"
    before = pane._list_face
    change(scene, monkeypatch, "workspace")
    pane._team_done(pane._generation, {"refs": {}, "later": {}, "known": 0, "total": 0})
    pane._team_step(pane._generation, 1, 2)
    assert pane._list_face == before
    assert pane._team_data is None


def test_map_rebuild_keeps_submitted_items_and_revokes_the_old_map(scene):
    first, second = scene.nodes
    scene.graph.on_add(first)
    scene.pane._rebuild_graph()
    current = scene.pane._map
    assert current is not scene.graph
    scene.graph.on_add(second)
    current.on_add(current.dots[first.key].node)
    current.on_add(current.dots[second.key].node)
    assert scene.submitted == [
        ("list-add", "list-A", first.title, "--doi", first.doi),
        ("list-add", "list-A", second.title, "--doi", second.doi),
    ]


def test_failed_graph_submission_can_retry_the_same_item(scene, monkeypatch):
    calls = []

    def failed(*args):
        calls.append(args)
        raise OSError("fixture process admission failed")

    node = scene.nodes[0]
    monkeypatch.setattr(cites_pane, "_spawn", failed)
    with pytest.raises(OSError):
        scene.graph.on_add(node)
    monkeypatch.setattr(cites_pane, "_spawn", lambda *args: calls.append(args))
    scene.graph.on_add(node)
    assert calls == [
        ("list-add", "list-A", node.title, "--doi", node.doi),
        ("list-add", "list-A", node.title, "--doi", node.doi),
    ]


def test_submission_does_not_write_a_notice_into_a_replacement_map(scene, monkeypatch):
    old_notice = scene.note.text()

    def navigate(*args):
        scene.submitted.append(args)
        scene.pane.load("B")
        scene.pane._build_graph_face()
        return Job()

    monkeypatch.setattr(cites_pane, "_spawn", navigate)
    node = scene.nodes[0]
    scene.graph.on_add(node)
    assert scene.submitted == [("list-add", "list-A", node.title, "--doi", node.doi)]
    assert scene.pane.paper_id == "B" and scene.pane._map is not scene.graph
    assert "已送到" not in scene.pane._graph_note.text()
    assert scene.note.text() == old_notice


def test_constructor_rejects_an_outer_owner_from_another_workspace(scene, monkeypatch):
    path = scene.root / "different.sqlite"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE sentinel(value)")
        conn.commit()
    before = path.read_bytes()
    monkeypatch.setattr(store, "DB_PATH", path)
    reads = []
    connect = cites_pane.connect

    def observed(*args, **kwargs):
        reads.append(kwargs.get("path", store.DB_PATH))
        return connect(*args, **kwargs)

    monkeypatch.setattr(cites_pane, "connect", observed)
    pane = cites_pane.CitesPane(scene.host, LIGHT)
    pane.load("A")
    assert reads == [] and path.read_bytes() == before and pane.paper_id is None
    pane.close()
    pane.deleteLater()
    scene.app.processEvents()

def test_old_map_callback_does_not_stop_new_papers_owned_timer(scene):
    old = scene.graph
    scene.pane.load("B")
    scene.pane._build_graph_face()
    scene.pane._run_links()
    job = scene.pane._links_job
    assert scene.pane._watch.isActive()
    old.on_open("A")
    assert scene.opened == []
    assert scene.pane._watch.isActive() and scene.pane._links_job is job


def test_queued_old_graph_layout_does_not_read_or_replace_new_paper_map(scene, monkeypatch):
    old_layout = scene.pane._graph_face.layout()
    scene.pane.load("B")
    scene.pane._build_graph_face()
    current = scene.pane._map
    reads, errors = [], []
    connect = cites_pane.connect

    def observed(*args, **kwargs):
        reads.append(kwargs.get("path", store.DB_PATH))
        return connect(*args, **kwargs)

    monkeypatch.setattr(cites_pane, "connect", observed)

    def invoke():
        try:
            scene.pane._fill_graph(old_layout)
        except RuntimeError as error:
            errors.append(type(error).__name__)

    QTimer.singleShot(0, scene.pane, invoke)
    scene.app.processEvents()
    assert reads == [] and errors == []
    assert scene.pane.paper_id == "B" and scene.pane._map is current


def test_completed_old_links_job_cannot_rebuild_the_new_paper_projection(scene, monkeypatch):
    pane = scene.pane
    pane._run_links()
    job = pane._links_job
    pane.load("B")
    pane._build_graph_face()
    current = pane._map
    job.status = 0
    reads = []
    connect = cites_pane.connect

    def observed(*args, **kwargs):
        reads.append(kwargs.get("path", store.DB_PATH))
        return connect(*args, **kwargs)

    monkeypatch.setattr(cites_pane, "connect", observed)
    pane._links_done()
    assert reads == [] and pane._map is current and pane.paper_id == "B"
    assert pane._links_job is job and not pane._watch.isActive()


def test_new_projection_allows_the_same_node_after_an_explicit_reload(scene):
    node = scene.nodes[0]
    scene.graph.on_add(node)
    scene.pane.load("A")
    scene.pane._build_graph_face()
    scene.pane._map.on_add(scene.pane._map.dots[node.key].node)
    assert scene.submitted == [
        ("list-add", "list-A", node.title, "--doi", node.doi),
        ("list-add", "list-A", node.title, "--doi", node.doi),
    ]


@pytest.mark.parametrize("scene", ["list-only"], indirect=True)
def test_actual_graph_button_after_list_switch_rebuilds_current_paper_safely(scene, monkeypatch):
    pane = scene.pane
    assert pane._view == "list" and pane._graph_face is None
    assert pane._list_face.isVisible() and pane._view_buttons["list"].isChecked()
    previous_list = pane._list_face
    before = records(scene.database)
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda _kind, error, _traceback: errors.append(error))
    scene.host.active_list = "list-B"
    pane._view_buttons["graph"].click()
    assert errors == []
    assert pane.paper_id == "A" and pane._view == "graph"
    assert pane._map is not None and pane._graph_face.isVisible()
    assert not previous_list.isVisible()
    assert pane._view_buttons["graph"].isChecked()
    assert not pane._view_buttons["list"].isChecked()
    assert records(scene.database) == before and scene.submitted == []
    node = next(dot.node for dot in pane._map.dots.values() if dot.node.side == "ref")
    pane._map.on_add(node)
    assert scene.submitted == [("list-add", "list-B", node.title, "--doi", node.doi)]


def test_actual_main_graph_switch_keeps_question_and_note_drafts_without_ai(reader, monkeypatch):
    _app, window, page = reader
    pane = page.cites_pane
    monkeypatch.setattr(llm, "capture_connections", lambda: pytest.fail("View switch read AI"))
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **k: pytest.fail("View switch called AI")
    )
    monkeypatch.setattr(cites_pane, "_spawn", lambda *a: pytest.fail("View switch started a job"))
    window.active_list = "list-A"
    window.stack.setCurrentWidget(page)
    page.tabs.setCurrentWidget(pane)
    pane.load(page.paper.id)
    page.ask_box.setText("Unsent question")
    page.note_edit.setPlainText("Unsent note")
    with closing(sqlite3.connect(store.DB_PATH)) as conn:
        original_notes = conn.execute("SELECT * FROM notes ORDER BY rowid").fetchall()
        original_chat = conn.execute("SELECT * FROM chat ORDER BY rowid").fetchall()
    window.show()
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda _kind, error, _traceback: errors.append(error))
    try:
        assert pane._graph_face is None and pane._list_face.isVisible()
        assert pane._outer_workspace is window._workspace_owner
        window.active_list = "list-B"
        pane._view_buttons["graph"].click()
        assert errors == [] and pane._graph_face is not None and pane._graph_face.isVisible()
        assert pane.paper_id == "local-paper" and pane._view_buttons["graph"].isChecked()
        assert page.ask_box.text() == "Unsent question"
        assert page.note_edit.toPlainText() == "Unsent note"
        with closing(sqlite3.connect(store.DB_PATH)) as conn:
            assert conn.execute("SELECT * FROM notes ORDER BY rowid").fetchall() == original_notes
            assert conn.execute("SELECT * FROM chat ORDER BY rowid").fetchall() == original_chat
    finally:
        page.ask_box.clear()
        page.note_edit.clear()


@pytest.mark.parametrize("scene", ["graph-only"], indirect=True)
def test_queued_preparation_cannot_build_hidden_cards_for_a_stale_list(scene, monkeypatch):
    pane = scene.pane
    assert pane._view == "graph" and pane._list_face is None
    generation, graph, face = pane._generation, pane._map, pane._graph_face
    reads, errors = [], []
    connect = cites_pane.connect

    def observed(*args, **kwargs):
        reads.append(kwargs.get("path", store.DB_PATH))
        return connect(*args, **kwargs)

    monkeypatch.setattr(cites_pane, "connect", observed)
    monkeypatch.setattr(sys, "excepthook", lambda _kind, error, _traceback: errors.append(error))
    scene.host.active_list = "list-B"
    QTimer.singleShot(0, pane, lambda: pane._prepare_rest(generation))
    scene.app.processEvents()
    assert reads == [] and errors == []
    assert pane._list_face is None and pane._map is graph and pane._graph_face is face
    assert pane._view == "graph" and pane._view_buttons["graph"].isChecked()
