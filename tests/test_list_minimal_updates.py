"""One key on the paper list changes one row: no second read of the list, no reset."""

import pytest
from PySide6.QtCore import QModelIndex
from test_workspace_transfer_ui import workspace as _workspace

from paper_daily import store
from paper_daily.desktop.main import MainWindow
from paper_daily.desktop.queue_view import SORT_IDS, PaperListModel

workspace = _workspace


def seed(count=6):
    with store.connect() as conn:
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('big','big','now')")
        for i in range(count):
            conn.execute(
                "INSERT INTO papers(id,title,title_key,venue,year,source) VALUES (?,?,?,?,?,?)",
                (f"p{i}", f"Paper {i}", f"k{i}", "NeurIPS", 2020, "fixture"),
            )
            conn.execute(
                "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES ('big',?,?,?)",
                (f"p{i}", i, "2026-01-01"),
            )


class Signals:
    def __init__(self, model):
        self.seen = []
        model.modelReset.connect(lambda: self.seen.append("reset"))
        model.rowsMoved.connect(lambda *a: self.seen.append(("moved", a[1], a[4])))
        model.rowsRemoved.connect(lambda _p, a, b: self.seen.append(("removed", a, b)))
        model.rowsInserted.connect(lambda _p, a, b: self.seen.append(("inserted", a, b)))


@pytest.fixture
def listed(workspace, monkeypatch):
    app, _root = workspace
    seed()
    window = MainWindow()
    window.show()
    window._open_list("big")
    page = window.queue_page
    page.sort.setCurrentIndex(SORT_IDS.index("custom"))
    page._select("p3")
    app.processEvents()
    # From here on the list must not be read again: every assertion below is about
    # what one key does to the papers already on screen.
    monkeypatch.setattr(
        window.data, "queue", lambda *a, **k: pytest.fail("the whole list was read again")
    )
    yield app, window, page, Signals(page.model)
    window.close()
    window.deleteLater()


def shown(page):
    return [paper.id for _position, paper in page.model._rows]


def test_marking_read_changes_that_row_and_keeps_the_view(listed):
    app, window, page, signals = listed
    page._read_current()
    app.processEvents()
    with store.connect() as conn:
        saved = conn.execute(
            "SELECT state, read_at FROM list_papers WHERE list_id='big' AND paper_id='p3'"
        ).fetchone()
    paper = page._current_paper()
    assert saved["state"] == "read" and saved["read_at"]
    assert paper.id == "p3" and paper.read and paper.read_at == saved["read_at"]
    assert window.progress.text() == "已讀 1 · 未讀 5"
    assert signals.seen == [] and shown(page) == [f"p{i}" for i in range(6)]

    page._read_current()
    assert not page._current_paper().read and window.progress.text() == "已讀 0 · 未讀 6"
    with store.connect() as conn:
        assert conn.execute(
            "SELECT state FROM list_papers WHERE paper_id='p3'").fetchone()[0] == "pending"
    assert signals.seen == []


def test_a_row_that_no_longer_matches_the_filter_leaves_alone(listed):
    app, window, page, signals = listed
    page.f_unread.setChecked(True)
    app.processEvents()
    signals.seen.clear()
    page._select("p3")
    page._read_current()
    assert shown(page) == ["p0", "p1", "p2", "p4", "p5"]
    assert signals.seen == [("removed", 3, 3)]


def test_pinning_moves_the_row_to_the_top_and_the_highlight_follows(listed):
    app, window, page, signals = listed
    page._pin_current()
    assert shown(page) == ["p3", "p0", "p1", "p2", "p4", "p5"]
    assert signals.seen == [("moved", 3, 0)]
    assert page._current_paper().id == "p3" and page._current_paper().pinned
    with store.connect() as conn:
        assert [r[0] for r in conn.execute("SELECT paper_id FROM pins WHERE scope='big'")] == ["p3"]

    signals.seen.clear()
    page._pin_current()
    assert shown(page) == [f"p{i}" for i in range(6)]
    assert signals.seen == [("moved", 0, 4)] and not page._current_paper().pinned


def test_the_windows_own_write_is_not_announced_as_an_outside_change(listed):
    app, window, page, _signals = listed
    watcher = window.workspace_changes
    watcher.poll()
    announced = []
    watcher.changed.connect(lambda: announced.append(True))

    page._read_current()
    page._pin_current()
    watcher.poll()
    assert announced == []

    # Someone else's write still is, including one that lands just before our own.
    with store.connect() as conn:
        conn.execute("UPDATE list_papers SET state='read' WHERE paper_id='p0'")
    page._read_current()
    announced.clear()
    watcher.poll()
    assert announced == [True]


def test_a_poll_older_than_the_windows_own_write_changes_nothing(listed):
    app, window, page, _signals = listed
    watcher = window.workspace_changes
    watcher.poll()
    stale = watcher._revision()
    announced = []
    watcher.changed.connect(lambda: announced.append(True))
    page._read_current()
    current = watcher.revision
    watcher._lifetime.begin()
    watcher._apply(stale)
    assert announced == [] and watcher.revision == current


def test_marking_read_in_the_ranked_queue_reports_what_was_saved(workspace):
    from paper_daily.desktop.main import Data

    with store.connect() as conn:
        conn.execute(
            "INSERT INTO papers(id,title,title_key,venue,year,source) "
            "VALUES ('q1','Queued','kq','ICLR',2024,'fixture')"
        )
        conn.execute("INSERT INTO queue(paper_id,rank,state,role) VALUES ('q1',1,'pending','main')")
    before, after, saved = Data().set_states(["q1", "q1"], "read")
    with store.connect() as conn:
        row = conn.execute("SELECT state, read_at FROM queue WHERE paper_id='q1'").fetchone()
        revision = conn.execute("SELECT revision FROM workspace_revision").fetchone()[0]
    assert row["state"] == "read" and saved == {"q1": ("read", row["read_at"], None)}
    assert after == revision and before <= after


class Named:
    def __init__(self, name):
        self.id = name


def rows(*names):
    # New objects every time, as a list read again from the database is.
    return [(i, Named(name)) for i, name in enumerate(names, 1)]


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ("abcd", "abcd", []),
        ("abcd", "dabc", [("moved", 3, 0)]),
        ("abcd", "bcda", [("moved", 0, 4)]),
        ("abcd", "acbd", [("moved", 2, 1)]),
        ("abcd", "abd", [("removed", 2, 2)]),
        ("abcd", "abc", [("removed", 3, 3)]),
        ("abd", "abcd", [("inserted", 2, 2)]),
        ("", "a", [("inserted", 0, 0)]),
        ("abcd", "dcba", ["reset"]),
        ("abcd", "ab", ["reset"]),
        ("abcd", "abxy", ["reset"]),
    ],
)
def test_the_model_announces_the_smallest_change_that_explains_the_new_rows(
    before, after, expected
):
    model = PaperListModel()
    model.set_rows(rows(*before))
    signals = Signals(model)
    epoch = model._epoch
    model.set_rows(rows(*after))
    assert signals.seen == expected
    assert [paper.id for _i, paper in model._rows] == list(after)
    assert model.rowCount(QModelIndex()) == len(after)
    # A drag started on the old rows must not be accepted on the new ones.
    assert (model._epoch == epoch) == (before == after == "")


def test_an_outside_change_to_the_same_papers_keeps_the_place_in_the_list(workspace):
    app, _root = workspace
    seed()
    window = MainWindow()
    window.show()
    try:
        window._open_list("big")
        page = window.queue_page
        page.sort.setCurrentIndex(SORT_IDS.index("custom"))
        page._select("p4")
        app.processEvents()
        signals = Signals(page.model)
        with store.connect() as conn:
            conn.execute("UPDATE list_papers SET state='read' WHERE paper_id='p1'")
        window._refresh_external_list_views()
        assert signals.seen == [] and page._current_paper().id == "p4"
        assert [p.read for _i, p in page.model._rows] == [False, True, False, False, False, False]
        assert window.progress.text() == "已讀 1 · 未讀 5"

        with store.connect() as conn:
            conn.execute("DELETE FROM list_papers WHERE paper_id='p2'")
        window._refresh_external_list_views()
        assert signals.seen == [("removed", 2, 2)] and page._current_paper().id == "p4"
    finally:
        window.close()
        window.deleteLater()


class Downloads:
    busy = False

    def __init__(self):
        self.states = {}

    def snapshot(self):
        return dict(self.states)


def test_an_idle_download_tick_does_not_walk_the_list(listed, monkeypatch):
    _app, _window, page, _signals = listed
    page.downloads = manager = Downloads()
    page._poll_pdfs()
    walked = []
    monkeypatch.setattr(page, "_poll_pdfs", lambda: walked.append(True))
    page._tick_pdfs()
    assert walked == []

    manager.states["p1"] = "queued"
    page._tick_pdfs()
    assert walked == [True]
    page.model.downloads = manager.snapshot()
    manager.busy = True
    page._tick_pdfs()
    assert walked == [True, True]


def test_coming_back_from_a_paper_does_not_read_an_unchanged_list_again(workspace, monkeypatch):
    app, _root = workspace
    seed()
    window = MainWindow()
    window.show()
    try:
        window._open_list("big")
        page = window.queue_page
        page.sort.setCurrentIndex(SORT_IDS.index("custom"))
        app.processEvents()
        real = window.data.queue
        reads = []
        monkeypatch.setattr(
            window.data, "queue", lambda *a, **k: reads.append(True) or real(*a, **k))

        window.open_paper("p2")
        window._toggle_read()
        window.go_back()
        assert reads == []
        opened = page._current_paper()
        assert opened.id == "p2" and opened.read and window.progress.text() == "已讀 1 · 未讀 5"
        with store.connect() as conn:
            assert conn.execute(
                "SELECT state FROM list_papers WHERE paper_id='p2'").fetchone()[0] == "read"

        # Something else changed the list while the next paper was open: read it again.
        window.open_paper("p3")
        with store.connect() as conn:
            conn.execute("UPDATE list_papers SET state='read' WHERE paper_id='p5'")
        window.go_back()
        assert reads == [True]
        assert [p.read for _i, p in page.model._rows] == [False, False, True, False, False, True]
        assert window.progress.text() == "已讀 2 · 未讀 4"

        # And another list is never mistaken for the one in memory.
        with store.connect() as conn:
            conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('other','other','now')")
        window._open_list("other")
        assert reads == [True, True] and page.model.rowCount() == 0
    finally:
        window.close()
        window.deleteLater()
