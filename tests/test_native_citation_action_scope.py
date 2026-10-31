"""Native citation actions retain their displayed paper and workspace."""

import shutil
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from paper_daily import followups, store
from paper_daily.desktop import cites_pane
from paper_daily.desktop.main import LIGHT


@pytest.fixture
def setup(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "a.sqlite"
    monkeypatch.setattr(store, "DB_PATH", path)
    store.init_db()
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                dict(
                    id=pid,
                    title="Unique focal investigation " + pid,
                    venue="",
                    year=2026,
                    source="fixture",
                )
                for pid in ("A", "B")
            ],
        )
        for pid in ("A", "B"):
            conn.execute(
                "INSERT INTO cites(paper_id,ref_key,title,purpose,written_at) VALUES(?,?,?,?,?)",
                (pid, "1", "A real reference title", "Original " + pid, "2026-10-31T00:00:00Z"),
            )
    host = SimpleNamespace(
        active_list="list-A", in_queue=lambda _pid: False, analysis_running=lambda _pid=None: False
    )
    pane = cites_pane.CitesPane(host, LIGHT)
    pane.paper_id = "A"
    reloads = []
    monkeypatch.setattr(pane, "_reload", lambda: reloads.append(pane.paper_id))
    with store.connect() as conn:
        reference = followups.references(conn, "A")[0]
    reference["here"] = None
    holder = QWidget()
    holder.setLayout(pane._actions(reference, True, "ref"))
    edit = next(b for b in holder.findChildren(QPushButton) if b.text() == "\u7de8\u8f2f")
    seen = []

    def execute(dialog):
        seen.append(pane.paper_id)
        dialog.findChildren(QPlainTextEdit)[0].setPlainText("User revision")
        buttons = dialog.findChild(QDialogButtonBox)
        buttons.button(QDialogButtonBox.StandardButton.Save).click()
        assert dialog.result() == QDialog.DialogCode.Accepted
        return dialog.result()

    monkeypatch.setattr(QDialog, "exec", execute)
    yield app, path, host, pane, holder, edit, seen, reloads
    holder.close()
    pane.close()
    holder.deleteLater()
    pane.deleteLater()
    app.processEvents()


def values(path):
    with closing(sqlite3.connect(path)) as conn:
        return dict(conn.execute("SELECT paper_id,purpose FROM cites ORDER BY paper_id"))


@pytest.mark.parametrize(
    "change", ["none", "paper", "workspace", "list", "reload", "close", "replacement", "owner"]
)
def test_native_citation_edit_uses_only_its_displayed_context(setup, monkeypatch, change):
    _app, path, host, pane, _holder, edit, seen, reloads = setup
    other = None
    if change == "paper":
        pane.paper_id = "B"
    elif change == "workspace":
        other = path.with_name("b.sqlite")
        with closing(sqlite3.connect(other)) as conn:
            conn.executescript(store.SCHEMA)
            store.upsert_papers(
                conn,
                [
                    dict(
                        id="A",
                        title="Other workspace focal investigation",
                        year=2026,
                        venue="",
                        source="fixture",
                    )
                ],
            )
            conn.execute(
                "INSERT INTO cites(paper_id,ref_key,title,purpose,written_at) VALUES(?,?,?,?,?)",
                (
                    "A",
                    "1",
                    "Other workspace reference",
                    "Other workspace original",
                    "2026-10-31T00:00:00Z",
                ),
            )
            conn.commit()
        monkeypatch.setattr(store, "DB_PATH", other)
    elif change == "list":
        host.active_list = "list-B"
    elif change == "reload":
        pane._clear()
    elif change == "close":
        pane.close()
    elif change == "replacement":
        replacement = path.with_name("replacement.sqlite")
        shutil.copyfile(path, replacement)
        replacement.replace(path)
    elif change == "owner":
        host._workspace_owner = SimpleNamespace(current=lambda: False)
    edit.click()
    assert values(path) == {
        "A": "User revision" if change == "none" else "Original A",
        "B": "Original B",
    }
    if other:
        assert values(other) == {"A": "Other workspace original"}
    assert seen == (["A"] if change == "none" else [])
    assert reloads == (["A"] if change == "none" else [])


def test_duplicate_native_add_has_one_submission(setup, monkeypatch):
    _app, _path, _host, pane, holder, _edit, _seen, _reloads = setup
    submissions = []
    monkeypatch.setattr(
        pane, "_send_to_list", lambda row: submissions.append(dict(row)) or "list-A"
    )
    add = next(
        b for b in holder.findChildren(QPushButton) if b.text() == "\u52a0\u5165\u6e05\u55ae"
    )
    add.clicked.emit()
    add.clicked.emit()
    assert submissions == [{"title": "A real reference title", "doi": None}]
    assert not add.isEnabled()


def test_delayed_native_projection_never_reads_next_workspace(setup, monkeypatch):
    app, path, _host, pane, _holder, _edit, _seen, _reloads = setup
    pane.load("A")
    generation = pane._generation
    other = path.with_name("next.sqlite")
    with closing(sqlite3.connect(other)) as conn, conn:
        conn.execute("CREATE TABLE private_sentinel(value TEXT)")
        conn.execute("INSERT INTO private_sentinel VALUES('untouched')")
    before = other.read_bytes()
    reads = []
    original = cites_pane.connect

    def observed(*args, **kwargs):
        reads.append(str(kwargs.get("path", store.DB_PATH)))
        return original(*args, **kwargs)

    monkeypatch.setattr(cites_pane, "connect", observed)
    monkeypatch.setattr(store, "DB_PATH", other)
    from PySide6.QtCore import QTimer

    QTimer.singleShot(0, pane, lambda: pane._prepare_rest(generation))
    QTimer.singleShot(0, pane, pane._links_done)
    app.processEvents()
    assert reads == []
    assert other.read_bytes() == before
    replacement = path.with_name("other-replacement.sqlite")
    replacement.write_bytes(before)
    replacement.replace(other)
    assert other.read_bytes() == before


@pytest.mark.parametrize("changed", [False, True])
def test_actual_map_add_callback_keeps_displayed_list_and_notice(setup, monkeypatch, changed):
    _app, path, host, pane, _holder, _edit, _seen, _reloads = setup
    host.open_paper = lambda _pid: None
    submitted = []
    monkeypatch.setattr(cites_pane, "_spawn", lambda *args: submitted.append(args))
    pane.load("A")
    pane._build_graph_face()
    graph = pane._map
    note = pane._graph_note
    previous = note.text()
    from paper_daily.citegraph import Node

    item = Node(key="ref:external", title="An external reference worth reading", side="ref")
    if changed:
        host.active_list = "list-B"
        pane.paper_id = "B"
    graph.on_add(item)
    assert submitted == (
        [] if changed else [("list-add", "list-A", "An external reference worth reading")]
    )
    assert (note.text() == previous) == changed
    assert values(path) == {"A": "Original A", "B": "Original B"}
