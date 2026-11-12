"""Actual reader chat preparation; isolated native fixtures and fake providers only."""

import threading
import time
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QWidget
from test_reader_chat import reader as _reader
from test_research_chat import legacy as _legacy
from test_research_chat import messages, start

from paper_daily import manual_highlight_ops, research_chat, store
from paper_daily import reader_saved_inputs as saved
from paper_daily import research_generation as generation
from paper_daily.desktop import main, rich_view
from paper_daily.desktop import reader_preparation as preparation

legacy = _legacy
reader = _reader


def settle(app, predicate):
    for _ in range(1000):
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    pytest.fail("Owned reader preparation did not drain")


@pytest.fixture
def ready(reader):
    app, window, view = reader
    view._highlight_owner = manual_highlight_ops.capture_owner(store.DB_PATH, "local-paper")
    yield app, window, view
    preparation = getattr(view, "preparation", None)
    if preparation is not None:
        preparation.dispose()
        settle(app, lambda: not preparation.busy)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_actual_chat_sql_and_markdown_move_off_gui(ready, monkeypatch):
    app, window, view = ready
    request, _ = research_chat.prepare_chat(start())
    original = window.data.chat_snapshot

    def old_sql(*args, **kwargs):
        assert threading.current_thread() is not threading.main_thread(), "GUI SQL"
        return original(*args, **kwargs)

    monkeypatch.setattr(window.data, "chat_snapshot", old_sql)
    main.ReaderPage._load_chat(view)
    settle(app, lambda: not view.preparation.busy)
    assert "resumeqa:" + request.request_id in view.chat_view._body
    assert view._chat_snapshot["rows"][0]["row"] == messages()[0]
    assert view.ask_box.text() == "Question"
    assert not view.runner.busy


def activate(view):
    main.ReaderPage._load_chat(view)


def pending_turn():
    request, _ = research_chat.prepare_chat(start())
    return request


def held(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = preparation._prepare
    calls = []

    def prepare(request, cancelled):
        calls.append(request.attempt)
        entered.set()
        assert release.wait(5)
        return original(request, cancelled)

    monkeypatch.setattr(preparation, "_prepare", prepare)
    return entered, release, calls


def test_repeated_requests_bound_running_and_latest_pending_and_keep_drafts(ready, monkeypatch):
    app, _, view = ready
    request = pending_turn()
    entered, release, calls = held(monkeypatch)
    view.note_edit.setPlainText("Unsent note")
    activate(view)
    assert entered.wait(2)
    try:
        for _ in range(50):
            activate(view)
        assert calls == [0] and view.preparation.busy
        view._qa_epoch += 1
        view.ask_box.setText("New A draft")
        for _ in range(50):
            activate(view)
        assert calls == [0]
    finally:
        release.set()
    settle(app, lambda: not view.preparation.busy)
    assert calls == [0, 0]
    assert request.request_id in view.chat_view._body
    assert view.ask_box.text() == "New A draft"
    assert view.note_edit.toPlainText() == "Unsent note"
    assert len(messages()) == 1


@pytest.mark.parametrize("interference", ["answer", "checkpoint"])
def test_queued_delivery_semantically_rechecks_rows_or_checkpoint_once(
    ready,
    monkeypatch,
    interference,
):
    app, _, view = ready
    request = pending_turn()
    original = preparation._prepare
    calls = []

    def prepare(*args):
        result = original(*args)
        calls.append(1)
        return result

    monkeypatch.setattr(preparation, "_prepare", prepare)
    activate(view)
    assert view.preparation._thread.wait(5000)
    assert view.preparation.busy  # Native completion still owns its queued delivery.
    if interference == "answer":
        assert research_chat.publish_answer(request, "LATEST ANSWER").status == "accepted"
    else:
        import sqlite3

        before = preparation._fence(Path(store.DB_PATH))
        with closing(sqlite3.connect(store.DB_PATH)) as conn:
            assert conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
        assert preparation._fence(Path(store.DB_PATH)) == before
    settle(app, lambda: not view.preparation.busy)
    assert len(calls) == (2 if interference == "answer" else 1)
    assert ("LATEST ANSWER" in view.chat_view._body) is (interference == "answer")
    assert view._chat_snapshot["rows"][0]["row"]["message_id"] == messages()[0]["message_id"]
    assert "reopen" not in view.ask_status.text()


def test_continuous_unrelated_writes_still_show_the_conversation(ready, monkeypatch):
    # The app writes reading positions and job progress into the same file while a
    # paper is open; on macOS that left every conversation and explanation blank.
    app, _, view = ready
    request = pending_turn()
    original = preparation._prepare
    attempts = []

    def changed(request, cancelled):
        publication = original(request, cancelled)
        attempts.append(request.attempt)
        with closing(generation._connect(request.scope.database)) as conn:
            store.set_kv(conn, "ui.fixture-interference", str(len(attempts)))
            conn.commit()
        return publication

    monkeypatch.setattr(preparation, "_prepare", changed)
    activate(view)
    settle(app, lambda: not view.preparation.busy)
    assert attempts == [0, 1]
    assert request.request_id in view.chat_view._body
    assert "reopen" not in view.ask_status.text()
    assert view.ask_box.text() == "Question"


def test_a_conversation_that_keeps_changing_is_bounded_and_keeps_drafts(ready, monkeypatch):
    app, _, view = ready
    pending_turn()
    original = preparation._prepare
    attempts = []

    def changing(request, cancelled):
        # Each read disagrees with the one before: the rows themselves keep moving.
        attempts.append(request.attempt)
        return replace(original(request, cancelled), recheck=True, settled=False)

    monkeypatch.setattr(preparation, "_prepare", changing)
    activate(view)
    settle(app, lambda: not view.preparation.busy)
    assert attempts == [0, 1]
    assert "reopen" in view.ask_status.text()
    assert view.ask_box.text() == "Question"
    assert view.chat_view._body == ""


def test_failure_then_explicit_retry_preserves_drafts_and_ids(ready, monkeypatch):
    app, _, view = ready
    request = pending_turn()
    original = preparation._prepare

    def failed(*args):
        raise ValueError("Private fixture body must not become a UI error")

    monkeypatch.setattr(preparation, "_prepare", failed)
    activate(view)
    settle(app, lambda: not view.preparation.busy)
    assert "Private fixture" not in view.ask_status.text()
    assert "reopen" in view.ask_status.text()
    assert view.ask_box.text() == "Question"
    monkeypatch.setattr(preparation, "_prepare", original)
    activate(view)
    settle(app, lambda: not view.preparation.busy)
    assert request.request_id in view.chat_view._body
    assert len(messages()) == 1 and view.ask_box.text() == "Question"


def test_close_veto_retains_busy_until_actual_drain_and_discard(ready, monkeypatch):
    app, _, view = ready
    pending_turn()
    entered, release, calls = held(monkeypatch)
    activate(view)
    assert entered.wait(2)
    try:
        assert not view.preparation.request_close()
        assert view.preparation.busy
        view.preparation.dispose()
        assert not view.preparation.request()
        assert view.preparation.busy
    finally:
        release.set()
    settle(app, lambda: not view.preparation.busy)
    assert view.chat_view._body == ""
    assert view.ask_box.text() == "Question" and calls == [0]


def test_changed_view_discards_old_queued_delivery(ready):
    app, _, view = ready
    pending_turn()
    activate(view)
    assert view.preparation._thread.wait(5000)
    view._qa_epoch += 1
    view.ask_box.setText("New view draft")
    settle(app, lambda: not view.preparation.busy)
    assert view.chat_view._body == ""
    assert getattr(view, "_chat_snapshot", None) is None
    assert view.ask_box.text() == "New view draft"


def test_source_and_workspace_changes_never_publish_old_chat(ready, monkeypatch, tmp_path):
    app, _, view = ready
    pending_turn()
    activate(view)
    assert view.preparation._thread.wait(5000)
    other = tmp_path / "other.sqlite"
    monkeypatch.setattr(store, "DB_PATH", other)
    settle(app, lambda: not view.preparation.busy)
    assert not other.exists() and view.chat_view._body == ""
    assert view.ask_box.text() == "Question"


def test_prepare_calls_sql_hash_and_markdown_only_on_worker(ready, monkeypatch):
    app, _, view = ready
    pending_turn()
    calls = []
    original = saved._connect

    def checked(*args):
        assert threading.current_thread() is not threading.main_thread()
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(saved, "_connect", checked)
    from paper_daily.desktop import reader_saved_render

    markdown = reader_saved_render._markdown

    def checked_markdown(*args):
        assert threading.current_thread() is not threading.main_thread()
        return markdown(*args)

    monkeypatch.setattr(reader_saved_render, "_markdown", checked_markdown)
    activate(view)
    settle(app, lambda: not view.preparation.busy)
    assert calls and view._chat_snapshot["rows"]


def test_account_change_does_not_route_or_clear_saved_drafts(ready, monkeypatch):
    from paper_daily import llm

    app, _, view = ready
    pending_turn()
    entered, release, _calls = held(monkeypatch)
    activate(view)
    assert entered.wait(2)

    def forbidden(*args, **kwargs):
        pytest.fail("Read-only rendering acquired an AI route")

    try:
        llm.save_settings(profile="changed", backend="none", isolated=True)
        llm.use_profile("changed", desktop=True)
        monkeypatch.setattr(llm, "capture_connections", forbidden)
        monkeypatch.setattr(llm, "settings", forbidden)
        monkeypatch.setattr(llm, "complete", forbidden)
    finally:
        release.set()
    settle(app, lambda: not view.preparation.busy)
    assert view._chat_snapshot["rows"] and view.ask_box.text() == "Question"


class HeldWeb(QWidget):
    def __init__(self):
        super().__init__()
        self.callbacks = []
        self.pages = []

    def page(self):
        return self

    def runJavaScript(self, _code, _world, callback):
        self.callbacks.append(callback)

    def setHtml(self, body, *_args):
        self.pages.append(body)


def test_actual_rich_view_rejects_old_delayed_keep_scroll_callback(ready, monkeypatch):
    app, _, _view = ready
    monkeypatch.setattr(rich_view, "web_available", lambda: True)
    monkeypatch.setattr(rich_view, "_web_view", lambda *_args: HeldWeb())
    view = rich_view.RichView(main.LIGHT)
    generation_token = [1]
    view.setHtml("OLD_A", keep_scroll=True, current=lambda: generation_token[0] == 1)
    old = view.view.callbacks.pop()
    generation_token[0] = 2
    view.setHtml("NEW_B", current=lambda: generation_token[0] == 2)
    old(100)
    assert len(view.view.pages) == 1
    assert "NEW_B" in view.view.pages[0] and "OLD_A" not in view.view.pages[0]
    assert view._body == "NEW_B"
    view.close()
    view.deleteLater()
    app.processEvents()


def test_rich_view_legacy_default_behavior_is_unchanged(ready, monkeypatch):
    _app, _, _view = ready
    monkeypatch.setattr(rich_view, "web_available", lambda: True)
    monkeypatch.setattr(rich_view, "_web_view", lambda *_args: HeldWeb())
    view = rich_view.RichView(main.LIGHT)
    view.setHtml("LEGACY_A", keep_scroll=True)
    callback = view.view.callbacks.pop()
    callback(15)
    assert "LEGACY_A" in view.view.pages[0]
    view.close()
    view.deleteLater()


def test_atomic_chat_fields_are_not_installed_when_final_rich_admission_rejects(ready, monkeypatch):
    app, _, view = ready
    pending_turn()
    original = view.chat_view.setHtml

    def changed_before_admission(body, **kwargs):
        view._qa_epoch += 1
        return original(body, **kwargs)

    monkeypatch.setattr(view.chat_view, "setHtml", changed_before_admission)
    activate(view)
    settle(app, lambda: not view.preparation.busy)
    assert getattr(view, "_chat_snapshot", None) is None
    assert getattr(view, "_qa_pending", {}) == {}
    assert view.chat_view._body == ""


def test_real_nonempty_wal_checkpoint_requires_exactly_one_semantic_recheck(ready, monkeypatch):
    import sqlite3

    app, _, view = ready
    keeper = sqlite3.connect(store.DB_PATH)
    try:
        keeper.execute("SELECT 1 FROM papers").fetchone()
        request = pending_turn()
        original = preparation._prepare
        calls = []

        def prepare(*args):
            result = original(*args)
            calls.append(1)
            return result

        monkeypatch.setattr(preparation, "_prepare", prepare)
        activate(view)
        assert view.preparation._thread.wait(5000)
        before = preparation._fence(Path(store.DB_PATH))
        assert before[1] is not None and before[1][2] > 0
        assert keeper.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
        after = preparation._fence(Path(store.DB_PATH))
        assert before != after
        settle(app, lambda: not view.preparation.busy)
        assert calls == [1, 1]
        assert request.request_id in view.chat_view._body
        assert view._chat_snapshot["rows"][0]["row"] == messages()[0]
        assert view.ask_box.text() == "Question"
    finally:
        keeper.close()


def test_native_loaded_source_change_discards_queued_chat(ready, tmp_path):
    from test_research_generation import pdf

    from paper_daily.document_reader import from_workspace

    app, _, view = ready
    request = pending_turn()
    root = tmp_path / "local-pdf"
    root.mkdir()
    path = root / "local-paper.pdf"
    pdf(path, "Actual native source A with stable words")
    document = from_workspace(store.DB_PATH, legacy_root=root).resolve("local-paper")
    view._active_document = document
    view._pdf_fingerprint = document.sha256
    assert view.pdf.load(path)
    activate(view)
    settle(app, lambda: not view.preparation.busy)
    previous = view._chat_snapshot
    research_chat.publish_answer(request, "NEW ANSWER")
    activate(view)
    assert view.preparation._thread.wait(5000)
    path.write_bytes(path.read_bytes())
    settle(app, lambda: not view.preparation.busy)
    assert view._chat_snapshot is previous
    assert "NEW ANSWER" not in view.chat_view._body
    assert view.ask_box.text() == "Question"


def test_native_retained_A_is_not_replaced_by_desired_B(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from test_document_reader import LOCAL, prepared
    from test_sync_document_research import document as operation
    from test_sync_document_research import pdf_bytes
    from test_sync_reading_state_research import save

    from paper_daily import sync_capture
    from paper_daily.sync_client import SyncClient
    from paper_daily.sync_research import research_writer

    app = QApplication.instance() or QApplication([])
    database, journal, _blobs, resolver, _alias, _data = prepared(tmp_path)
    SyncClient(journal, research_writer)
    with closing(generation._connect(database)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        sync_capture.install(conn, workspace_id="workspace", device_id="device")
        conn.commit()
    monkeypatch.setattr(store, "DB_PATH", database)
    window = SimpleNamespace(pal=main.LIGHT, remember=lambda *_: None, data=main.Data())
    view = main.ReaderPage(window)
    view.paper = SimpleNamespace(id=LOCAL)
    view._qa_view_database = database
    view._highlight_owner = manual_highlight_ops.capture_owner(database, LOCAL)
    loaded_a = resolver.resolve(LOCAL)
    view._active_document = loaded_a
    view._pdf_fingerprint = loaded_a.sha256
    try:
        assert view.pdf.load(loaded_a.path)
        settle(app, lambda: not view.preparation.busy)
        position = view.pdf.position_identity()
        witness = view.pdf.position_source_version()
        activate(view)
        assert view.preparation._thread.wait(5000)
        save(journal, operation(pdf_bytes("Desired B"), op_id="reader-new-b"))
        assert resolver.intact(loaded_a) and not resolver.current(loaded_a)
        settle(app, lambda: not view.preparation.busy)
        assert view._active_document is loaded_a
        assert view.pdf.position_identity() == position
        assert view.pdf.position_source_version() == witness
        assert view._chat_snapshot["paper_id"] == LOCAL
    finally:
        view.preparation.dispose()
        settle(app, lambda: not view.preparation.busy)
        view.pdf.unload()
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_destroying_reader_drains_global_worker_without_delivery(legacy, monkeypatch):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    window = SimpleNamespace(pal=main.LIGHT, remember=lambda *_: None, data=main.Data())
    view = main.ReaderPage(window)
    view.paper = SimpleNamespace(id="local-paper")
    view._qa_view_database = legacy
    view._highlight_owner = manual_highlight_ops.capture_owner(legacy, "local-paper")
    pending_turn()
    control = view.preparation
    entered, release, _calls = held(monkeypatch)
    activate(view)
    assert entered.wait(2)
    try:
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert control.busy
    finally:
        release.set()
    settle(app, lambda: not control.busy)
    assert not preparation._LIVE


def test_native_source_signal_does_not_admit_chat_before_explicit_chat_request(ready):
    _app, _, view = ready
    view.pdf.source_changed.emit()
    assert not view.preparation.busy


def test_actual_reader_load_switches_to_empty_B_then_restores_A_draft(ready, monkeypatch):
    app, _, view = ready
    pending_turn()
    with store.connect() as conn:
        store.upsert_papers(
            conn,
            [
                dict(
                    id="second",
                    title="Second paper",
                    venue="Fixture",
                    year=2026,
                    source="fixture",
                )
            ],
        )
    for name in (
        "_render_facts",
        "_check_resources",
        "_load_pdf",
        "_load_dive",
        "_load_notes",
        "_show_cites_if_visible",
    ):
        monkeypatch.setattr(view, name, lambda: None)
    monkeypatch.delattr(view, "_load_chat")
    monkeypatch.setattr(view.analysis_bar, "show_paper", lambda *_: None)
    monkeypatch.setattr(view.questions, "load", lambda *_: None)
    monkeypatch.setattr(view.presentation_pane, "load", lambda *_, **__: None)

    def paper(identity, title):
        return main.Paper(
            identity,
            title,
            "Fixture",
            2026,
            None,
            None,
            [],
            None,
            None,
            False,
            None,
            None,
            None,
            "",
            None,
            "pending",
            None,
        )

    first, second = paper("local-paper", "A"), paper("second", "B")
    view.load(first)
    settle(app, lambda: not view.preparation.busy)
    assert "resumeqa:" in view.chat_view._body
    view.ask_box.setText("Draft A")
    view.note_edit.setPlainText("Unsent note")
    entered, release, calls = held(monkeypatch)
    view._load_chat()
    assert entered.wait(2)
    try:
        view.load(second)
        assert view.chat_view._body == ""
        assert view._chat_snapshot is None
        view.ask_box.setText("Draft B")
    finally:
        release.set()
    settle(app, lambda: not view.preparation.busy)
    assert "resumeqa:" not in view.chat_view._body
    assert view._chat_snapshot["paper_id"] == "second"
    assert view.ask_box.text() == "Draft B"
    assert view.note_edit.toPlainText() == "Unsent note"
    view.load(first)
    settle(app, lambda: not view.preparation.busy)
    assert view.ask_box.text() == "Draft A"
    assert "resumeqa:" in view.chat_view._body
    assert len(calls) == 3
