"""Native local audit controls preserve drafts and reject late/source-stale output."""

import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QWidget
from test_research_evidence import source as source_fixture

from paper_daily import audit_inputs
from paper_daily.desktop.research_audit import TEXT, AuditDialog

source = source_fixture


def wait(app, condition, seconds=15):
    end = time.monotonic() + seconds
    while not condition() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert condition()


@pytest.fixture
def view(source):
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    question = QLineEdit("Unsent question", parent)
    note = QPlainTextEdit("Unsent note", parent)
    active = [source._owner.db_path, "paper", source]
    dialog = AuditDialog(
        source._owner.db_path,
        "paper",
        document=source,
        current_view=lambda: tuple(active),
        parent=parent,
        language="en",
    )
    dialog.show()
    wait(app, lambda: not dialog.busy and dialog.status.text() != TEXT["en"]["working"])
    assert dialog.report is not None, dialog.status.text()
    value = SimpleNamespace(
        app=app, d=dialog, active=active, question=question, note=note, parent=parent, source=source
    )
    yield value
    if dialog.busy:
        dialog.cancel()
        wait(app, lambda: not dialog.busy)
    dialog.close()
    parent.close()
    dialog.deleteLater()
    parent.deleteLater()
    app.processEvents()


def test_open_is_local_readonly_and_empty_scope_honest(view):
    assert view.d.status.text() == TEXT["en"]["empty"]
    assert view.d.report["semantics"] == "not_checked"
    assert not view.d.progress.isVisible()
    assert view.question.text() == "Unsent question" and view.note.toPlainText() == "Unsent note"


@pytest.mark.parametrize("mode", ["failure", "cancel", "switch", "close"])
def test_pending_duplicate_failure_cancel_switch_close_preserve_report(view, mode):
    dialog = view.d
    original = dialog.report
    started, release = threading.Event(), threading.Event()
    calls = []
    capture = audit_inputs.AuditCapture.capture

    def pending(*args, **kwargs):
        calls.append(1)
        started.set()
        release.wait(10)
        if mode == "failure":
            raise ValueError("private details not shown")
        return capture(*args, **kwargs)

    dialog.capture = pending
    try:
        assert dialog.refresh()
        wait(view.app, started.is_set)
        assert not dialog.refresh() and not dialog.refresh_button.isEnabled()
        if mode == "cancel":
            dialog.cancel()
        elif mode == "switch":
            view.active[1] = "different"
        elif mode == "close":
            assert not dialog.close() and not dialog.disposed
        release.set()
        wait(view.app, lambda: not dialog.busy)
        assert calls == [1] and dialog.report is original
        assert (
            view.question.text() == "Unsent question" and view.note.toPlainText() == "Unsent note"
        )
        assert "private details" not in dialog.status.text()
        if mode == "close":
            assert dialog.disposed
        if mode == "switch":
            assert not dialog.refresh_button.isEnabled()
        if mode == "failure":
            dialog.capture = capture
            assert dialog.refresh()
            wait(view.app, lambda: not dialog.busy)
            assert dialog.status.text() == TEXT["en"]["empty"]
    finally:
        release.set()


def test_change_between_worker_return_and_gui_delivery_discards_new_result(view):
    dialog = view.d
    original = dialog.report
    capture = dialog.capture

    def stale(*args, **kwargs):
        result = capture(*args, **kwargs)

        class Delivery:
            def run(self, **kw):
                return result.run(**kw)

            def current(self):
                return False

        return Delivery()

    dialog.capture = stale
    dialog.refresh()
    wait(view.app, lambda: not dialog.busy)
    assert dialog.report is original and dialog.status.text() == TEXT["en"]["changed"]


@pytest.mark.parametrize("mode", ["navigate", "source-changed", "saved-changed"])
def test_original_navigation_rechecks_real_source_and_saved_context(view, mode):
    import hashlib
    import json
    import sqlite3
    from contextlib import closing

    from paper_daily import manual_highlight_ops
    from paper_daily import research_evidence as evidence

    source = view.source
    quote = "Replication used a held-out cohort of 50 participants."
    proposals = {
        "format": evidence.FORMAT,
        "source": {"paper_id": "paper", "document_hash": source.sha256},
        "claims": [
            {
                "text": "A fixture assertion",
                "judgment": {"status": "unresolved", "reason": "Requires review"},
                "passages": [{"quote": quote, "page": 2, "anchor": None}],
            }
        ],
    }
    anchor = evidence.verify(source, proposals)["claims"][0]["passages"][0]["location"]["anchor"]
    database = source._owner.db_path
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            "INSERT INTO pdf_highlights(paper_id,document_hash,quote,anchor,created_at) "
            "VALUES(?,?,?,?,?)",
            ("paper", source.sha256, quote, json.dumps(anchor), "now"),
        )
    dialog = view.d
    dialog.owner = manual_highlight_ops.capture_owner(database, "paper")
    jumps = []
    dialog.source_callback = lambda request: jumps.append(request) or True
    dialog.refresh()
    wait(view.app, lambda: not dialog.busy)
    dialog.filter.setChecked(False)
    check = next(c for c in dialog.report["checks"] if c["state"] == "located")
    assert len(dialog.source_buttons) == 1
    if mode == "source-changed":
        source.path.write_bytes(b"changed fixture source")
    if mode == "saved-changed":
        with closing(sqlite3.connect(database)) as conn, conn:
            conn.execute("INSERT INTO dives VALUES('paper','new saved analysis','now',NULL)")
        assert dialog.open_source(check) is False
        assert jumps == []
        return
    assert dialog.open_source(check)
    assert not dialog.open_source(check)
    wait(view.app, lambda: not dialog.busy)
    if mode == "navigate":
        assert len(jumps) == 1
        assert jumps[0]["anchor"] == anchor and jumps[0]["document_hash"] == source.sha256
        assert jumps[0]["text"] == quote
        assert hashlib.sha256(source.path.read_bytes()).hexdigest() == source.sha256
    else:
        assert jumps == [] and dialog.status.text() == TEXT["en"]["source_failed"]
