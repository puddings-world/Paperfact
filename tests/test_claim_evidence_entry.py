"""One optional menu entry shares the real reader and preserves owner/draft/close guards."""

from pathlib import Path

import pytest
from test_reader_chat import reader as reader_fixture
from test_research_chat import legacy as legacy_fixture

from paper_daily import llm, manual_highlight_ops, store
from paper_daily.desktop import claim_evidence, research_tasks

reader = reader_fixture
legacy = legacy_fixture


class Dialog:
    instances = []

    def __init__(self, database, paper_id, parent, **options):
        self.path, self.paper_id = Path(database).resolve(), paper_id
        self.parent, self.options = parent, options
        self.document = options["document"]
        self.disposed = False
        self.opened = self.raised = 0
        self.instances.append(self)

    def open(self):
        self.opened += 1

    def show(self):
        pass

    def raise_(self):
        self.raised += 1

    def close(self):
        return False


@pytest.fixture
def dialogs(monkeypatch):
    Dialog.instances = []
    monkeypatch.setattr(claim_evidence, "ClaimEvidenceDialog", Dialog)
    monkeypatch.setattr(
        llm, "capture_connections", lambda: pytest.fail("Opening read view read AI")
    )
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **k: pytest.fail("Opening read view called AI")
    )
    return Dialog


def test_single_optional_entry_reuses_current_paper_view_without_changing_drafts(
    reader,
    dialogs,
    monkeypatch,
):
    _app, window, page = reader
    loaded_owner = manual_highlight_ops.capture_owner(store.DB_PATH, page.paper.id)
    monkeypatch.setattr(page, "_highlight_owner", loaded_owner, raising=False)
    draft = page.ask_box.text()
    widget = research_tasks.button(page)
    action = [item for item in widget.menu().actions() if item.data() == "claim_evidence"]
    assert len(action) == 1
    try:
        action[0].trigger()
        action[0].trigger()
        assert len(dialogs.instances) == 1
        dialog = dialogs.instances[0]
        assert dialog.path == store.DB_PATH.resolve() and dialog.paper_id == page.paper.id
        assert dialog.opened == 1 and dialog.raised == 1
        assert page.ask_box.text() == draft
        assert dialog.options["current_path"]() == store.DB_PATH
        assert dialog.options["owner"] is page._highlight_owner
        assert dialog.options["changes"] is window.workspace_changes
    finally:
        window._claim_dialog = None
        widget.deleteLater()


def test_empty_reader_does_not_open_report_or_ai(reader, dialogs):
    _app, _window, page = reader
    original = page.paper
    page.paper = None
    try:
        assert claim_evidence.open_report(page) is None and not dialogs.instances
    finally:
        page.paper = original


def test_current_reader_source_hash_and_identity_are_rechecked_before_callback(
    reader, dialogs, monkeypatch
):
    _app, window, page = reader
    marker = object()
    monkeypatch.setattr(page, "_active_document", marker, raising=False)
    monkeypatch.setattr(page, "_pdf_fingerprint", "a" * 64, raising=False)
    monkeypatch.setattr(page.pdf, "isVisible", lambda: True)
    monkeypatch.setattr(page.pdf, "selection", object())
    jumps = []
    monkeypatch.setattr(page, "_jump_to_source", jumps.append)
    try:
        dialog = claim_evidence.open_report(page)
        callback = dialog.options["source_callback"]
        source = {"document_hash": "a" * 64, "anchor": {"p0": 0, "o0": 0, "p1": 0, "o1": 2}}
        assert callback(source) and jumps == [source]
        page._pdf_fingerprint = "b" * 64
        assert callback(source) is False and jumps == [source]
        page._pdf_fingerprint = "a" * 64
        page._active_document = object()
        assert callback(source) is False and jumps == [source]
    finally:
        window._claim_dialog = None


def test_claim_worker_guard_blocks_parent_close_and_update_without_discarding_input(
    reader, dialogs
):
    app, window, page = reader
    window.show()
    app.processEvents()
    draft = page.ask_box.text()
    try:
        claim_evidence.open_report(page)
        assert window._prepare_update() is False
        assert window.close() is False
        assert page.ask_box.text() == draft
    finally:
        window._claim_dialog = None
