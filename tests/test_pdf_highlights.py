"""Highlights survive reopening and remain scoped to the original PDF."""

import os
from types import SimpleNamespace

import pymupdf
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from test_manual_highlight_ui import loaded as _owned_reader
from test_research_generation import workspace as _workspace

from paper_daily import pdf_highlights, store
from paper_daily.desktop.main import MainWindow, ReaderPage, palette

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def reader(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    app = QApplication.instance() or QApplication([])
    pdf_path = tmp_path / "paper.pdf"
    with pymupdf.open() as doc:
        for _ in range(2):
            page = doc.new_page(width=400, height=500)
            page.insert_text((40, 60), "Alpha beta gamma evidence", fontsize=18)
        doc.save(pdf_path)
    widget = ReaderPage(SimpleNamespace(pal=palette(), remember=lambda *a: None))
    widget.paper = SimpleNamespace(id="test:paper", pdf_path=pdf_path)
    widget.resize(1300, 850)
    widget.show()
    widget._load_pdf()
    app.processEvents()
    yield widget, app, pdf_path
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_highlight_add_reload_remove_and_document_scope(reader):
    widget, app, path = reader
    selection = widget.pdf.selection
    anchor = selection.find(0, "Alpha beta")
    assert selection.focus(anchor)
    selection.highlight.emit()
    fingerprint = widget._pdf_fingerprint
    marks = pdf_highlights.list_marks(widget.paper.id, fingerprint)
    assert len(marks) == 1 and marks[0]["quote"] == "Alpha beta"
    assert len(selection._marks) == 1 and not selection._selected
    pdf_highlights.add(widget.paper.id, fingerprint, anchor, "Alpha beta")
    assert len(pdf_highlights.list_marks(widget.paper.id, fingerprint)) == 1
    assert not pdf_highlights.list_marks("another-paper", fingerprint)
    assert not pdf_highlights.list_marks(widget.paper.id, "different-file")
    widget._load_pdf()
    assert len(selection._marks) == 1
    assert selection.focus(selection.find(0, "beta"))
    selection.erase_highlight.emit()
    assert not pdf_highlights.list_marks(widget.paper.id, fingerprint)
    assert not selection._marks


def test_highlighter_mode_marks_a_drag_and_single_click_selects_saved_mark(reader):
    widget, app, _path = reader
    selection = widget.pdf.selection
    widget.highlight_button.setChecked(True)
    words = selection.words_on(0)
    first, last = selection.map.rect_for(words[0]), selection.map.rect_for(words[1])
    start = QPoint(first.left() + 1, first.center().y())
    end = QPoint(last.right() - 1, last.center().y())
    for kind, point, button, buttons in (
        (QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
    ):
        app.sendEvent(
            selection,
            QMouseEvent(
                kind,
                QPointF(point),
                QPointF(point),
                button,
                buttons,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
    assert len(selection._marks) == 1
    widget.highlight_button.setChecked(False)
    from PySide6.QtTest import QTest

    QTest.mouseClick(selection, Qt.MouseButton.LeftButton, pos=first.center())
    assert selection.selected_highlights() == [selection._marks[0][0]["id"]]
    assert selection.bar.buttons["highlight"].isChecked()
    selection.bar.buttons["highlight"].click()
    assert not selection._marks


def test_cross_page_mark_does_not_drift_when_zooming(reader):
    widget, app, _path = reader
    selection = widget.pdf.selection
    anchor = dict(p0=0, o0=2, p1=1, o1=1)
    assert selection.focus(anchor)
    widget._highlight_selection()
    before = [(w.page, w.order) for w in selection._marks[0][1]]
    widget.pdf.zoom_by(1.3)
    app.processEvents()
    assert [(w.page, w.order) for w in selection._marks[0][1]] == before
    assert {page for page, _ in before} == {0, 1}
    assert len(pdf_highlights.list_marks(widget.paper.id, widget._pdf_fingerprint)) == 1


def test_top_collapse_frees_space_preserves_draft_and_remembers_state(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.processEvents()
    window.reader_page.note_edit.setPlainText("未完成的筆記")
    window.top_toggle.click()
    app.processEvents()
    assert window.top_toolbar.isHidden() and window.reader_page.paper_header.isHidden()
    assert window.compact_header.isVisible()
    assert window.reader_page.note_edit.toPlainText() == "未完成的筆記"
    other = MainWindow()
    assert other.top_toggle.isChecked()
    window.top_expand.click()
    assert not window.top_toolbar.isHidden() and not window.reader_page.paper_header.isHidden()
    assert window.reader_page.note_edit.toPlainText() == "未完成的筆記"
    window.close()
    other.close()
    window.deleteLater()
    other.deleteLater()
    app.processEvents()


def test_ai_sync_preserves_manual_marks_and_dismissed_ai_marks(reader):
    widget, app, path = reader
    analysis = dict(
        source_hash="analysis-1",
        items=[
            dict(page=1, text="Alpha beta gamma evidence", reason="完整研究證據", kind="evidence")
        ],
    )
    selection = widget.pdf.selection
    selection.focus(selection.find(0, "Alpha beta"))
    widget._highlight_selection()
    result = pdf_highlights.sync_ai(widget.paper.id, path, analysis)
    assert result["mapped"] == 1
    marks = pdf_highlights.list_marks(widget.paper.id, widget._pdf_fingerprint)
    assert {m["origin"] for m in marks} == {"manual", "ai"}
    auto = next(m for m in marks if m["origin"] == "ai")
    assert auto["anchor"] == dict(p0=0, o0=0, p1=0, o1=3)
    pdf_highlights.remove(widget.paper.id, widget._pdf_fingerprint, [auto["id"]])
    pdf_highlights.sync_ai(widget.paper.id, path, analysis)
    marks = pdf_highlights.list_marks(widget.paper.id, widget._pdf_fingerprint)
    assert len(marks) == 1 and marks[0]["origin"] == "manual"
    bad = dict(
        source_hash="analysis-2",
        items=[
            dict(page=1, text="Alpha beta fabricated conclusion", reason="bad", kind="evidence")
        ],
    )
    result = pdf_highlights.sync_ai(widget.paper.id, path, bad)
    assert result["mapped"] == 0 and len(result["unmatched"]) == 1
    assert len(pdf_highlights.list_marks(widget.paper.id, widget._pdf_fingerprint)) == 1


def test_cached_reading_function_feeds_pdf_and_materials_without_model_calls(reader, monkeypatch):
    from paper_daily import llm, materials, paper_highlights
    from paper_daily.fetch import _safe_name
    from paper_daily.presentations import _atomic_json

    widget, app, path = reader
    pid = widget.paper.id
    target = path.parent / (_safe_name(pid) + ".pdf")
    target.write_bytes(path.read_bytes())
    monkeypatch.setattr(paper_highlights, "PDF_DIR", path.parent)
    monkeypatch.setattr(materials, "PDF_DIR", path.parent)
    monkeypatch.setattr(paper_highlights, "CACHE_DIR", path.parent / "cache")
    pages = paper_highlights.read_original(pid)
    analysis = dict(
        version=paper_highlights.VERSION,
        paper_id=pid,
        source_hash=paper_highlights._hash(pages),
        items=[dict(page=1, text="Alpha beta gamma evidence", reason="證據", kind="evidence")],
    )
    _atomic_json(paper_highlights._path(pid), analysis)
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("cached AI called"))
    for _ in range(2):
        result, reason = paper_highlights.prepare_reading(pid)
        assert reason == "cached" and result["marks"]["mapped"] == 1
    assert len(pdf_highlights.list_marks(pid, pdf_highlights.document_hash(target))) == 1
    sentence = materials.collect(pid).sentences[0]
    assert sentence["text"] == analysis["items"][0]["text"]
    assert sentence["origin"] == "ai" and sentence["anchor"]["p0"] == 0


def test_first_pdf_auto_preparation_is_once_and_can_be_disabled(reader, monkeypatch):
    widget, app, _path = reader
    pane = widget.presentation_pane
    pane.paper_id = widget.paper.id
    seen = []

    def start(**kw):
        seen.append(kw)
        pane._highlights_busy = True

    monkeypatch.setattr(pane, "_analyze_highlights", start)
    widget._prepare_reading_highlights()
    widget._prepare_reading_highlights()
    assert seen == [dict(force=False)]
    widget.auto_highlights.setChecked(False)
    widget._highlight_attempts.clear()
    widget._prepare_reading_highlights()
    assert len(seen) == 1


def test_highlight_and_material_are_linked_both_ways_without_a_deck(reader, monkeypatch):
    from paper_daily import materials
    from paper_daily.fetch import _safe_name

    widget, app, path = reader
    pid = widget.paper.id
    target = path.parent / (_safe_name(pid) + ".pdf")
    target.write_bytes(path.read_bytes())
    monkeypatch.setattr(materials, "PDF_DIR", path.parent)
    widget.auto_highlights.setChecked(False)
    widget.presentation_pane.load(pid, "Test paper")
    selection = widget.pdf.selection
    selection.focus(selection.find(0, "Alpha beta"))
    widget._highlight_selection()
    assert "手動 1 段" in widget.highlight_status.text()
    assert widget.presentation_pane.deck is None
    widget.browse_highlights.click()
    app.processEvents()
    panel = widget.presentation_pane.materials_panel
    assert panel.isVisible()
    payload = panel.tree.currentItem().data(0, Qt.ItemDataRole.UserRole)
    assert payload["text"] == "Alpha beta" and payload["origin"] == "manual"
    assert selection.selected_text() == "Alpha beta"
    selection.clear()
    panel.tree.itemClicked.emit(panel.tree.currentItem(), 0)
    assert selection.selected_text() == "Alpha beta"
    assert "material" not in selection.bar.buttons
    assert "erase" not in selection.bar.buttons
    widget._erase_selection_highlights()
    assert not materials.collect(pid).sentences


def test_missing_ai_is_visible_in_reader_and_retry_does_not_force_regeneration(reader, monkeypatch):
    from paper_daily import llm, paper_highlights

    widget, app, _path = reader
    pane = widget.presentation_pane
    # Analysis requires a real loaded research owner, not only a legacy PDF widget.
    with store.connect() as conn:
        store.upsert_papers(conn, [{
            "id": widget.paper.id, "title": "Test paper", "venue": "Fixture",
            "year": 2026, "source": "fixture",
        }])
    from paper_daily.desktop import ai_access, highlight_actions

    highlight_actions.capture(widget, widget.paper, store.DB_PATH)
    pane.load(widget.paper.id, "Test paper")
    assert pane._annotation_owner is not None
    requested = []
    monkeypatch.setattr(ai_access, "login", lambda *a: requested.append(a[1]))
    monkeypatch.setattr(llm, "capture_connections", lambda: {})
    monkeypatch.setattr(paper_highlights, "cached", lambda *a: None)
    monkeypatch.setattr(llm, "available", lambda **kw: False)
    widget.prepare_highlights.click()
    assert "AI 設定" in widget.highlight_status.text()
    assert requested == ["paper_highlights"]
    calls = []
    monkeypatch.setattr(pane, "_analyze_highlights", lambda **kw: calls.append(kw))
    widget.prepare_highlights.click()
    assert calls == [dict(force=False)]


def test_showing_reader_retries_preparation_after_hidden_load(reader, monkeypatch):
    widget, app, _path = reader
    widget.hide()
    calls = []
    monkeypatch.setattr(widget, "_prepare_reading_highlights", lambda: calls.append(True))
    widget.show()
    app.processEvents()
    assert calls


workspace = _workspace
owned_reader = _owned_reader


@pytest.fixture
def source_reader(owned_reader):
    """The real resolved original and completed native load own the saved-input read."""
    import time

    w = owned_reader
    w.widget._active_document = w.document
    w.paper._loaded_document = w.document
    end = time.monotonic() + 10
    while (w.widget.pdf.position_source_version() is None
           or w.widget.reading_positions.busy or w.widget.preparation.busy):
        assert time.monotonic() < end, "Native source preparation did not settle"
        w.app.processEvents()
    assert w.widget.pdf.position_identity()[1] == w.document.path
    w.widget._load_highlights(w.document.path, fingerprint=w.document.sha256)
    assert w.widget._highlight_view.document is w.document
    # Drain actual queued native-load/page-record admission before holding a new job.
    # A ready accessor alone does not mean its already-posted GUI callbacks ran.
    from PySide6.QtCore import QTimer

    admitted = []
    QTimer.singleShot(0, w.widget, lambda: admitted.append(True))
    end = time.monotonic() + 10
    while not admitted or w.widget.reading_positions.busy or w.widget.preparation.busy:
        assert time.monotonic() < end, "Native load admission did not settle"
        w.app.processEvents()
    yield w
    w.widget.preparation.dispose()
    end = time.monotonic() + 10
    while w.widget.preparation.busy:
        assert time.monotonic() < end, "Owned mark preparation did not drain"
        w.app.processEvents()


def test_a_mark_drawn_before_the_saved_ones_arrive_is_kept(source_reader, monkeypatch):
    """A held, real owned saved-input read cannot replace a newer manual UI mark."""
    import threading
    import time

    from paper_daily import reader_saved_inputs as saved

    w = source_reader
    widget, app = w.widget, w.app
    selection = widget.pdf.selection
    gate, entered = threading.Event(), threading.Event()
    original, real = saved.read, pdf_highlights.list_marks
    snapshots = []

    def slow(request, *, document=None):
        found = original(request, document=document)
        snapshots.append(found)
        entered.set()
        assert gate.wait(5)
        return found

    monkeypatch.setattr(saved, "read", slow)
    widget.ask_box.setText("Unsent question")
    widget.note_edit.setPlainText("Unsent note")
    widget._load_highlights(w.paper.pdf_path, fingerprint=w.document.sha256, prepare=True)
    try:
        assert entered.wait(2), "Saved highlights did not enter the owned worker lane"
        assert widget.preparation.busy and snapshots[0].data["marks"] == []
        assert widget._pdf_fingerprint
        assert selection.focus(selection.find(0, "Original experiment"))
        selection.bar.buttons["highlight"].click()
        assert len(real(widget.paper.id, widget._pdf_fingerprint)) == 1
        assert len(selection._marks) == 1
    finally:
        gate.set()
    end = time.monotonic() + 10
    while widget.preparation.busy and time.monotonic() < end:
        app.processEvents()
    assert not widget.preparation.busy
    assert len(real(widget.paper.id, widget._pdf_fingerprint)) == 1
    assert len(selection._marks) == 1
    assert selection._marks[0][0]["origin"] == "manual"
    assert selection._marks[0][0]["quote"] == "Original experiment"
    assert widget.ask_box.text() == "Unsent question"
    assert widget.note_edit.toPlainText() == "Unsent note"


def _until_marks(w, predicate):
    import time

    end = time.monotonic() + 10
    while not predicate() and time.monotonic() < end:
        w.app.processEvents()
    assert predicate(), "Owned mark display did not reach its expected state"


def _held_marks(monkeypatch):
    import threading

    from paper_daily import reader_saved_inputs as saved

    entered, release, snapshots = threading.Event(), threading.Event(), []
    original = saved.read

    def read(request, *, document=None):
        assert threading.current_thread() is not threading.main_thread()
        result = original(request, document=document)
        snapshots.append(result)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(saved, "read", read)
    return entered, release, snapshots


@pytest.mark.parametrize("change", ["paper", "workspace", "source", "parent", "close"])
def test_pending_saved_marks_cannot_repaint_a_changed_owner(
    source_reader, monkeypatch, tmp_path, change
):
    w = source_reader
    widget, selection = w.widget, w.widget.pdf.selection
    entered, release, _snapshots = _held_marks(monkeypatch)
    installed, original = [], selection.set_highlights

    def display(marks):
        installed.append(marks)
        return original(marks)

    monkeypatch.setattr(selection, "set_highlights", display)
    widget.ask_box.setText("Keep current question")
    widget.note_edit.setPlainText("Keep current note")
    widget._load_highlights(w.document.path, prepare=True)
    try:
        assert entered.wait(2) and widget.preparation.busy
        if change == "paper":
            widget.paper = SimpleNamespace(id="other-paper", pdf_path=w.document.path)
            widget._qa_epoch += 1
        elif change == "workspace":
            monkeypatch.setattr(store, "DB_PATH", tmp_path / "other.db")
        elif change == "source":
            other = tmp_path / "other.pdf"
            with pymupdf.open() as doc:
                doc.new_page().insert_text((40, 50), "Different source")
                doc.save(other)
            assert widget.pdf.load(other)
        elif change == "parent":
            from paper_daily import sync_capture

            with store.connect() as conn, sync_capture.suppress_capture(conn):
                conn.execute("DELETE FROM papers WHERE id=?", (w.paper.id,))
        else:
            assert not widget.preparation.request_close()
            assert widget.isVisible() and widget.preparation.busy
    finally:
        release.set()
    _until_marks(w, lambda: not widget.preparation.busy)
    assert installed == [] and selection._marks == []
    assert widget.ask_box.text() == "Keep current question"
    assert widget.note_edit.toPlainText() == "Keep current note"
    assert not (tmp_path / "other.db").exists()


def test_removing_a_mark_while_saved_display_is_held_cannot_resurrect_it(
    source_reader, monkeypatch
):
    w = source_reader
    widget, selection = w.widget, w.widget.pdf.selection
    assert selection.focus(selection.find(0, "Original experiment"))
    selection.bar.buttons["highlight"].click()
    assert len(selection._marks) == 1
    entered, release, snapshots = _held_marks(monkeypatch)
    widget._load_highlights(w.document.path, prepare=True)
    try:
        assert entered.wait(2) and len(snapshots[0].data["marks"]) == 1
        assert selection.focus(selection.find(0, "Original experiment"))
        selection.bar.buttons["highlight"].click()
        assert not selection._marks
    finally:
        release.set()
    _until_marks(w, lambda: not widget.preparation.busy)
    assert not selection._marks
    assert not pdf_highlights.list_marks(w.paper.id, w.document.sha256)


def test_mark_display_coalesces_repeated_requests_and_primes_words_off_gui(
    source_reader, monkeypatch
):
    import threading

    from paper_daily.desktop import pdfselect, reader_preparation

    w = source_reader
    widget, selection = w.widget, w.widget.pdf.selection
    assert selection.focus(selection.find(0, "Original experiment"))
    selection.bar.buttons["highlight"].click()
    entered, release, snapshots = _held_marks(monkeypatch)
    reads, original = [], pdfselect.words_in
    preparations, prepare = [], reader_preparation._prepare

    def prepared(request, cancelled):
        preparations.append(request.attempt)
        return prepare(request, cancelled)

    def words(*args):
        assert threading.current_thread() is not threading.main_thread()
        reads.append(args)
        return original(*args)

    monkeypatch.setattr(pdfselect, "words_in", words)
    monkeypatch.setattr(reader_preparation, "_prepare", prepared)
    widget._load_highlights(w.document.path, prepare=True)
    try:
        assert entered.wait(2)
        for _ in range(30):
            assert not widget.preparation.request(marks=True)
        assert len(snapshots) == 1
    finally:
        release.set()
    _until_marks(w, lambda: not widget.preparation.busy)
    assert preparations == [0]
    assert len(reads) == 1 and len(snapshots) == 2
    assert len(selection._marks) == 1
    assert len(pdf_highlights.list_marks(w.paper.id, w.document.sha256)) == 1


def test_mark_display_error_keeps_prior_overlay_and_explicit_retry_works(
    source_reader, monkeypatch
):
    from paper_daily.desktop import pdfselect

    w = source_reader
    widget, selection = w.widget, w.widget.pdf.selection
    assert selection.focus(selection.find(0, "Original experiment"))
    selection.bar.buttons["highlight"].click()
    prior = list(selection._marks)
    original = pdfselect.words_in

    def fail(*_args):
        raise ValueError("Private fixture parsing error")

    monkeypatch.setattr(pdfselect, "words_in", fail)
    widget._load_highlights(w.document.path, prepare=True)
    _until_marks(w, lambda: not widget.preparation.busy)
    assert selection._marks == prior
    assert "Private fixture" not in widget.ask_status.text()
    assert "reopen" in widget.ask_status.text()
    monkeypatch.setattr(pdfselect, "words_in", original)
    widget._load_highlights(w.document.path, prepare=True)
    _until_marks(w, lambda: not widget.preparation.busy)
    assert len(selection._marks) == 1
    assert selection._marks[0][0]["quote"] == "Original experiment"


def test_native_original_arrival_prepares_saved_overlay_on_the_owned_lane(
    source_reader, monkeypatch
):
    w = source_reader
    widget, selection = w.widget, w.widget.pdf.selection
    assert selection.focus(selection.find(0, "Original experiment"))
    selection.bar.buttons["highlight"].click()
    entered, release, snapshots = _held_marks(monkeypatch)
    widget.ask_box.setText("Keep reading question")
    widget._document_arrived(w.paper.id, w.document)
    try:
        assert entered.wait(2) and widget.preparation.busy
        assert len(snapshots[0].data["marks"]) == 1
        assert selection._marks == []
        assert widget._highlight_view.document is w.document
    finally:
        release.set()
    _until_marks(w, lambda: not widget.preparation.busy)
    assert len(selection._marks) == 1
    assert selection._marks[0][0]["quote"] == "Original experiment"
    assert widget.ask_box.text() == "Keep reading question"
