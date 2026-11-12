"""Real claim child completion refreshes its parent row without changing navigation."""

import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from shiboken6 import isValid
from test_claim_draft_storage import rows
from test_claim_original_read_ui import app as app
from test_claim_original_read_ui import claims as claims
from test_claim_original_read_ui import decided as decided
from test_claim_original_read_ui import ready as ready
from test_claim_original_read_ui import receiver as receiver
from test_claim_original_read_ui import remote as remote
from test_claim_original_read_ui import scene as scene
from test_claim_original_read_ui import source_pair as source_pair
from test_claim_original_read_ui import workspace as workspace
from test_claim_remote_ui import close_host, entry
from test_review_dialog import wait

from paper_daily import research_generation as generation
from paper_daily import review_decisions

pytestmark = pytest.mark.parametrize("workspace", [True], indirect=True)


def test_page_reports_typed_claim_decision_under_original_source(decided):
    host = decided["host"]
    key = host.selection_key
    row = next(
        row for row in host.service.page(limit=100)["items"] if (row["origin"], row["id"]) == key
    )
    assert row["decision"] == "applied"


@pytest.mark.parametrize("decided", ["en", "zh-TW"], indirect=True)
def test_child_close_refreshes_local_decision_without_moving_parent_selection(decided, app):
    host, child = decided["host"], decided["dialog"]
    item = host.list.currentItem()
    key = tuple(item.data(Qt.ItemDataRole.UserRole))
    before = rows(host.service.path, "SELECT * FROM paper_claim_sets")
    body = host.draft.toPlainText()
    child.close()
    wait(app, lambda: child.disposed and not host.jobs, timeout=20)
    assert host.selection_key == key and host.list.currentItem() is item
    assert host.draft.toPlainText() == body
    expected = "已在本機套用" if child.language == "zh-TW" else "applied locally"
    assert expected in item.text()
    assert "synchronized" not in item.text().lower()
    if child.language == "zh-TW":
        folder = Path(__file__).resolve().parents[1] / "build"
        assert host.grab().save(str(folder / "parent-review-local-decision-zh-TW.png"))
    assert rows(host.service.path, "SELECT * FROM paper_claim_sets") == before
    assert not decided["b"].journal.pending(1000)


def test_closing_unapplied_child_does_not_mark_a_local_decision(remote, app):
    host, child = entry(
        app, remote["b"].journal.path, "remote", remote["origin"].split(":", 1)[1], "zh-TW"
    )
    before = rows(host.service.path, "SELECT * FROM paper_claim_sets")
    item = host.list.currentItem()
    label = item.text()
    try:
        child.close()
        wait(app, lambda: child.disposed and not host.jobs, timeout=20)
        assert item.text() == label
        assert item.data(Qt.ItemDataRole.UserRole + 1)["decision"] is None
        assert rows(host.service.path, "SELECT * FROM paper_claim_sets") == before
        assert not remote["b"].journal.pending(1000)
    finally:
        close_host(app, host)


def text_candidate(value):
    path, paper = value["b"].journal.path, value["local"]
    with closing(generation._connect(path)) as conn:
        old = generation.begin_generation(
            conn, table="close_readings", owner_id=paper, input_reader="target"
        )
    row = dict(
        paper_id=paper,
        body="Another saved view",
        spec="fixture-v1",
        written_at="2026-11-02T00:00:00+00:00",
    )
    with closing(generation._connect(path)) as conn:
        current = generation.begin_generation(
            conn, table="close_readings", owner_id=paper, input_reader="target"
        )
    generation.publish_generation(current, row=row)
    result = generation.publish_generation(old, row=dict(row, body="Another retained view"))
    assert result.status == "candidate"
    return result.request_id


def held_capture(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = review_decisions.capture
    calls = []

    def held(*args, **kwargs):
        snapshot = original(*args, **kwargs)
        calls.append(snapshot)
        if len(calls) == 1:
            entered.set()
            assert release.wait(20)
        return snapshot

    monkeypatch.setattr(review_decisions, "capture", held)
    return entered, release, calls


def test_held_parent_refresh_keeps_other_unsaved_text_focus_cursor_scroll_and_selection(
    decided, app, monkeypatch
):
    host, child = decided["host"], decided["dialog"]
    identity = text_candidate(decided)
    row = next(
        row
        for row in host.service.page(limit=100)["items"]
        if (row["origin"], row["id"]) == ("generation", identity)
    )
    # Seed a second genuine inventory row; external whole-list refresh is not under test.
    host._page(dict(items=[row], next=host.cursor))
    original_item = host.list.currentItem()
    entered, release, _calls = held_capture(monkeypatch)
    try:
        child.close()
        wait(app, entered.is_set, timeout=20)
        host.list.setCurrentRow(host.list.count() - 1)
        wait(
            app,
            lambda: host.preview is not None and host.selection_key == ("generation", identity),
            timeout=20,
        )
        body = "Keep this unsaved reading interpretation.\n" * 40
        host.draft.setPlainText(body)
        host.autosave.stop()
        cursor = host.draft.textCursor()
        cursor.setPosition(12)
        host.draft.setTextCursor(cursor)
        host.list.setMaximumHeight(28)
        host.list.verticalScrollBar().setValue(host.list.verticalScrollBar().maximum())
        host.draft.verticalScrollBar().setValue(12)
        host.activateWindow()
        host.draft.setFocus()
        app.processEvents()
        before = (
            host.selection_key,
            host.preview.serialized,
            host.request,
            host.draft.textCursor().position(),
            host.draft.verticalScrollBar().value(),
            host.list.verticalScrollBar().value(),
        )
        assert host.draft.hasFocus() and before[-1] > 0
        pending = decided["b"].journal.pending(1000)
        release.set()
        wait(app, lambda: not host.jobs, timeout=20)
        assert "已在本機套用" in original_item.text()
        assert host.draft.toPlainText() == body and host.draft.hasFocus()
        assert before == (
            host.selection_key,
            host.preview.serialized,
            host.request,
            host.draft.textCursor().position(),
            host.draft.verticalScrollBar().value(),
            host.list.verticalScrollBar().value(),
        )
        assert host.selection_key in host.dirty
        assert decided["b"].journal.pending(1000) == pending
    finally:
        release.set()


def test_late_status_from_replaced_native_database_never_updates_parent(decided, app, monkeypatch):
    host, child = decided["host"], decided["dialog"]
    entered, release, _calls = held_capture(monkeypatch)
    item, path = host.list.currentItem(), host.service.path
    label = item.text()
    try:
        child.close()
        wait(app, entered.is_set, timeout=20)
        replacement = path.with_suffix(".replacement")
        with (
            closing(sqlite3.connect(path)) as source,
            closing(sqlite3.connect(replacement)) as target,
        ):
            source.backup(target)
        replacement.replace(path)
        before = path.read_bytes()
        release.set()
        wait(app, lambda: not host.jobs, timeout=20)
        assert item.text() == label
        assert host.words["decision_retry"] in item.toolTip()
        assert path.read_bytes() == before
    finally:
        release.set()


def test_status_failure_keeps_parent_and_explicit_refresh_can_retry(decided, app, monkeypatch):
    host, child = decided["host"], decided["dialog"]
    item = host.list.currentItem()
    label = item.text()
    before = rows(host.service.path, "SELECT * FROM paper_claim_sets")
    with monkeypatch.context() as patch:

        def failed(*args):
            raise sqlite3.DatabaseError("Synthetic local metadata failure")

        patch.setattr(review_decisions, "capture", failed)
        child.close()
        wait(app, lambda: child.disposed and not host.jobs, timeout=20)
        assert item.text() == label
        assert host.words["decision_retry"] in item.toolTip()
    host.refresh.click()
    wait(app, lambda: not host.jobs and host.preview is not None, timeout=20)
    assert "已在本機套用" in item.text()
    assert rows(host.service.path, "SELECT * FROM paper_claim_sets") == before
    assert not decided["b"].journal.pending(1000)


def test_closing_parent_with_held_status_discards_delivery_without_writing(
    decided, app, monkeypatch
):
    host, child = decided["host"], decided["dialog"]
    entered, release, calls = held_capture(monkeypatch)
    item = host.list.currentItem()
    label = item.text()
    before = rows(host.service.path, "SELECT * FROM paper_claim_sets")
    try:
        child.close()
        wait(app, entered.is_set, timeout=20)
        future = host.jobs[-1][0]
        host.close()
        assert host.disposed
        release.set()
        future.result(timeout=20)
        app.processEvents()
        # Closing retires the parent's native widgets; a surviving row must still
        # show its old label, and the late delivery must record no decision.
        assert not isValid(item) or item.text() == label
        assert not review_decisions.current(calls[0])
        assert rows(host.service.path, "SELECT * FROM paper_claim_sets") == before
        assert not decided["b"].journal.pending(1000)
    finally:
        release.set()


def test_intervening_title_write_retries_one_status_read_without_new_decision(
    decided, app, monkeypatch
):
    host, child = decided["host"], decided["dialog"]
    entered, release, calls = held_capture(monkeypatch)
    item = host.list.currentItem()
    before = rows(host.service.path, "SELECT * FROM research_review_receipts")
    try:
        child.close()
        wait(app, entered.is_set, timeout=20)
        with closing(generation._connect(host.service.path)) as conn, conn:
            conn.execute("UPDATE papers SET title='New title' WHERE id=?", (decided["local"],))
        pending = decided["b"].journal.pending(1000)
        release.set()
        wait(app, lambda: not host.jobs, timeout=20)
        assert len(calls) == 2 and "已在本機套用" in item.text()
        assert rows(host.service.path, "SELECT * FROM research_review_receipts") == before
        assert decided["b"].journal.pending(1000) == pending
    finally:
        release.set()
