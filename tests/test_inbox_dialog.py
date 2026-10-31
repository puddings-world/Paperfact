"Native Inbox actions are saved-first and never perform SQL/hash on Qt."

import hashlib
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from test_list_navigation import window as navigation_window_fixture
from test_research_inbox import payload, rows, setup

from paper_daily import inbox_content as content
from paper_daily.desktop.inbox_dialog import COPY, InboxDialog
from paper_daily.research_inbox import Inbox

navigation_window = navigation_window_fixture


def background(task):
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(task).result(timeout=5)


def wait(app, predicate):
    deadline = time.monotonic() + 8
    while not predicate():
        app.processEvents()
        assert time.monotonic() < deadline, "Inbox UI did not finish"
        QTest.qWait(1)
    app.processEvents()


@pytest.fixture
def panel(tmp_path, monkeypatch):
    from paper_daily import connection_vault, llm

    app = QApplication.instance() or QApplication([])
    service, _ = setup(tmp_path / "inbox.sqlite")
    path = [service.path]
    gui = threading.get_ident()
    connect, digest, sha = sqlite3.connect, hashlib.file_digest, hashlib.sha256
    observed = []

    def sql(*args, **kwargs):
        assert threading.get_ident() != gui, "Inbox opened SQL on Qt"
        observed.append("sql")
        return connect(*args, **kwargs)

    def hashed(*args, **kwargs):
        assert threading.get_ident() != gui, "Inbox hashed on Qt"
        return sha(*args, **kwargs)

    def file_digest(*args, **kwargs):
        assert threading.get_ident() != gui, "Inbox hashed a file on Qt"
        return digest(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", sql)
    monkeypatch.setattr(hashlib, "sha256", hashed)
    monkeypatch.setattr(hashlib, "file_digest", file_digest)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: pytest.fail("Inbox called AI"))
    monkeypatch.setattr(
        connection_vault.ConnectionVault,
        "__init__",
        lambda *a, **k: pytest.fail("Inbox opened accounts"),
    )
    service = Inbox(service.path, current_path=lambda: path[0])
    dialog = InboxDialog(service, language="en")
    answer, questions = [QMessageBox.StandardButton.Cancel], []

    def question(*args):
        questions.append(args)
        return answer[0]

    monkeypatch.setattr(QMessageBox, "question", question)
    dialog.show()
    wait(app, lambda: not dialog.busy and dialog._view is not None)
    value = SimpleNamespace(
        app=app,
        dialog=dialog,
        service=service,
        path=path,
        answer=answer,
        questions=questions,
        io=observed,
        rows=lambda table: background(lambda: rows(service.path, table)),
        connect=connect,
    )
    yield value
    if dialog.busy:
        dialog._worker.ticket.cancel()
        wait(app, lambda: not dialog.busy)
    answer[0] = QMessageBox.StandardButton.Discard
    dialog.close()
    app.processEvents()


def capture(panel, text="Exact offline idea"):
    dialog = panel.dialog
    dialog.editor.setPlainText(text)
    assert dialog.save()
    wait(panel.app, lambda: not dialog.busy)
    assert dialog.status.text() == COPY["en"]["saved"]
    assert panel.rows(content.ITEMS)[0]["active"] == 1


def test_constructor_poll_read_render_and_save_are_gui_sql_hash_free(panel):
    dialog = panel.dialog
    assert dialog.windowTitle() == COPY["en"]["title"]
    assert dialog.tree.topLevelItemCount() == 0 and not panel.rows(content.OWNER)
    dialog._check()
    capture(panel, "  DOI:10.1234/Mixed  ")
    # Kind defaults to idea; exact text is never rewritten by classification.
    assert dialog.editor.toPlainText() == "  DOI:10.1234/Mixed  "
    assert dialog.tree.topLevelItem(0).text(0) == "  DOI:10.1234/Mixed  "
    assert dialog.tree.topLevelItem(0).text(2) == COPY["en"]["sync_local"]
    assert panel.io and not dialog._dirty and not dialog.save()


def test_duplicate_save_and_failure_retry_keep_one_durable_request(panel, monkeypatch):
    dialog, service = panel.dialog, panel.service
    original, started, release = service.save, threading.Event(), threading.Event()
    requests = []

    def held(*args, **kwargs):
        requests.append(kwargs["request_id"])
        started.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "save", held)
    dialog.editor.setPlainText("A retained input")
    try:
        assert dialog.save() and started.wait(1)
        for _ in range(15):
            assert not dialog.save() and not dialog.refresh()
    finally:
        release.set()
    wait(panel.app, lambda: not dialog.busy)
    assert len(requests) == 1 and len(panel.rows(content.ITEMS)) == 1
    assert len(panel.rows(content.REQUESTS)) == 1
    assert not dialog.save()
    assert dialog.new_capture()
    dialog.editor.setPlainText("Retry this text")
    attempts = []

    def failed(*args, **kwargs):
        attempts.append(kwargs["request_id"])
        if len(attempts) == 1:
            raise sqlite3.OperationalError("fixture failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "save", failed)
    assert dialog.save()
    wait(panel.app, lambda: not dialog.busy)
    assert dialog.editor.toPlainText() == "Retry this text" and dialog._dirty
    assert dialog.save()
    wait(panel.app, lambda: not dialog.busy)
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert len(panel.rows(content.ITEMS)) == 2


def test_empty_invalid_capture_and_cancelled_replacement_close_preserve_draft(panel):
    dialog = panel.dialog
    assert not dialog.save() and panel.rows(content.ITEMS) == []
    dialog.editor.setPlainText("Keep unsaved words")
    before = dialog.editor.toPlainText()
    assert not dialog.new_capture()
    assert dialog.editor.toPlainText() == before and not dialog.busy
    assert not dialog.close() and dialog.isVisible() and not dialog.disposed
    assert dialog.editor.toPlainText() == before
    assert panel.questions[-1][-1] == QMessageBox.StandardButton.Cancel
    dialog.kind.setCurrentIndex(dialog.kind.findData("url"))
    assert not dialog.save() and dialog.status.text() == COPY["en"]["limit"]
    assert dialog.editor.toPlainText() == before


def test_refresh_keeps_new_draft_and_original_observation(panel):
    capture(panel)
    dialog = panel.dialog
    original = dialog._item.copy()
    dialog.editor.setPlainText("Unsent edited capture")
    assert dialog.refresh()
    wait(panel.app, lambda: not dialog.busy)
    assert dialog.editor.toPlainText() == "Unsent edited capture" and dialog._dirty
    assert dialog._item == original


@pytest.mark.parametrize("change", ["workspace", "binding"])
def test_scope_change_before_worker_save_never_writes_or_discards_text(panel, monkeypatch, change):
    dialog, service = panel.dialog, panel.service
    original, started, release = service.save, threading.Event(), threading.Event()

    def held(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "save", held)
    dialog.editor.setPlainText("Keep exact late draft")
    try:
        assert dialog.save() and started.wait(1)
        if change == "workspace":
            panel.path[0] = service.path.with_name("other.sqlite")
        else:

            def mutate():
                conn = panel.connect(service.path)
                try:
                    conn.execute(
                        "CREATE TABLE research_sync_binding(id INTEGER"
                        " PRIMARY KEY,workspace,origin)"
                    )
                    conn.execute(
                        "INSERT INTO research_sync_binding VALUES(1,'replacement','other')"
                    )
                    conn.commit()
                finally:
                    conn.close()

            background(mutate)
    finally:
        release.set()
    wait(panel.app, lambda: not dialog.busy)
    assert panel.rows(content.ITEMS) == []
    assert dialog.editor.toPlainText() == "Keep exact late draft" and dialog._dirty


def test_queued_read_delivery_rejects_native_change_without_gui_sql(panel):
    dialog = panel.dialog
    capture(panel)
    assert dialog.refresh()
    worker = dialog._worker
    assert worker.wait(3000)

    def mutate():
        conn = panel.connect(panel.service.path)
        try:
            conn.execute("INSERT INTO kv VALUES('unrelated.fixture','changed')")
            conn.commit()
        finally:
            conn.close()

    background(mutate)
    wait(panel.app, lambda: not dialog.busy)
    assert dialog._stale and dialog.status.text() == COPY["en"]["changed"]
    assert not dialog.buttons["save"].isEnabled()


def test_close_cancels_active_worker_then_default_cancel_keeps_unsaved_capture(panel, monkeypatch):
    dialog, service = panel.dialog, panel.service
    original, started, release = service.save, threading.Event(), threading.Event()

    def held(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "save", held)
    dialog.editor.setPlainText("Do not lose this draft")
    try:
        assert dialog.save() and started.wait(1)
        assert not dialog.close() and dialog._closing and dialog.busy
    finally:
        release.set()
    wait(panel.app, lambda: not dialog.busy and not dialog._closing)
    assert not dialog.disposed and dialog.isVisible()
    assert dialog.editor.toPlainText() == "Do not lose this draft"
    assert panel.rows(content.ITEMS) == []


def test_delete_restore_are_explicit_default_cancel_and_keep_history(panel):
    capture(panel)
    dialog = panel.dialog
    assert not dialog.delete() and panel.rows(content.ITEMS)[0]["active"] == 1
    panel.answer[0] = QMessageBox.StandardButton.Yes
    assert dialog.delete()
    wait(panel.app, lambda: not dialog.busy)
    assert panel.rows(content.ITEMS)[0]["active"] == 0
    panel.answer[0] = QMessageBox.StandardButton.Cancel
    assert not dialog.restore()
    panel.answer[0] = QMessageBox.StandardButton.Yes
    assert dialog.restore()
    wait(panel.app, lambda: not dialog.busy)
    assert panel.rows(content.ITEMS)[0]["active"] == 1 and len(panel.rows(content.HISTORY)) == 3


def test_dirty_selection_change_never_replaces_the_other_capture(panel):
    capture(panel, "First")
    dialog = panel.dialog
    assert dialog.new_capture()
    capture(panel, "Second")
    dialog.editor.setPlainText("Draft in second")
    for index in range(dialog.tree.topLevelItemCount()):
        item = dialog.tree.topLevelItem(index)
        if item.data(0, Qt.ItemDataRole.UserRole)["id"] != dialog._identity:
            dialog.tree.setCurrentItem(item)
            break
    assert dialog.editor.toPlainText() == "Draft in second"
    assert len(panel.rows(content.ITEMS)) == 2


def test_accepted_close_hides_and_releases_native_modal(panel):
    dialog = panel.dialog
    assert panel.app.activeModalWidget() is dialog
    assert dialog.close() and dialog.disposed and not dialog.isVisible()
    assert panel.app.activeModalWidget() is not dialog


def test_bilingual_keys_match_and_literal_text_is_not_markup(panel):
    assert set(COPY["en"]) == set(COPY["zh-TW"])
    capture(panel, "<script>private idea</script>")
    assert panel.dialog.tree.topLevelItem(0).text(0) == "<script>private idea</script>"
    other = InboxDialog(panel.service, language="zh-TW")
    other.show()
    wait(panel.app, lambda: not other.busy and other._view is not None)
    assert other.windowTitle() == COPY["zh-TW"]["title"]
    assert other.close()


def test_main_menu_reuses_saved_first_inbox_without_reader_activation(navigation_window):
    window, app = navigation_window
    action = window.research_inbox_action
    assert action in window.research_data_button.menu().actions()
    action.trigger()
    dialog = window._research_inbox_dialog
    wait(app, lambda: not dialog.busy and dialog._view is not None)
    assert dialog.tree.topLevelItemCount() == 0
    action.trigger()
    assert window._research_inbox_dialog is dialog
    assert dialog.close()


def test_main_close_restart_update_keep_inbox_worker_alive():
    from paper_daily.desktop import main

    ignored = []
    dialog = SimpleNamespace(disposed=False, close=lambda: False)
    window = SimpleNamespace(_research_inbox_dialog=dialog, findChildren=lambda _type: [])
    main.MainWindow.closeEvent(window, SimpleNamespace(ignore=lambda: ignored.append(True)))
    assert ignored == [True]
    assert not main.MainWindow._prepare_restart(window)
    assert not main.MainWindow._prepare_update(window)


def test_retained_gui_proposal_is_reviewed_explicitly_without_overwriting_drafts(panel):
    capture(panel, "Original capture")
    dialog, service = panel.dialog, panel.service
    old, item = dialog._view, dialog._item
    background(
        lambda: service.save(
            old,
            request_id=str(uuid4()),
            item_id=item["id"],
            payload=dict(item["payload"], text="Newer saved capture"),
            observed=service.observe(item),
        )
    )
    dialog.editor.setPlainText("Offline GUI proposal")
    assert dialog.save()
    wait(panel.app, lambda: not dialog.busy)
    assert dialog.status.text() == COPY["en"]["conflict"]
    assert dialog.editor.toPlainText() == "Offline GUI proposal"
    assert dialog.review()
    wait(panel.app, lambda: not dialog.busy)
    assert dialog.review_tree.topLevelItemCount() >= 1
    assert not dialog.buttons["use_proposal"].isEnabled()
    panel.answer[0] = QMessageBox.StandardButton.Discard
    assert dialog.new_capture()
    proposal = next(
        dialog.review_tree.topLevelItem(i)
        for i in range(dialog.review_tree.topLevelItemCount())
        if dialog.review_tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
    )
    dialog.review_tree.setCurrentItem(proposal)
    assert dialog.preview.toPlainText() == "Offline GUI proposal"
    assert dialog.decide("incoming")
    wait(panel.app, lambda: not dialog.busy)
    actual = json.loads(panel.rows(content.ITEMS)[0]["body_json"])
    assert actual["text"] == "Offline GUI proposal"
    assert actual["state"] == "new" and actual["created_at"] == item["payload"]["created_at"]
    assert (
        len(panel.rows(content.CANDIDATES)) == 1
        and panel.rows(content.CANDIDATES)[0]["resolved_by"] is not None
    )


def test_page_refresh_keeps_unsent_text_and_shows_next_capture_page(panel):
    capture(panel)

    def seed():
        conn = panel.connect(panel.service.path)
        try:
            owner = conn.execute(f"SELECT token FROM {content.OWNER}").fetchone()[0]
            conn.execute("BEGIN IMMEDIATE")
            for index in range(256):
                identity, operation_id = str(uuid4()), str(uuid4())
                operation = dict(
                    version=2,
                    operation_id=operation_id,
                    workspace_id=owner,
                    device_id="fixture",
                    entity_type="inbox_item",
                    entity_id=identity,
                    action="put",
                    base_revision=0,
                    depends_on=None,
                    payload=payload("Capture " + str(index)),
                    incarnation=operation_id,
                    parents=[],
                    structure_revision=0,
                )
                content.write(conn, operation)
            conn.commit()
        finally:
            conn.close()

    background(seed)
    dialog = panel.dialog
    dialog.editor.setPlainText("Keep while paging")
    assert dialog.refresh()
    wait(panel.app, lambda: not dialog.busy)
    assert dialog.tree.topLevelItemCount() == 256 and dialog.next_button.isEnabled()
    assert dialog.page(1)
    wait(panel.app, lambda: not dialog.busy)
    assert dialog.tree.topLevelItemCount() == 1 and dialog.previous_button.isEnabled()
    assert dialog.editor.toPlainText() == "Keep while paging" and dialog._dirty
