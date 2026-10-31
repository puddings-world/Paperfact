"""Progressive thumbnail work yields while keeping real slide data unchanged."""

import copy
import os
import sqlite3
import time
from contextlib import closing
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt, QThread, QTimer
from PySide6.QtGui import QColor, QImage, QPalette, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete, isValid
from test_audit_decks import saved as saved_fixture

from paper_daily import llm, presentations, store
from paper_daily.desktop import slide_thumbnails
from paper_daily.desktop.presentation_pane import PresentationPane
from paper_daily.desktop.window_workspace import WindowWorkspace

saved = saved_fixture


@pytest.fixture
def deck_view(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(presentations, "DECK_DIR", tmp_path / "decks")
    store.init_db()
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [dict(id="paper", title="Fixture paper", year=2026, venue="Fixture", source="fixture")],
        )
    slides = [
        presentations.Slide(
            f"Page {i + 1}",
            "Method",
            f"Claim {i + 1}",
            ["Exact saved content"],
            "Exact saved script",
            ["original"],
        )
        for i in range(24)
    ]
    deck = presentations.Deck(
        "paper",
        "Fixture paper",
        "Fixture deck",
        "guide",
        "Researchers",
        15,
        slides,
        [{"id": "original", "label": "Original", "kind": "original", "page": 1}],
        [],
        [],
        "2026-10-31",
    )
    presentations.save_deck(deck)
    widget = PresentationPane()
    widget.language = "en"
    # Establish normal paper-open ownership before measuring rendering-only effects.
    widget.load(deck.paper_id, deck.paper_title)
    yield widget, deck, app, tmp_path
    if isValid(widget):
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def saved_rows(database):
    with closing(sqlite3.connect(database)) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {
            name: conn.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall()
            for name in tables
        }


def test_long_deck_returns_and_services_gui_before_all_real_icons_are_drawn(deck_view, monkeypatch):
    widget, deck, app, _tmp = deck_view
    before = saved_rows(store.DB_PATH)
    stored = presentations.load_deck(deck.paper_id, deck.mode).to_dict()
    rendered, heartbeat = [], []
    actual = widget._thumbnail_canvas.scene.render

    def draw(*args, **kwargs):
        rendered.append(True)
        return actual(*args, **kwargs)

    monkeypatch.setattr(widget._thumbnail_canvas.scene, "render", draw)
    QTimer.singleShot(0, lambda: heartbeat.append(len(rendered)))
    widget.load(deck.paper_id, deck.paper_title)
    assert widget.outline.count() == len(deck.slides)
    assert len(rendered) < len(deck.slides), "All slide icons were drawn before load returned"
    app.processEvents()
    assert heartbeat and heartbeat[0] < len(deck.slides)
    assert saved_rows(store.DB_PATH) == before
    assert presentations.load_deck(deck.paper_id, deck.mode).to_dict() == stored


def until(app, predicate):
    deadline = time.monotonic() + 10
    while not predicate():
        assert time.monotonic() < deadline, "GUI thumbnail queue did not drain"
        app.processEvents()
        QTest.qWait(1)


def drain(widget, app):
    until(app, lambda: not widget._thumbnails.pending)


def track(monkeypatch):
    calls = []
    actual = slide_thumbnails.draw

    def draw(pane, deck, index):
        calls.append((deck.paper_id, index, deck.slides[index].title))
        return actual(pane, deck, index)

    monkeypatch.setattr(slide_thumbnails, "draw", draw)
    return calls


def icon(widget, index=0):
    return widget.outline.item(index).icon().pixmap(*slide_thumbnails.SIZE).toImage()


def test_real_icons_selected_first_and_a_midstream_gui_action_runs_before_completion(
    deck_view, monkeypatch
):
    widget, deck, app, _tmp = deck_view
    calls = track(monkeypatch)
    observations = []
    actual = slide_thumbnails.draw

    def draw(pane, drawing_deck, index):
        image = actual(pane, drawing_deck, index)
        if len(calls) == 1:
            QTimer.singleShot(0, lambda: observations.append(len(calls)))
        return image

    monkeypatch.setattr(slide_thumbnails, "draw", draw)
    widget.load(deck.paper_id, deck.paper_title)
    placeholder = icon(widget, 8)
    widget.outline.setCurrentRow(8)
    drain(widget, app)
    assert calls[0][1] == 8
    assert len(calls) == len(deck.slides)
    assert observations and observations[0] < len(deck.slides)
    assert widget.outline.currentRow() == 8 and widget._index == 8
    assert icon(widget, 8) != placeholder
    assert all(not widget.outline.item(i).icon().isNull() for i in range(len(deck.slides)))
    assert all(not widget.outline.item(i).toolTip() for i in range(len(deck.slides)))


def test_repeated_pending_requests_deduplicate_and_do_not_edit_saved_content(
    deck_view, monkeypatch
):
    widget, deck, app, _tmp = deck_view
    drain(widget, app)
    rows, body = saved_rows(store.DB_PATH), deck.to_dict()
    calls = track(monkeypatch)
    for _ in range(80):
        widget._thumbnail(7)
    drain(widget, app)
    assert calls == [(deck.paper_id, 7, "Page 8")]
    assert saved_rows(store.DB_PATH) == rows
    assert presentations.load_deck(deck.paper_id, deck.mode).to_dict() == body
    assert not widget._dirty and not widget._canvas_dirty


def test_edit_while_queued_draws_current_content_without_extra_saved_writes(deck_view, monkeypatch):
    widget, deck, app, _tmp = deck_view
    drain(widget, app)
    before_icon = icon(widget)
    calls = track(monkeypatch)
    widget._thumbnail(0)
    widget.slide_title.setText("Edited central result")
    assert widget.save_changes()
    expected = presentations.load_deck(deck.paper_id, deck.mode).to_dict()
    rows = saved_rows(store.DB_PATH)
    drain(widget, app)
    assert calls[0][2] == "Edited central result"
    assert icon(widget) != before_icon
    assert presentations.load_deck(deck.paper_id, deck.mode).to_dict() == expected
    assert saved_rows(store.DB_PATH) == rows
    assert expected["slides"][0]["title"] == "Edited central result"


def test_actual_reorder_revokes_old_queue_and_keeps_selected_slide_and_saved_order(
    deck_view, monkeypatch
):
    widget, deck, app, _tmp = deck_view
    calls = track(monkeypatch)
    widget.load(deck.paper_id, deck.paper_title)
    widget._move(1)
    expected = presentations.load_deck(deck.paper_id, deck.mode).to_dict()
    rows = saved_rows(store.DB_PATH)
    drain(widget, app)
    assert calls[0][1:] == (1, "Page 1")
    assert len(calls) == len(deck.slides)
    assert widget.outline.currentRow() == 1 and widget.deck.slides[1].title == "Page 1"
    assert [x["title"] for x in expected["slides"][:2]] == ["Page 2", "Page 1"]
    assert presentations.load_deck(deck.paper_id, deck.mode).to_dict() == expected
    assert saved_rows(store.DB_PATH) == rows


def other_deck(deck, count=3):
    value = presentations.deck_from_dict(deck.to_dict())
    value.paper_id = "other"
    value.paper_title = "Other paper"
    value.slides = [replace(s, title=f"Other {i}") for i, s in enumerate(value.slides[:count])]
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [dict(id="other", title="Other paper", year=2026, venue="Fixture", source="fixture")],
        )
    presentations.save_deck(value)
    return value


def test_fast_paper_switch_never_renders_or_installs_the_revoked_deck(deck_view, monkeypatch):
    widget, deck, app, _tmp = deck_view
    other = other_deck(deck)
    calls = track(monkeypatch)
    widget.load(deck.paper_id, deck.paper_title)
    widget.load(other.paper_id, other.paper_title)
    rows = saved_rows(store.DB_PATH)
    drain(widget, app)
    assert [c[0] for c in calls] == [other.paper_id] * len(other.slides)
    assert widget.outline.count() == 3
    assert [widget.outline.item(i).text() for i in range(3)] == [
        f"{i + 1}. Other {i}" for i in range(3)
    ]
    assert saved_rows(store.DB_PATH) == rows


def test_deck_switch_during_actual_render_cannot_install_old_icon(deck_view, monkeypatch):
    widget, deck, app, _tmp = deck_view
    other = other_deck(deck, count=1)
    original = slide_thumbnails.draw
    switched = []

    def drawing(pane, captured_deck, index):
        original(pane, captured_deck, index)
        image = QPixmap(*slide_thumbnails.SIZE)
        image.fill(QColor("red" if captured_deck.paper_id == "paper" else "blue"))
        if not switched:
            switched.append(True)
            widget.load(other.paper_id, other.paper_title)
        return image

    monkeypatch.setattr(slide_thumbnails, "draw", drawing)
    widget.load(deck.paper_id, deck.paper_title)
    drain(widget, app)
    assert switched and widget.deck.paper_id == "other"
    assert icon(widget).pixelColor(144, 81) == QColor("blue")
    assert widget.outline.item(0).text() == "1. Other 0"


@pytest.mark.parametrize("action", ["close", "hide"])
def test_close_or_hide_revokes_queued_draws_and_show_can_prepare_again(
    deck_view, monkeypatch, action
):
    widget, deck, app, _tmp = deck_view
    widget.show()
    drain(widget, app)
    calls = track(monkeypatch)
    rows = saved_rows(store.DB_PATH)
    widget._thumbnails.refresh()
    getattr(widget, action)()
    QCoreApplication.sendEvent(widget, QEvent(QEvent.Type.PaletteChange))
    app.processEvents()
    assert calls == [] and not widget._thumbnails.pending
    assert saved_rows(store.DB_PATH) == rows
    widget.show()
    drain(widget, app)
    assert len(calls) == len(deck.slides)
    assert widget.outline.currentRow() == 0


def test_failed_icon_is_sanitized_and_real_row_click_retries_once(deck_view, monkeypatch):
    widget, deck, app, _tmp = deck_view
    widget.resize(900, 700)
    widget.show()
    drain(widget, app)
    original = slide_thumbnails.draw
    failed = []

    def draw(pane, captured_deck, index):
        if index == 0 and not failed:
            failed.append(True)
            raise OSError("private fixture payload must never be shown")
        return original(pane, captured_deck, index)

    monkeypatch.setattr(slide_thumbnails, "draw", draw)
    rows = saved_rows(store.DB_PATH)
    widget._thumbnail(0)
    placeholder = icon(widget)
    drain(widget, app)
    assert widget.outline.item(0).toolTip() == slide_thumbnails.COPY["en"][1]
    assert icon(widget) == placeholder
    assert "private" not in widget.outline.item(0).toolTip()
    rect = widget.outline.visualItemRect(widget.outline.item(0))
    QTest.mouseClick(widget.outline.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    drain(widget, app)
    assert icon(widget) != placeholder and widget.outline.item(0).toolTip() == ""
    assert saved_rows(store.DB_PATH) == rows


def test_palette_and_icon_size_change_revoke_old_context_without_saved_mutation(
    deck_view, monkeypatch
):
    widget, deck, app, _tmp = deck_view
    widget.show()
    drain(widget, app)
    calls = track(monkeypatch)
    rows = saved_rows(store.DB_PATH)
    previous = app.palette()
    try:
        changed = QPalette(previous)
        changed.setColor(QPalette.ColorRole.Base, QColor("#152333"))
        app.setPalette(changed)
        widget.outline.setIconSize(QSize(160, 90))
        drain(widget, app)
        assert len(calls) >= len(deck.slides)
        assert {c[1] for c in calls} == set(range(len(deck.slides)))
        assert widget.outline.iconSize() == QSize(160, 90)
        assert saved_rows(store.DB_PATH) == rows
    finally:
        app.setPalette(previous)


def test_mutable_legacy_asset_bytes_are_read_again_instead_of_reusing_an_icon(deck_view):
    widget, deck, app, _tmp = deck_view
    drain(widget, app)
    value = presentations.deck_from_dict(deck.to_dict())
    value.sources.append(dict(id="figure:1", label="Chart", kind="figure", page=1))
    value.figures.append(dict(id="figure:1", label="Chart", caption="Chart", asset="chart.png"))
    value.slides[0].sources.append("figure:1")
    value.slides[0].elements = [dict(kind="figure", figure="figure:1", x=100, y=100, w=1000, h=450)]
    target = presentations._folder(deck.paper_id) / "assets" / "chart.png"
    target.parent.mkdir(parents=True, exist_ok=True)

    def replace_asset(color):
        image = QImage(32, 24, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        assert image.save(str(target), "PNG")

    replace_asset("red")
    presentations.save_deck(value)
    widget.load(value.paper_id, value.paper_title)
    drain(widget, app)
    assert icon(widget).pixelColor(144, 81) == QColor("red")
    body, rows = value.to_dict(), saved_rows(store.DB_PATH)
    replace_asset("blue")
    widget._thumbnail(0)
    drain(widget, app)
    assert icon(widget).pixelColor(144, 81) == QColor("blue")
    assert presentations.load_deck(value.paper_id, value.mode).to_dict() == body
    assert saved_rows(store.DB_PATH) == rows


def test_real_enrolled_deck_render_preserves_typed_content_operation_and_outbox(saved, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(presentations, "DECK_DIR", saved.root / "legacy-decks")
    widget = PresentationPane()
    try:
        widget.load(saved.deck.paper_id, saved.deck.paper_title)
        body = widget.deck.to_dict()
        operation = copy.deepcopy(widget.deck._file_operation)
        rows = saved_rows(saved.path)
        outbox = saved.client.journal.pending()
        assert outbox and any(op["entity_type"] == "research_file" for op in outbox)
        for _ in range(40):
            widget._thumbnail(0)
        drain(widget, app)
        assert not widget.outline.item(0).icon().isNull()
        assert widget.outline.item(0).toolTip() == ""
        assert widget.deck.to_dict() == body and widget.deck._file_operation == operation
        assert saved_rows(saved.path) == rows
        assert saved.client.journal.pending() == outbox
        assert not widget._dirty and not widget._canvas_dirty
    finally:
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_destroyed_pane_cannot_deliver_queued_icons(deck_view, monkeypatch):
    widget, _deck, app, _tmp = deck_view
    calls = track(monkeypatch)
    controller = widget._thumbnails
    assert controller.pending
    delete(widget)
    app.processEvents()
    assert not isValid(widget) and controller._disposed
    assert calls == []


def test_reentrant_request_revokes_first_draw_and_installs_only_latest_result(
    deck_view, monkeypatch
):
    widget, _deck, app, _tmp = deck_view
    drain(widget, app)
    actual = slide_thumbnails.draw
    calls, observations = [], []
    rows = saved_rows(store.DB_PATH)

    def draw(pane, captured_deck, index):
        actual(pane, captured_deck, index)
        calls.append(index)
        image = QPixmap(*slide_thumbnails.SIZE)
        image.fill(QColor("red" if len(calls) == 1 else "blue"))
        if len(calls) == 1:
            widget._thumbnail(index)
            QTimer.singleShot(0, lambda: observations.append(icon(widget).pixelColor(144, 81)))
        return image

    monkeypatch.setattr(slide_thumbnails, "draw", draw)
    widget._thumbnail(0)
    drain(widget, app)
    assert calls == [0, 0]
    assert observations and all(color != QColor("red") for color in observations)
    assert icon(widget).pixelColor(144, 81) == QColor("blue")
    assert saved_rows(store.DB_PATH) == rows


def test_constructor_workspace_change_drops_queue_without_opening_new_database(
    deck_view, monkeypatch, tmp_path
):
    widget, _deck, app, _tmp = deck_view
    drain(widget, app)
    database = store.DB_PATH
    rows = saved_rows(database)
    widget._workspace_owner = WindowWorkspace.capture()
    target = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(target)) as conn:
        conn.execute("CREATE TABLE marker(value)")
    data = target.read_bytes()
    calls = track(monkeypatch)
    widget._thumbnails.refresh()
    monkeypatch.setattr(store, "DB_PATH", target)
    opened = []
    actual = sqlite3.connect

    def connect(path, *args, **kwargs):
        opened.append(path)
        return actual(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    drain(widget, app)
    assert not calls and not opened
    assert target.read_bytes() == data
    replacement = target.with_suffix(".new")
    replacement.write_bytes(data)
    os.replace(replacement, target)
    assert target.read_bytes() == data
    assert saved_rows(database) == rows


def test_empty_deck_and_invalid_requests_do_not_draw_or_change_saved_content(
    deck_view, monkeypatch
):
    widget, _deck, app, _tmp = deck_view
    widget._show_deck(None)
    calls = track(monkeypatch)
    rows = saved_rows(store.DB_PATH)
    for _ in range(25):
        widget._thumbnail(-1)
        widget._thumbnail(10)
    app.processEvents()
    assert widget.deck is None and widget.outline.count() == 0
    assert not calls and not widget._thumbnails.pending
    assert saved_rows(store.DB_PATH) == rows


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_pending_status_uses_localized_meaningful_text_and_preserves_page_size(deck_view, language):
    widget, deck, app, _tmp = deck_view
    widget.language = language
    widget.load(deck.paper_id, deck.paper_title)
    item = widget.outline.item(3)
    expected = slide_thumbnails.COPY[language][0]
    assert item.toolTip() == expected and "?" not in expected
    assert item.icon().pixmap(*slide_thumbnails.SIZE).size() == QSize(*slide_thumbnails.SIZE)
    drain(widget, app)
    assert item.toolTip() == ""
    assert item.icon().pixmap(*slide_thumbnails.SIZE).size() == QSize(*slide_thumbnails.SIZE)


def test_reentrant_gui_event_pump_never_starts_another_draw_before_current_returns(
    deck_view, monkeypatch
):
    widget, _deck, app, _tmp = deck_view
    drain(widget, app)
    before = saved_rows(store.DB_PATH)
    actual = slide_thumbnails.draw
    calls, depth = [], []
    active = 0

    def draw(pane, captured_deck, index):
        nonlocal active
        assert QThread.currentThread() == app.thread()
        active += 1
        depth.append(active)
        calls.append(index)
        image = actual(pane, captured_deck, index)
        if len(calls) == 1:
            widget._thumbnail(1)
            app.processEvents()
            QTest.qWait(1)
        active -= 1
        return image

    monkeypatch.setattr(slide_thumbnails, "draw", draw)
    widget._thumbnail(0)
    drain(widget, app)
    assert max(depth) == 1, "Nested event delivery began a second thumbnail draw"
    assert calls == [0, 1]
    assert not widget.outline.item(0).toolTip() and not widget.outline.item(1).toolTip()
    assert saved_rows(store.DB_PATH) == before
