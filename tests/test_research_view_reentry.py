"""Native research actions recover stale views and report actual navigation outcomes.

These use real dialogs, action activation, workers and a fixture-loaded native PDF.
No ordinary reader loading, real providers or account operations are exercised.
"""

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton
from test_audit_decks import saved as deck_saved_fixture
from test_audit_ui import wait
from test_claim_jobs import claims as claims_fixture
from test_claim_jobs import job as claim_job
from test_claim_jobs import ready as ready_fixture
from test_claim_jobs import workspace as workspace_fixture
from test_deck_audit_ui import panel as deck_panel_fixture

from paper_daily import annotation_reader, audit_inputs, llm, manual_highlight_ops, updates
from paper_daily.desktop import document_flow, main

workspace = workspace_fixture
ready = ready_fixture
claims = claims_fixture
saved = deck_saved_fixture
panel = deck_panel_fixture


@pytest.fixture
def reading_window(claims, monkeypatch):
    assert claim_job(claims).run().status == "accepted"
    ready = claims[0]
    document = ready[2]
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(updates, "check", lambda *a, **k: None)
    monkeypatch.setattr(main, "PDF_DIR", document.path.parent)
    from paper_daily import config

    monkeypatch.setattr(config, "PDF_DIR", document.path.parent)
    window = main.MainWindow()
    reader = window.reader_page
    reader.reading_positions.close()
    reader.paper = main.Paper(
        "paper",
        "Fixture original",
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
        "main",
        None,
        "pending",
        None,
    )
    reader.paper._document_reader = document._owner
    reader.paper._document_status = document
    reader.paper._loaded_document = document
    reader._qa_view_database = ready[0]
    reader._active_document = document
    reader._pdf_fingerprint = document.sha256
    reader._highlight_owner = manual_highlight_ops.capture_owner(ready[0], "paper")
    reader._qa_epoch += 1
    assert reader.pdf.load(document.path)
    assert reader.pdf.selection is not None
    reader.ask_box.setText("Unsent question")
    reader.note_edit.blockSignals(True)
    reader.note_edit.setPlainText("Unsent note")
    reader.note_edit.blockSignals(False)
    window.stack.setCurrentWidget(reader)
    window.show()
    app.processEvents()
    assert reader.pdf.isVisible()
    value = SimpleNamespace(
        app=app, window=window, reader=reader, ready=ready, calls=claims[2], document=document
    )
    yield value
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard)
    for name in ("_audit_dialog", "_claim_dialog"):
        dialog = getattr(window, name, None)
        if dialog is not None and not dialog.disposed:
            child = getattr(dialog, "_appraisal_dialog", None)
            if child is not None and not child.disposed:
                child.cancel()
                wait(app, lambda child=child: not child.busy)
                child.close()
            if dialog.busy:
                dialog.cancel()
                wait(app, lambda dialog=dialog: not dialog.busy)
            dialog.close()
    reader.ask_box.clear()
    reader.note_edit.blockSignals(True)
    reader.note_edit.clear()
    reader.note_edit.blockSignals(False)
    reader._note_dirty = False
    window._closing_with_recovery = True
    window.workspace_changes.close()
    window.close()
    window.deleteLater()
    app.processEvents()


def activate(view, kind):
    picker = view.reader.findChild(QPushButton, "researchTasks")
    assert picker is not None
    action = next(a for a in picker.menu().actions() if a.data() == kind)
    action.trigger()
    dialog = getattr(view.window, "_claim_dialog" if kind == "claim_evidence" else "_audit_dialog")
    return action, dialog


def loaded(view, dialog, kind):
    def ready():
        report = (dialog.saved or {}).get("report") if kind == "claim_evidence" else dialog.report
        return not dialog.busy and report is not None

    wait(view.app, ready)


@pytest.mark.parametrize("kind", ["claim_evidence", "analysis_audit"])
def test_actual_menu_reopen_after_reader_epoch_change_retires_stale_view(reading_window, kind):
    view = reading_window
    action, original = activate(view, kind)
    loaded(view, original, kind)
    view.reader._qa_epoch += 1
    action.trigger()
    current = getattr(view.window, "_claim_dialog" if kind == "claim_evidence" else "_audit_dialog")
    assert current is not original and original.disposed
    loaded(view, current, kind)
    assert current.isVisible()
    assert current.refresh_button.isEnabled()
    for _ in range(8):
        action.trigger()
    assert (
        getattr(view.window, "_claim_dialog" if kind == "claim_evidence" else "_audit_dialog")
        is current
    )
    assert len(view.calls) == 1
    assert view.reader.ask_box.text() == "Unsent question"
    assert view.reader.note_edit.toPlainText() == "Unsent note"


def test_actual_saved_deck_action_reopens_for_current_selection(panel):
    pane = panel.pane
    pane.deck_audit_action.trigger()
    original = pane._deck_audit_dialog
    wait(panel.app, lambda: not original.busy and original.prepared is not None)
    pane._annotation_epoch += 1
    pane.deck_audit_action.trigger()
    current = pane._deck_audit_dialog
    assert current is not original and original.disposed
    wait(panel.app, lambda: not current.busy and current.prepared is not None)
    assert current.isVisible() and current.refresh_button.isEnabled()
    assert pane._deck_audit_running == 0 and not pane.busy


@pytest.mark.parametrize("kind", ["claim_evidence", "analysis_audit"])
@pytest.mark.parametrize("failure", ["guard", "focus"])
def test_actual_source_button_keeps_view_when_final_navigation_fails(
    reading_window, monkeypatch, kind, failure
):
    view = reading_window
    _action, dialog = activate(view, kind)
    loaded(view, dialog, kind)
    if kind == "analysis_audit":
        dialog.filter.setChecked(False)
    assert dialog.source_buttons
    focused, scrolled = [], []
    selection = view.reader.pdf.selection
    original_focus = selection.focus

    def focus(anchor):
        focused.append(anchor)
        return False if failure == "focus" else original_focus(anchor)

    monkeypatch.setattr(selection, "focus", focus)
    monkeypatch.setattr(selection, "scroll_to_page", scrolled.append)
    if failure == "guard":
        monkeypatch.setattr(main, "anchor_allowed", lambda *a: False)
        monkeypatch.setattr(document_flow, "anchor_allowed", lambda *a: False)
    dialog.source_buttons[0].click()
    wait(view.app, lambda: not dialog.busy)
    assert not dialog.disposed and dialog.isVisible()
    assert dialog.status.text() == dialog.t["source_failed"]
    assert not scrolled
    assert bool(focused) is (failure == "focus")
    assert len(view.calls) == 1
    assert view.reader.ask_box.text() == "Unsent question"
    assert view.reader.note_edit.toPlainText() == "Unsent note"


def test_saved_item_full_qualification_is_readable_in_existing_disclosure(reading_window):
    view = reading_window
    tail = "CRITICAL QUALIFICATION: the conclusion excludes this population."
    body = "Source context and argument. " * 40 + tail
    view.window.data.add_note("paper", body)
    _action, dialog = activate(view, "analysis_audit")
    loaded(view, dialog, "analysis_audit")
    dialog.filter.setChecked(False)
    section = next(
        s for s in dialog.sections if s.button.text().startswith(dialog.features["note"])
    )
    section.button.click()
    assert not section.body.isVisible()
    section.button.click()
    assert section.body.isVisible()
    labels = [label.text() for label in section.findChildren(QLabel)]
    assert body in labels and any(tail in text for text in labels)
    assert len(view.calls) == 1


@pytest.mark.parametrize("kind", ["claim_evidence", "analysis_audit"])
def test_stale_busy_menu_view_drains_before_later_explicit_reopen(
    reading_window, monkeypatch, kind
):
    view = reading_window
    entered, release = threading.Event(), threading.Event()
    starts = []
    if kind == "claim_evidence":
        original = annotation_reader.saved

        def pending(*args, **kwargs):
            starts.append(1)
            entered.set()
            assert release.wait(15)
            return original(*args, **kwargs)

        monkeypatch.setattr(annotation_reader, "saved", pending)
    else:
        original = audit_inputs.AuditCapture.run

        def pending(capture, *args, **kwargs):
            starts.append(1)
            entered.set()
            assert release.wait(15)
            return original(capture, *args, **kwargs)

        monkeypatch.setattr(audit_inputs.AuditCapture, "run", pending)
    action, dialog = activate(view, kind)
    try:
        wait(view.app, entered.is_set)
        worker = dialog._worker
        view.reader._qa_epoch += 1
        for _ in range(5):
            action.trigger()
        assert dialog._closing and dialog.busy and not dialog.disposed
        assert dialog._worker is worker and starts == [1]
        assert not view.window.close() and view.window.isVisible()
        assert (
            getattr(view.window, "_claim_dialog" if kind == "claim_evidence" else "_audit_dialog")
            is dialog
        )
    finally:
        release.set()
        wait(view.app, lambda: not dialog.busy)
    wait(view.app, lambda: dialog.disposed)
    if kind == "claim_evidence":
        monkeypatch.setattr(annotation_reader, "saved", original)
    else:
        monkeypatch.setattr(audit_inputs.AuditCapture, "run", original)
    action.trigger()
    fresh = getattr(view.window, "_claim_dialog" if kind == "claim_evidence" else "_audit_dialog")
    assert fresh is not dialog
    loaded(view, fresh, kind)
    assert len(view.calls) == 1


def install_document(view, document, *, paper=None, advance_epoch=True):
    reader = view.reader
    if paper is not None:
        reader.paper = paper
    reader.paper._document_reader = document._owner
    reader.paper._document_status = document
    reader.paper._loaded_document = document
    reader._active_document = document
    reader._pdf_fingerprint = document.sha256
    reader._highlight_owner = manual_highlight_ops.capture_owner(view.ready[0], reader.paper.id)
    if advance_epoch:
        reader._qa_epoch += 1
    assert reader.pdf.load(document.path)
    view.app.processEvents()


@pytest.mark.parametrize("kind", ["claim_evidence", "analysis_audit"])
@pytest.mark.parametrize("change", ["paper", "pdf", "revalidated_document"])
def test_real_paper_pdf_or_document_switch_reopens_current_saved_view(reading_window, kind, change):
    from dataclasses import replace

    from test_research_generation import pdf

    from paper_daily import store
    from paper_daily.document_reader import from_workspace

    view = reading_window
    action, original = activate(view, kind)
    loaded(view, original, kind)
    root = view.document.path.parent
    paper = view.reader.paper
    if change == "paper":
        with store.connect() as conn:
            store.upsert_papers(
                conn,
                [
                    dict(
                        id="other",
                        title="Other fixture",
                        year=2026,
                        venue="Fixture",
                        source="fixture",
                    )
                ],
            )
        pdf(root / "other.pdf", "A genuinely different paper and original.")
        document = from_workspace(view.ready[0], legacy_root=root).resolve("other")
        paper = replace(paper, id="other", title="Other fixture")
    elif change == "pdf":
        replacement_root = root.parent / "replacement-pdf"
        replacement_root.mkdir()
        pdf(replacement_root / "paper.pdf", "The replacement original has different conclusions.")
        document = from_workspace(view.ready[0], legacy_root=replacement_root).resolve("paper")
        assert document.sha256 != view.document.sha256
    else:
        document = from_workspace(view.ready[0], legacy_root=root).resolve("paper")
        assert document is not view.document and document.sha256 == view.document.sha256
    assert document.available
    install_document(view, document, paper=paper, advance_epoch=change != "revalidated_document")
    action.trigger()
    current = getattr(view.window, "_claim_dialog" if kind == "claim_evidence" else "_audit_dialog")
    assert current is not original and original.disposed
    assert current.document is document and current.paper_id == paper.id
    if kind == "analysis_audit":
        wait(view.app, lambda: not current.busy and current.report is not None)
        assert current.report["source"]["document_hash"] == document.sha256
    else:
        wait(view.app, lambda: not current.busy and current.status.text() != current.t["loading"])
        if change == "paper":
            assert current.saved is None
        else:
            assert current.saved["report"]["source"]["document_hash"] == view.document.sha256
    assert view.reader.ask_box.text() == "Unsent question"
    assert view.reader.note_edit.toPlainText() == "Unsent note"
    assert len(view.calls) == 1


@pytest.mark.parametrize("kind", ["claim_evidence", "analysis_audit"])
def test_actual_source_focus_success_still_navigates_and_preserves_drafts(reading_window, kind):
    view = reading_window
    _action, dialog = activate(view, kind)
    loaded(view, dialog, kind)
    if kind == "analysis_audit":
        dialog.filter.setChecked(False)
    assert dialog.source_buttons
    dialog.source_buttons[0].click()
    wait(view.app, lambda: not dialog.busy)
    if kind == "claim_evidence":
        assert dialog.disposed
    else:
        assert dialog.status.text() == dialog.t["source"]
    assert view.reader.pdf.selection.selected_text()
    assert view.reader.ask_box.text() == "Unsent question"
    assert view.reader.note_edit.toPlainText() == "Unsent note"
    assert len(view.calls) == 1


def test_stale_busy_deck_drains_and_keeps_parent_busy_until_release(panel, monkeypatch):
    from paper_daily.desktop import deck_audit

    entered, release = threading.Event(), threading.Event()
    original_prepare = deck_audit.DeckAuditReader.prepare
    calls = []

    def pending(service, *args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(15)
        return original_prepare(service, *args, **kwargs)

    monkeypatch.setattr(deck_audit.DeckAuditReader, "prepare", pending)
    pane = panel.pane
    pane.deck_audit_action.trigger()
    dialog = pane._deck_audit_dialog
    try:
        wait(panel.app, entered.is_set)
        pane._annotation_epoch += 1
        for _ in range(5):
            pane.deck_audit_action.trigger()
        assert pane._deck_audit_dialog is dialog
        assert dialog._closing and dialog.busy and not dialog.disposed
        assert pane.busy and pane._deck_audit_running == 1 and calls == [1]
        assert not panel.parent.close() and pane.busy
    finally:
        release.set()
        wait(panel.app, lambda: not dialog.busy and not pane.busy)
    assert dialog.disposed and pane._deck_audit_running == 0
    monkeypatch.setattr(deck_audit.DeckAuditReader, "prepare", original_prepare)
    pane.deck_audit_action.trigger()
    current = pane._deck_audit_dialog
    assert current is not dialog
    wait(panel.app, lambda: not current.busy and current.prepared is not None)
    assert not pane.busy and pane._deck_audit_running == 0


@pytest.mark.parametrize("failure", ["guard", "focus"])
def test_appraisal_inherits_actual_navigation_rejection_without_extra_call(
    reading_window, monkeypatch, failure
):
    from test_audit_appraisal import response

    view = reading_window
    _action, audit = activate(view, "analysis_audit")
    loaded(view, audit, "analysis_audit")
    calls = []

    def complete(prompt, **kwargs):
        calls.append(1)
        return response(prompt, **kwargs)

    monkeypatch.setattr(llm, "complete_result", complete)
    audit.appraisal_button.click()
    dialog = audit._appraisal_dialog
    assert dialog is not None
    wait(view.app, lambda: not dialog.busy and dialog.status.text() != dialog.t["loading"])
    dialog.review_button.click()
    wait(view.app, lambda: not dialog.busy and dialog.report is not None)
    assert calls == [1] and dialog.source_buttons
    if failure == "guard":
        monkeypatch.setattr(main, "anchor_allowed", lambda *a: False)
        monkeypatch.setattr(document_flow, "anchor_allowed", lambda *a: False)
    else:
        monkeypatch.setattr(view.reader.pdf.selection, "focus", lambda _anchor: False)
    dialog.source_buttons[0].click()
    wait(view.app, lambda: not dialog.busy)
    assert dialog.isVisible() and not dialog.disposed
    assert dialog.status.text() == dialog.t["source_failed"] and calls == [1]
    assert view.reader.ask_box.text() == "Unsent question"
    assert view.reader.note_edit.toPlainText() == "Unsent note"


def test_appraisal_actual_source_success_preserves_drafts_and_one_call(reading_window, monkeypatch):
    from test_audit_appraisal import response

    view = reading_window
    _action, audit = activate(view, "analysis_audit")
    loaded(view, audit, "analysis_audit")
    calls = []

    def complete(prompt, **kwargs):
        calls.append(1)
        return response(prompt, **kwargs)

    monkeypatch.setattr(llm, "complete_result", complete)
    audit.appraisal_button.click()
    dialog = audit._appraisal_dialog
    wait(view.app, lambda: not dialog.busy and dialog.status.text() != dialog.t["loading"])
    dialog.review_button.click()
    wait(view.app, lambda: not dialog.busy and dialog.report is not None)
    assert calls == [1] and dialog.source_buttons
    assert not view.reader.pdf.selection.selected_text()
    dialog.source_buttons[0].click()
    wait(view.app, lambda: not dialog.busy)
    assert dialog.status.text() == dialog.t["source"]
    assert view.reader.pdf.selection.selected_text()
    assert calls == [1] and len(view.calls) == 1
    assert view.reader.ask_box.text() == "Unsent question"
    assert view.reader.note_edit.toPlainText() == "Unsent note"


def test_full_saved_note_markup_stays_plain_text_in_existing_group(reading_window):
    from PySide6.QtCore import Qt

    view = reading_window
    body = "Context. " * 110 + "<b>unverified</b> & <script>not executable</script>"
    view.window.data.add_note("paper", body)
    _action, dialog = activate(view, "analysis_audit")
    loaded(view, dialog, "analysis_audit")
    dialog.filter.setChecked(False)
    section = next(
        s for s in dialog.sections if s.button.text().startswith(dialog.features["note"])
    )
    label = next(label for label in section.findChildren(QLabel) if label.text() == body)
    assert label.textFormat() == Qt.TextFormat.PlainText
    assert label.isVisible()
    assert len(view.calls) == 1


@pytest.mark.parametrize("kind", ["claim_evidence", "analysis_audit"])
def test_rejected_source_can_be_reloaded_then_retried_without_ai(reading_window, monkeypatch, kind):
    view = reading_window
    _action, dialog = activate(view, kind)
    loaded(view, dialog, kind)
    if kind == "analysis_audit":
        dialog.filter.setChecked(False)
    guard, legacy_guard = document_flow.anchor_allowed, main.anchor_allowed
    monkeypatch.setattr(document_flow, "anchor_allowed", lambda *a: False)
    monkeypatch.setattr(main, "anchor_allowed", lambda *a: False)
    dialog.source_buttons[0].click()
    wait(view.app, lambda: not dialog.busy)
    assert not dialog.disposed and dialog.status.text() == dialog.t["source_failed"]
    monkeypatch.setattr(document_flow, "anchor_allowed", guard)
    monkeypatch.setattr(main, "anchor_allowed", legacy_guard)
    dialog.refresh_button.click()
    loaded(view, dialog, kind)
    assert dialog.source_buttons and dialog.source_buttons[0].isEnabled()
    dialog.source_buttons[0].click()
    wait(view.app, lambda: not dialog.busy)
    if kind == "claim_evidence":
        assert dialog.disposed
    else:
        assert dialog.status.text() == dialog.t["source"]
    assert view.reader.pdf.selection.selected_text()
    assert len(view.calls) == 1
    assert view.reader.ask_box.text() == "Unsent question"
    assert view.reader.note_edit.toPlainText() == "Unsent note"


@pytest.fixture(autouse=True)
def _normal_fonts_for_layout_geometry(request):
    if "test_saved_evidence_layout_geometry" not in request.node.name:
        yield
        return
    from PySide6.QtGui import QFont, QFontDatabase, QPalette

    from paper_daily.desktop import fonts

    app = QApplication.instance() or QApplication([])
    previous_font = QFont(app.font())
    previous_style = app.style().objectName()
    previous_stylesheet = app.styleSheet()
    previous_palette = QPalette(app.palette())
    try:
        fonts.load()
        # Match normal startup without reinstalling an unchanged live style.
        if app.style().objectName().casefold() != "fusion":
            app.setStyle("Fusion")
        normal_font = fonts.font(fonts.SANS, pixels=fonts.UI_PIXELS)
        if app.font() != normal_font:
            app.setFont(normal_font)
        assert "Noto Sans TC" in QFontDatabase.families(), "Native layout needs the bundled font."
        yield
    finally:
        if app.style().objectName() != previous_style:
            app.setStyle(previous_style)
        if app.styleSheet() != previous_stylesheet:
            app.setStyleSheet(previous_stylesheet)
        if app.palette() != previous_palette:
            app.setPalette(previous_palette)
        if app.font() != previous_font:
            app.setFont(previous_font)


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_saved_evidence_layout_geometry_tracks_wrapping_resize_and_source_failure(
    reading_window, monkeypatch, language
):
    from PySide6.QtCore import QPoint

    from paper_daily.desktop.research_audit import AuditDialog
    from paper_daily.desktop.research_source_navigation import focus

    view = reading_window
    tail = "CRITICAL QUALIFICATION: the conclusion excludes this population."
    body = "Source context and argument. " * 40 + tail
    view.window.data.add_note("paper", body)
    reader = view.reader

    def current():
        return (
            view.ready[0].resolve(),
            reader.paper.id,
            reader._qa_epoch,
            reader._active_document,
            reader._pdf_fingerprint,
        )

    def locate(source):
        return focus(
            reader, source, document=dialog.document, current=lambda: current() == dialog.view
        )

    dialog = AuditDialog(
        view.ready[0],
        "paper",
        document=view.document,
        owner=reader._highlight_owner,
        current_view=current,
        source_callback=locate,
        language=language,
        parent=reader,
        paper_title="Fixture original",
    )
    view.window._audit_dialog = dialog
    dialog.open()
    loaded(view, dialog, "analysis_audit")
    dialog.filter.setChecked(False)
    section = next(
        s for s in dialog.sections if s.button.text().startswith(dialog.features["note"])
    )
    label = next(w for w in section.findChildren(QLabel) if w.text() == body)
    following = next(w for w in section.findChildren(QLabel) if w.text() == dialog.t["unknown"])

    def geometry():
        view.app.processEvents()
        required = label.heightForWidth(label.width())
        assert label.isVisible() and label.wordWrap()
        assert required > 0
        assert label.height() >= required, (
            language,
            dialog.width(),
            label.width(),
            label.height(),
            required,
        )
        start = label.mapTo(section.body, QPoint(0, 0)).y()
        next_start = following.mapTo(section.body, QPoint(0, 0)).y()
        assert next_start >= start + required, (language, start, required, next_start)
        end = label.mapTo(dialog.scroll.widget(), QPoint(0, required)).y()
        dialog.scroll.verticalScrollBar().setValue(
            max(0, end - dialog.scroll.viewport().height() + 20)
        )
        view.app.processEvents()
        tail_bottom = label.mapTo(dialog.scroll.viewport(), QPoint(0, required)).y()
        assert 0 < tail_bottom <= dialog.scroll.viewport().height()
        assert dialog.scroll.horizontalScrollBar().maximum() == 0
        return required

    required_heights = []
    for width in (540, 960, 540):
        dialog.resize(width, 780)
        view.app.processEvents()
        required_heights.append(geometry())
        section.button.click()
        assert not section.body.isVisible()
        section.button.click()
        assert section.body.isVisible()
        assert geometry() == required_heights[-1]
    assert required_heights[0] > required_heights[1]
    assert required_heights[2] == required_heights[0]
    assert dialog.source_buttons
    with monkeypatch.context() as rejected:
        rejected.setattr(document_flow, "anchor_allowed", lambda *a: False)
        dialog.source_buttons[0].click()
        wait(view.app, lambda: not dialog.busy)
    assert not dialog.disposed and dialog.status.text() == dialog.t["source_failed"]
    assert geometry() == required_heights[-1]
    assert view.reader.ask_box.text() == "Unsent question"
    assert view.reader.note_edit.toPlainText() == "Unsent note"
    assert len(view.calls) == 1
