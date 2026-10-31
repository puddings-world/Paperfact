"""One optional menu entry shares the real reader and preserves owner/draft/close guards."""

import sqlite3
from pathlib import Path

import pymupdf
import pytest
from test_reader_chat import reader as reader_fixture
from test_research_chat import legacy as legacy_fixture

from paper_daily import llm, manual_highlight_ops, store
from paper_daily.desktop import claim_evidence, research_tasks
from paper_daily.document_reader import from_workspace

reader = reader_fixture
legacy = legacy_fixture


class Dialog:
    instances = []

    def __init__(self, database, paper_id, parent, **options):
        self.path, self.paper_id = Path(database).resolve(strict=True), paper_id
        info = self.path.stat()
        self.identity = info.st_dev, info.st_ino
        self.parent, self.options = parent, options
        self.current_path = options["current_path"]
        self.current_view = options["current_view"]
        self.view = self.current_view()
        self.document = options["document"]
        self.disposed = self._closing = self._invalid = False
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

    def _check(self):
        """Mirror the real dialog's metadata guard without its worker/UI shell."""
        if self.disposed:
            return False
        try:
            info = self.path.stat()
            same = (
                Path(self.current_path()).resolve() == self.path
                and (info.st_dev, info.st_ino) == self.identity
                and self.current_view() == self.view
            )
        except (OSError, ValueError, RuntimeError):
            same = False
        if not same:
            self._invalid = True
        return same and not self._invalid


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


@pytest.mark.parametrize("change", ["path", "view", "database"])
def test_dialog_fixture_rejects_changed_metadata_and_stays_invalid(tmp_path, change):
    path = tmp_path / "workspace.sqlite"
    sqlite3.connect(path).close()
    current_path, current_view = [path], [(path, "paper", 0, None, None)]
    dialog = Dialog(
        path,
        "paper",
        None,
        document=None,
        current_path=lambda: current_path[0],
        current_view=lambda: current_view[0],
    )
    assert dialog._check() and not dialog._closing
    original_view = current_view[0]
    if change == "path":
        current_path[0] = tmp_path / "other.sqlite"
    elif change == "view":
        current_view[0] = (path, "other-paper", 1, None, None)
    else:
        replacement = tmp_path / "replacement.sqlite"
        sqlite3.connect(replacement).close()
        replacement.replace(path)
        assert (path.stat().st_dev, path.stat().st_ino) != dialog.identity
    assert not dialog._check()
    current_path[0], current_view[0] = path, original_view
    assert not dialog._check()


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
    app, window, page = reader
    root = store.DB_PATH.parent / "pdf"
    root.mkdir()
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 50), "Alpha original evidence passage")
        document.save(root / "local-paper.pdf")
    resolver = from_workspace(store.DB_PATH, legacy_root=root)
    marker = resolver.resolve(page.paper.id)
    assert marker.available and marker.sha256 and marker.path is not None
    assert marker.sha256 != "b" * 64
    monkeypatch.setattr(page.paper, "_document_reader", resolver, raising=False)
    monkeypatch.setattr(page.paper, "_document_status", marker, raising=False)
    monkeypatch.setattr(page.paper, "_loaded_document", marker, raising=False)
    monkeypatch.setattr(page.paper, "_has_pdf", True, raising=False)
    monkeypatch.setattr(page, "_active_document", marker, raising=False)
    monkeypatch.setattr(page, "_pdf_fingerprint", marker.sha256, raising=False)
    monkeypatch.setattr(
        page,
        "_highlight_owner",
        manual_highlight_ops.capture_owner(store.DB_PATH, page.paper.id),
        raising=False,
    )
    assert page.pdf.load(marker.path)
    window.stack.setCurrentWidget(page)
    window.show()
    page.pdf.show()
    app.processEvents()
    assert page.pdf.isVisible() and page.pdf.selection is not None
    selection = page.pdf.selection
    real_focus = selection.focus
    jumps = []

    def focus(anchor):
        assert anchor == source["anchor"]
        focused = real_focus(anchor)
        assert focused and selection.anchor() == anchor
        jumps.append(source)
        return focused

    monkeypatch.setattr(selection, "focus", focus)
    try:
        dialog = claim_evidence.open_report(page)
        callback = dialog.options["source_callback"]
        source = {
            "kind": "claims",
            "document_hash": marker.sha256,
            "anchor": {"p0": 0, "o0": 0, "p1": 0, "o1": 2},
        }
        assert callback(source) and jumps == [source]
        page._pdf_fingerprint = "b" * 64
        assert callback(source) is False and jumps == [source]
        page._pdf_fingerprint = marker.sha256
        replacement = resolver.resolve(page.paper.id)
        assert replacement.available and replacement.sha256 == marker.sha256
        assert replacement is not marker
        page._active_document = replacement
        assert callback(source) is False and jumps == [source]
    finally:
        window._claim_dialog = None
        page.pdf.unload()
        resolver.close()


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
