"""Compact themed claim cards retain saved data, keyboard controls and uncertainty."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel
from test_claim_evidence_restore_ui import delete_set
from test_claim_evidence_ui import claims as _claims
from test_claim_evidence_ui import generate, saved, wait
from test_claim_evidence_ui import ready as _ready
from test_claim_evidence_ui import view as _view
from test_claim_evidence_ui import workspace as _workspace

from paper_daily import llm
from paper_daily.desktop.claim_evidence import TEXT, ClaimEvidenceDialog
from paper_daily.desktop.main import DARK

claims, ready, view, workspace = _claims, _ready, _view, _workspace

# Well under the full 660; macOS fonts wrap the empty state to about 441.
COMPACT = 460


def test_empty_and_deleted_states_are_compact_and_have_one_status_explanation(view):
    assert view.d.height() <= COMPACT and not view.d.stop_button.isVisible()
    labels = view.d.findChildren(QLabel)
    assert sum(label.text() == TEXT["en"]["empty"] for label in labels) == 1
    assert any(label.text() == TEXT["en"]["empty_heading"] for label in labels)
    generate(view)
    delete_set(view)
    view.d.refresh()
    wait(view.app, lambda: not view.d.busy)
    labels = view.d.findChildren(QLabel)
    assert sum(label.text() == TEXT["en"]["deleted"] for label in labels) == 1
    assert view.d.height() <= COMPACT and not view.d.version.isVisible()
    assert view.d.generate_button.isEnabled()


def test_reason_and_original_disclosures_work_with_keyboard_without_writes_or_ai(view):
    generate(view)
    before = saved(view)
    reason = next(section for section in view.d.sections if section.property("section") == "reason")
    sources = next(
        section for section in view.d.sections if section.property("section") == "sources"
    )
    assert not reason.body.isVisible() and sources.body.isVisible()
    reason.button.setFocus()
    QTest.keyClick(reason.button, Qt.Key.Key_Space)
    assert reason.body.isVisible() and reason.button.isChecked()
    QTest.keyClick(reason.button, Qt.Key.Key_Return)
    assert not reason.body.isVisible() and not view.d.busy
    QTest.keyClick(reason.button, Qt.Key.Key_Enter)
    assert reason.body.isVisible() and not view.d.busy
    assert any(label.text() == "Check study assumptions." for label in reason.findChildren(QLabel))
    sources.button.setFocus()
    QTest.keyClick(sources.button, Qt.Key.Key_Space)
    assert not sources.body.isVisible() and not sources.button.isChecked()
    QTest.keyClick(sources.button, Qt.Key.Key_Space)
    assert sources.body.isVisible() and sources.button.hasFocus()
    assert saved(view) == before and len(view.claims[2]) == 1
    assert view.question.text() == "Unsent question" and view.note.toPlainText() == "Unsent notes"


def test_saved_reload_preserves_disclosure_preferences_without_reading_accounts(view, monkeypatch):
    generate(view)
    view.d.sections[0].button.click()
    view.d.sections[1].button.click()
    monkeypatch.setattr(
        llm, "capture_connections", lambda: (_ for _ in ()).throw(AssertionError("AI"))
    )
    assert view.d.refresh()
    wait(view.app, lambda: not view.d.busy)
    assert view.d.sections[0].button.isChecked() and not view.d.sections[1].button.isChecked()
    before = list(view.d.sections)
    view.d.request_refresh()
    wait(view.app, lambda: not view.d.busy)
    assert view.d.sections == before and len(view.claims[2]) == 1


def test_single_claim_has_natural_height_and_keeps_visible_semantic_limits(view):
    generate(view)
    view.app.processEvents()
    card = view.d.cards_layout.itemAt(0).widget()
    assert card.height() < 440
    text = "\n".join(label.text() for label in view.d.findChildren(QLabel) if label.isVisible())
    assert "Proposed judgment: unresolved" in text
    chip = next(
        label
        for label in view.d.findChildren(QLabel)
        if label.text() == "Proposed judgment: unresolved"
    )
    assert chip.contentsRect().width() >= chip.fontMetrics().horizontalAdvance(chip.text())
    assert "semantic support has not been verified" in text
    assert TEXT["en"]["located"] in text and view.d.source_buttons[0].isVisible()
    assert view.d.generate_button.property("ai") == "primary"


def test_parent_palette_renders_dark_surface_without_fallback_to_light(view):
    view.parent.pal = DARK
    other = ClaimEvidenceDialog(
        view.ready[0],
        "paper",
        view.parent,
        legacy_root=view.ready[2].path.parent,
        owner=view.d.owner,
        document=view.ready[2],
        language="en",
    )
    other.show()
    try:
        wait(view.app, lambda: not other.busy and other.status.text() != TEXT["en"]["loading"])
        assert other.grab().toImage().pixelColor(1, 1) == QColor(DARK["ground"])
        assert "Noto Sans TC" in other.font().families()
        assert not view.claims[2]
    finally:
        other.close()
        other.deleteLater()
        view.app.processEvents()


def test_long_content_wraps_in_narrow_dialog_and_source_action_stays_reachable(view):
    view.claims[1]["claims"][0]["text"] = "An important scientific assertion with caveats. " * 8
    generate(view)
    view.d.resize(460, 660)
    view.app.processEvents()
    assert not view.d.scroll.horizontalScrollBar().isVisible()
    assert view.d.cards.width() <= view.d.scroll.viewport().width()
    button = view.d.source_buttons[0]
    button.setFocus()
    view.d.scroll.ensureWidgetVisible(button)
    view.app.processEvents()
    assert button.hasFocus() and button.isEnabled()
    assert len(view.claims[2]) == 1 and view.d.saved["report"]
