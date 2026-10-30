"""Real saved citation edits must never follow a link from an obsolete page."""

import json
import os
import threading
import time
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PAPERFACT_PLAIN_VIEWS", "1")

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
)

from paper_daily import lineage_team, store
from paper_daily.desktop import cites_pane, ui_state
from paper_daily.desktop.main import LIGHT


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs))


def _edit_link(pane, index=0):
    parser = _Links()
    parser.feed(pane._list_view._body)
    # Capture the exact URL actually emitted by the original rendered page.
    anchor = f"a-edit-refs-{index}"
    return next(a["href"] for a in parser.links if a.get("id") == anchor)


def _rows():
    with store.connect() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM cites ORDER BY paper_id, ref_key")]


def _dispatch_and_save(pane, href, before_save=None):
    observed = []

    def accept_visible_editor():
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, QDialog):
            return
        observed.append([label.text() for label in dialog.findChildren(QLabel)])
        boxes = dialog.findChildren(QPlainTextEdit)
        assert boxes
        boxes[0].setPlainText("Curated from the captured source card")
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        if before_save is not None:
            before_save()
        buttons.button(QDialogButtonBox.StandardButton.Save).click()

    QTimer.singleShot(0, accept_visible_editor)
    pane._link(QUrl(href))
    QApplication.processEvents()
    return observed


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
    window = SimpleNamespace(waiting=set, analysis_running=lambda *_: False, active_list=None)
    widget = cites_pane.CitesPane(window, LIGHT)
    widget.resize(900, 700)
    widget.show()
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
    assert pane._rows["refs"][0]["ref_key"] == "2"
    href = _edit_link(pane)
    before = _rows()
    pane.observation.update(href=href, dialogs=_dispatch_and_save(pane, href))
    after = _rows()
    expected = [dict(row) for row in before]
    selected = next(r for r in expected if (r["paper_id"], r["ref_key"]) == ("alpha", "2"))
    selected.update(purpose="Curated from the captured source card", edited=1)
    assert after == expected


def test_old_paper_html_edit_cannot_modify_a_different_papers_saved_source(pane):
    href = _edit_link(pane)
    captured = dict(pane._rows["refs"][0])
    pane.load("beta")
    QApplication.processEvents()
    assert pane._rows["refs"][0]["title"] == "Different optical source"
    before = _rows()
    pane.observation.update(href=href, captured=captured, dialogs=_dispatch_and_save(pane, href))
    assert _rows() == before, "An obsolete alpha card must not edit beta's different source"


def test_old_sorted_html_edit_cannot_modify_the_new_reference_at_that_index(pane):
    href = _edit_link(pane)
    captured = dict(pane._rows["refs"][0])
    assert captured["ref_key"] == "2"
    pane._set_order("number")
    assert pane._rows["refs"][0]["ref_key"] == "1"
    before = _rows()
    pane.observation.update(href=href, captured=captured, dialogs=_dispatch_and_save(pane, href))
    assert _rows() == before, "An obsolete source-2 card must not edit source 1 after reorder"


def test_pending_team_lookup_cannot_retarget_an_old_source_card(pane, monkeypatch):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def held_lookup(*args, **kwargs):
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

    monkeypatch.setattr(lineage_team, "team", held_lookup)
    href = _edit_link(pane)
    captured = dict(pane._rows["refs"][0])
    assert captured["ref_key"] == "2"
    try:
        pane._set_team("team")
        assert started.wait(1)
        release.set()
        deadline = time.monotonic() + 5
        while pane._team_loading and time.monotonic() < deadline:
            QTest.qWait(5)
        assert not pane._team_loading
        assert pane._rows["refs"][0]["ref_key"] == "1"
        assert "First matrix source" in pane._list_view.view.toPlainText()
        assert "Second matrix source" not in pane._list_view.view.toPlainText()
        before = _rows()
        pane.observation.update(
            href=href, captured=captured, dialogs=_dispatch_and_save(pane, href)
        )
        assert _rows() == before, "A completed filter lookup must not retarget an old source edit"
    finally:
        release.set()
        assert finished.wait(1)
        QApplication.processEvents()


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


def test_late_kept_scroll_callback_cannot_replace_new_papers_actual_html(pane):
    # Actual RichView.setHtml/_load; only the native browser I/O is simulated.
    web = _FakeWebView()
    pane._list_view.rich = True
    pane._list_view.view = web
    pane._render(keep_scroll=True)
    callbacks = [args[-1] for script, args in web.javascript.calls if script == "window.scrollY"]
    assert len(callbacks) == 1
    pane.load("beta")
    assert "Different optical source" in web.pages[-1]
    delivered_beta = web.pages[-1]
    callbacks[0](127)
    assert web.pages[-1] == delivered_beta, "Late Alpha scroll callback replaced visible Beta HTML"
    assert "Different optical source" in pane._list_view._body


def test_edit_dialog_save_stays_with_captured_paper_when_reader_changes(pane):
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO cites(paper_id,ref_key,title,purpose,gist,verdict,why,"
            "contexts_json,basis,written_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "beta",
                "2",
                "Unrelated optical source",
                "beta-two",
                "other",
                "??",
                "unrelated",
                "[]",
                "context",
                "2026-10-31T00:00:00+00:00",
            ),
        )
    href = _edit_link(pane)
    before = _rows()
    _dispatch_and_save(pane, href, before_save=lambda: pane.load("beta"))
    expected = [dict(row) for row in before]
    captured = next(r for r in expected if (r["paper_id"], r["ref_key"]) == ("alpha", "2"))
    captured.update(purpose="Curated from the captured source card", edited=1)
    assert _rows() == expected
    assert pane.paper_id == "beta"
    assert "Different optical source" in pane._list_view.view.toPlainText()


@pytest.mark.parametrize(
    "invalid", ["unscoped", "wrong-frame", "unknown", "extra", "query", "fragment"]
)
def test_invalid_or_unknown_current_action_never_changes_saved_sources(pane, invalid):
    href = _edit_link(pane)
    scheme, frame, token = href.split(":")
    candidate = {
        "unscoped": "cite:edit:refs:0",
        "wrong-frame": f"{scheme}:{'0' * 32}:{token}",
        "unknown": f"{scheme}:{frame}:{'0' * 24}",
        "extra": href + ":extra",
        "query": href + "?x=1",
        "fragment": href + "#x",
    }[invalid]
    before = _rows()
    assert not _dispatch_and_save(pane, candidate)
    assert _rows() == before


def test_cancel_then_retry_and_reentrant_click_preserve_the_same_saved_target(pane, monkeypatch):
    from paper_daily import followups

    href, before = _edit_link(pane), _rows()

    def cancel_editor():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QDialog)
        dialog.findChildren(QPlainTextEdit)[0].setPlainText("Not saved")
        dialog.reject()

    QTimer.singleShot(0, cancel_editor)
    pane._link(QUrl(href))
    assert _rows() == before
    calls = []
    actual = followups.edit_reference

    def record_saved(*args, **kwargs):
        calls.append(args)
        return actual(*args, **kwargs)

    monkeypatch.setattr(followups, "edit_reference", record_saved)
    _dispatch_and_save(pane, href, before_save=lambda: pane._link(QUrl(href)))
    pane._link(QUrl(href))
    assert calls == [("alpha", "2")]
    expected = [dict(row) for row in before]
    selected = next(row for row in expected if (row["paper_id"], row["ref_key"]) == ("alpha", "2"))
    selected.update(purpose="Curated from the captured source card", edited=1)
    assert _rows() == expected


def test_writer_failure_does_not_consume_edit_retry_or_change_saved_content(pane, monkeypatch):
    from paper_daily import followups

    href, before = _edit_link(pane), _rows()
    actual = followups.edit_reference

    def unavailable(*args, **kwargs):
        raise OSError("fixture storage unavailable")

    monkeypatch.setattr(followups, "edit_reference", unavailable)
    with pytest.raises(OSError, match="fixture storage unavailable"):
        _dispatch_and_save(pane, href)
    assert _rows() == before
    monkeypatch.setattr(followups, "edit_reference", actual)
    _dispatch_and_save(pane, href)
    assert (
        next(row for row in _rows() if (row["paper_id"], row["ref_key"]) == ("alpha", "2"))[
            "edited"
        ]
        == 1
    )


def test_workspace_change_or_close_rejects_the_old_action(pane, monkeypatch, tmp_path):
    href = _edit_link(pane)
    before = _rows()
    original = store.DB_PATH
    other = tmp_path / "other.db"
    import sqlite3
    from contextlib import closing

    with store.connect() as conn, closing(sqlite3.connect(other)) as target:
        conn.backup(target)
    monkeypatch.setattr(store, "DB_PATH", other)
    assert not _dispatch_and_save(pane, href)
    assert _rows() == before
    monkeypatch.setattr(store, "DB_PATH", original)
    pane.close()
    assert not _dispatch_and_save(pane, href)
    assert _rows() == before


def _rich_fixture(pane):
    web = _FakeWebView()
    pane._list_view.rich = True
    pane._list_view.view = web
    pane._render()
    return web


def _probe(web):
    return next(
        args[-1] for script, args in reversed(web.javascript.calls) if "?.dataset.frame" in script
    )


def test_old_page_loaded_and_queued_scripts_cannot_affect_the_next_frame(pane):
    web = _rich_fixture(pane)
    alpha = pane._page_scope.nonce
    pane._js("window.alphaFeedback = true;")
    pane._page_loaded(True)
    old_probe = _probe(web)
    pane.load("beta")
    beta = pane._page_scope.nonce
    pane._js("window.betaFeedback = true;")
    before = len(web.javascript.calls)
    old_probe(alpha)
    assert len(web.javascript.calls) == before and not pane._page_ready
    pane._page_loaded(True)
    current_probe = _probe(web)
    current_probe(alpha)
    assert not pane._page_ready
    current_probe(beta)
    assert pane._page_ready
    scripts = [script for script, _ in web.javascript.calls]
    assert not any("alphaFeedback" in script for script in scripts)
    feedback = [script for script in scripts if "betaFeedback" in script]
    assert len(feedback) == 1
    assert f'root.dataset.frame !== "{beta}"' in feedback[0]
    current_probe(beta)
    assert len([script for script, _ in web.javascript.calls if "betaFeedback" in script]) == 1


def test_close_while_page_probe_pending_ignores_late_completion(pane):
    web = _rich_fixture(pane)
    frame = pane._page_scope.nonce
    pane._js("window.closedFeedback = true;")
    pane._page_loaded(True)
    callback = _probe(web)
    pane.close()
    callback(frame)
    assert not any("closedFeedback" in script for script, _ in web.javascript.calls)


def test_optional_rich_view_guard_rejects_body_and_scroll_then_allows_retry(pane):
    web = _rich_fixture(pane)
    old_body, old_pages = pane._list_view._body, list(web.pages)
    pane._list_view.setHtml("Rejected frame", keep_scroll=True, current=lambda: False)
    assert pane._list_view._body == old_body and web.pages == old_pages
    active = [True]
    pane._list_view.setHtml("Accepted retry", keep_scroll=True, current=lambda: active[0])
    callback = next(
        args[-1] for script, args in reversed(web.javascript.calls) if script == "window.scrollY"
    )
    callback(11)
    assert "Accepted retry" in web.pages[-1] and "START_AT = 11" in web.pages[-1]
    active[0] = False
    before = list(web.pages)
    callback(22)
    assert web.pages == before


def test_plain_guard_has_no_stale_body_or_scroll_effect(pane):
    before = pane._list_view._body
    pane._list_view.setHtml("Rejected plain", current=lambda: False)
    assert pane._list_view._body == before
    pane._list_view.setHtml("Accepted plain", current=lambda: True)
    assert pane._list_view.view.toPlainText() == "Accepted plain"


def test_list_context_change_rejects_old_source_action(pane):
    href, before = _edit_link(pane), _rows()
    pane.win.active_list = "different-list"
    assert not _dispatch_and_save(pane, href)
    assert _rows() == before


def test_story_modal_save_updates_original_paper_without_reloading_new_one(pane):
    with store.connect() as conn:
        conn.executemany(
            "INSERT INTO paper_context(paper_id,summary,reading_json,written_at,edited) "
            "VALUES(?,?,?, ?,0)",
            [
                ("alpha", "Original Alpha story", "[]", "2026-10-31T00:00:00+00:00"),
                ("beta", "Independent Beta story", "[]", "2026-10-31T00:00:00+00:00"),
            ],
        )
    pane.load("alpha")
    links = _Links()
    links.feed(pane._list_view._body)
    href = next(a["href"] for a in links.links if a.get("class") == "btn")
    _dispatch_and_save(pane, href, before_save=lambda: pane.load("beta"))
    with store.connect() as conn:
        actual = [
            tuple(row)
            for row in conn.execute(
                "SELECT paper_id,summary,edited FROM paper_context ORDER BY paper_id"
            )
        ]
    assert actual == [
        ("alpha", "Curated from the captured source card", 1),
        ("beta", "Independent Beta story", 0),
    ]
    assert pane.paper_id == "beta"
    assert "Independent Beta story" in pane._list_view.view.toPlainText()


def test_close_during_held_team_lookup_cannot_recreate_a_live_action_frame(pane, monkeypatch):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def held_lookup(*args, **kwargs):
        started.set()
        assert release.wait(5)
        finished.set()
        return {"own": True, "known": 0, "total": 0, "refs": {}, "later": {}}

    monkeypatch.setattr(lineage_team, "team", held_lookup)
    try:
        pane._set_team("team")
        assert started.wait(1)
        body = pane._list_view._body
        pane.close()
        release.set()
        assert finished.wait(1)
        QTest.qWait(20)
        assert pane._page_scope is None
        assert pane._list_view._body == body
    finally:
        release.set()
        assert finished.wait(1)
        QApplication.processEvents()


def test_delayed_action_feedback_cannot_mark_a_new_papers_web_frame(pane):
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                {
                    "id": "target",
                    "title": "Second matrix source",
                    "venue": "Fixture",
                    "year": 2026,
                    "source": "test",
                }
            ],
        )
    pane.load("alpha")
    web = _rich_fixture(pane)
    parser = _Links()
    parser.feed(pane._list_view._body)
    href = next(a["href"] for a in parser.links if a.get("id") == "a-lift-refs-0")
    pane.win.promote = lambda target: pane.load("beta")
    pane._link(QUrl(href))
    assert pane.paper_id == "beta"
    assert "Different optical source" in web.pages[-1]
    assert not any("mark(" in script for script, _ in web.javascript.calls)
    assert not pane._done
