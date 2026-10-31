"""Filtered local audit absence is different from no saved research."""

import json
import sqlite3
from contextlib import closing

import pytest
from PySide6.QtWidgets import QLabel, QPushButton
from test_audit_ui import view as view_fixture
from test_audit_ui import wait
from test_research_evidence import UNIQUE, proposal
from test_research_evidence import source as source_fixture

from paper_daily import manual_highlight_ops, research_evidence

source = source_fixture
view = view_fixture


def test_true_empty_has_explicit_zero_count_without_show_all(view):
    count = view.d.findChild(QLabel, "auditVisibleCount")
    assert count is not None and count.isVisible()
    assert "0 of 0" in count.text() and "Semantic support is not checked" in count.text()
    assert view.d.findChild(QPushButton, "auditShowAll") is None
    assert "No saved content" in view.d.status.text()


def test_filtered_empty_explains_hidden_material_and_show_all_is_read_only(view, monkeypatch):
    source = view.source
    result = research_evidence.verify(source, proposal(source, page=2))
    anchor = result["claims"][0]["passages"][0]["location"]["anchor"]
    database = source._owner.db_path
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute(
            "INSERT INTO pdf_highlights(paper_id,document_hash,quote,anchor,created_at) "
            "VALUES(?,?,?,?,?)",
            ("paper", source.sha256, UNIQUE, json.dumps(anchor), "2026-10-31T00:00:00+00:00"),
        )
    view.d.owner = manual_highlight_ops.capture_owner(database, "paper")
    view.d.refresh()
    wait(view.app, lambda: not view.d.busy)
    report = view.d.report
    assert not view.d.sections and view.d.filter.isChecked()
    count = view.d.findChild(QLabel, "auditVisibleCount")
    assert count is not None and "0 of 1" in count.text()
    empty = view.d.findChild(QLabel, "auditFilteredEmpty")
    assert empty is not None and empty.isVisible() and "hidden" in empty.text()
    show = view.d.findChild(QPushButton, "auditShowAll")
    assert show is not None and show.isVisible()
    monkeypatch.setattr(view.d, "capture", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    show.click()
    show.click()
    assert not view.d.filter.isChecked() and len(view.d.sections) == 1
    assert "1 of 1" in count.text() and "Semantic support is not checked" in count.text()
    assert view.d.report is report and not view.d.busy
    assert view.question.text() == "Unsent question" and view.note.toPlainText() == "Unsent note"


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_localized_compact_empty_count_and_no_unsupported_all_clear(view, language):
    from paper_daily.desktop.research_audit import TEXT, AuditDialog

    dialog = AuditDialog(
        view.source._owner.db_path,
        "paper",
        document=view.source,
        language=language,
        parent=view.parent,
    )
    dialog.resize(480, 620)
    dialog.show()
    try:
        wait(view.app, lambda: not dialog.busy and dialog.report is not None)
        count = dialog.findChild(QLabel, "auditVisibleCount")
        assert count.isVisible() and count.wordWrap()
        assert count.text() == TEXT[language]["count"].format(shown=0, total=0, checks=0)
        assert count.height() >= count.heightForWidth(count.width())
        assert dialog.findChild(QPushButton, "auditShowAll") is None
        assert dialog.report["semantics"] == "not_checked"
    finally:
        dialog.close()
        dialog.deleteLater()
        view.app.processEvents()
