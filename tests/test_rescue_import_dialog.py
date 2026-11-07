"""Native rescue shell with controlled backend; codec/SQL retention has separate tests."""

import copy
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import types
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog
from shiboken6 import isValid
from test_sync_files import png

from paper_daily import llm, presentations, store
from paper_daily.desktop.pending_generation import PendingDeckHub
from paper_daily.desktop.rescue_import_dialog import RescueImportDialog
from paper_daily.desktop.window_workspace import WindowWorkspace
from paper_daily.sync_deck_publication import DraftRetention


def settle(app, condition, timeout=8):
    end = time.monotonic() + timeout
    while not condition() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert condition()


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("No real provider, account process or network")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(llm, "complete", deny)
    monkeypatch.setattr(llm, "complete_result", deny)


@pytest.fixture
def ui(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    database = tmp_path / "receiver.sqlite"
    monkeypatch.setattr(store, "DB_PATH", database)
    with sqlite3.connect(database) as conn:
        conn.executescript(store.SCHEMA)
        store.upsert_papers(
            conn,
            [
                dict(
                    id=key,
                    title=title,
                    venue="Fixture",
                    year=2026,
                    source="fixture",
                    doi="10.1234/" + key,
                )
                for key, title in [
                    ("receiver-a", "Receiver A"),
                    ("receiver-b", "Receiver B"),
                    ("literal", "Literal%_paper"),
                ]
            ],
        )
    owner = WindowWorkspace.capture()
    pending = PendingDeckHub(app)
    monkeypatch.setattr(app, "_pending_deck_hub", pending, raising=False)
    deck = presentations.Deck(
        "sender-only-id",
        "Original synthetic paper",
        "Rescued explanation",
        "guide",
        "Researchers",
        10,
        [
            presentations.Slide(
                "Question",
                "Background",
                "Exact statement",
                ["Evidence"],
                "Exact speaker explanation",
                ["original", "figure:1"],
                figure="figure:1",
            )
        ],
        [
            dict(
                id="original", label="Original source", kind="original", text="Exact source passage"
            ),
            dict(id="figure:1", label="Image 1", kind="figure", text="Figure caption"),
        ],
        [
            dict(
                id="figure:" + str(i),
                label="Image " + str(i),
                caption="Unused caption" if i == 3 else "Figure caption",
                page=i,
            )
            for i in range(1, 4)
        ],
        [],
        "2026-11-01",
    )
    presentations.deck_from_dict(deck.to_dict())  # Admit a supported scientific deck.
    images = dict(
        zip(
            ["figure:1", "figure:2", "figure:3"],
            [png("red"), png("blue"), png("green")],
            strict=True,
        )
    )
    data = dict(
        deck=deck.to_dict(),
        image_bytes=images,
        evidence=dict(sources=deck.sources, coverage=[], source_hash="fixture"),
    )
    state = types.SimpleNamespace(
        calls=[],
        block=None,
        entered=threading.Event(),
        release=threading.Event(),
        error=None,
        durable=True,
        actual=None,
        source_data=data,
    )
    gui = threading.get_ident()

    def check(kind, current):
        assert threading.get_ident() != gui
        state.calls.append(kind)
        if state.block == kind:
            state.entered.set()
            assert state.release.wait(6)
        if not current():
            raise ValueError("Fixture original context closed")
        if state.error == kind:
            raise ValueError("Synthetic corrupted source")

    class Source:
        source_path = tmp_path / "rescued.paperfact-draft.json"

        @property
        def preview_data(self):
            assert threading.get_ident() != gui
            return copy.deepcopy(data)

    source = Source()
    source.source_path.write_bytes(b"Synthetic file; backend is controlled in this shell test")
    backend = types.ModuleType("paper_daily.rescue_deck_import")

    def inspect_file(path, *, current):
        check("inspect", current)
        return source

    def capture(path, paper_id, slot, *, expected_native, request_id, current):
        check("capture", current)
        assert Path(path) == database and expected_native == owner.identity
        return types.SimpleNamespace(paper_id=paper_id, slot=slot, request_id=request_id)

    def prepare(target, actual_source, *, current):
        check("prepare", current)
        assert actual_source is source
        return types.SimpleNamespace(target=target)

    def run(job, *, current):
        check("run", current)
        actual = presentations.deck_from_dict(data["deck"])
        actual.paper_id = job.target.paper_id
        actual._revision_figures = copy.deepcopy(images)
        retained = DraftRetention(
            job.target.request_id,
            "cas" if state.durable else "incomplete",
            actual,
            copy.deepcopy(data["evidence"]),
            "Synthetic unavailable storage",
        )
        state.actual = retained
        return types.SimpleNamespace(retention=retained, context_current=current())

    backend.inspect_file, backend.capture, backend.prepare, backend.run = (
        inspect_file,
        capture,
        prepare,
        run,
    )
    monkeypatch.setitem(sys.modules, backend.__name__, backend)
    import paper_daily

    monkeypatch.setattr(paper_daily, "rescue_deck_import", backend, raising=False)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(source.source_path), ""))
    value = types.SimpleNamespace(
        app=app,
        database=database,
        owner=owner,
        pending=pending,
        state=state,
        source=source,
        dialogs=[],
    )
    yield value
    state.release.set()
    for dialog in value.dialogs:
        if isValid(dialog):
            dialog.lease.closed.set()
            if dialog.busy:
                settle(app, lambda actual_dialog=dialog: not actual_dialog.busy)
            dialog.reject()
            dialog.deleteLater()
    for key, result in pending.results.items():
        pending.results.discard(key, expected=result)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def dialog_for(ui, parent=None):
    dialog = RescueImportDialog(ui.owner, parent, language="zh-TW")
    ui.dialogs.append(dialog)
    dialog.show()
    settle(ui.app, lambda: not dialog.busy and dialog.targets.count() == 3)
    assert dialog.targets.currentRow() == -1
    return dialog


def load(ui, dialog):
    dialog.choose()
    settle(ui.app, lambda: not dialog.busy)
    assert dialog.source is not None, dialog.status.text()
    dialog.targets.setCurrentRow(0)


def test_preview_then_explicit_receiver_retention_preserves_saved_research(ui):
    dialog = dialog_for(ui)
    assert not dialog.retain_button.isEnabled() and ui.state.calls == []
    before = ui.database.read_bytes()
    load(ui, dialog)
    assert dialog.images.count() == 3
    assert "Exact speaker explanation" in dialog.text.toPlainText()
    assert "Exact source passage" in dialog.sources.toPlainText()
    dialog.images.setCurrentRow(2)
    assert "Unused caption" in dialog.image_detail.toPlainText()
    assert dialog.retain_button.isEnabled()
    for _ in range(25):
        dialog.retain()
    settle(ui.app, lambda: not dialog.busy)
    assert dialog.result is not None, dialog.status.text()
    assert ui.state.calls == ["inspect", "capture", "prepare", "run"]
    assert dialog.result["paper_id"] == "literal"
    assert dialog.review_button.isEnabled() and not dialog.retain_button.isEnabled()
    assert "未被替換" in dialog.status.text()
    assert ui.database.read_bytes() == before


def test_cancelled_chooser_and_failed_replacement_keep_displayed_preview(ui, monkeypatch):
    dialog = dialog_for(ui)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: ("", ""))
    dialog.choose()
    assert dialog.source is None and ui.state.calls == []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(ui.source.source_path), ""))
    load(ui, dialog)
    source, text = dialog.source, dialog.text.toPlainText()
    ui.state.error = "inspect"
    dialog.choose()
    settle(ui.app, lambda: not dialog.busy)
    assert dialog.source is source and dialog.text.toPlainText() == text
    assert "corrupted" in dialog.status.text()


def test_literal_search_and_empty_selection_never_import(ui):
    dialog = dialog_for(ui)
    dialog.query.setText("%_")
    dialog.search()
    settle(ui.app, lambda: not dialog.busy)
    assert dialog.targets.count() == 1 and "Literal%_paper" in dialog.targets.item(0).text()
    dialog.retain()
    assert ui.state.calls == []
    dialog.query.setText("does not exist")
    dialog.search()
    settle(ui.app, lambda: not dialog.busy)
    assert dialog.targets.count() == 0 and not dialog.retain_button.isEnabled()


def test_fast_repeat_is_single_flight_and_target_change_does_not_relabel_result(ui):
    dialog = dialog_for(ui)
    load(ui, dialog)
    ui.state.block = "run"
    dialog.retain()
    assert ui.state.entered.wait(3)
    for _ in range(25):
        dialog.retain()
    dialog.targets.setCurrentRow(1)
    ui.state.release.set()
    settle(ui.app, lambda: not dialog.busy)
    assert ui.state.calls.count("run") == 1
    assert dialog.result is None and not dialog.review_button.isEnabled()
    assert ui.state.actual.deck.paper_id == "literal"
    assert "選擇已變更" in dialog.status.text()


@pytest.mark.parametrize("change", ["workspace", "close", "destroy"])
def test_held_preview_handles_context_end_and_native_view_teardown(
    ui, monkeypatch, tmp_path, change
):
    dialog = dialog_for(ui)
    ui.state.block = "inspect"
    dialog.choose()
    assert ui.state.entered.wait(3)
    completion = dialog._task
    if change == "workspace":
        other = tmp_path / "other.sqlite"
        other.write_bytes(b"Unrelated file must remain untouched")
        monkeypatch.setattr(store, "DB_PATH", other)
    elif change == "close":
        assert not dialog.close() and dialog.isVisible() and dialog.busy
    else:
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        ui.app.processEvents()
        assert not isValid(dialog)
    ui.state.release.set()
    settle(ui.app, lambda: not isValid(completion))
    if change == "workspace":
        assert dialog.source is None and not dialog.retain_button.isEnabled()
        assert other.read_bytes() == b"Unrelated file must remain untouched"
    elif change == "close":
        assert dialog.disposed and not dialog.isVisible()


def test_failed_storage_keeps_actual_result_and_retry_does_not_restart_import(ui, monkeypatch):
    from paper_daily import raw_deck_closure

    dialog = dialog_for(ui)
    load(ui, dialog)
    ui.state.durable = False
    dialog.retain()
    settle(ui.app, lambda: not dialog.busy)
    assert dialog.pending_key is not None, dialog.status.text()
    actual = ui.state.actual
    assert ui.pending.results.items()[0][1] is actual
    assert actual.deck._revision_figures == ui.state.source_data["image_bytes"]
    monkeypatch.setattr(
        raw_deck_closure, "retry_retention", lambda result: replace(result, state="cas")
    )
    dialog.retain()
    settle(ui.app, lambda: not dialog.busy)
    assert dialog.result is not None, dialog.status.text()
    assert ui.state.calls.count("run") == 1 and ui.state.calls.count("inspect") == 1
    assert not ui.pending.results.pending


def test_review_opens_exact_receiver_candidate_without_reimport(ui, monkeypatch):
    from paper_daily.desktop import rescue_import_dialog as module

    dialog = dialog_for(ui)
    load(ui, dialog)
    dialog.retain()
    settle(ui.app, lambda: not dialog.busy)
    assert dialog.result is not None, dialog.status.text()
    opened = []

    class Review(QDialog):
        def __init__(self, database, candidate_id, *, parent, language):
            super().__init__(parent)
            opened.append((database, candidate_id, language))

    monkeypatch.setattr(module, "_FocusedReview", Review)
    dialog.review()
    assert opened == [(ui.database, ui.state.actual.candidate_id, "zh-TW")]
    assert dialog.disposed and ui.state.calls.count("run") == 1
    dialog.review_dialog.reject()
    dialog.review_dialog.deleteLater()


def test_global_menu_singleton_and_hidden_worker_blocks_main_close_restart_update(ui, monkeypatch):
    from paper_daily import updates
    from paper_daily.ai_types import Settings
    from paper_daily.desktop import main
    from paper_daily.desktop.account_status import AccountStatus
    from paper_daily.desktop.ai_dialog import AIStatusButton

    monkeypatch.setattr(AccountStatus, "check", lambda *a, **kw: None)
    monkeypatch.setattr(AIStatusButton, "refresh", lambda button: button.setText("AI fixture"))
    monkeypatch.setattr(main.ReaderPage, "_check_resources", lambda *a: None)
    monkeypatch.setattr(main.ReaderPage, "_prepare_reading_highlights", lambda *a: None)
    monkeypatch.setattr(main.MainWindow, "top_up_dives", lambda *a: None)
    monkeypatch.setattr(updates, "check", lambda *a, **kw: None)
    monkeypatch.setattr(llm, "settings", lambda **kw: Settings("gateway", model="fixture"))
    monkeypatch.setattr(llm, "available", lambda **kw: False)
    window = main.MainWindow()
    try:
        window.show()
        for _ in range(25):
            window.rescue_import_action.trigger()
        dialog = window._rescue_dialog
        ui.dialogs.append(dialog)
        settle(ui.app, lambda: not dialog.busy and dialog.targets.count() == 3)
        assert len(window.findChildren(RescueImportDialog)) == 1
        ui.state.block = "inspect"
        dialog.choose()
        assert ui.state.entered.wait(3)
        dialog.hide()
        assert not window._prepare_restart() and not window._prepare_update()
        assert not window.close() and window.isVisible()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        ui.app.processEvents()
        assert not window.close()
        ui.state.release.set()
        settle(ui.app, lambda: not window.activity_hub.busy)
    finally:
        ui.state.release.set()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        ui.app.processEvents()
