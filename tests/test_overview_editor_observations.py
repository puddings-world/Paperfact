"""Native overview editor saves its loaded owner and keeps rejected drafts open."""

import os
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from test_producer_observations import receipt
from test_research_generation import rows
from test_research_generation import workspace as workspace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
)

from paper_daily import followups, store  # noqa: E402
from paper_daily.desktop.cites_pane import CitesPane  # noqa: E402
from paper_daily.desktop.main import LIGHT  # noqa: E402


@pytest.mark.parametrize("action", ["save", "cancel", "paper", "workspace", "stale", "failure"])
def test_overview_editor_keeps_draft_and_original_owner(workspace, monkeypatch, action):
    path, _client, _document = workspace
    followups.edit_overview("paper", "Original context", [])
    app = QApplication.instance() or QApplication([])
    pane = CitesPane(SimpleNamespace(), LIGHT)
    pane.paper_id = "paper"
    reloads = []
    monkeypatch.setattr(pane, "_reload", lambda: reloads.append(pane.paper_id))
    errors = []
    original_exec = QDialog.exec

    def execute(dialog):
        def interact():
            try:
                fields = dialog.findChildren(QPlainTextEdit)
                assert fields[0].toPlainText() == "Original context"
                fields[0].setPlainText("Current draft")
                fields[1].setPlainText("before | Precursor | Background")
                buttons = dialog.findChild(QDialogButtonBox)
                if action == "cancel":
                    buttons.button(QDialogButtonBox.StandardButton.Cancel).click()
                    return
                if action == "paper":
                    pane.paper_id = "other"
                elif action == "workspace":
                    other = path.with_name("editor-other.sqlite")
                    with closing(sqlite3.connect(other)) as conn:
                        conn.executescript(store.SCHEMA)
                    monkeypatch.setattr(store, "DB_PATH", other)
                elif action == "stale":
                    followups.edit_overview("paper", "Newer context", [])
                elif action == "failure":
                    with closing(sqlite3.connect(path)) as conn, conn:
                        conn.execute(
                            "CREATE TRIGGER reject_edit BEFORE INSERT ON paper_context BEGIN "
                            "SELECT RAISE(ABORT,'fixture storage failure'); END"
                        )
                buttons.button(QDialogButtonBox.StandardButton.Save).click()
                if action in ("stale", "failure"):
                    assert dialog.isVisible()
                    assert fields[0].toPlainText() == "Current draft"
                    assert dialog.findChild(QLabel, "overview-save-status").text()
                    if action == "stale":
                        buttons.button(QDialogButtonBox.StandardButton.Save).click()
                        assert (
                            len(
                                [
                                    r
                                    for r in receipt(path, "paper_context")
                                    if r["status"] == "candidate"
                                ]
                            )
                            == 1
                        )
                        fields[0].setPlainText("Revised stale draft")
                        buttons.button(QDialogButtonBox.StandardButton.Save).click()
                        assert fields[0].toPlainText() == "Revised stale draft"
                        assert (
                            len(
                                [
                                    r
                                    for r in receipt(path, "paper_context")
                                    if r["status"] == "candidate"
                                ]
                            )
                            == 2
                        )
                        dialog.reject()
                    else:
                        with closing(sqlite3.connect(path)) as conn, conn:
                            conn.execute("DROP TRIGGER reject_edit")
                        buttons.button(QDialogButtonBox.StandardButton.Save).click()
                else:
                    # Late duplicate activation repeats the same durable request.
                    buttons.accepted.emit()
            except BaseException as exc:
                errors.append(exc)
                dialog.reject()

        QTimer.singleShot(0, interact)
        return original_exec(dialog)

    monkeypatch.setattr(QDialog, "exec", execute)
    try:
        pane._edit_story({"summary": "Stale card text", "reading": []})
        if errors:
            raise errors[0]
        expected = {"cancel": "Original context", "stale": "Newer context"}.get(
            action, "Current draft"
        )
        assert rows(path, "SELECT summary FROM paper_context") == [{"summary": expected}]
        if action == "workspace":
            assert rows(store.DB_PATH, "SELECT * FROM paper_context") == []
        assert reloads == ([] if action in ("cancel", "paper", "workspace", "stale") else ["paper"])
    finally:
        pane.close()
        pane.deleteLater()
        app.processEvents()
