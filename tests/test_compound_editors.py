"""Native item editors publish before dismissal and keep rejected drafts intact."""

import os
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from test_research_compound import driver as driver
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
from paper_daily.desktop import cites_pane  # noqa: E402
from paper_daily.desktop.cites_pane import CitesPane  # noqa: E402
from paper_daily.desktop.main import LIGHT  # noqa: E402


@pytest.mark.parametrize("kind", ["ref", "later"])
@pytest.mark.parametrize("action", ["save", "cancel", "paper", "workspace", "stale", "failure"])
def test_item_editor_retains_original_owner_and_draft(driver, monkeypatch, kind, action):
    path, _client, _document, _calls, install, invoke = driver
    phase = "citations" if kind == "ref" else "fetch"
    table = "cites" if kind == "ref" else "followups"
    column, key = ("ref_key", "1") if kind == "ref" else ("work_id", "one")
    field = "purpose" if kind == "ref" else "relation"
    writer = followups.edit_reference if kind == "ref" else followups.edit_followup
    install(phase)
    assert invoke(phase) == 2
    writer("paper", key, **{field: "Original"})
    app = QApplication.instance() or QApplication([])
    pane = CitesPane(SimpleNamespace(), LIGHT)
    pane.paper_id = "paper"
    reloads, errors = [], []
    monkeypatch.setattr(pane, "_reload", lambda: reloads.append(pane.paper_id))
    original_exec = QDialog.exec

    def execute(dialog):
        def interact():
            try:
                boxes = dialog.findChildren(QPlainTextEdit)
                assert boxes[0].toPlainText() == "Original"
                boxes[0].setPlainText("Draft")
                buttons = dialog.findChild(QDialogButtonBox)
                save = buttons.button(QDialogButtonBox.StandardButton.Save)
                if action == "cancel":
                    buttons.button(QDialogButtonBox.StandardButton.Cancel).click()
                    return
                if action == "paper":
                    pane.paper_id = "other"
                elif action == "workspace":
                    other = path.with_name("other.sqlite")
                    with closing(sqlite3.connect(other)) as conn:
                        conn.executescript(store.SCHEMA)
                    monkeypatch.setattr(store, "DB_PATH", other)
                elif action == "stale":
                    writer("paper", key, **{field: "Newer"})
                elif action == "failure":
                    with closing(sqlite3.connect(path)) as conn, conn:
                        conn.execute(
                            f"CREATE TRIGGER reject_editor BEFORE INSERT ON {table} "
                            "BEGIN SELECT RAISE(ABORT,'fixture disk'); END"
                        )
                save.click()
                if action in ("stale", "failure"):
                    assert dialog.isVisible()
                    assert boxes[0].toPlainText() == "Draft"
                    assert dialog.findChild(QLabel, "research-item-save-status").text()
                    if action == "failure":
                        with closing(sqlite3.connect(path)) as conn, conn:
                            conn.execute("DROP TRIGGER reject_editor")
                        save.click()
                    else:
                        save.click()
                        boxes[0].setPlainText("Changed stale draft")
                        save.click()
                        assert boxes[0].toPlainText() == "Changed stale draft"
                        assert (
                            len(
                                rows(
                                    path,
                                    "SELECT * FROM research_compound_requests "
                                    "WHERE status='candidate'",
                                )
                            )
                            == 2
                        )
                        dialog.reject()
                else:
                    assert dialog.result() == QDialog.DialogCode.Accepted, dialog.findChild(
                        QLabel, "research-item-save-status"
                    ).text()
                    buttons.accepted.emit()
            except BaseException as error:
                errors.append(error)
                dialog.reject()

        QTimer.singleShot(0, interact)
        return original_exec(dialog)

    monkeypatch.setattr(QDialog, "exec", execute)
    try:
        pane._edit_item(kind, {column: key, "title": "Stale card", field: "Stale"})
        if errors:
            raise errors[0]
        value = {"cancel": "Original", "stale": "Newer"}.get(action, "Draft")
        assert rows(path, f"SELECT {field} FROM {table} WHERE {column}='{key}'") == [{field: value}]
        if action == "workspace":
            assert rows(store.DB_PATH, f"SELECT * FROM {table}") == []
        assert reloads == ([] if action in ("cancel", "stale", "paper", "workspace") else ["paper"])
    finally:
        pane.close()
        pane.deleteLater()
        app.processEvents()


def test_child_process_has_explicit_original_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "workspace" / "papers.db")
    seen = []
    import subprocess
    import sys

    from paper_daily import llm, runtime
    from paper_daily.ai_job_intent import FrozenRoutes
    from paper_daily.ai_types import Settings

    real_popen = subprocess.Popen
    code = ("import sys,types; from paper_daily import integration_entry; "
            "sys.modules['paper_daily.cli']=types.SimpleNamespace(main=lambda a:0); "
            "raise SystemExit(integration_entry.main(sys.argv[1:]))")
    monkeypatch.setattr(runtime, "cli_command", lambda *a: [sys.executable, "-c", code, *a])

    def launch(args, **kwargs):
        seen.append(kwargs)
        assert args[3] == "_desktop-job-v1" and args[5:] == ["cites", "paper"]
        return real_popen(args, **kwargs)

    monkeypatch.setattr(cites_pane.subprocess, "Popen", launch)
    with llm.connection_scope(FrozenRoutes(
        Settings("none"), {"citations": Settings("none")}
    )):
        process = cites_pane._spawn("cites", "paper")
    assert process.wait(timeout=10) == 0
    # The actual bootstrap accepts only an exact matching private frame.
    assert process._paperfact_ai_handoff.ready
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "other" / "papers.db")
    assert seen[0]["env"]["PAPERFACT_DATA"] == str((tmp_path / "workspace").resolve())
