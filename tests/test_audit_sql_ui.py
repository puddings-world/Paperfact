"""New saved A1 cards keep all SQL/hash work off Qt and never offer paid selection."""

import hashlib
import sqlite3
import threading

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QWidget
from test_audit_sql_outputs import context, highlights, links, put, questions
from test_audit_ui import wait
from test_research_evidence import source as source_fixture

from paper_daily import llm, manual_highlight_ops
from paper_daily.desktop.research_audit import FEATURE_TEXT, TEXT, AuditDialog

source = source_fixture


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_new_native_categories_poll_render_and_exact_quote_activation_never_sql_or_hash_on_qt(
    source, monkeypatch, language
):
    app = QApplication.instance() or QApplication([])
    put(source, "highlight_analysis", highlights())
    put(source, "reading_links", links())
    put(source, "research_questions", questions())
    context(source)
    owner = manual_highlight_ops.capture_owner(source._owner.db_path, "paper")
    main_thread = threading.get_ident()
    observed = []

    def guard(call, label):
        def checked(*args, **kwargs):
            assert threading.get_ident() != main_thread, "A1 performed SQL/hash on Qt"
            observed.append(label)
            return call(*args, **kwargs)

        return checked

    monkeypatch.setattr(sqlite3, "connect", guard(sqlite3.connect, "connect"))
    monkeypatch.setattr(hashlib, "sha256", guard(hashlib.sha256, "sha256"))
    monkeypatch.setattr(hashlib, "file_digest", guard(hashlib.file_digest, "file_digest"))
    monkeypatch.setattr(
        llm, "capture_connections", lambda: pytest.fail("Read captured an AI route")
    )
    parent = QWidget()
    question, note = QLineEdit("Unsent question", parent), QPlainTextEdit("Unsent note", parent)
    navigations = []

    def navigate(value):
        assert threading.get_ident() == main_thread
        navigations.append(value)
        return True

    active = (source._owner.db_path, "paper", source)
    dialog = AuditDialog(
        source._owner.db_path,
        "paper",
        document=source,
        owner=owner,
        current_view=lambda: active,
        source_callback=navigate,
        language=language,
        parent=parent,
    )
    try:
        dialog.show()
        wait(app, lambda: not dialog.busy and dialog.report is not None)
        dialog.filter.setChecked(False)
        dialog._render()
        dialog._controls()
        texts = [section.button.text() for section in dialog.sections]
        for feature in ("reading_links", "research_questions", "paper_context"):
            assert any(FEATURE_TEXT[language][feature] in value for value in texts)
        assert dialog.source_buttons
        dialog.source_buttons[0].click()
        wait(app, lambda: not dialog.busy)
        assert len(navigations) == 1 and navigations[0]["document_hash"] == source.sha256
        assert question.text() == "Unsent question" and note.toPlainText() == "Unsent note"
        assert {"connect", "sha256", "file_digest"} <= set(observed)
        assert not dialog.appraisal_button.isEnabled()  # These are A1 cards, not claims.
        assert set(FEATURE_TEXT["en"]) == set(FEATURE_TEXT["zh-TW"])
        assert set(TEXT["en"]) == set(TEXT["zh-TW"])
    finally:
        if dialog.busy:
            dialog.cancel()
            wait(app, lambda: not dialog.busy)
        dialog.close()
        parent.close()
        dialog.deleteLater()
        parent.deleteLater()
        app.processEvents()
