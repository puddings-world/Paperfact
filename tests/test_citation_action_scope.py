"""Saved citation protections exercised through the current native presentation.

RichView body/scroll guards remain covered independently of the native pane.
"""

import json
import os
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
)
from shiboken6 import isValid

from paper_daily import lineage_team, store
from paper_daily.desktop import cites_pane, ui_state
from paper_daily.desktop.main import LIGHT
from paper_daily.desktop.rich_view import RichView


def _rows():
    with store.connect() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM cites ORDER BY paper_id, ref_key")]


def _cards(pane):
    pane._complete("refs")
    box = pane._boxes["refs"]
    return [
        box.itemAt(i).widget()
        for i in range(box.count())
        if box.itemAt(i).widget() is not None
        and any(b.text() == "編輯" for b in box.itemAt(i).widget().findChildren(QPushButton))
    ]


def _text(widget):
    return " ".join(label.text() for label in widget.findChildren(QLabel) if not label.isHidden())


def _edit(pane, index=0):
    return next(b for b in _cards(pane)[index].findChildren(QPushButton) if b.text() == "編輯")


def _dispatch_and_save(pane, button, before_save=None):
    observed = []

    def save():
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, QDialog):
            return
        observed.append([label.text() for label in dialog.findChildren(QLabel)])
        dialog.findChildren(QPlainTextEdit)[0].setPlainText("Curated from the captured source card")
        if before_save:
            before_save()
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()

    if isValid(button):
        QTimer.singleShot(0, save)
        button.click()
    QApplication.processEvents()
    return observed


def _expected(before):
    expected = [dict(row) for row in before]
    selected = next(r for r in expected if (r["paper_id"], r["ref_key"]) == ("alpha", "2"))
    selected.update(purpose="Curated from the captured source card", edited=1)
    return expected


@pytest.fixture
def pane(tmp_path, monkeypatch, request):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                {
                    "id": "alpha",
                    "title": "Alpha anchor",
                    "venue": "Fixture",
                    "year": 2026,
                    "source": "test",
                },
                {
                    "id": "beta",
                    "title": "Beta anchor",
                    "venue": "Fixture",
                    "year": 2026,
                    "source": "test",
                },
            ],
        )
        conn.executemany(
            "INSERT INTO cites(paper_id,ref_key,title,purpose,gist,verdict,why,"
            "contexts_json,basis,written_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    "alpha",
                    "1",
                    "First matrix source",
                    "alpha-one",
                    "first gist",
                    "參考",
                    "first reason",
                    "[]",
                    "context",
                    "2026-10-31T00:00:00+00:00",
                ),
                (
                    "alpha",
                    "2",
                    "Second matrix source",
                    "alpha-two",
                    "second gist",
                    "必讀",
                    "second reason",
                    "[]",
                    "context",
                    "2026-10-31T00:00:00+00:00",
                ),
                (
                    "beta",
                    "1",
                    "Different optical source",
                    "beta-one",
                    "other gist",
                    "參考",
                    "other reason",
                    "[]",
                    "context",
                    "2026-10-31T00:00:00+00:00",
                ),
            ],
        )

    def no_lookup(*args, **kwargs):
        raise AssertionError("network lookup is forbidden in this fixture")

    monkeypatch.setattr(lineage_team, "team", no_lookup)
    app = QApplication.instance() or QApplication([])
    window = SimpleNamespace(
        waiting=set,
        analysis_running=lambda *_: False,
        active_list=None,
        in_queue=lambda _: True,
        open_paper=lambda _: None,
    )
    widget = cites_pane.CitesPane(window, LIGHT)
    widget.resize(900, 700)
    widget.show()
    widget._ref_order = "verdict"
    widget.load("alpha")
    app.processEvents()
    widget.observation = {"test": request.node.name, "before": _rows()}
    yield widget
    widget.observation["after"] = _rows()
    output = os.environ.get("CITATION_OBSERVATIONS")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(widget.observation, ensure_ascii=False) + "\n")
    widget._watch.stop()
    widget.close()
    widget.deleteLater()
    app.processEvents()
    ui_state.flush()


def test_current_rendered_edit_updates_only_its_actual_saved_reference(pane):
    assert "Second matrix source" in _text(_cards(pane)[0])
    before = _rows()
    assert _dispatch_and_save(pane, _edit(pane))
    assert _rows() == _expected(before)


@pytest.mark.parametrize("change", ["paper", "sort", "list", "close"])
def test_retired_card_never_edits_any_saved_reference(pane, change):
    button = _edit(pane)
    before = _rows()
    if change == "paper":
        pane.load("beta")
        assert "Different optical source" in _text(_cards(pane)[0])
    elif change == "sort":
        pane._set_order("number")
        assert "First matrix source" in _text(_cards(pane)[0])
    elif change == "list":
        pane.win.active_list = "other-list"
    else:
        pane.close()
    assert not _dispatch_and_save(pane, button)
    assert _rows() == before


def test_pending_team_lookup_cannot_retarget_an_old_source_card(pane, monkeypatch):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def lookup(*a, **k):
        started.set()
        assert release.wait(5)
        finished.set()
        return {
            "own": True,
            "known": 2,
            "total": 2,
            "refs": {"1": {"authors": [], "institutions": ["Fixture Institute"]}},
            "later": {},
        }

    monkeypatch.setattr(lineage_team, "team", lookup)
    button = _edit(pane)
    before = _rows()
    try:
        pane._set_team("team")
        assert started.wait(1)
        release.set()
        deadline = time.monotonic() + 5
        while pane._team_loading and time.monotonic() < deadline:
            QTest.qWait(5)
        assert not pane._team_loading
        cards = _cards(pane)
        assert len(cards) == 1 and "First matrix source" in _text(cards[0])
        assert not _dispatch_and_save(pane, button)
        assert _rows() == before
    finally:
        release.set()
        assert finished.wait(1)


def test_edit_dialog_save_stays_with_captured_paper_when_reader_changes(pane):
    before = _rows()
    _dispatch_and_save(pane, _edit(pane), before_save=lambda: pane.load("beta"))
    assert _rows() == _expected(before)
    assert pane.paper_id == "beta"
    assert "Different optical source" in _text(_cards(pane)[0])


@pytest.mark.parametrize(
    "candidate",
    [
        "cite:edit:refs:0",
        "cite:" + "0" * 32 + ":wrong",
        "cite:unknown:unknown",
        "cite:edit:refs:0:extra",
        "cite:edit:refs:0?x=1",
        "cite:edit:refs:0#x",
    ],
)
def test_legacy_action_urls_in_source_text_cannot_change_saved_sources(pane, candidate):
    before = _rows()
    labels = _cards(pane)[0].findChildren(QLabel)
    assert labels
    for label in labels:
        label.linkActivated.emit(candidate)
    assert QApplication.activeModalWidget() is None
    assert _rows() == before


def test_cancel_retry_and_reentrant_click_preserve_saved_target(pane, monkeypatch):
    from paper_daily import followups

    button, before = _edit(pane), _rows()

    def cancel():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QDialog)
        dialog.findChildren(QPlainTextEdit)[0].setPlainText("Not saved")
        dialog.reject()

    QTimer.singleShot(0, cancel)
    button.click()
    assert _rows() == before
    calls = []
    actual = followups.edit_reference

    def save(*args, **kwargs):
        calls.append(args)
        return actual(*args, **kwargs)

    monkeypatch.setattr(followups, "edit_reference", save)
    _dispatch_and_save(pane, button, before_save=button.click)
    if isValid(button):
        button.click()
    assert calls == [("alpha", "2")]
    assert _rows() == _expected(before)


def test_writer_failure_keeps_draft_and_retry_saves_once(pane, monkeypatch):
    from paper_daily import followups

    before = _rows()
    actual = followups.edit_reference

    def unavailable(*args, **kwargs):
        raise OSError("fixture storage unavailable")

    monkeypatch.setattr(followups, "edit_reference", unavailable)

    def retry():
        dialog = QApplication.activeModalWidget()
        editor = dialog.findChildren(QPlainTextEdit)[0]
        editor.setPlainText("Curated from the captured source card")
        save = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save)
        save.click()
        assert dialog.isVisible() and _rows() == before
        assert editor.toPlainText() == "Curated from the captured source card"
        assert "Not saved" in dialog.findChild(QLabel, "research-item-save-status").text()
        monkeypatch.setattr(followups, "edit_reference", actual)
        save.click()

    QTimer.singleShot(0, retry)
    _edit(pane).click()
    assert _rows() == _expected(before)


def test_workspace_change_rejects_old_action(pane, monkeypatch, tmp_path):
    import sqlite3
    from contextlib import closing

    button, before = _edit(pane), _rows()
    original = store.DB_PATH
    other = tmp_path / "other.db"
    with store.connect() as conn, closing(sqlite3.connect(other)) as target:
        conn.backup(target)
    monkeypatch.setattr(store, "DB_PATH", other)
    assert not _dispatch_and_save(pane, button)
    assert _rows() == before
    monkeypatch.setattr(store, "DB_PATH", original)
    assert _rows() == before


def test_story_modal_save_updates_original_without_reloading_new_paper(pane):
    with store.connect() as conn:
        conn.executemany(
            "INSERT INTO paper_context(paper_id,summary,reading_json,written_at,edited) "
            "VALUES(?,?,?, ?,0)",
            [
                ("alpha", "Original Alpha story", "[]", "2026-10-31"),
                ("beta", "Independent Beta story", "[]", "2026-10-31"),
            ],
        )
    pane.load("alpha")
    story = pane._data["story"]
    card = pane._story(story, pane._data["refs"], [], "now")
    button = next(b for b in card.findChildren(QPushButton) if b.text() == "編輯")
    _dispatch_and_save(pane, button, before_save=lambda: pane.load("beta"))
    with store.connect() as conn:
        actual = [
            tuple(r)
            for r in conn.execute(
                "SELECT paper_id,summary,edited FROM paper_context ORDER BY paper_id"
            )
        ]
    assert actual == [
        ("alpha", "Curated from the captured source card", 1),
        ("beta", "Independent Beta story", 0),
    ]
    assert pane.paper_id == "beta" and pane._data["story"]["summary"] == "Independent Beta story"


@pytest.mark.parametrize("change", ["paper", "close", "list"])
def test_late_projection_preparation_cannot_replace_current_content(pane, change):
    generation = pane._generation
    if change == "paper":
        pane.load("beta")
    elif change == "close":
        pane.close()
    else:
        pane.win.active_list = "other-list"
    before = pane._data.copy()
    face = pane._list_face
    pane._prepare_rest(generation)
    assert pane._data == before and pane._list_face is face


def test_close_during_held_lookup_cannot_recreate_live_cards(pane, monkeypatch):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def lookup(*a, **k):
        started.set()
        assert release.wait(5)
        finished.set()
        return {"own": True, "known": 0, "total": 0, "refs": {}, "later": {}}

    monkeypatch.setattr(lineage_team, "team", lookup)
    try:
        pane._set_team("team")
        assert started.wait(1)
        before = pane._data.copy()
        pane.close()
        release.set()
        assert finished.wait(1)
        QTest.qWait(20)
        assert pane._closed and pane._data == before and not pane._pending
    finally:
        release.set()


def test_action_feedback_does_not_mark_new_papers_cards(pane):
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                dict(
                    id="target",
                    title="Second matrix source",
                    year=2026,
                    venue="Fixture",
                    source="test",
                )
            ],
        )
    pane.load("alpha")
    button = next(b for b in _cards(pane)[0].findChildren(QPushButton) if b.text() == "插到最前面")
    pane.win.promote = lambda _: pane.load("beta")
    button.click()
    assert pane.paper_id == "beta"
    assert "Different optical source" in _text(_cards(pane)[0])
    assert not any(
        b.text() == "已插到最前面" for card in _cards(pane) for b in card.findChildren(QPushButton)
    )


class _FakePage:
    def __init__(self):
        self.calls = []

    def runJavaScript(self, script, *args):
        self.calls.append((script, args))


class _FakeWebView:
    def __init__(self):
        self.javascript = _FakePage()
        self.pages = []

    def page(self):
        return self.javascript

    def setHtml(self, page, *args):
        self.pages.append(page)


@pytest.mark.parametrize("change", ["paper", "close", "list"])
def test_rich_view_delayed_scroll_guard_keeps_new_body(pane, change):
    view = RichView(LIGHT)
    web = _FakeWebView()
    view.rich = True
    view.view = web
    scope = pane._projection
    view.setHtml("Alpha body", keep_scroll=True, current=lambda: pane._projection_current(scope))
    callback = web.javascript.calls[-1][1][-1]
    if change == "paper":
        pane.load("beta")
    elif change == "close":
        pane.close()
    else:
        pane.win.active_list = "other-list"
    view.setHtml("Current body")
    before = list(web.pages)
    callback(127)
    assert web.pages == before and view._body == "Current body"
    view.close()


def test_optional_rich_view_guard_rejects_body_scroll_then_allows_retry(pane):
    view = RichView(LIGHT)
    web = _FakeWebView()
    view.rich = True
    view.view = web
    old = view._body
    view.setHtml("Rejected frame", keep_scroll=True, current=lambda: False)
    assert view._body == old and not web.pages
    active = [True]
    view.setHtml("Accepted retry", keep_scroll=True, current=lambda: active[0])
    callback = web.javascript.calls[-1][1][-1]
    callback(11)
    assert "Accepted retry" in web.pages[-1] and "START_AT = 11" in web.pages[-1]
    active[0] = False
    before = list(web.pages)
    callback(22)
    assert web.pages == before
    view.close()


def test_plain_guard_has_no_stale_body_or_scroll_effect(pane):
    view = RichView(LIGHT)
    before = view._body
    view.setHtml("Rejected plain", current=lambda: False)
    assert view._body == before
    view.setHtml("Accepted plain", current=lambda: True)
    assert view.view.toPlainText() == "Accepted plain"
    view.close()
