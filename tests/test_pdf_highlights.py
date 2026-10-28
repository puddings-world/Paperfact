"""Highlights survive reopening and remain scoped to the original PDF."""

import os
from types import SimpleNamespace

import pymupdf
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from paper_daily import pdf_highlights, store
from paper_daily.desktop.main import MainWindow, ReaderPage, palette

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _loaded(widget, app):
    """Saved highlights are matched to words on a worker; wait for them to land."""
    assert widget.prepare.wait()
    app.processEvents()


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
    _loaded(widget, app)
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
    _loaded(widget, app)
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
    pane.paper_id = widget.paper.id
    monkeypatch.setattr(paper_highlights, "cached", lambda *a: None)
    monkeypatch.setattr(llm, "available", lambda **kw: False)
    widget.prepare_highlights.click()
    assert "AI 設定" in widget.highlight_status.text()
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


def test_a_mark_drawn_before_the_saved_ones_arrive_is_kept(reader, monkeypatch):
    # Opening a paper reads its saved highlights on a worker; one drawn at once is
    # saved against the right file and not wiped when the older list lands.
    import threading

    widget, app, _path = reader
    selection = widget.pdf.selection
    gate, real = threading.Event(), pdf_highlights.list_marks

    def slow(paper_id, fingerprint):
        found = real(paper_id, fingerprint)
        gate.wait(5)
        return found

    monkeypatch.setattr(pdf_highlights, "list_marks", slow)
    widget._load_pdf()
    assert widget._pdf_fingerprint
    selection.focus(selection.find(0, "Alpha beta"))
    widget._highlight_selection()
    gate.set()
    _loaded(widget, app)
    assert len(real(widget.paper.id, widget._pdf_fingerprint)) == 1
    assert len(selection._marks) == 1
