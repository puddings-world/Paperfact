"""Current-corpus Qt checks: visible results, honest progress and safe worker delivery."""

import json
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel
from test_audit_lineage import equal_originals as equal_originals
from test_lineage_desktop import until
from test_lineage_jobs import routes
from test_research_lineage import corpus as corpus

from paper_daily import audit_lineage, llm
from paper_daily.desktop.lineage_dialog import TEXT, LineageDialog


@pytest.fixture
def desk(equal_originals, monkeypatch):
    owner, row, corpus = equal_originals
    app = QApplication.instance() or QApplication([])
    from paper_daily.desktop import fonts
    from paper_daily.desktop.main import style

    fonts.load()
    style(app)
    route = routes()
    monkeypatch.setattr(llm, "available", lambda **_k: True)
    monkeypatch.setattr(llm, "capture_configured_connections", lambda: route)
    monkeypatch.setattr(llm, "settings", lambda task=None, **_k: route.settings(task))
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No AI in audit"))
    view = ["focal-reader"]
    dialog = LineageDialog(
        owner.database, owner.paper_id, owner=owner, document=None, legacy_root=corpus[1],
        current_view=lambda: view[0], language="en",
    )
    dialog.show()
    until(app, lambda: not dialog.busy and dialog.results.count() == 1)
    yield app, dialog, view, row
    if dialog.busy:
        dialog.cancel()
        until(app, lambda: not dialog.busy)
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_actual_corpus_button_results_progress_and_original_navigation(desk, monkeypatch, language):
    app, dialog, _view, row = desk
    # The same real controls are exercised with both shipped language tables.
    dialog.language, dialog.t = language, TEXT[language]
    dialog.audit_button.setText(dialog.t["audit"])
    dialog.results.setCurrentIndex(-1)
    assert not dialog.audit_sources() and not dialog.audit_button.isEnabled()
    dialog.results.setCurrentIndex(0)
    before = dialog.path.read_bytes()
    stages = []
    stage = dialog._stage

    def record(value):
        stages.append(value)
        stage(value)

    monkeypatch.setattr(dialog, "_stage", record)
    dialog.audit_button.click()
    assert dialog.busy and not dialog.audit_button.isEnabled()
    assert not dialog.audit_sources()
    until(app, lambda: not dialog.busy)
    report = dialog._audit_report(row)
    assert report["originals_checked"] == report["originals_total"] == 3
    assert [s for s in stages if s.startswith("lineage_audit:")] == [
        "lineage_audit:0:3", "lineage_audit:1:3", "lineage_audit:2:3", "lineage_audit:3:3",
    ]
    assert dialog.progress.maximum() == dialog.progress.value() == 3
    assert dialog.status.text() == dialog._audit_summary(report)
    assert dialog.findChild(QLabel, "lineageAuditSummary").text() == dialog.status.text()
    from paper_daily.desktop.research_audit import TEXT as AUDIT_TEXT

    assert dialog.audit_labels
    assert all(label.text() == AUDIT_TEXT[language]["located"] for label in dialog.audit_labels)
    assert dialog.audit_button.isEnabled() and dialog.path.read_bytes() == before
    dialog.source_buttons[0].click()
    until(app, lambda: not dialog.busy)
    assert dialog._original_viewer is not None and not dialog._original_viewer.disposed
    assert dialog.document is None and dialog.path.read_bytes() == before
    dialog._original_viewer.close()
    _view[0] = "another-paper"
    assert not dialog._check() and dialog._audit_result is None
    assert all(not label.isVisible() for label in dialog.audit_labels)
    assert not dialog._audit_summary_label.isVisible()


def test_failed_corpus_check_preserves_research_and_can_retry(desk, monkeypatch):
    app, dialog, _view, row = desk
    real = audit_lineage.prepare
    before = dialog.path.read_bytes()

    def failed(*_a, **_k):
        raise ValueError("Synthetic changed original")

    monkeypatch.setattr(audit_lineage, "prepare", failed)
    assert dialog.audit_sources()
    until(app, lambda: not dialog.busy)
    assert dialog._audit_result is None and not dialog.audit_labels
    assert dialog.status.text() == dialog.t["audit_failed"]
    assert dialog.audit_button.isEnabled() and dialog.path.read_bytes() == before
    monkeypatch.setattr(audit_lineage, "prepare", real)
    assert dialog.audit_sources()
    until(app, lambda: not dialog.busy)
    assert dialog._audit_report(row)["originals_checked"] == 3
    assert dialog.path.read_bytes() == before
    from paper_daily import lineage_originals

    read = lineage_originals.prepare
    selected = json.loads(row["body_json"])["report"]["sources"][1]["id"]

    def missing(owner, expected, source_id, **kwargs):
        return None if source_id == selected else read(owner, expected, source_id, **kwargs)

    monkeypatch.setattr(lineage_originals, "prepare", missing)
    assert dialog.audit_sources()
    until(app, lambda: not dialog.busy)
    report = dialog._audit_report(row)
    assert report["originals_checked"] == 2 and report["originals_total"] == 3
    assert any(label.text() == dialog.t["audit_unavailable"] for label in dialog.audit_labels)
    assert dialog.status.text() == dialog._audit_summary(report)
    assert dialog.path.read_bytes() == before
    assert dialog.close() and dialog.disposed
    assert dialog._audit_result is None  # Do not retain verified PDF bytes after close.


@pytest.mark.parametrize("change", ["cancel", "selection", "view", "close"])
def test_pending_corpus_check_cannot_fill_cancelled_or_changed_view(desk, monkeypatch, change):
    app, dialog, view, _row = desk
    real = audit_lineage.prepare
    entered, release = threading.Event(), threading.Event()
    before = dialog.path.read_bytes()

    def delayed(*args, **kwargs):
        result = real(*args, **kwargs)
        entered.set()
        assert release.wait(10)
        return result  # Exercise actual delivery even if cancellation was late.

    monkeypatch.setattr(audit_lineage, "prepare", delayed)
    assert dialog.audit_sources()
    until(app, entered.is_set)
    try:
        assert not dialog.audit_sources()
        if change == "cancel":
            dialog.stop_button.click()
        elif change == "selection":
            dialog.mode.setCurrentIndex(1)
        elif change == "view":
            view[0] = "another-paper"
            assert not dialog._check()
        else:
            assert not dialog.close() and dialog.busy and not dialog.disposed
    finally:
        release.set()
    until(app, lambda: not dialog.busy)
    assert dialog._audit_result is None and not dialog.audit_labels
    assert dialog.path.read_bytes() == before
    if change == "close":
        until(app, lambda: dialog.disposed)
    elif change == "view":
        assert dialog.status.text() == dialog.t["changed"]
    elif change == "cancel":
        assert dialog.status.text() == dialog.t["stopped"]
    else:
        assert dialog.status.text() == dialog.t["audit_failed"]
