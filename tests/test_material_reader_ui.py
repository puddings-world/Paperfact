"""Real reader material refresh, version navigation and owned background jobs."""

import json
import sqlite3
import threading
from contextlib import closing

import pytest
from PySide6.QtCore import Qt, QThread
from PySide6.QtTest import QTest
from test_material_original_navigation_audit import (
    actual_desktop_capture_and_owned_drain as actual_desktop_capture_and_owned_drain,
)
from test_material_original_navigation_audit import await_original, await_owned
from test_material_original_navigation_audit import no_external as no_external
from test_material_original_navigation_audit import workspace as workspace
from test_reader_preparation import settle

from paper_daily import figures, material_sources, materials, paper_highlights, store
from paper_daily.desktop import main, material_preparation
from paper_daily.desktop.slide_canvas import MATERIAL_MIME
from paper_daily.sync_source_files import publish


def sql(w):
    with closing(sqlite3.connect(w.side.journal.path.as_uri() + "?mode=ro", uri=True)) as conn:
        return list(conn.iterdump())


@pytest.fixture
def loaded(workspace, monkeypatch, request):
    w, view = workspace, workspace.widget
    for name, value in (
        ("DATA_DIR", w.root),
        ("FIG_DIR", w.root / "figures"),
        ("TEXT_DIR", w.root / "text"),
        ("PDF_DIR", w.root / "legacy-pdf"),
    ):
        monkeypatch.setattr(materials, name, value)
    monkeypatch.setattr(figures, "FIG_DIR", w.root / "figures")
    monkeypatch.setattr(paper_highlights, "CACHE_DIR", w.root / "paper-highlights")
    view.win.reader_page = view
    view.auto_highlights.setChecked(False)
    w.first = w.attach("1 Original A Method\nAlpha material.\n2 Original A Results", "material-a")
    if getattr(request, "param", True):
        with w.side.journal.transaction() as conn:
            parent = w.side._optimistic_graph(conn)[0][("paper", w.identity)]["incarnation"]
        publish(
            w.side,
            w.identity,
            w.root / "material-a.pdf",
            document_hash=w.first.sha256,
            parent_incarnation=parent,
            store=w.blobs,
            version_root=w.root / "originals",
            request_id="retain-material-a",
        )
    view.load(w.data.queue(list_id=w.list_id)[0])
    await_owned(w, "document_runner", "preparation", "reading_positions")
    assert view._active_document.sha256 == w.first.sha256
    pane = view.presentation_pane
    view.tabs.setCurrentWidget(pane)
    pane.load(view.paper.id, view.paper.title)
    view.note_edit.setPlainText("Unsent research interpretation")
    return w


def collect(w):
    pane = w.widget.presentation_pane
    if not pane.materials_button.isChecked():
        pane.materials_button.click()
    else:
        pane.materials_panel.refresh.click()
    await_owned(w, "material_preparation")
    panel = pane.materials_panel
    assert panel._source_collection is not None, pane.status.text()
    assert panel.refresh.isEnabled()
    return panel


def heading(panel):
    group = panel.tree.topLevelItem(1)
    assert group.childCount() == 2
    group.setExpanded(True)
    return group.child(0)


def click(w, panel, node):
    panel.tree.setCurrentItem(node)
    panel.tree.scrollToItem(node)
    w.app.processEvents()
    QTest.mouseClick(
        panel.tree.viewport(),
        Qt.MouseButton.LeftButton,
        pos=panel.tree.visualItemRect(node).center(),
    )


def use_b(w):
    replacement = w.attach("1 Current B Method\nBeta material.\n2 Current B Results", "material-b")
    w.widget._check_document_update()
    w.widget.document_refresh.click()
    await_owned(w, "document_runner", "preparation", "reading_positions")
    assert w.widget._active_document.sha256 == replacement.sha256 != w.first.sha256
    return replacement


def hold(monkeypatch, module, name, *, requests=None):
    entered, release, calls = threading.Event(), threading.Event(), []
    original = getattr(module, name)

    def controlled(*args, **kwargs):
        calls.append(QThread.currentThread())
        if requests is not None:
            requests.append(args[0])
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, controlled)
    return entered, release, calls


def test_refresh_coalesces_off_gui_and_publishes_plain_materials_without_saving_drafts(
    loaded,
    monkeypatch,
):
    w, view = loaded, loaded.widget
    before = sql(w)
    entered, release, calls = hold(monkeypatch, material_preparation, "_collect")
    try:
        view.presentation_pane.materials_button.click()
        settle(w.app, entered.is_set)
        panel = view.presentation_pane.materials_panel
        for _ in range(50):
            assert not view.material_preparation.request()
            panel.refresh.click()
        assert len(calls) == 1 and calls[0] is not w.app.thread()
        assert view.material_preparation.busy and not panel.refresh.isEnabled()
    finally:
        release.set()
    await_owned(w, "material_preparation")
    node = heading(panel)
    payload = node.data(0, Qt.ItemDataRole.UserRole)
    assert payload["document_hash"] == w.first.sha256
    assert json.loads(bytes(panel.tree.mimeData([node]).data(MATERIAL_MIME))) == payload
    assert panel.refresh.isEnabled() and sql(w) == before
    assert view.note_edit.toPlainText() == "Unsent research interpretation"


def test_failed_refresh_preserves_visible_collection_and_explicit_retry_works(loaded, monkeypatch):
    w = loaded
    panel = collect(w)
    old = panel._source_collection
    content = heading(panel).data(0, Qt.ItemDataRole.UserRole)
    before = sql(w)
    original = material_preparation._collect

    def fail(*_args):
        raise RuntimeError("PRIVATE SQL AND PATH DETAILS")

    monkeypatch.setattr(material_preparation, "_collect", fail)
    panel.refresh.click()
    await_owned(w, "material_preparation")
    assert panel._source_collection is old and panel.refresh.isEnabled()
    assert heading(panel).data(0, Qt.ItemDataRole.UserRole) == content
    assert "PRIVATE" not in w.widget.presentation_pane.status.text()
    assert sql(w) == before
    monkeypatch.setattr(material_preparation, "_collect", original)
    collect(w)
    assert panel._source_collection is not old
    assert heading(panel).data(0, Qt.ItemDataRole.UserRole) == content
    assert sql(w) == before


@pytest.mark.parametrize("change", ["paper", "source", "workspace", "close"])
def test_pending_collection_never_publishes_after_context_change(loaded, monkeypatch, change):
    w, view = loaded, loaded.widget
    panel = collect(w)
    previous = panel._source_collection
    requests = []
    entered, release, calls = hold(monkeypatch, material_preparation, "_collect", requests=requests)
    other = w.root / "other-workspace.db"
    with closing(sqlite3.connect(other)) as conn, conn:
        conn.execute("CREATE TABLE sentinel(value TEXT)")
        conn.execute("INSERT INTO sentinel VALUES('unrelated workspace')")
    other_bytes = other.read_bytes()
    try:
        panel.refresh.click()
        settle(w.app, entered.is_set)
        if change == "paper":
            view.load(w.data.queue(list_id=w.list_id)[0])
        elif change == "source":
            use_b(w)
        elif change == "workspace":
            monkeypatch.setattr(store, "DB_PATH", other)
        else:
            assert not main.MainWindow._preparation_ready(view.win)
            assert not view.close()
        assert view.material_preparation.busy and len(calls) == 1
    finally:
        release.set()
    await_owned(w, "material_preparation")
    if change == "paper":
        # Reopening legitimately requests new materials. Prove it is the new
        # reader owner, rather than admitting the cancelled old result.
        assert len(requests) == 2 and requests[0].stop.is_set()
        assert requests[0].owner is not requests[1].owner
        assert requests[1].owner is view._highlight_owner
        assert panel._source_collection is not previous
        assert panel._source_collection.document_hash == view._pdf_fingerprint
    else:
        assert panel._source_collection is previous
    assert panel.refresh.isEnabled() and other.read_bytes() == other_bytes
    assert view.note_edit.toPlainText() == "Unsent research interpretation"
    if change == "source":
        collect(w)
        assert heading(panel).data(0, Qt.ItemDataRole.UserRole)["document_hash"] != w.first.sha256


def test_repeated_old_material_click_opens_one_exact_original_and_preserves_current_pdf(
    loaded,
    monkeypatch,
):
    w, view = loaded, loaded.widget
    panel = collect(w)
    node = heading(panel)
    replacement = use_b(w)
    before = sql(w)
    entered, release, calls = hold(monkeypatch, material_sources, "prepare")
    try:
        click(w, panel, node)
        settle(w.app, entered.is_set)
        for _ in range(25):
            click(w, panel, node)
        assert len(calls) == 1 and calls[0] is not w.app.thread()
        assert view.material_originals.busy
    finally:
        release.set()
    await_original(w)
    viewer = view.material_originals.viewer
    assert viewer is not None and viewer.snapshot.data == (w.root / "material-a.pdf").read_bytes()
    assert view._active_document.sha256 == replacement.sha256
    assert sql(w) == before and view.note_edit.toPlainText() == "Unsent research interpretation"
    click(w, panel, node)
    assert view.material_originals.viewer is viewer and len(calls) == 1
    viewer.close()
    settle(w.app, lambda: view.material_originals.viewer is None)
    assert not view.material_originals.busy
    click(w, panel, node)
    await_original(w)
    assert view.material_originals.viewer is not viewer and len(calls) == 2
    assert view.material_originals.viewer.snapshot.document_hash == w.first.sha256


@pytest.mark.parametrize("loaded", [False], indirect=True)
def test_unretained_original_keeps_material_content_and_explains_unavailable(loaded):
    w, view = loaded, loaded.widget
    panel = collect(w)
    node = heading(panel)
    payload = node.data(0, Qt.ItemDataRole.UserRole)
    assert not panel._source_collection.historical_available
    use_b(w)
    click(w, panel, node)
    assert not view.material_originals.busy and view.material_originals.viewer is None
    assert node.data(0, Qt.ItemDataRole.UserRole) == payload
    assert "保存原文" in view.presentation_pane.status.text()


def test_modified_material_cannot_open_historical_original(loaded):
    w, view = loaded, loaded.widget
    panel = collect(w)
    node = heading(panel)
    use_b(w)
    payload = node.data(0, Qt.ItemDataRole.UserRole)
    node.setData(0, Qt.ItemDataRole.UserRole, dict(payload, text="Not the captured passage"))
    click(w, panel, node)
    assert not view.material_originals.busy and view.material_originals.viewer is None
    assert panel.feedback.isVisible()
    assert view.note_edit.toPlainText() == "Unsent research interpretation"


def test_original_failure_keeps_content_and_explicit_retry_opens_same_a(loaded, monkeypatch):
    w, view = loaded, loaded.widget
    panel = collect(w)
    node = heading(panel)
    payload = node.data(0, Qt.ItemDataRole.UserRole)
    use_b(w)
    before = sql(w)
    original = material_sources.prepare

    def fail(*_args, **_kwargs):
        raise RuntimeError("PRIVATE ORIGINAL PATH")

    monkeypatch.setattr(material_sources, "prepare", fail)
    click(w, panel, node)
    await_original(w)
    assert view.material_originals.viewer is None and not view.material_originals.busy
    assert "PRIVATE" not in view.presentation_pane.status.text()
    assert node.data(0, Qt.ItemDataRole.UserRole) == payload and sql(w) == before
    monkeypatch.setattr(material_sources, "prepare", original)
    click(w, panel, node)
    await_original(w)
    assert view.material_originals.viewer.snapshot.document_hash == w.first.sha256
    assert sql(w) == before


@pytest.mark.parametrize("change", ["selection", "paper", "source", "workspace", "close"])
def test_pending_original_does_not_open_after_context_change(loaded, monkeypatch, change):
    w, view = loaded, loaded.widget
    panel = collect(w)
    node = heading(panel)
    current = use_b(w)
    entered, release, calls = hold(monkeypatch, material_sources, "prepare")
    other = w.root / "independent.db"
    with closing(sqlite3.connect(other)) as conn, conn:
        conn.execute("CREATE TABLE unrelated(value TEXT)")
    other_bytes = other.read_bytes()
    try:
        click(w, panel, node)
        settle(w.app, entered.is_set)
        if change == "selection":
            panel.tree.setCurrentItem(node.parent().child(1))
        elif change == "paper":
            view.load(w.data.queue(list_id=w.list_id)[0])
        elif change == "source":
            newest = w.attach(
                "1 Current C Method\nGamma material.\n2 Current C Results", "material-c"
            )
            view._check_document_update()
            view.document_refresh.click()
            await_owned(w, "document_runner", "preparation", "reading_positions")
            assert view._active_document.sha256 == newest.sha256
        elif change == "workspace":
            monkeypatch.setattr(store, "DB_PATH", other)
        else:
            assert not main.MainWindow._preparation_ready(view.win)
            assert not view.close()
        assert len(calls) == 1 and view.material_originals.busy
    finally:
        release.set()
    await_owned(w, "material_originals", "material_preparation")
    assert view.material_originals.viewer is None
    assert other.read_bytes() == other_bytes
    if change in ("selection", "workspace", "close"):
        assert view._active_document.sha256 == current.sha256
    assert view.note_edit.toPlainText() == "Unsent research interpretation"


def test_selecting_another_material_queues_only_latest_after_old_work_drains(loaded, monkeypatch):
    w, view = loaded, loaded.widget
    panel = collect(w)
    first = heading(panel)
    second = first.parent().child(1)
    use_b(w)
    entered, release, calls = hold(monkeypatch, material_sources, "prepare")
    try:
        click(w, panel, first)
        settle(w.app, entered.is_set)
        for _ in range(25):
            click(w, panel, second)
        assert len(calls) == 1 and view.material_originals.busy
    finally:
        release.set()
    await_original(w)
    viewer = view.material_originals.viewer
    assert viewer is not None and viewer.snapshot.document_hash == w.first.sha256
    assert len(calls) == 2
    assert view.material_originals._context.selection.payload == second.data(
        0, Qt.ItemDataRole.UserRole
    )
    assert view.note_edit.toPlainText() == "Unsent research interpretation"
