"""Actual collected heading A after Use Latest B: independent material provenance."""

import hashlib
import json
import sqlite3
from contextlib import closing
from types import MethodType

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_managed_reader_ui import open_pdf, wait_for
from test_managed_reader_ui import workspace as workspace
from test_raw_deck_receipts import no_external as no_external
from test_reader_preparation import settle

from paper_daily import figures, materials, paper_highlights, sync_capture
from paper_daily import research_generation as generation
from paper_daily.desktop import main
from paper_daily.desktop.document_flow import anchor_allowed, loaded_document_valid
from paper_daily.desktop.original_version import OriginalVersionDialog
from paper_daily.fetch import document_current
from paper_daily.sync_artifacts import desired_file, paper_current, verify_closure
from paper_daily.sync_files import file_id
from paper_daily.sync_source_files import publish


def await_owned(w, *names):
    for name in names:
        controller = getattr(w.widget, name, None)
        if controller is not None:
            try:
                settle(
                    w.app,
                    lambda owned=controller: (
                        not owned.busy and getattr(owned, "_worker", None) is None
                    ),
                )
            except BaseException:
                state = {}
                for owned_name in (
                    "document_runner",
                    "preparation",
                    "reading_positions",
                    "material_preparation",
                    "material_originals",
                ):
                    owned = getattr(w.widget, owned_name, None)
                    if owned is None:
                        continue
                    thread = getattr(owned, "_thread", None) or getattr(owned, "_worker", None)
                    state[owned_name] = dict(
                        busy=bool(owned.busy),
                        thread=type(thread).__name__ if thread is not None else None,
                        thread_running=thread.isRunning() if hasattr(thread, "isRunning") else None,
                        thread_finished=thread.isFinished()
                        if hasattr(thread, "isFinished")
                        else None,
                        pending=getattr(owned, "_pending", None) is not None,
                        source_pending=getattr(owned, "_source_pending", None),
                        token=getattr(owned, "_token", None),
                        epoch=getattr(owned, "_epoch", None),
                    )
                (w.root / "await-owned-failure.json").write_text(
                    json.dumps(dict(waiting_for=name, controllers=state), indent=2), encoding="utf8"
                )
                raise


def await_original(w):
    controller = getattr(w.widget, "material_originals", None)
    if controller is None:
        return
    await_owned(w, "material_originals")
    viewer = controller.viewer
    if viewer is not None:
        settle(
            w.app,
            lambda: (
                viewer.disposed
                or (viewer.pdf.pageCount() > 0 if viewer.native else viewer._rendered_page >= 0)
            ),
        )


@pytest.fixture(autouse=True)
def actual_desktop_capture_and_owned_drain(workspace):
    w = workspace
    with closing(generation._connect(w.side.journal.path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(
            conn, workspace_id=w.side.journal.workspace_id, device_id=w.side.journal.device_id
        )
    host = w.widget.win
    host._dive_job = None
    host._job_paper = None
    host.analysis_running = MethodType(main.MainWindow.analysis_running, host)
    yield
    for name in (
        "material_preparation",
        "material_originals",
        "active_originals",
        "preparation",
        "reading_positions",
    ):
        controller = getattr(w.widget, name, None)
        if controller is not None:
            close = getattr(controller, "request_close", None)
            if close is not None:
                close()
            await_owned(w, name)
            dispose = getattr(controller, "dispose", None)
            if dispose is not None:
                dispose()
    w.app.processEvents()


def saved_state(w):
    with closing(sqlite3.connect(w.side.journal.path.as_uri() + "?mode=ro", uri=True)) as conn:
        sql = list(conn.iterdump())
    return sql, {
        str(path.relative_to(w.root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in w.root.rglob("*")
        if path.is_file() and not path.name.endswith(("-wal", "-shm"))
    }


def test_actual_collected_a_material_opens_owned_original_after_use_latest_b(
    workspace, monkeypatch
):
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
    view.auto_highlights.setChecked(False)
    w.first = w.attach(
        "1 Original A Method\nAlpha scoped original material.\n2 Original A Results", "materials-a"
    )
    with w.side.journal.transaction() as conn:
        parent = w.side._optimistic_graph(conn)[0][("paper", w.identity)]["incarnation"]
    operation_a = publish(
        w.side,
        w.identity,
        w.root / "materials-a.pdf",
        document_hash=w.first.sha256,
        parent_incarnation=parent,
        store=w.blobs,
        version_root=w.root / "source-versions",
        request_id="material-original-a",
    )
    paper = next(paper for paper in w.data.queue(list_id=w.list_id) if paper.id == view.paper.id)
    view.load(paper)
    await_owned(w, "document_runner", "preparation", "reading_positions")
    open_pdf(w)
    document_a = view._active_document
    assert document_current(document_a) and document_a._owner.intact(document_a)
    pane = view.presentation_pane
    view.tabs.setCurrentWidget(pane)
    pane.load(view.paper.id, view.paper.title)
    assert pane.deck is None  # There is no active deck or proposal grant to borrow.
    found = []
    collect = materials.collect

    def observed(*args, **kwargs):
        result = collect(*args, **kwargs)
        found.append(result)
        return result

    monkeypatch.setattr(materials, "collect", observed)
    pane.materials_button.click()
    await_owned(w, "material_preparation")
    w.app.processEvents()
    assert len(found) == 1 and found[0].headings
    heading = next(row for row in found[0].headings if row["text"] == "1 Original A Method")
    assert heading["document_hash"] == document_a.sha256
    assert heading["navigation_available"] and heading["rect"]
    group = pane.materials_panel.tree.topLevelItem(1)
    node = next(
        group.child(index)
        for index in range(group.childCount())
        if group.child(index).data(0, Qt.ItemDataRole.UserRole)["text"] == heading["text"]
    )
    selected_a = node.data(0, Qt.ItemDataRole.UserRole)
    assert selected_a["document_hash"] == document_a.sha256
    view.note_edit.setPlainText("Keep this unsaved interpretation across the PDF switch")
    primary_b = w.attach(
        "1 Current B Material\nBeta current material.\n2 Current B Results", "materials-b"
    )
    view._check_document_update()
    assert view.document_refresh.isVisible()
    view.document_refresh.click()  # Actual explicit Use Latest action and document worker.
    wait_for(w.app, lambda: not view.document_runner.busy)
    await_owned(w, "preparation", "reading_positions")
    document_b = view._active_document
    assert document_b.sha256 == primary_b.sha256 != document_a.sha256
    assert loaded_document_valid(view) and not anchor_allowed(view, selected_a)
    assert document_a._owner.intact(document_a) and not document_current(document_a)
    assert node.data(0, Qt.ItemDataRole.UserRole) == selected_a
    assert view.note_edit.toPlainText() == "Keep this unsaved interpretation across the PDF switch"
    with w.side.journal.transaction() as conn:
        original = desired_file(conn, file_id(w.identity, "original_source", document_a.sha256))
        assert original == operation_a and paper_current(conn, original)
    _proof, original_body, original_bytes = verify_closure(w.blobs, original)
    assert original_body["document_hash"] == document_a.sha256
    assert original_bytes[document_a.sha256] == (w.root / "materials-a.pdf").read_bytes()
    fresh_b = collect(view.paper.id)
    assert any(row["text"] == "1 Current B Material" for row in fresh_b.headings)
    assert all(row.get("document_hash") == document_b.sha256 for row in fresh_b.headings)
    assert not any(row["text"] == heading["text"] for row in fresh_b.headings)

    def forbid_deck_grant(*_args, **_kwargs):
        raise AssertionError("Collected materials must not borrow active-deck authority")

    monkeypatch.setattr(view.active_originals, "open", forbid_deck_grant)
    seen, focus, scroll = [], [], []
    pane.materials_panel.source_requested.connect(seen.append)
    typed_seen = []
    typed_signal = getattr(pane.materials_panel, "source_selection_requested", None)
    if typed_signal is not None:
        typed_signal.connect(typed_seen.append)
    original_focus, original_scroll = view.pdf.selection.focus, view.pdf.selection.scroll_to_page

    def observe_focus(anchor):
        focus.append(anchor)
        return original_focus(anchor)

    def observe_scroll(page):
        scroll.append(page)
        return original_scroll(page)

    monkeypatch.setattr(view.pdf.selection, "focus", observe_focus)
    monkeypatch.setattr(view.pdf.selection, "scroll_to_page", observe_scroll)
    group.setExpanded(True)
    pane.materials_panel.tree.setCurrentItem(node)
    pane.materials_panel.tree.scrollToItem(node)
    w.app.processEvents()
    before = saved_state(w)
    b_bytes = document_b.path.read_bytes()
    QTest.mouseClick(
        pane.materials_panel.tree.viewport(),
        Qt.MouseButton.LeftButton,
        pos=pane.materials_panel.tree.visualItemRect(node).center(),
    )
    w.app.processEvents()
    await_original(w)
    if getattr(view, "material_originals", None) is not None:
        assert len(typed_seen) == 1 and typed_seen[0].payload == selected_a
    assert seen == [selected_a] and not focus and not scroll
    assert view._active_document is document_b and view._pdf_fingerprint == document_b.sha256
    assert document_b.path.read_bytes() == b_bytes
    assert view.note_edit.toPlainText() == "Keep this unsaved interpretation across the PDF switch"
    assert saved_state(w) == before
    viewers = [
        item
        for item in QApplication.topLevelWidgets()
        if isinstance(item, OriginalVersionDialog) and item.isVisible()
    ]
    info = w.side.journal.path.stat()
    observation = dict(
        mode="managed",
        database_native=[info.st_dev, info.st_ino],
        collected_source_hash=document_a.sha256,
        loaded_hash=document_b.sha256,
        source_operation=operation_a,
        source_owner_parent=parent,
        material_payload=selected_a,
        collection_fields=list(found[0].__dataclass_fields__),
        source_a_intact=True,
        source_a_is_current=False,
        fresh_collection_has_only_b=True,
        stale_selected_a_survives=True,
        sql_and_nonjournal_files_unchanged=True,
        b_focus_and_scroll_calls=0,
        deck_grant_used=False,
        independent_original_views=len(viewers),
        status=pane.status.text(),
    )
    (w.root / "observed-material-navigation.json").write_text(
        json.dumps(observation, indent=2), encoding="utf8"
    )
    assert len(viewers) == 1, "Missing independent historical-material source adapter"
    assert viewers[0].snapshot.data == original_bytes[document_a.sha256]
    assert viewers[0].snapshot.document_hash == document_a.sha256
